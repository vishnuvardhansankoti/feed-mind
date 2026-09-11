"""Entrypoint: `python -m news_curator`.

The tuning tool design doc §11 step 2 calls for: "Run it against a day of real
ingested data with the Firestore write disabled and read the output; tau and
the anchor sentences get tuned here, before anything downstream depends on
them." Firestore is always read for real (fetch_pending_articles); SINK
(default "local") controls only where the output goes — local JSON under
./output/stories/ by default, or the real `stories` collection with
SINK=firestore.

Never used in production — main.py is what Cloud Run's Pub/Sub push actually
calls, and it always writes to Firestore. Keeping this separate is what makes
"can I safely re-run this against today's backlog to check the clustering"
always answerable with SINK=local.
"""

from __future__ import annotations

import logging
import sys

from .config import load_config
from .embedder import Embedder
from .events import publish_content_ready
from .pipeline import run
from .store import build_firestore_client, build_sink, fetch_pending_articles


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    log = logging.getLogger("news_curator")

    config = load_config()
    log.info(
        "starting run — sink=%s coarse_threshold=%.2f cluster_tau=%.2f top_k=%d",
        config.sink,
        config.coarse_threshold,
        config.cluster_distance_threshold,
        config.top_k_per_category,
    )

    db = build_firestore_client(config.firestore_project, config.firestore_database)
    sink = build_sink(config.sink, config.output_dir, db if config.sink == "firestore" else None)

    articles = fetch_pending_articles(db)
    summary = run(config, Embedder(), articles, sink)
    # A no-op unless SINK=firestore — see Config.content_ready_enabled. A
    # SINK=local tuning run has nothing downstream to announce.
    publish_content_ready(config, summary)

    log.info(
        "done: read=%d uncategorized=%d clusters=%s stories=%d canonical=%d",
        summary.articles_read,
        summary.articles_uncategorized,
        summary.clusters_by_category,
        summary.stories_written,
        summary.canonical_selected,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
