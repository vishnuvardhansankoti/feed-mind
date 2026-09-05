import pytest
from feedmind.ingestion import Article
from feedmind.notification import (
    _category_header,
    _title_from_code,
    build_category_messages,
)


def _article(category: str) -> Article:
    return Article(
        article_id="1",
        title="Test Title",
        url="http://example.com",
        feed_source="Test Source",
        feed_category=category,
        published_at="2023-01-01",
        snippet="Snippet",
    )


def test_build_category_messages_empty():
    messages = build_category_messages("academic", [])
    assert messages == []


def test_build_category_messages_single():
    article = Article(
        article_id="1",
        title="Test Title",
        url="http://example.com",
        feed_source="Test Source",
        feed_category="industry",
        published_at="2023-01-01",
        snippet="Snippet",
    )

    # 1. With summary
    msgs = build_category_messages("industry", [(article, "Test summary")])
    assert len(msgs) == 1
    assert "Test Title" in msgs[0]
    assert "Test summary" in msgs[0]
    assert "🏢 Industry" in msgs[0]

    # 2. Without summary (falls back to title only)
    msgs_no_sum = build_category_messages("industry", [(article, "Test Title")])
    assert len(msgs_no_sum) == 1
    assert "Test Title" in msgs_no_sum[0]
    # In my logic, if summary == title, the summary isn't appended with a dash


def test_build_category_messages_chunking(monkeypatch):
    from feedmind import config

    # Force a very small chunk limit
    monkeypatch.setattr(config, "TELEGRAM_MAX_MESSAGE_LENGTH", 200)

    article = Article(
        article_id="1",
        title="Very Long Title Just To Take Up Space So It Wraps Quickly",
        url="http://example.com/very/long/url/to/take/up/space",
        feed_source="Source",
        feed_category="cloud",
        published_at="2023-01-01",
        snippet="",
    )

    # Passing 3 items should exceed the 200 character limit and chunk them
    items = [(article, "Summary 1"), (article, "Summary 2"), (article, "Summary 3")]
    msgs = build_category_messages("cloud", items)

    assert len(msgs) > 1
    assert "☁️ Cloud" in msgs[0]
    assert "☁️ Cloud News \\(Cont\\.\\)" in msgs[1]


# --- category headers ------------------------------------------------------
# The category codes in config.RSS_FEEDS use inconsistent separators, and the
# header used to run them through str.capitalize(): "top_stories" surfaced in
# Telegram as a literal "Top\_stories" (the underscore MarkdownV2-escaped), and
# "open-source" as "Open\-source News".


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("academic", "🎓 Academic News"),
        ("industry", "🏢 Industry News"),
        ("cloud", "☁️ Cloud News"),
        ("open-source", "💻 Open Source"),
        ("top_stories", "🗞️ Top Stories"),
    ],
)
def test_category_header_text(category, expected):
    assert _category_header(category) == expected


def test_category_header_never_leaks_a_raw_separator():
    # The specific regression: an escaped separator reaching the user.
    for category in ("top_stories", "open-source"):
        header = _category_header(category)
        assert "_" not in header
        assert "\\" not in header
        assert "-" not in header


def test_unknown_category_still_renders_a_sane_header():
    # Adding a feed under a new category must not require touching this module.
    assert _category_header("developer_tools") == "📰 Developer Tools"


def test_title_from_code_handles_both_separators():
    assert _title_from_code("top_stories") == "Top Stories"
    assert _title_from_code("open-source") == "Open Source"
    assert _title_from_code("mixed_case-code") == "Mixed Case Code"
    assert _title_from_code("") == "News"


def test_top_stories_message_header():
    msgs = build_category_messages("top_stories", [(_article("top_stories"), "A summary")])
    assert len(msgs) == 1
    assert msgs[0].startswith("*🗞️ Top Stories*")
    assert "Top\\_stories" not in msgs[0]


def test_top_stories_continuation_header(monkeypatch):
    from feedmind import config

    monkeypatch.setattr(config, "TELEGRAM_MAX_MESSAGE_LENGTH", 200)

    article = Article(
        article_id="1",
        title="Very Long Title Just To Take Up Space So It Wraps Quickly",
        url="http://example.com/very/long/url/to/take/up/space",
        feed_source="TOI Top Stories",
        feed_category="top_stories",
        published_at="2023-01-01",
        snippet="",
    )
    items = [(article, "Summary 1"), (article, "Summary 2"), (article, "Summary 3")]
    msgs = build_category_messages("top_stories", items)

    assert len(msgs) > 1
    # The continuation header must match the first one, escaping and all.
    assert msgs[0].startswith("*🗞️ Top Stories*")
    assert msgs[1].startswith("*🗞️ Top Stories \\(Cont\\.\\)*")


def test_open_source_static_link_header():
    # open-source reaches Telegram via config.STATIC_LINKS, not an RSS feed.
    msgs = build_category_messages("open-source", [(_article("open-source"), "A summary")])
    assert msgs[0].startswith("*💻 Open Source*")
    assert "Open\\-source" not in msgs[0]
