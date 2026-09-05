from feedmind import config
from feedmind.notification import _CATEGORY_META

# Feed categories the pipeline knows how to render. This list is duplicated by
# paper-prism's `constants.js::NEWS_CATEGORIES`, which keys its reader tabs off
# the same strings — including the inconsistent separators, which must be
# preserved exactly on both sides.
KNOWN_CATEGORIES = ["academic", "industry", "cloud", "open-source", "top_stories"]


def test_rss_feeds_structure():
    assert isinstance(config.RSS_FEEDS, list)
    assert len(config.RSS_FEEDS) > 0
    for feed in config.RSS_FEEDS:
        assert len(feed) == 4
        name, url, category, post_to_telegram = feed
        assert isinstance(name, str)
        assert isinstance(url, str)
        assert isinstance(category, str)
        assert isinstance(post_to_telegram, bool)
        assert category in KNOWN_CATEGORIES
        assert url.startswith("http")


def test_only_top_stories_opts_out_of_telegram():
    # Feeds default to being posted; TOI Top Stories is ingested for the web
    # reader only. If another feed opts out, add it here deliberately.
    opted_out = {name for name, _u, _c, post in config.RSS_FEEDS if not post}
    assert opted_out == {"TOI Top Stories"}


def test_static_links_use_known_categories():
    for _title, url, category, _msg in config.STATIC_LINKS:
        assert category in KNOWN_CATEGORIES
        assert url.startswith("http")


def test_every_configured_category_has_telegram_header_metadata():
    # Without an entry the header falls back to a generic badge and a
    # title-cased code — legible, but not the wording anyone intended.
    used = {c for _n, _u, c, _p in config.RSS_FEEDS}
    used |= {c for _t, _u, c, _m in config.STATIC_LINKS}
    assert used <= set(_CATEGORY_META), f"no header metadata for: {used - set(_CATEGORY_META)}"


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


def test_gemini_toggles():
    assert isinstance(config.ENABLE_GEMINI_SUMMARIES, bool)
    assert isinstance(config.GEMINI_REQUEST_DELAY_S, (int, float))


def test_youtube_feeds_structure():
    assert isinstance(config.YOUTUBE_FEEDS, list)
    assert len(config.YOUTUBE_FEEDS) > 0
    for feed in config.YOUTUBE_FEEDS:
        assert len(feed) == 2
        name, url = feed
        assert isinstance(name, str) and name
        assert url.startswith("https://www.youtube.com/feeds/videos.xml")


def test_youtube_config():
    assert isinstance(config.MAX_VIDEO_AGE_DAYS, int)
    assert config.MAX_VIDEO_AGE_DAYS > 0
    assert isinstance(config.FIRESTORE_YOUTUBE_COLLECTION, str)
    assert config.FIRESTORE_YOUTUBE_COLLECTION
