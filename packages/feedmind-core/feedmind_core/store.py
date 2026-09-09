"""
deduplication.py — Firestore-backed deduplication check.
"""

import logging
from datetime import UTC, datetime, timedelta

from google.cloud import firestore

from feedmind_core import settings as config
from feedmind_core.models import Article, Video

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


def save_article(
    db: firestore.Client,
    article: Article,
    summary: str = "",
    telegram_status: str = config.TELEGRAM_SKIPPED,
) -> None:
    """
    Write an ingested article to Firestore.

    Called by an ingest service as soon as the article is summarized — not after
    Telegram delivery, which now happens in a different function entirely.

    `telegram_status` is how the notifier finds its work: pass
    `config.TELEGRAM_PENDING` for a feed whose articles should be delivered, and
    the default `TELEGRAM_SKIPPED` for one that only feeds the web reader. The
    default is the safe one — a service that forgets to set it produces articles
    the notifier ignores, rather than an unexpected Telegram flood.

    Fields written match the schema defined in the PRD (Section 6). `summary` is
    the one-sentence summary; it is persisted so the web app can render it (docs
    written before this field existed simply lack it, and the reader degrades
    gracefully).

    `snippet` is the article text already fetched for summarization. Nothing in
    this pipeline reads it back — it is persisted so the eventual BigQuery
    archive has real prose rather than titles and one-liners. A doc can only
    ever be archived with what was written here, and the 90-day TTL means
    anything not captured now is unrecoverable. See
    docs/bigquery-archival-plan.md.
    """
    now = datetime.now(UTC)
    doc_ref = db.collection(config.FIRESTORE_COLLECTION).document(article.article_id)
    doc_ref.set(
        {
            "article_id": article.article_id,
            "url": article.url,
            "title": article.title,
            "snippet": article.snippet,
            "feed_source": article.feed_source,
            "feed_category": article.feed_category,
            "summary": summary,
            "published_at": article.published_at,
            "processed_at": now.isoformat(),
            # Firestore TTL requires a native datetime object, not a string
            "expires_at": now + timedelta(days=90),
            # "stored", not the old "delivered": this write no longer implies
            # anything about Telegram. Rows archived to BigQuery before the
            # split still read "delivered", which is how you tell them apart.
            "status": "stored",
            "telegram_status": telegram_status,
        }
    )
    logger.info(
        "Firestore write: article_id=%s source=%s telegram_status=%s",
        article.article_id,
        article.feed_source,
        telegram_status,
    )


def is_duplicate_video(db: firestore.Client, video: Video) -> bool:
    """
    Check if a YouTube video has already been persisted.

    Returns True if the video's document exists in the `youtube_videos`
    collection. One Firestore read per call. Document ID is the video ID.
    """
    doc_ref = db.collection(config.FIRESTORE_YOUTUBE_COLLECTION).document(video.video_id)
    return doc_ref.get().exists


def save_video(db: firestore.Client, video: Video) -> None:
    """
    Write a YouTube video to the `youtube_videos` Firestore collection.

    Videos are not summarized or delivered via Telegram; they are surfaced by
    the paper-prism web app's "Videos" page, which reads this collection
    directly. `expires_at` drives a 90-day TTL, matching `processed_articles`.
    """
    now = datetime.now(UTC)
    doc_ref = db.collection(config.FIRESTORE_YOUTUBE_COLLECTION).document(video.video_id)
    doc_ref.set(
        {
            "video_id": video.video_id,
            "url": video.url,
            "title": video.title,
            "channel": video.channel,
            "thumbnail_url": video.thumbnail_url,
            "published_at": video.published_at,
            "processed_at": now.isoformat(),
            # Firestore TTL requires a native datetime object, not a string
            "expires_at": now + timedelta(days=90),
        }
    )
    logger.info(
        "Firestore video write: video_id=%s channel=%s",
        video.video_id,
        video.channel,
    )


def fetch_pending_telegram(
    db: firestore.Client, limit: int = config.TELEGRAM_MAX_ARTICLES_PER_RUN
) -> list[tuple[Article, str]]:
    """
    Every article still waiting to be sent to Telegram, oldest work first.

    This query — not the Pub/Sub message — is what the notifier acts on, and
    that is the whole reliability story. A dropped message, a crashed notifier
    or a Telegram outage leaves documents PENDING, and the next trigger picks
    them up. The message only decides *when* to look.

    Deliberately a single-field equality filter with no `order_by`: Firestore
    indexes single fields automatically, but adding an ordering on a different
    field would need a composite index deployed before this could run at all.
    Ordering happens in Python instead, on `published_at`, which is what the
    digest is grouped by anyway. `limit` keeps a long backlog from running the
    function past its timeout — the remainder stays PENDING.

    Returns (Article, summary) pairs, the shape `telegram.build_category_messages`
    expects.
    """
    docs = (
        db.collection(config.FIRESTORE_COLLECTION)
        .where(filter=firestore.FieldFilter("telegram_status", "==", config.TELEGRAM_PENDING))
        .limit(limit)
        .stream()
    )

    items: list[tuple[Article, str]] = []
    for snapshot in docs:
        doc = snapshot.to_dict() or {}
        # A document missing url or title cannot be rendered into a message and
        # would strand itself PENDING forever, re-read on every single run.
        if not doc.get("url") or not doc.get("title"):
            logger.warning("Skipping unrenderable pending article: %s", snapshot.id)
            continue
        items.append(
            (
                Article(
                    article_id=doc.get("article_id", snapshot.id),
                    url=doc["url"],
                    title=doc["title"],
                    snippet=doc.get("snippet", ""),
                    feed_source=doc.get("feed_source", ""),
                    feed_category=doc.get("feed_category", ""),
                    published_at=doc.get("published_at", ""),
                ),
                doc.get("summary", ""),
            )
        )

    items.sort(key=lambda pair: pair[0].published_at or "")
    logger.info("Pending Telegram articles fetched: %d (limit %d)", len(items), limit)
    return items


def mark_telegram_sent(db: firestore.Client, article_ids: list[str]) -> int:
    """
    Flip articles to SENT once Telegram has accepted them.

    Batched: Firestore caps a write batch at 500 operations, and a category
    digest can exceed that after a backlog. Only called for articles whose
    message chunks all succeeded — a partial failure leaves the whole category
    PENDING and the next run re-sends it, which risks a duplicate message but
    never a silently dropped article. That trade is deliberate.
    """
    written = 0
    for start in range(0, len(article_ids), 500):
        chunk = article_ids[start : start + 500]
        batch = db.batch()
        for article_id in chunk:
            ref = db.collection(config.FIRESTORE_COLLECTION).document(article_id)
            batch.update(ref, {"telegram_status": config.TELEGRAM_SENT})
        batch.commit()
        written += len(chunk)

    logger.info("Marked %d article(s) as telegram_status=sent", written)
    return written
