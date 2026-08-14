"""Entrypoint: `python -m paper_prism`.

Wires config -> clients -> pipeline. This is what the Cloud Run Job invokes
(PRD §7 / P2) and what runs locally for P1 validation.
"""

from __future__ import annotations

import logging
import sys

from .arxiv_client import ArxivClient
from .config import load_config
from .embedder import Embedder
from .pipeline import Pipeline
from .sinks import build_sink
from .summarizer import Summarizer


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("paper_prism")

    config = load_config()
    log.info(
        "starting run — sink=%s summaries=%s window=%dd top_k=%d",
        config.sink,
        "on" if config.summaries_enabled else "off",
        config.window_days,
        config.top_k,
    )

    pipeline = Pipeline(
        config=config,
        arxiv=ArxivClient(
            page_size=config.arxiv_page_size,
            throttle_seconds=config.arxiv_throttle_seconds,
            max_pages=config.arxiv_max_pages,
        ),
        embedder=Embedder(),
        summarizer=Summarizer(config.gemini_api_key, config.gemini_model),
        sink=build_sink(
            config.sink,
            config.output_dir,
            config.firestore_project,
            config.firestore_database,
        ),
    )

    status = pipeline.run()
    return 1 if status.has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
