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

from feedmind import archival, bigquery, config
from feedmind.deduplication import (
    is_duplicate,
    is_duplicate_video,
    mark_as_delivered,
    save_video,
)
from feedmind.events import publish_content_ready
from feedmind.ingestion import fetch_feed, fetch_youtube_feed
from feedmind.notification import build_category_messages, send_message, send_plain_message
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
    articles_stored_without_telegram = 0
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

    # Articles from feeds with post_to_telegram=False. They skip the batched
    # Telegram messages entirely and are written straight to Firestore for the
    # paper-prism web reader — same shape as the YouTube ingest below.
    firestore_only_items = []

    # ------------------------------------------------------------------
    # Step 3: Process feeds sequentially
    # ------------------------------------------------------------------
    for feed_index, (feed_source, feed_url, feed_category, post_to_telegram) in enumerate(
        config.RSS_FEEDS
    ):
        # Soft timeout guard — exit gracefully before the 5-minute hard limit
        elapsed = time.monotonic() - run_start
        if elapsed >= config.FUNCTION_SOFT_TIMEOUT_S:
            logger.warning(
                json.dumps(
                    {
                        "message": "Soft timeout reached — stopping early",
                        "elapsed_seconds": round(elapsed, 1),
                        "feeds_remaining": len(config.RSS_FEEDS) - feed_index,
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

            if not post_to_telegram:
                firestore_only_items.append((article, summary))
                continue

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
                    "post_to_telegram": post_to_telegram,
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
    # Step 4a: Persist articles from feeds that opt out of Telegram
    # ------------------------------------------------------------------
    # There is no delivery to gate these on, so they are written directly. The
    # web reader still surfaces them; only the Telegram digest skips them.
    for article, summary in firestore_only_items:
        if is_local_run:
            print(f"--- WOULD SAVE (NO TELEGRAM) TO FIRESTORE: {article.article_id} ---")
        else:
            mark_as_delivered(db, article, summary)
        articles_stored_without_telegram += 1

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
        "articles_stored_without_telegram": articles_stored_without_telegram,
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
    # The consumer reads Firestore, so the count is everything this run wrote —
    # including articles from feeds that opted out of Telegram.
    articles_written = articles_delivered + articles_stored_without_telegram
    if is_local_run:
        print(f"--- WOULD PUBLISH CONTENT-READY EVENT: {articles_written} article(s) written ---")
    else:
        publish_content_ready(articles_written, run_summary=summary_log)

    return (json.dumps(summary_log), 200, {"Content-Type": "application/json"})


# ---------------------------------------------------------------------------
# Archive entry point — Firestore → BigQuery
# ---------------------------------------------------------------------------
# Deployed as a *second* Cloud Function from this same source, on its own
# Scheduler job (1st and 16th of each month). Every source collection is on a
# TTL — 90 days for this repo's, 45 for paper-prism's `runs` — so anything not
# copied out is deleted permanently. See docs/bigquery-archival-plan.md.

# (table spec, Firestore collection, doc → rows). Papers are the one source
# where a single document becomes many rows, so every builder returns a list.
_ARCHIVE_SOURCES = (
    (
        archival.ARTICLES,
        config.FIRESTORE_COLLECTION,
        lambda doc_id, doc, at: [archival.article_row(doc_id, doc, at)],
    ),
    (
        archival.VIDEOS,
        config.FIRESTORE_YOUTUBE_COLLECTION,
        lambda doc_id, doc, at: [archival.video_row(doc_id, doc, at)],
    ),
    (
        archival.PAPERS,
        config.FIRESTORE_RUNS_COLLECTION,
        archival.paper_rows,
    ),
)


def _collect_rows(db, spec, collection_name, build_rows, archived_at):
    """
    Read every live document in one collection and reshape it into BigQuery rows.

    A full scan, deliberately: the live set is a few thousand documents against
    a 50,000/day free read allowance, run twice a month. Paying those reads buys
    an archive with no watermark and no cursor to corrupt — a missed run, a
    failed run or a late `ai_summary` is simply corrected by the next run.
    """
    rows = []
    docs_read = 0

    for snapshot in db.collection(collection_name).stream():
        docs_read += 1
        rows.extend(build_rows(snapshot.id, snapshot.to_dict() or {}, archived_at))

    return docs_read, archival.dedupe_by_key(rows, spec.key_fields)


def _format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024


def _archive_report(results: dict, errors: dict, storage_bytes: int, duration: float) -> str:
    """One scannable message. The failure case has to be obvious at a glance."""
    headline = "FeedMind archive complete" if not errors else "FeedMind archive FAILED"
    lines = [headline]

    for name, counts in results.items():
        lines.append(f"{name}: {counts['rows']} rows from {counts['docs_read']} docs")
    for name, message in errors.items():
        lines.append(f"{name}: ERROR — {message}")

    if storage_bytes:
        # Storage is the only free-tier limit that never resets, so the run
        # report is where its growth becomes visible.
        line = (
            f"storage: {_format_bytes(storage_bytes)} "
            f"of {_format_bytes(config.BQ_FREE_STORAGE_BYTES)} free tier"
        )
        if storage_bytes >= config.BQ_STORAGE_WARN_BYTES:
            line += " — APPROACHING LIMIT"
        lines.append(line)

    lines.append(f"duration: {duration}s")
    return "\n".join(lines)


@functions_framework.http
def archive(request):
    """
    HTTP-triggered Cloud Function. Copies all live Firestore docs to BigQuery.

    Idempotent by construction: every run reads everything and MERGEs, so
    running it twice in a row is harmless and running it late still catches up.
    Run locally (`python main.py archive`) it is a dry run — it reads Firestore
    and builds rows, but writes nothing.
    """
    is_local_run = request is None

    run_start = time.monotonic()
    logger.info(
        json.dumps(
            {
                "message": "FeedMind archive started",
                "timestamp": datetime.now(UTC).isoformat(),
                "dry_run": is_local_run,
            }
        )
    )

    # The report is best-effort infrastructure around the archive, not a
    # precondition for it: if secrets are unavailable we still copy the data and
    # simply lose the notification.
    telegram = None
    if config.ENABLE_ARCHIVE_TELEGRAM_REPORT and not is_local_run:
        try:
            secrets = load_all_secrets()
            telegram = (secrets["telegram_token"], secrets["telegram_chat_id"])
        except RuntimeError as exc:
            logger.error("Secret loading failed — archiving without a report: %s", exc)

    db = firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DATABASE)

    bq = None
    if not is_local_run:
        bq = bigquery.client()
        bigquery.ensure_dataset_and_tables(bq, [spec for spec, _c, _b in _ARCHIVE_SOURCES])

    archived_at = datetime.now(UTC).isoformat()
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for spec, collection_name, build_rows in _ARCHIVE_SOURCES:
        # One failing table must not cost the other two — archiving two of three
        # sources beats archiving none, and the run reports what it missed.
        try:
            docs_read, rows = _collect_rows(db, spec, collection_name, build_rows, archived_at)

            if is_local_run:
                print(f"--- WOULD ARCHIVE {len(rows)} row(s) to {spec.name} ---")
                affected = 0
            else:
                affected = bigquery.archive_table(bq, spec, rows)

            results[spec.name] = {
                "docs_read": docs_read,
                "rows": len(rows),
                "affected_rows": affected,
            }
        except Exception as exc:
            logger.exception("Archiving failed for table=%s", spec.name)
            errors[spec.name] = str(exc)

    # Free metadata call, never a query. Best-effort: a metadata hiccup must not
    # fail an archive that already succeeded.
    storage_bytes = 0
    if bq is not None:
        try:
            storage_bytes = bigquery.dataset_bytes(bq, [spec for spec, _c, _b in _ARCHIVE_SOURCES])
        except Exception:
            logger.warning("Could not read archive storage size", exc_info=True)

    duration = round(time.monotonic() - run_start, 2)
    summary_log = {
        "message": "FeedMind archive complete",
        "tables": results,
        "errors": errors,
        "storage_bytes": storage_bytes,
        "free_storage_bytes": config.BQ_FREE_STORAGE_BYTES,
        "duration_seconds": duration,
    }
    logger.info(json.dumps(summary_log))

    report = _archive_report(results, errors, storage_bytes, duration)
    if telegram:
        send_plain_message(telegram[0], telegram[1], report)
    elif is_local_run:
        print(f"--- WOULD REPORT TO TELEGRAM ---\n{report}\n--------------------------------")

    status = 500 if errors else 200
    return (json.dumps(summary_log), status, {"Content-Type": "application/json"})


if __name__ == "__main__":
    # Allow running either entry point directly without functions-framework
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "archive":
        print("Running FeedMind archive locally (dry run — nothing is written)...")
        archive(None)
    else:
        print("Running FeedMind locally...")
        feedmind(None)
