"""main.py — HTTP entrypoint for Cloud Run: Pub/Sub push delivers
feedmind-news-ingested here.

Deployed as a Cloud Run **service** (design doc §3.3), not a Cloud Function,
because it responds to a Pub/Sub push subscription rather than an Eventarc
trigger — Eventarc cannot target a Job directly, and this needs to run on an
event rather than a clock.

The push envelope's own payload is never read: feedmind-news-ingested is a
doorbell, not a data source (see feedmind_core.events.publish_news_ingested).
Every run queries Firestore for curation_status=="pending" itself, so this
entrypoint always writes to Firestore — unlike `__main__.py`, the CLI tool
used for local tuning against SINK=local, there is no "local mode" here: a
production push that silently wrote to the container's ephemeral disk instead
of Firestore would look like a healthy 204 with nothing to show for it.

Pub/Sub redelivers on anything but a 2xx. Returning 204 even when the pipeline
raised is deliberate: articles already written to `stories` before a mid-run
failure would otherwise be reprocessed from scratch on redelivery, and any
article whose curation_status is still "pending" is picked up by the next
trigger regardless — the read query is what makes this safe, the same
reasoning as fetch_pending_telegram.
"""

from __future__ import annotations

import logging

from flask import Flask

from .config import load_config
from .embedder import Embedder
from .events import publish_content_ready
from .pipeline import run
from .store import FirestoreSink, build_firestore_client, fetch_pending_articles

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("news-curator")

app = Flask(__name__)

# Lazy and process-global: a ~90MB model download on every push would be both
# slow and wasteful. Cloud Run keeps an instance warm between requests, so this
# pays the cost once per container, not once per doorbell.
_embedder: Embedder | None = None


def _get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder


@app.post("/")
def handle_push():
    config = load_config()
    db = build_firestore_client(config.firestore_project, config.firestore_database)
    sink = FirestoreSink(db)

    try:
        articles = fetch_pending_articles(db)
        summary = run(config, _get_embedder(), articles, sink)
        logger.info("Curation run complete: %s", summary)
        # Published last, after every story is written — services/summarizer
        # reads Firestore, so announcing earlier would race it to documents
        # that do not exist yet. Best-effort: see events.py.
        publish_content_ready(config, summary)
    except Exception:
        logger.exception("Curation run failed")

    # 204 regardless — see module docstring for why redelivery would not help.
    return "", 204


@app.get("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    import os

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
