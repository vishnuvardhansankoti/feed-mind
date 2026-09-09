"""
events.py — Announce the end of a run on Pub/Sub.

FeedMind is the only thing that knows when new articles have landed in
Firestore, so downstream consumers are told rather than left to poll or to
guess with a schedule. Today there is one consumer: feed-mind-summarizer, which
turns the new articles into spoken summaries.

    FeedMind run ends → publish → feedmind-content-ready → feedmind-audio

The message body is the contract, and it is deliberately small:

    {"process_doc": "RSS_FEED", "source": "feed-mind", ...}

`process_doc` is the only field the consumer requires — it selects which
pipeline to run. The rest is provenance, useful when reading logs.

Publishing is best-effort. A run that summarized and delivered articles has
done its job; failing it at the last step because Pub/Sub was unreachable would
turn a good run into a retried one, and the retry would re-deliver every
article to Telegram. Errors are logged and swallowed.
"""

import json
import logging
from datetime import UTC, datetime

from google.cloud import pubsub_v1

from feedmind_core import settings as config

logger = logging.getLogger(__name__)

# Publish timeout. Short on purpose: this runs after the work is done, inside a
# function with a 300s hard limit, and there is nothing worth waiting for.
PUBLISH_TIMEOUT_S = 30


def publish_content_ready(articles_delivered: int, run_summary: dict | None = None) -> bool:
    """
    Tell downstream consumers that new articles are in Firestore.

    Does nothing when the run delivered no articles: waking the summarizer to
    find an empty batch costs a cold start and buys nothing.

    Args:
        articles_delivered: how many articles this run wrote to Firestore.
        run_summary: optional counters, attached to the message as provenance.

    Returns:
        True if a message was published, False if it was skipped or failed.
    """
    if not config.ENABLE_CONTENT_READY_EVENTS:
        logger.info("Content-ready events disabled — not publishing")
        return False

    if articles_delivered <= 0:
        logger.info("No articles delivered — not publishing a content-ready event")
        return False

    payload = {
        "process_doc": config.CONTENT_READY_PROCESS_DOC,
        "source": "feed-mind",
        "articles_delivered": articles_delivered,
        "run_completed_at": datetime.now(UTC).isoformat(),
    }
    if run_summary:
        payload["run_summary"] = run_summary

    return _publish(
        config.CONTENT_READY_TOPIC,
        payload,
        # Duplicated as attributes so a subscription can filter without decoding
        # the body — a filter cannot see inside it.
        process_doc=config.CONTENT_READY_PROCESS_DOC,
        source="feed-mind",
    )


def publish_telegram_ready(service: str, pending_articles: int) -> bool:
    """
    Ring the notifier's doorbell: there are articles waiting to be sent.

    The message carries no articles, on purpose. The notifier queries Firestore
    for everything marked PENDING, so this only has to say "now would be a good
    time to look" — which means a dropped message costs a delay, not data. Put
    the articles in here instead and losing the message would lose them.

    Best-effort like every other publish in this module: the articles are
    already stored, and failing the ingest to signal a Pub/Sub problem would
    re-run every feed on the retry.
    """
    payload = {
        "trigger": "articles_pending",
        "source": service,
        "pending_articles": pending_articles,
        "published_at": datetime.now(UTC).isoformat(),
    }
    return _publish(config.TELEGRAM_READY_TOPIC, payload, source=service)


def _publish(topic_name: str, payload: dict, **attributes: str) -> bool:
    """Publish one JSON message, swallowing any failure. Returns success."""
    topic = f"projects/{config.GCP_PROJECT_ID}/topics/{topic_name}"

    try:
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(
            topic, json.dumps(payload).encode("utf-8"), **attributes
        )
        message_id = future.result(timeout=PUBLISH_TIMEOUT_S)
    except Exception as exc:
        # Best-effort by design — see the module docstring.
        logger.error(
            json.dumps({"message": "Publish failed", "topic": topic_name, "error": str(exc)})
        )
        return False

    logger.info(
        json.dumps({"message": "Published", "topic": topic_name, "message_id": message_id,
                    "payload": payload})
    )
    return True
