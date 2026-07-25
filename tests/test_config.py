from feedmind import config


def test_rss_feeds_structure():
    assert isinstance(config.RSS_FEEDS, list)
    assert len(config.RSS_FEEDS) > 0
    for feed in config.RSS_FEEDS:
        assert len(feed) == 3
        name, url, category = feed
        assert isinstance(name, str)
        assert isinstance(url, str)
        assert isinstance(category, str)
        assert category in ["academic", "industry", "cloud"]
        assert url.startswith("http")

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
