"""Announcing a finished run on Pub/Sub.

Copies paper-prism's events.py pattern rather than importing it: this service
has no shared dependency with paper-prism either (see embedder.py's pointer
comment), and both independently implement the same three-rule contract
against the topic services/summarizer owns.

    pipeline.run() writes `stories` -> publish -> feedmind-content-ready -> feedmind-audio

The message body is the contract, and it is deliberately small:

    {"process_doc": "NEWS_STORIES", "source": "news-curator", ...}

`process_doc` is the only field the consumer requires — one topic carries three
pipelines now (RSS_FEED, RESEARCH_PAPERS, NEWS_STORIES) and this selects which.
The rest is provenance for the logs.

Three rules, same as every other publisher in this system:

  * nothing is published when the run wrote to local JSON, not Firestore — a
    local tuning run has no downstream consumer to tell;
  * nothing is published when no cluster was marked canonical, because waking
    the consumer to find nothing new to summarize costs a cold start and buys
    nothing; and
  * a publish failure is logged and swallowed. The stories are already in
    Firestore, which is the job; failing the run at the announcement would
    only invite a retry that redoes the whole clustering pass.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoids a circular import at runtime
    from .config import Config
    from .models import CurationRunSummary

log = logging.getLogger("news_curator.events")

PROCESS_DOC = "NEWS_STORIES"
SOURCE = "news-curator"

# Short on purpose: this runs after the work is done, and there is nothing
# worth holding the request open for — Cloud Run bills for time used.
PUBLISH_TIMEOUT_S = 30


def publish_content_ready(config: Config, summary: CurationRunSummary) -> bool:
    """Tell services/summarizer that new canonical stories are in Firestore.

    Returns True if a message was published, False if it was skipped or
    failed. Never raises — see the module docstring.
    """
    if not config.content_ready_enabled:
        log.info(
            "content-ready events disabled (sink=%s topic=%s) — not publishing",
            config.sink,
            config.content_ready_topic or "unset",
        )
        return False

    if summary.canonical_selected <= 0:
        log.info("no clusters marked canonical — not publishing a content-ready event")
        return False

    payload = {
        "process_doc": PROCESS_DOC,
        "source": SOURCE,
        "canonical_selected": summary.canonical_selected,
        "stories_written": summary.stories_written,
    }

    topic = f"projects/{config.firestore_project}/topics/{config.content_ready_topic}"

    try:
        from google.cloud import pubsub_v1  # imported lazily, like the Firestore client

        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(
            topic,
            json.dumps(payload).encode("utf-8"),
            # Duplicated as attributes so a subscription can filter without
            # decoding the body.
            process_doc=PROCESS_DOC,
            source=SOURCE,
        )
        message_id = future.result(timeout=PUBLISH_TIMEOUT_S)
    except Exception as exc:  # best-effort by design
        log.error("failed to publish content-ready event to %s: %s", topic, exc)
        return False

    log.info(
        "published content-ready event: topic=%s message_id=%s canonical=%d",
        config.content_ready_topic,
        message_id,
        summary.canonical_selected,
    )
    return True
