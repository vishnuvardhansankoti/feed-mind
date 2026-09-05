"""Text-to-speech through the Google Cloud Text-to-Speech API.

The sibling module `speech` drives whatever engine the machine provides.
That works on a laptop and not at all on a serverless runtime, which has no
speech engine and no way to install one - so this module exists as the
deployable backend.

Two consequences beyond "it runs in the cloud":

  * the API returns MP3 directly, so the ffmpeg transcode `speech` needs
    disappears; and
  * synthesis is billed per character and capped per request, so long text is
    split on sentence boundaries and the MP3 frames of each chunk are
    concatenated. MP3 is a stream of independent frames, so joining the bytes
    end to end produces a playable file.

The client library is imported lazily, the same way pyttsx3 and spaCy are, so
the rest of the package keeps working without it:

    uv pip install google-cloud-texttospeech
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import SpeechError
from .speech import clean_for_speech

INSTALL_HINT = (
    "google-cloud-texttospeech is not installed - run: "
    "uv pip install google-cloud-texttospeech"
)

DEFAULT_LANGUAGE = "en-US"
DEFAULT_VOICE = "en-US-Neural2-F"

# Words per minute the pyttsx3 drivers speak at by default. --rate is given in
# WPM to stay interchangeable with the local backend; the API instead wants a
# multiplier, so the two are related through this constant.
BASELINE_WPM = 175
MIN_SPEAKING_RATE, MAX_SPEAKING_RATE = 0.25, 4.0

# The API rejects a request whose input exceeds 5000 bytes. Chunking well under
# the limit leaves room for the UTF-8 expansion of whatever punctuation the
# model produced.
MAX_CHUNK_CHARS = 4000

SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


def speaking_rate(rate):
    """Convert a words-per-minute figure into the API's rate multiplier."""
    if rate is None:
        return None
    multiplier = float(rate) / BASELINE_WPM
    return max(MIN_SPEAKING_RATE, min(multiplier, MAX_SPEAKING_RATE))


def split_for_synthesis(text, limit=MAX_CHUNK_CHARS):
    """Break `text` into chunks under `limit`, preferring sentence boundaries.

    A single sentence longer than the limit is hard-split on whitespace; that
    is rare enough in a 2-3 sentence summary to not be worth more care.
    """
    chunks = []
    current = ""

    def flush():
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for piece in SENTENCE_END_RE.split(text):
        while len(piece) > limit:
            head, _, piece = piece[:limit].rpartition(" ")
            chunks.append(head or piece[:limit])
        if not piece:
            continue
        if len(current) + len(piece) + 1 > limit:
            flush()
        current = f"{current} {piece}".strip()

    flush()
    return chunks or [text[:limit]]


def _client():
    try:
        from google.cloud import texttospeech
    except ImportError as error:
        raise SpeechError(INSTALL_HINT) from error

    try:
        return texttospeech, texttospeech.TextToSpeechClient()
    except Exception as error:  # credentials, network, quota project
        raise SpeechError(f"Could not create a Text-to-Speech client: {error}") from error


def synthesize_mp3(text, output, voice=None, rate=None, language=None):
    """Speak `text` into an MP3 at `output`, and return that Path.

    `voice` is a full Cloud TTS voice name such as "en-US-Neural2-F"; `rate` is
    words per minute, matching the local backend's flag.
    """
    text = clean_for_speech(text)
    if not text:
        raise SpeechError("Nothing to speak.")

    texttospeech, client = _client()
    name = voice or DEFAULT_VOICE
    language = language or "-".join(name.split("-")[:2]) or DEFAULT_LANGUAGE

    selection = texttospeech.VoiceSelectionParams(language_code=language, name=name)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    multiplier = speaking_rate(rate)
    if multiplier is not None:
        audio_config.speaking_rate = multiplier

    audio = bytearray()
    for chunk in split_for_synthesis(text):
        try:
            response = client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=chunk),
                voice=selection,
                audio_config=audio_config,
            )
        except Exception as error:  # google.api_core exceptions, mostly
            raise SpeechError(f"Text-to-Speech synthesis failed: {error}") from error
        audio += response.audio_content

    if not audio:
        raise SpeechError("Text-to-Speech returned no audio.")

    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(audio))
    return path
