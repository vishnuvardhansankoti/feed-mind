"""
ingestion.py — Fetch and parse RSS feeds using feedparser.
"""

import hashlib
import html
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import feedparser

from feedmind import config

logger = logging.getLogger(__name__)

# Strip HTML tags from snippet text
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape HTML entities."""
    text = _HTML_TAG_RE.sub("", text)
    return html.unescape(text).strip()


def _compute_article_id(url: str) -> str:
    """Return the SHA-256 hex digest of a URL (used as Firestore document ID)."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _parse_published_at(entry) -> str:
    """
    Extract publication timestamp from a feedparser entry.
    Returns ISO 8601 UTC string. Falls back to current UTC time.
    """
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            dt = datetime(*entry.published_parsed[:6], tzinfo=UTC)
            return dt.isoformat()
    except Exception:
        pass

    return datetime.now(UTC).isoformat()


@dataclass
class Article:
    article_id: str
    url: str
    title: str
    snippet: str  # truncated to MAX_SNIPPET_CHARS
    feed_source: str
    feed_category: str
    published_at: str


@dataclass
class Video:
    video_id: str  # YouTube video ID (used as Firestore document ID)
    url: str  # canonical watch URL
    title: str
    channel: str  # human-readable channel name
    thumbnail_url: str  # derived from video_id
    published_at: str


def _youtube_thumbnail(video_id: str) -> str:
    """Return the standard high-quality thumbnail URL for a YouTube video ID."""
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def fetch_youtube_feed(channel_name: str, feed_url: str) -> list[Video]:
    """
    Fetch and parse a single YouTube channel Atom feed.

    Returns a list of Video objects published within MAX_VIDEO_AGE_DAYS.
    Returns an empty list on any error so the caller can continue with the
    remaining channels. Videos are NOT summarized or sent to Telegram — they are
    written to the `youtube_videos` Firestore collection for the web reader.
    """
    logger.info("Fetching YouTube feed: %s (%s)", channel_name, feed_url)
    try:
        parsed = feedparser.parse(
            feed_url,
            request_headers={"User-Agent": "FeedMind/1.0 (RSS Reader)"},
        )
    except Exception as exc:
        logger.warning("YouTube feed fetch exception: channel=%s error=%s", channel_name, exc)
        return []

    if parsed.get("bozo") and not parsed.entries:
        logger.warning(
            "YouTube feed bozo error: channel=%s bozo_exception=%s",
            channel_name,
            parsed.get("bozo_exception"),
        )
        return []

    videos: list[Video] = []
    for entry in parsed.entries:
        video_id: str | None = getattr(entry, "yt_videoid", None)
        url: str | None = getattr(entry, "link", None)
        if not video_id or not url:
            continue

        title: str = getattr(entry, "title", "Untitled").strip()

        published_at_str = _parse_published_at(entry)
        try:
            pub_dt = datetime.fromisoformat(published_at_str)
            if (datetime.now(UTC) - pub_dt).days > config.MAX_VIDEO_AGE_DAYS:
                continue
        except Exception:
            pass

        videos.append(
            Video(
                video_id=video_id,
                url=url,
                title=title,
                channel=channel_name,
                thumbnail_url=_youtube_thumbnail(video_id),
                published_at=published_at_str,
            )
        )

    logger.info("YouTube feed parsed: channel=%s videos_found=%d", channel_name, len(videos))
    return videos


def fetch_feed(feed_source: str, feed_url: str, feed_category: str) -> list[Article]:
    """
    Fetch and parse a single RSS feed.

    Returns a list of Article objects. Returns an empty list on any error
    so the caller can continue processing remaining feeds.
    """
    logger.info("Fetching feed: %s (%s)", feed_source, feed_url)
    try:
        parsed = feedparser.parse(
            feed_url,
            request_headers={"User-Agent": "FeedMind/1.0 (RSS Reader)"},
            # feedparser uses socket.setdefaulttimeout; we set it in main.py
        )
    except Exception as exc:
        logger.warning("Feed fetch exception: source=%s error=%s", feed_source, exc)
        return []

    if parsed.get("bozo") and not parsed.entries:
        logger.warning(
            "Feed bozo error: source=%s bozo_exception=%s",
            feed_source,
            parsed.get("bozo_exception"),
        )
        return []

    articles: list[Article] = []
    for entry in parsed.entries:
        url: str | None = getattr(entry, "link", None)
        if not url:
            continue

        title: str = getattr(entry, "title", "Untitled").strip()

        # Prefer 'summary', fall back to 'description', then empty string
        raw_text: str = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        snippet: str = _strip_html(raw_text)[: config.MAX_SNIPPET_CHARS]

        published_at_str = _parse_published_at(entry)

        try:
            pub_dt = datetime.fromisoformat(published_at_str)
            if (datetime.now(UTC) - pub_dt).days > config.MAX_ARTICLE_AGE_DAYS:
                continue
        except Exception:
            pass

        articles.append(
            Article(
                article_id=_compute_article_id(url),
                url=url,
                title=title,
                snippet=snippet,
                feed_source=feed_source,
                feed_category=feed_category,
                published_at=published_at_str,
            )
        )

    logger.info("Feed parsed: source=%s entries_found=%d", feed_source, len(articles))
    return articles
