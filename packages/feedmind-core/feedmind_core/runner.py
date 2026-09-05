"""
runner.py — the ingest pipeline itself: feed URLs in, Firestore documents out.

This is the part every ingest service shares. A service is a `feeds.yaml`, a
Cloud Scheduler cron, and a `main.py` that calls one of these two functions —
so adding a fourth ingest service is a directory, not a code change.

Deliberately NOT here: anything about Telegram beyond stamping
`telegram_status` and ringing the doorbell. Formatting and sending live in the
notifier, which is a separate function precisely so a Telegram failure cannot
cost us an ingest.

Both functions return a counters dict, which the caller logs as the run summary
and returns as the HTTP body.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from datetime import UTC, datetime

from google.cloud import firestore

from feedmind_core import serviceconfig
from feedmind_core import settings as config
from feedmind_core.store import (
    is_duplicate,
    is_duplicate_video,
    save_article,
    save_video,
)

# `ingestion` (feedparser), `events` (pubsub) and `summarization` (sumy/gemini)
# are imported lazily, inside the functions that use them.
#
# This is not premature optimization — it is what makes the per-service
# dependency extras work. youtube-ingest installs feedmind-core[feeds] and has
# no pubsub; the notifier installs [telegram] and has no feedparser. A
# top-level import here would make every service carry every extra, and the
# ImportError would land at cold start rather than at deploy time.

logger = logging.getLogger(__name__)


def _firestore_client() -> firestore.Client:
    return firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DATABASE)


def _init_summarizer(cfg: serviceconfig.ServiceConfig):
    """
    Prepare whichever summarizer the config asked for.

    Returns (mode, gemini_model). Sumy needs NLTK's punkt data, which is not in
    the deployed image — it is downloaded to /tmp, the only writable path in a
    Cloud Function. Doing that here rather than at import time keeps a service
    that summarizes with `none` (YouTube) from paying for it.
    """
    if cfg.summarize == serviceconfig.SUMMARIZE_NONE:
        return serviceconfig.SUMMARIZE_NONE, None

    if cfg.summarize == serviceconfig.SUMMARIZE_GEMINI:
        from feedmind_core.secrets import load_all_secrets
        from feedmind_core.summarization import init_gemini

        secrets = load_all_secrets()
        return serviceconfig.SUMMARIZE_GEMINI, init_gemini(secrets["gemini_api_key"])

    import nltk

    nltk_data_dir = "/tmp/nltk_data"
    os.makedirs(nltk_data_dir, exist_ok=True)
    if nltk_data_dir not in nltk.data.path:
        nltk.data.path.append(nltk_data_dir)
    nltk.download("punkt", download_dir=nltk_data_dir, quiet=True)
    nltk.download("punkt_tab", download_dir=nltk_data_dir, quiet=True)
    return serviceconfig.SUMMARIZE_SUMY, None


def _summarize(mode, gemini_model, article) -> str | None:
    """Summary for one article, or None if it should be retried next run."""
    if mode == serviceconfig.SUMMARIZE_NONE:
        return ""
    if mode == serviceconfig.SUMMARIZE_GEMINI:
        from feedmind_core.summarization import summarize

        # None means the Gemini call failed. Returning it unchanged skips the
        # Firestore write, so the article is picked up again on the next run
        # rather than being stored with an empty summary forever.
        return summarize(gemini_model, article)

    from feedmind_core.summarization import summarize_with_sumy

    return summarize_with_sumy(article)


def run_rss_ingest(cfg: serviceconfig.ServiceConfig, *, dry_run: bool = False) -> dict:
    """
    Fetch every feed in `cfg`, store what is new, and announce it.

    Articles are stamped `telegram_status=PENDING` when `cfg.deliver_telegram`
    is set, `SKIPPED` otherwise — that field, not this function, is what the
    notifier acts on.
    """
    socket.setdefaulttimeout(config.FEED_FETCH_TIMEOUT_SECONDS)
    run_start = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    logger.info(json.dumps({"message": "Ingest started", "service": cfg.service,
                            "timestamp": started_at}))

    counters = {
        "service": cfg.service,
        "feeds_checked": 0,
        "feeds_failed": 0,
        "new_articles_found": 0,
        "articles_stored": 0,
        "summarizer_failures": 0,
        "duplicates_skipped": 0,
    }

    mode, gemini_model = _init_summarizer(cfg)
    db = None if dry_run else _firestore_client()

    telegram_status = (
        config.TELEGRAM_PENDING if cfg.deliver_telegram else config.TELEGRAM_SKIPPED
    )

    for index, feed in enumerate(cfg.feeds):
        # Soft timeout guard — leave before the platform's hard kill, so the run
        # ends with a usable summary instead of a truncated log.
        if time.monotonic() - run_start >= config.FUNCTION_SOFT_TIMEOUT_S:
            logger.warning(
                json.dumps({"message": "Soft timeout — stopping early",
                            "feeds_remaining": len(cfg.feeds) - index})
            )
            break

        from feedmind_core.ingestion import fetch_feed

        articles = fetch_feed(feed.name, feed.url, feed.category)
        counters["feeds_checked"] += 1
        if not articles:
            counters["feeds_failed"] += 1
            continue

        for article in articles:
            if not dry_run and is_duplicate(db, article):
                counters["duplicates_skipped"] += 1
                continue

            # Re-checked inside the loop: one feed with a large backlog can
            # blow the budget on its own.
            if time.monotonic() - run_start >= config.FUNCTION_SOFT_TIMEOUT_S:
                logger.warning("Soft timeout inside feed loop — stopping early")
                break

            counters["new_articles_found"] += 1

            summary = _summarize(mode, gemini_model, article)
            if summary is None:
                counters["summarizer_failures"] += 1
                continue  # no write, so the next run retries it

            if dry_run:
                print(f"--- WOULD STORE [{telegram_status}] {article.title[:70]}")
            else:
                save_article(db, article, summary, telegram_status=telegram_status)
            counters["articles_stored"] += 1

    counters["duration_seconds"] = round(time.monotonic() - run_start, 2)

    _announce(cfg, counters, stored=counters["articles_stored"], dry_run=dry_run)

    logger.info(json.dumps({"message": "Ingest complete", **counters}))
    return counters


def run_youtube_ingest(cfg: serviceconfig.ServiceConfig, *, dry_run: bool = False) -> dict:
    """
    Fetch every channel feed in `cfg` and store new videos.

    Videos are never summarized and never delivered to Telegram — the web app
    reads `youtube_videos` directly — so this path has no summarizer and no
    delivery state.
    """
    socket.setdefaulttimeout(config.FEED_FETCH_TIMEOUT_SECONDS)
    run_start = time.monotonic()
    logger.info(json.dumps({"message": "YouTube ingest started", "service": cfg.service}))

    counters = {
        "service": cfg.service,
        "channels_checked": 0,
        "new_videos_found": 0,
        "videos_stored": 0,
        "duplicates_skipped": 0,
    }

    db = None if dry_run else _firestore_client()

    for index, feed in enumerate(cfg.feeds):
        if time.monotonic() - run_start >= config.FUNCTION_SOFT_TIMEOUT_S:
            logger.warning(
                json.dumps({"message": "Soft timeout — stopping early",
                            "channels_remaining": len(cfg.feeds) - index})
            )
            break

        from feedmind_core.ingestion import fetch_youtube_feed

        videos = fetch_youtube_feed(feed.name, feed.url)
        counters["channels_checked"] += 1

        for video in videos:
            if not dry_run and is_duplicate_video(db, video):
                counters["duplicates_skipped"] += 1
                continue

            counters["new_videos_found"] += 1
            if dry_run:
                print(f"--- WOULD STORE VIDEO {video.channel}: {video.title[:60]}")
            else:
                save_video(db, video)
            counters["videos_stored"] += 1

    counters["duration_seconds"] = round(time.monotonic() - run_start, 2)

    _announce(cfg, counters, stored=counters["videos_stored"], dry_run=dry_run)

    logger.info(json.dumps({"message": "YouTube ingest complete", **counters}))
    return counters


def _announce(cfg: serviceconfig.ServiceConfig, counters: dict, *, stored: int,
              dry_run: bool) -> None:
    """
    Publish the run's downstream notifications, both best-effort.

    Ordered after every write, never before: both consumers read Firestore, so
    announcing earlier would race them to documents that do not exist yet.

    Nothing is published when the run stored nothing. Waking a consumer to find
    an empty batch costs a cold start and buys nothing, and for the notifier it
    would mean a Telegram message with no articles in it.
    """
    if stored <= 0:
        logger.info("Nothing stored — no downstream events published")
        return

    if not (cfg.deliver_telegram or cfg.content_ready):
        return

    from feedmind_core import events

    if cfg.deliver_telegram:
        if dry_run:
            print(f"--- WOULD RING TELEGRAM DOORBELL ({stored} pending)")
        else:
            events.publish_telegram_ready(cfg.service, stored)

    if cfg.content_ready:
        if dry_run:
            print(f"--- WOULD PUBLISH CONTENT-READY ({stored} stored)")
        else:
            events.publish_content_ready(stored, run_summary=counters)
