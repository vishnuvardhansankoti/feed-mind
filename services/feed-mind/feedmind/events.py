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

from feedmind import config

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

    topic = f"projects/{config.GCP_PROJECT_ID}/topics/{config.CONTENT_READY_TOPIC}"

    try:
        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(
            topic,
            json.dumps(payload).encode("utf-8"),
            # Duplicated as an attribute so the topic can be filtered on without
            # decoding the body — a subscription filter cannot see inside it.
            process_doc=config.CONTENT_READY_PROCESS_DOC,
            source="feed-mind",
        )
        message_id = future.result(timeout=PUBLISH_TIMEOUT_S)
    except Exception as exc:
        # Best-effort by design — see the module docstring.
        logger.error(
            json.dumps(
                {
                    "message": "Failed to publish content-ready event",
                    "topic": config.CONTENT_READY_TOPIC,
                    "error": str(exc),
                }
            )
        )
        return False

    logger.info(
        json.dumps(
            {
                "message": "Published content-ready event",
                "topic": config.CONTENT_READY_TOPIC,
                "message_id": message_id,
                "articles_delivered": articles_delivered,
            }
        )
    )
    return True
