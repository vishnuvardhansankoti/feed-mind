"""
main.py — feedmind-telegram-notifier: send the digest to Telegram.

Triggered by a Pub/Sub message on `feedmind-telegram-ready`, published by
feedmind-news-ingest once its articles are safely in Firestore.

**The message is a doorbell, not a payload.** It carries no articles, and this
function does not read its body beyond logging it. The work is defined entirely
by what is sitting in Firestore with `telegram_status == "pending"` — which is
what makes the split safe:

  - a dropped Pub/Sub message costs a delay, not articles
  - a Telegram outage leaves the batch pending; the next trigger re-sends it
  - the ingest can never lose an article to a delivery failure, because the
    article is already stored before this function is told anything

The cost is one extra Firestore write per article to flip it to "sent", and the
risk of a duplicate message if delivery succeeds but the flip does not. That
trade is deliberate: a repeated digest entry is a nuisance, a dropped one is
invisible.
"""

import base64
import json
import logging
from pathlib import Path

import functions_framework
import yaml
from feedmind_core import settings as config
from feedmind_core.models import Article
from feedmind_core.secrets import load_all_secrets
from feedmind_core.store import fetch_pending_telegram, mark_telegram_sent
from feedmind_core.telegram import build_category_messages, send_message
from google.cloud import firestore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("telegram-notifier")

NOTIFIER_CONFIG = yaml.safe_load((Path(__file__).resolve().parent / "notifier.yaml").read_text())


def _ordered_categories(present: set[str]) -> list[str]:
    """Configured order first, then anything unconfigured, so nothing is dropped."""
    configured = [c for c in NOTIFIER_CONFIG.get("category_order", []) if c in present]
    return configured + sorted(present - set(configured))


def _static_items() -> dict[str, list[tuple[Article, str]]]:
    """
    The evergreen links, shaped like real articles so they batch identically.

    Their ids are prefixed `static_` and they are never persisted — the web
    reader pins the same links itself and dedupes on id, so a document here
    would be redundant. `mark_telegram_sent` is only ever given real ids.
    """
    items: dict[str, list[tuple[Article, str]]] = {}
    for link in NOTIFIER_CONFIG.get("static_links", []):
        article = Article(
            article_id=f"static_{link['title'].replace(' ', '_').lower()}",
            url=link["url"],
            title=link["title"],
            snippet="",
            feed_source="Daily Reminder",
            feed_category=link["category"],
            published_at="",
        )
        items.setdefault(link["category"], []).append((article, link.get("message", "")))
    return items


def _run(dry_run: bool = False) -> dict:
    secrets = load_all_secrets()
    db = firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DATABASE)

    pending = fetch_pending_telegram(db)

    by_category: dict[str, list[tuple[Article, str]]] = {}
    for article, summary in pending:
        by_category.setdefault(article.feed_category, []).append((article, summary))

    # Static links ride along with whatever else is going out. When nothing is
    # pending the function returns before this, so they never generate a digest
    # of their own — a message containing only "check GitHub Trending" every
    # time the doorbell rang would train you to ignore it.
    if by_category:
        for category, items in _static_items().items():
            by_category.setdefault(category, []).extend(items)

    counters = {
        "service": "feedmind-telegram-notifier",
        "pending_found": len(pending),
        "categories": len(by_category),
        "messages_sent": 0,
        "messages_failed": 0,
        "articles_marked_sent": 0,
    }

    if not by_category:
        logger.info(json.dumps({"message": "Nothing pending — no digest sent", **counters}))
        return counters

    for category in _ordered_categories(set(by_category)):
        items = by_category[category]
        messages = build_category_messages(category, items)

        all_delivered = True
        for text in messages:
            if dry_run:
                print(f"--- WOULD SEND ({category}) ---\n{text}\n---")
                delivered = True
            else:
                delivered = send_message(
                    secrets["telegram_token"], secrets["telegram_chat_id"], text
                )
            if delivered:
                counters["messages_sent"] += 1
            else:
                counters["messages_failed"] += 1
                all_delivered = False

        # All-or-nothing per category. A partial send leaves every article in it
        # pending, so the next trigger re-sends the whole category — a duplicate
        # rather than a silent hole.
        if not all_delivered:
            logger.warning("Category %s partially failed — leaving it pending", category)
            continue

        real_ids = [a.article_id for a, _ in items if not a.article_id.startswith("static_")]
        if real_ids and not dry_run:
            counters["articles_marked_sent"] += mark_telegram_sent(db, real_ids)
        elif dry_run:
            counters["articles_marked_sent"] += len(real_ids)

    logger.info(json.dumps({"message": "Digest run complete", **counters}))
    return counters


@functions_framework.cloud_event
def telegram_notifier(cloud_event):
    """Pub/Sub entry point. The message body is logged as provenance, never acted on."""
    try:
        raw = base64.b64decode(cloud_event.data["message"].get("data", "")).decode("utf-8")
        logger.info("Doorbell: %s", raw or "(empty)")
    except Exception:  # a malformed body must not stop a real backlog going out
        logger.warning("Could not decode trigger message — proceeding anyway")

    _run()


if __name__ == "__main__":
    # Local dry run: reads real pending articles, sends and marks nothing.
    print(json.dumps(_run(dry_run=True), indent=2))
