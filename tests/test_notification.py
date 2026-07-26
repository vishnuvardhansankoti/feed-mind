from feedmind.ingestion import Article
from feedmind.notification import build_category_messages


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
        snippet="Snippet"
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
        snippet=""
    )

    # Passing 3 items should exceed the 200 character limit and chunk them
    items = [(article, "Summary 1"), (article, "Summary 2"), (article, "Summary 3")]
    msgs = build_category_messages("cloud", items)

    assert len(msgs) > 1
    assert "☁️ Cloud" in msgs[0]
    assert "☁️ Cloud News \\(Cont\\.\\)" in msgs[1]
