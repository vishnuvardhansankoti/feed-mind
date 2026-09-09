"""
models.py — the two document shapes, with no dependencies at all.

Split out of `ingestion.py` when the services were given per-extra dependency
sets. `store.py` and `telegram.py` need `Article`, but importing it from
`ingestion` also imported feedparser — so the Telegram notifier, which fetches
nothing, could not start without an RSS parser installed, and neither could the
archiver.

Keeping these here means a consumer pays only for what it uses. Nothing in this
module may import anything outside the standard library.
"""

from dataclasses import dataclass


@dataclass
class Article:
    article_id: str      # SHA-256 of url; the Firestore document id
    url: str
    title: str
    snippet: str         # truncated to settings.MAX_SNIPPET_CHARS
    feed_source: str
    feed_category: str
    published_at: str    # ISO 8601 UTC


@dataclass
class Video:
    video_id: str        # YouTube's id; the Firestore document id
    url: str
    title: str
    channel: str
    thumbnail_url: str
    published_at: str    # ISO 8601 UTC
