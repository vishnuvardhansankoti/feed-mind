"""Reading the summary out loud, or saving it as an audio file.

Two local (non-Cloud-TTS) mechanisms live here:

  speak()             pyttsx3, the only non-stdlib dependency in the package,
                       imported lazily so everything else keeps working when
                       it is not installed. Drives whatever engine the
                       platform provides - NSSpeechSynthesizer on macOS,
                       SAPI5 on Windows, espeak on Linux - which is what the
                       CLI's --speak uses to play audio out loud interactively.

  synthesize_wav()     Piper (https://github.com/rhasspy/piper) invoked
                       directly as a subprocess. This is what
                       feedmind_audio.py's deployed pipeline actually uses for
                       FEEDMIND_TTS=local, *not* speak() - see its docstring
                       for why: pyttsx3's Linux driver is not safe to call off
                       the process's main thread, and the Cloud Run container
                       always calls it from a functions-framework dispatch
                       thread. A subprocess has no such thread-affinity
                       requirement, and it is what espeak-ng (this function's
                       previous backend) relied on too - see
                       docs/feed-mind/tts-switch.md for why Piper replaced it
                       (same reason: free, unlimited, no Cloud TTS metering -
                       just a neural vocoder instead of espeak-ng's formant
                       synthesizer, for meaningfully better voice quality at
                       the same zero marginal cost). `piper-tts`'s own
                       phonemizer is still eSpeak-NG-based under the hood,
                       bundled directly into its own wheel (no separate
                       `piper-phonemize` package as a declared dependency) -
                       it is the *waveform* synthesizer being replaced, not
                       every trace of eSpeak NG.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import SpeechError

PIPER_INSTALL_HINT = "piper is not installed - run: uv pip install piper-tts"

# Baked into the Cloud Run image at build time (see Dockerfile) so synthesis
# never needs a network call. Overridable for local dev/testing against a
# differently-placed or different-voice model without touching code.
PIPER_VOICE_MODEL_ENV_VAR = "PIPER_VOICE_MODEL"
PIPER_DEFAULT_MODEL = os.environ.get(
    PIPER_VOICE_MODEL_ENV_VAR, "/app/voices/en_US-lessac-medium.onnx"
)

# Piper takes --length_scale (a duration multiplier: <1.0 faster, >1.0
# slower, 1.0 = the model's own natural pace), not words-per-minute, so `rate`
# is converted against this constant. Deliberately set to the same value as
# cloud_speech.py's BASELINE_WPM (not a measurement of this exact voice's true
# native pace) so that a given `rate` maps to the identical proportional
# speedup on both backends - otherwise the two backends drift apart at any
# rate other than the one they happen to have been tuned by ear against.
PIPER_NATIVE_WPM = 175

INSTALL_HINT = "pyttsx3 is not installed - run: uv pip install pyttsx3"

# The macOS driver ignores the extension and always writes AIFF - and worse,
# it spins forever at 100% CPU on an extension it does not recognise (.mp3),
# never returning from runAndWait(). So unknown extensions are rewritten to the
# platform's native one rather than passed through.
NATIVE_AUDIO_SUFFIX = {"darwin": ".aiff", "win32": ".wav"}
DEFAULT_AUDIO_SUFFIX = NATIVE_AUDIO_SUFFIX.get(sys.platform, ".wav")

SAFE_AUDIO_SUFFIXES = {
    "darwin": {".aiff", ".aif", ".wav"},
    "win32": {".wav"},
}

MIN_VOLUME, MAX_VOLUME = 0.0, 1.0


def _engine(driver=None):
    """Create a fresh engine; engines do not survive being reused."""
    try:
        import pyttsx3
    except ImportError as error:  # pragma: no cover - depends on environment
        raise SpeechError(INSTALL_HINT) from error

    try:
        return pyttsx3.init(driver)
    except Exception as error:  # pyttsx3 raises driver-specific errors
        raise SpeechError(f"Could not start the speech engine: {error}") from error


def list_voices():
    """Return [(id, name, languages)] for every installed voice."""
    engine = _engine()
    try:
        return [
            (voice.id, voice.name, getattr(voice, "languages", []) or [])
            for voice in engine.getProperty("voices")
        ]
    finally:
        engine.stop()


def find_voice(engine, wanted):
    """Match `wanted` against voice names and ids, case-insensitively."""
    wanted = wanted.strip().lower()
    voices = engine.getProperty("voices")
    for voice in voices:
        if wanted in (voice.id.lower(), (voice.name or "").lower()):
            return voice.id
    for voice in voices:
        if wanted in voice.id.lower() or wanted in (voice.name or "").lower():
            return voice.id
    raise SpeechError(
        f"No voice matches {wanted!r}. Run --list-voices to see the options."
    )


def clean_for_speech(text):
    """Strip the markdown-ish decoration the renderer adds."""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(#{1,6}|>|-)\s*", "", line)
        line = re.sub(r"^=+$", "", line)
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def require_piper():
    piper = shutil.which("piper")
    if not piper:
        raise SpeechError(PIPER_INSTALL_HINT)
    return piper


def synthesize_wav(text, output, rate=None, voice=None, piper=None):
    """Speak `text` into a WAV at `output` via a direct `piper` subprocess.

    `voice` is a path to a Piper `.onnx` model (its `.onnx.json` must sit
    alongside it, same directory - Piper finds it automatically); omitted,
    PIPER_DEFAULT_MODEL (baked into the image at build time) is used. `rate`
    is words per minute, converted to Piper's `--length_scale` against
    PIPER_NATIVE_WPM - see this module's docstring for why that's an
    approximation, not a spec.

    A subprocess call has no thread-affinity requirement, unlike pyttsx3's
    ctypes-driven engine in speak() - see this module's docstring. Text goes
    over stdin rather than argv, since Piper reads it that way and a long
    article would risk the platform's argv length limit otherwise.
    """
    text = clean_for_speech(text)
    if not text:
        raise SpeechError("Nothing to speak.")

    piper = piper or require_piper()
    model = voice or PIPER_DEFAULT_MODEL
    if not Path(model).exists():
        raise SpeechError(f"Piper voice model not found: {model}")

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    argv = [piper, "--model", str(model), "--output_file", str(path)]
    if rate is not None:
        argv += ["--length_scale", f"{PIPER_NATIVE_WPM / float(rate):.3f}"]

    result = subprocess.run(argv, input=text, capture_output=True, text=True)
    if result.returncode != 0 or not path.exists():
        detail = (result.stderr or "").strip()[:300]
        raise SpeechError(f"piper failed: {detail}")
    return path


def resolve_output_path(output):
    """Expand the path, and swap an unusable extension for the native one."""
    path = Path(output).expanduser()

    safe = SAFE_AUDIO_SUFFIXES.get(sys.platform)
    if safe is not None and path.suffix.lower() not in safe:
        original = path.name
        path = path.with_suffix(DEFAULT_AUDIO_SUFFIX)
        print(
            f"Note: this platform's speech driver cannot write {original}; "
            f"saving {path.name} instead.",
            file=sys.stderr,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def speak(text, rate=None, volume=None, voice=None, output=None, driver=None):
    """Say `text` aloud, or write it to `output` when a path is given.

    Returns the Path written, or None when the audio was only played.
    """
    text = clean_for_speech(text)
    if not text:
        raise SpeechError("Nothing to speak.")

    engine = _engine(driver)
    try:
        if rate is not None:
            engine.setProperty("rate", int(rate))
        if volume is not None:
            clamped = max(MIN_VOLUME, min(float(volume), MAX_VOLUME))
            engine.setProperty("volume", clamped)
        if voice:
            engine.setProperty("voice", find_voice(engine, voice))

        path = resolve_output_path(output) if output else None
        if path:
            engine.save_to_file(text, str(path))
        else:
            engine.say(text)

        try:
            engine.runAndWait()
        except Exception as error:  # driver failures surface here
            raise SpeechError(f"Speech synthesis failed: {error}") from error

        if path and not path.exists():
            raise SpeechError(f"The engine did not write {path}.")
        return path
    finally:
        engine.stop()
