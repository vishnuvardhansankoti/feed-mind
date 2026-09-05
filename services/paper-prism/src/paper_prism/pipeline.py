"""Pipeline orchestration (PRD §3.2, §3.3).

Best-effort per category: a failure in one lens is logged and recorded in
run_status; other lenses proceed. Ranking is authoritative (cosine); Gemini only
summarizes and its failure yields a null summary rather than dropping the paper.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import numpy as np

from .arxiv_client import ArxivClient
from .config import Config
from .embedder import Embedder, rank_top_k
from .models import LENSES, Paper, RunDocument, RunStatus, utc_run_date
from .sinks import Sink
from .summarizer import Summarizer

log = logging.getLogger("paper_prism.pipeline")


class Pipeline:
    def __init__(
        self,
        config: Config,
        arxiv: ArxivClient,
        embedder: Embedder,
        summarizer: Summarizer,
        sink: Sink,
    ) -> None:
        self.config = config
        self.arxiv = arxiv
        self.embedder = embedder
        self.summarizer = summarizer
        self.sink = sink

    def run(self) -> RunStatus:
        run_date = utc_run_date()
        expire_at = run_date + timedelta(days=self.config.retention_days)
        status = RunStatus(run_date=run_date, expire_at=expire_at)

        for category, sources in LENSES.items():
            try:
                doc = self._run_lens(category, sources, run_date, expire_at)
                self.sink.write_run(doc)
                status.mark_ok(category, len(doc.papers))
            except Exception as exc:  # best-effort: isolate per-lens failures
                log.exception("lens %s failed", category)
                status.mark_skipped(category, reason=type(exc).__name__)

        self.sink.write_status(status)
        if status.has_failure:
            # Surfaced to Cloud Logging -> log-based alert in production (PRD §5).
            log.error("RUN COMPLETED WITH FAILURES: %s", status.to_dict()["categories"])
        return status

    def _run_lens(self, category, sources, run_date, expire_at) -> RunDocument:
        candidates = self.arxiv.fetch_lens(sources, self.config.window_days)
        if not candidates:
            log.warning("lens %s: no candidates in window", category)
            return RunDocument(
                category=category, run_date=run_date, papers=[], expire_at=expire_at
            )

        profile_vec = self.embedder.encode([self.config.profiles[category]])[0]
        candidate_vecs = self.embedder.encode([c.embed_text for c in candidates])

        ranked = rank_top_k(profile_vec, candidate_vecs, self.config.top_k)

        papers: list[Paper] = []
        for rank, (idx, score) in enumerate(ranked, start=1):
            c = candidates[idx]
            summary = self.summarizer.summarize(c.title, c.abstract)
            papers.append(
                Paper(
                    rank=rank,
                    title=c.title,
                    arxiv_id=c.arxiv_id,
                    url=c.url,
                    score=score,
                    summary=summary,
                    abstract=c.abstract,
                )
            )
        log.info("lens %s: ranked %d papers", category, len(papers))
        return RunDocument(
            category=category, run_date=run_date, papers=papers, expire_at=expire_at
        )
