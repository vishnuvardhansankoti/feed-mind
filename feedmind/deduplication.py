"""
deduplication.py — Firestore-backed deduplication check.
"""

import logging
from datetime import UTC, datetime, timedelta

from google.cloud import firestore

from feedmind import config
from feedmind.ingestion import Article

logger = logging.getLogger(__name__)


def is_duplicate(db: firestore.Client, article: Article) -> bool:
    """
    Check if an article has already been processed.

    Returns True if the article's document exists in Firestore, False otherwise.
    This is a single document .get() — one Firestore read per call.
    """
    doc_ref = db.collection(config.FIRESTORE_COLLECTION).document(article.article_id)
    snapshot = doc_ref.get()
    return snapshot.exists


def mark_as_delivered(db: firestore.Client, article: Article, summary: str = "") -> None:
    """
    Write the article metadata to Firestore after successful Telegram delivery.
    This is the only Firestore write in the pipeline.

    Fields written match the schema defined in the PRD (Section 6). `summary` is
    the one-sentence summary already generated for the Telegram message; it is
    persisted so the paper-prism web app can render it (docs written before this
    field existed simply lack it, and the reader degrades gracefully).
    """
    now = datetime.now(UTC)
    doc_ref = db.collection(config.FIRESTORE_COLLECTION).document(article.article_id)
    doc_ref.set(
        {
            "article_id":   article.article_id,
            "url":          article.url,
            "title":        article.title,
            "feed_source":  article.feed_source,
            "feed_category": article.feed_category,
            "summary":      summary,
            "published_at": article.published_at,
            "processed_at": now.isoformat(),
            # Firestore TTL requires a native datetime object, not a string
            "expires_at":   now + timedelta(days=90),
            "status":       "delivered",
        }
    )
    logger.info(
        "Firestore write: article_id=%s source=%s",
        article.article_id,
        article.feed_source,
    )
