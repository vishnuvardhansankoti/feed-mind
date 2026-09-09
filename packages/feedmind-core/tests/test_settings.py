"""Sanity checks on the constants every service shares.

Feed lists are NOT tested here any more — they moved out of settings.py into
each service's feeds.yaml. See tests/test_service_configs.py, which validates
those files directly.
"""

from feedmind_core import settings as config


def test_gemini_config():
    assert config.GEMINI_MODEL.startswith("gemini")
    assert isinstance(config.GEMINI_TIMEOUT_SECONDS, int)
    assert config.GEMINI_TIMEOUT_SECONDS > 0
    assert isinstance(config.MAX_SNIPPET_CHARS, int)
    assert config.MAX_SNIPPET_CHARS > 0
    assert isinstance(config.GEMINI_SYSTEM_PROMPT, str)
    assert len(config.GEMINI_SYSTEM_PROMPT) > 0


def test_telegram_config():
    assert config.TELEGRAM_API_BASE.startswith("http")
    assert isinstance(config.TELEGRAM_MESSAGE_DELAY_S, (int, float))
    assert isinstance(config.TELEGRAM_MAX_MESSAGE_LENGTH, int)



def test_youtube_config():
    assert isinstance(config.MAX_VIDEO_AGE_DAYS, int)
    assert config.MAX_VIDEO_AGE_DAYS > 0
    assert isinstance(config.FIRESTORE_YOUTUBE_COLLECTION, str)
    assert config.FIRESTORE_YOUTUBE_COLLECTION
