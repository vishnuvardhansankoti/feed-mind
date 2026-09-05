"""Reading the summary out loud, or saving it as an audio file.

pyttsx3 is the only non-stdlib dependency in the package and it is imported
lazily, so everything else keeps working when it is not installed:

    uv pip install --python .venv/bin/python pyttsx3

pyttsx3 drives whatever engine the platform provides - NSSpeechSynthesizer on
macOS, SAPI5 on Windows, espeak on Linux. That means saved audio takes the
driver's native format: on macOS the output is always AIFF, whatever extension
you ask for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .errors import SpeechError

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
