"""
ingestion.py — Fetch and parse RSS feeds using feedparser.
"""

import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import feedparser

import config

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
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.isoformat()
    except Exception:
        pass

    return datetime.now(timezone.utc).isoformat()


@dataclass
class Article:
    article_id:    str
    url:           str
    title:         str
    snippet:       str           # truncated to MAX_SNIPPET_CHARS
    feed_source:   str
    feed_category: str
    published_at:  str


def fetch_feed(feed_source: str, feed_url: str, feed_category: str) -> List[Article]:
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
        logger.warning(
            "Feed fetch exception: source=%s error=%s", feed_source, exc
        )
        return []

    if parsed.get("bozo") and not parsed.entries:
        logger.warning(
            "Feed bozo error: source=%s bozo_exception=%s",
            feed_source,
            parsed.get("bozo_exception"),
        )
        return []

    articles: List[Article] = []
    for entry in parsed.entries:
        url: Optional[str] = getattr(entry, "link", None)
        if not url:
            continue

        title: str = getattr(entry, "title", "Untitled").strip()

        # Prefer 'summary', fall back to 'description', then empty string
        raw_text: str = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
        snippet: str = _strip_html(raw_text)[: config.MAX_SNIPPET_CHARS]

        articles.append(
            Article(
                article_id    = _compute_article_id(url),
                url           = url,
                title         = title,
                snippet       = snippet,
                feed_source   = feed_source,
                feed_category = feed_category,
                published_at  = _parse_published_at(entry),
            )
        )

    logger.info(
        "Feed parsed: source=%s entries_found=%d", feed_source, len(articles)
    )
    return articles
