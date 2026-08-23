"""Announcing a finished run on Pub/Sub.

The `runs` documents this pipeline writes are read downstream by
feed-mind-summarizer, which turns each paper into a spoken summary. This
pipeline is the only thing that knows when a run actually finished, so it says
so rather than leaving the consumer to guess with a schedule of its own.

    pipeline.run() ends -> publish -> feedmind-content-ready -> feedmind-audio

The message body is the contract, and it is deliberately small:

    {"process_doc": "RESEARCH_PAPERS", "source": "paper-prism", ...}

`process_doc` is the only field the consumer requires — one topic carries both
of its pipelines and this selects which. The rest is provenance for the logs.

Three rules, all of them about not making a good run look bad:

  * nothing is published unless the run wrote to Firestore. A local run has no
    downstream consumer to tell;
  * nothing is published when no papers were written, because waking the
    consumer to find an empty batch costs a cold start and buys nothing; and
  * a publish failure is logged and swallowed. The papers are already in
    Firestore, which is the job; failing the run at the announcement would only
    invite a retry that redoes the whole thing.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoids a circular import at runtime
    from .config import Config
    from .models import RunStatus

log = logging.getLogger("paper_prism.events")

PROCESS_DOC = "RESEARCH_PAPERS"
SOURCE = "paper-prism"

# Publish timeout. Short on purpose: this runs after the work is done, and
# there is nothing worth holding the job open for.
PUBLISH_TIMEOUT_S = 30


def papers_written(status: RunStatus) -> int:
    """Total papers across the lenses that succeeded."""
    return sum(
        entry.get("paper_count", 0)
        for entry in status.categories.values()
        if entry.get("status") == "ok"
    )


def publish_content_ready(config: Config, status: RunStatus) -> bool:
    """Tell downstream consumers that new papers are in Firestore.

    Returns True if a message was published, False if it was skipped or failed.
    Never raises — see the module docstring.
    """
    if not config.content_ready_enabled:
        log.info(
            "content-ready events disabled (sink=%s topic=%s) — not publishing",
            config.sink,
            config.content_ready_topic or "unset",
        )
        return False

    total = papers_written(status)
    if total <= 0:
        log.info("no papers written — not publishing a content-ready event")
        return False

    payload = {
        "process_doc": PROCESS_DOC,
        "source": SOURCE,
        "run_date": status.doc_id,
        "papers_written": total,
        "categories": status.categories,
    }

    topic = f"projects/{config.firestore_project}/topics/{config.content_ready_topic}"

    try:
        from google.cloud import pubsub_v1  # imported lazily, like the Firestore sink

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
        "published content-ready event: topic=%s message_id=%s papers=%d",
        config.content_ready_topic,
        message_id,
        total,
    )
    return True
