"""Reading the summary out loud, or saving it as an audio file.

Two local (non-Cloud-TTS) mechanisms live here:

  speak()             pyttsx3, the only non-stdlib dependency in the package,
                       imported lazily so everything else keeps working when
                       it is not installed. Drives whatever engine the
                       platform provides - NSSpeechSynthesizer on macOS,
                       SAPI5 on Windows, espeak on Linux - which is what the
                       CLI's --speak uses to play audio out loud interactively.

  synthesize_wav()     espeak-ng invoked directly as a subprocess, stdlib
                       only. This is what feedmind_audio.py's deployed
                       pipeline actually uses for FEEDMIND_TTS=local, *not*
                       speak() - see its docstring for why: pyttsx3's Linux
                       driver is not safe to call off the process's main
                       thread, and the Cloud Run container always calls it
                       from a functions-framework dispatch thread. A
                       subprocess has no such thread-affinity requirement.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

from .errors import SpeechError

ESPEAK_INSTALL_HINT = "espeak-ng is not on PATH - install it with: apt-get install espeak-ng"

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


def require_espeak():
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak:
        raise SpeechError(ESPEAK_INSTALL_HINT)
    return espeak


def synthesize_wav(text, output, rate=None, voice=None, espeak=None):
    """Speak `text` into a WAV at `output` via a direct espeak-ng subprocess.

    `rate` is words per minute, passed straight through to espeak-ng's own
    `-s` flag - no WPM-to-multiplier conversion needed here, unlike
    cloud_speech.py's speaking_rate() (the Cloud TTS API wants a multiplier
    instead of raw WPM). `voice` is an espeak-ng voice name (see
    `espeak-ng --voices`); omitted, espeak-ng uses its own default.

    A subprocess call has no thread-affinity requirement, unlike pyttsx3's
    ctypes-driven engine in speak() - see this module's docstring.
    """
    text = clean_for_speech(text)
    if not text:
        raise SpeechError("Nothing to speak.")

    espeak = espeak or require_espeak()
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    argv = [espeak, "-w", str(path)]
    if rate is not None:
        argv += ["-s", str(int(rate))]
    if voice:
        argv += ["-v", voice]
    argv.append(text)

    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0 or not path.exists():
        detail = (result.stderr or "").strip()[:300]
        raise SpeechError(f"espeak-ng failed: {detail}")
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
