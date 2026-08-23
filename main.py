"""
main.py — FeedMind Cloud Function entry point.

Triggered by Cloud Scheduler via authenticated HTTPS POST.
Orchestrates: secret loading → RSS ingestion → deduplication → summarization → Telegram delivery.
"""

import json
import logging
import socket
import time
from datetime import UTC, datetime

import functions_framework
from google.cloud import firestore

from feedmind import config
from feedmind.deduplication import (
    is_duplicate,
    is_duplicate_video,
    mark_as_delivered,
    save_video,
)
from feedmind.events import publish_content_ready
from feedmind.ingestion import fetch_feed, fetch_youtube_feed
from feedmind.notification import build_category_messages, send_message
from feedmind.secrets import load_all_secrets
from feedmind.summarization import init_gemini, summarize, summarize_with_sumy

# ---------------------------------------------------------------------------
# Logging — structured JSON for Cloud Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("feedmind")

# ---------------------------------------------------------------------------
# Set global socket timeout so feedparser respects FEED_FETCH_TIMEOUT_SECONDS
# ---------------------------------------------------------------------------
socket.setdefaulttimeout(config.FEED_FETCH_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# Cloud Function entry point
# ---------------------------------------------------------------------------
@functions_framework.http
def feedmind(request):
    """
    HTTP-triggered Cloud Function.
    Cloud Scheduler calls this endpoint once daily with an OIDC token.
    The Cloud Function platform validates the token before invoking this handler.
    """
    is_local_run = request is None

    run_start = time.monotonic()
    started_at = datetime.now(UTC).isoformat()

    logger.info(json.dumps({"message": "FeedMind run started", "timestamp": started_at}))

    # --- Counters ---
    feeds_checked = 0
    feeds_failed = 0
    new_articles_found = 0
    articles_summarized = 0
    articles_delivered = 0
    gemini_failures = 0
    telegram_failures = 0
    youtube_feeds_checked = 0
    new_videos_found = 0
    videos_saved = 0

    # ------------------------------------------------------------------
    # Step 1: Load secrets
    # ------------------------------------------------------------------
    try:
        secrets = load_all_secrets()
    except RuntimeError as exc:
        logger.critical("Secret loading failed — aborting run: %s", exc)
        return ("Secret loading failed. See Cloud Logging for details.", 500)

    telegram_token = secrets["telegram_token"]
    telegram_chat_id = secrets["telegram_chat_id"]
    gemini_api_key = secrets["gemini_api_key"]

    # ------------------------------------------------------------------
    # Step 2: Initialise Gemini model and Firestore client
    # ------------------------------------------------------------------
    if config.ENABLE_GEMINI_SUMMARIES:
        gemini_model = init_gemini(gemini_api_key)
    else:
        gemini_model = None

        # Download required NLTK datasets for Sumy to a writable temp dir
        import os

        import nltk

        nltk_data_dir = "/tmp/nltk_data"
        os.makedirs(nltk_data_dir, exist_ok=True)
        if nltk_data_dir not in nltk.data.path:
            nltk.data.path.append(nltk_data_dir)
        nltk.download("punkt", download_dir=nltk_data_dir, quiet=True)
        nltk.download("punkt_tab", download_dir=nltk_data_dir, quiet=True)

    db = firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DATABASE)

    category_items = {"academic": [], "industry": [], "cloud": []}

    # ------------------------------------------------------------------
    # Step 3: Process feeds sequentially
    # ------------------------------------------------------------------
    for feed_source, feed_url, feed_category in config.RSS_FEEDS:
        # Soft timeout guard — exit gracefully before the 5-minute hard limit
        elapsed = time.monotonic() - run_start
        if elapsed >= config.FUNCTION_SOFT_TIMEOUT_S:
            logger.warning(
                json.dumps(
                    {
                        "message": "Soft timeout reached — stopping early",
                        "elapsed_seconds": round(elapsed, 1),
                        "feeds_remaining": config.RSS_FEEDS.index(
                            (feed_source, feed_url, feed_category)
                        ),
                    }
                )
            )
            break

        # --- Fetch feed ---
        articles = fetch_feed(feed_source, feed_url, feed_category)
        feeds_checked += 1

        if not articles:
            feeds_failed += 1
            continue

        feed_new = 0
        feed_duplicates = 0

        for article in articles:
            # --- Deduplication ---
            if is_duplicate(db, article):
                feed_duplicates += 1
                logger.debug("SKIP duplicate: article_id=%s", article.article_id)
                continue

            # Check soft timeout inside the loop to avoid crashing on huge backlogs
            if time.monotonic() - run_start >= config.FUNCTION_SOFT_TIMEOUT_S:
                logger.warning("Soft timeout reached inside feed loop — stopping early")
                break

            feed_new += 1
            new_articles_found += 1

            # --- Summarization ---
            if config.ENABLE_GEMINI_SUMMARIES:
                summary = summarize(gemini_model, article)
                if summary is None:
                    gemini_failures += 1
                    continue  # do NOT write to Firestore; allow retry on next run
                articles_summarized += 1
            else:
                summary = summarize_with_sumy(article)
                articles_summarized += 1

            # Collect for batching
            if article.feed_category not in category_items:
                category_items[article.feed_category] = []
            category_items[article.feed_category].append((article, summary))

        logger.info(
            json.dumps(
                {
                    "message": "Feed processed",
                    "feed_source": feed_source,
                    "feed_category": feed_category,
                    "entries_found": len(articles),
                    "new_articles": feed_new,
                    "skipped_duplicates": feed_duplicates,
                }
            )
        )

    # ------------------------------------------------------------------
    # Step 4: Batch and Send Messages per Category
    # ------------------------------------------------------------------
    # --- Append static daily reminders ---
    from feedmind.ingestion import Article

    for title, url, category, msg in getattr(config, "STATIC_LINKS", []):
        dummy_id = f"static_{title.replace(' ', '_').lower()}"
        dummy_article = Article(
            article_id=dummy_id,
            url=url,
            title=title,
            snippet="",
            feed_source="Daily Reminder",
            feed_category=category,
            published_at=datetime.now(UTC).isoformat(),
        )
        if category not in category_items:
            category_items[category] = []
        category_items[category].append((dummy_article, msg))

    for category, items in category_items.items():
        if not items:
            continue

        messages = build_category_messages(category, items)

        all_chunks_delivered = True
        for msg_text in messages:
            if is_local_run:
                print(
                    f"--- WOULD SEND TO TELEGRAM ({category}) ---\n{msg_text}\n-----------------------------"
                )
                delivered = True
            else:
                delivered = send_message(telegram_token, telegram_chat_id, msg_text)

            if not delivered:
                telegram_failures += 1
                all_chunks_delivered = False

        if all_chunks_delivered:
            # Mark all as delivered only if all message chunks for this category succeeded
            # Persist real (RSS) articles with their summary. Static links (e.g.
            # the daily "GitHub Trending" reminder) are NOT persisted: they are
            # evergreen and the paper-prism web reader pins them client-side, so
            # writing them here would just create a redundant daily doc.
            for article, summary in items:
                if not article.article_id.startswith("static_"):
                    if is_local_run:
                        print(f"--- WOULD MARK AS DELIVERED IN FIRESTORE: {article.article_id} ---")
                    else:
                        mark_as_delivered(db, article, summary)
                    articles_delivered += 1

    # ------------------------------------------------------------------
    # Step 4b: Ingest YouTube subscriptions -> Firestore (no Telegram)
    # ------------------------------------------------------------------
    # New videos from the last MAX_VIDEO_AGE_DAYS are written to the
    # `youtube_videos` collection. They are NOT summarized or delivered via
    # Telegram — the paper-prism web app's "Videos" page reads them directly.
    for channel_name, feed_url in getattr(config, "YOUTUBE_FEEDS", []):
        # Honor the same soft-timeout guard as the RSS loop.
        if time.monotonic() - run_start >= config.FUNCTION_SOFT_TIMEOUT_S:
            logger.warning("Soft timeout reached before YouTube ingest — stopping early")
            break

        videos = fetch_youtube_feed(channel_name, feed_url)
        youtube_feeds_checked += 1

        channel_new = 0
        for video in videos:
            if is_duplicate_video(db, video):
                logger.debug("SKIP duplicate video: video_id=%s", video.video_id)
                continue

            channel_new += 1
            new_videos_found += 1

            if is_local_run:
                print(
                    f"--- WOULD SAVE VIDEO TO FIRESTORE: {video.video_id} "
                    f"({video.channel}) {video.title} ---"
                )
            else:
                save_video(db, video)
            videos_saved += 1

        logger.info(
            json.dumps(
                {
                    "message": "YouTube feed processed",
                    "channel": channel_name,
                    "videos_found": len(videos),
                    "new_videos": channel_new,
                }
            )
        )

    # ------------------------------------------------------------------
    # Step 5: Emit run summary
    # ------------------------------------------------------------------
    duration = round(time.monotonic() - run_start, 2)
    summary_log = {
        "message": "FeedMind run complete",
        "feeds_checked": feeds_checked,
        "feeds_failed": feeds_failed,
        "new_articles_found": new_articles_found,
        "articles_summarized": articles_summarized,
        "articles_delivered": articles_delivered,
        "gemini_failures": gemini_failures,
        "telegram_failures": telegram_failures,
        "youtube_feeds_checked": youtube_feeds_checked,
        "new_videos_found": new_videos_found,
        "videos_saved": videos_saved,
        "duration_seconds": duration,
    }
    logger.info(json.dumps(summary_log))

    # ------------------------------------------------------------------
    # Step 6: Announce the run so downstream consumers can pick it up
    # ------------------------------------------------------------------
    # Published last, after every article is safely in Firestore — the
    # consumer reads that collection, so announcing any earlier would race it.
    # Best-effort: a failure here is logged, never raised. See events.py.
    if is_local_run:
        print(
            f"--- WOULD PUBLISH CONTENT-READY EVENT: "
            f"{articles_delivered} article(s) delivered ---"
        )
    else:
        publish_content_ready(articles_delivered, run_summary=summary_log)

    return (json.dumps(summary_log), 200, {"Content-Type": "application/json"})


if __name__ == "__main__":
    # Allow running the script directly without functions-framework
    print("Running FeedMind locally...")
    feedmind(None)
