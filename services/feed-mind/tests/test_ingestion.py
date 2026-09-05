from datetime import UTC, datetime, timedelta

import feedparser
from feedmind import ingestion
from feedmind.ingestion import Video, fetch_youtube_feed

# Real parser captured before any monkeypatch, so patched replacements can still
# parse the fixture XML without recursing into themselves.
_REAL_PARSE = feedparser.parse

# Minimal YouTube channel Atom feed. feedparser.parse() accepts a raw XML string,
# so these tests never hit the network. {published} is templated so the entry
# lands inside the MAX_VIDEO_AGE_DAYS window.
_ATOM_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Sam Witteveen AI</title>
  <entry>
    <yt:videoId>dQw4w9WgXcQ</yt:videoId>
    <title>How to Build an AI Agent</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=dQw4w9WgXcQ"/>
    <author><name>Sam Witteveen AI</name></author>
    <published>{published}</published>
  </entry>
</feed>
"""


def _feed_xml(published: datetime) -> str:
    return _ATOM_TEMPLATE.format(published=published.isoformat())


def test_fetch_youtube_feed_parses_recent_video(monkeypatch):
    xml = _feed_xml(datetime.now(UTC))
    monkeypatch.setattr(ingestion.feedparser, "parse", lambda *a, **k: _REAL_PARSE(xml))

    videos = fetch_youtube_feed("Sam Witteveen AI", "https://example/feed")

    assert len(videos) == 1
    v = videos[0]
    assert isinstance(v, Video)
    assert v.video_id == "dQw4w9WgXcQ"
    assert v.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert v.title == "How to Build an AI Agent"
    assert v.channel == "Sam Witteveen AI"
    assert v.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_fetch_youtube_feed_filters_old_video(monkeypatch):
    old = datetime.now(UTC) - timedelta(days=10)
    xml = _feed_xml(old)
    monkeypatch.setattr(ingestion.feedparser, "parse", lambda *a, **k: _REAL_PARSE(xml))

    videos = fetch_youtube_feed("Sam Witteveen AI", "https://example/feed")

    assert videos == []


def test_fetch_youtube_feed_handles_fetch_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(ingestion.feedparser, "parse", _boom)
    assert fetch_youtube_feed("Sam Witteveen AI", "https://example/feed") == []
