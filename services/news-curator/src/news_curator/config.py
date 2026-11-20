"""Runtime configuration, loaded from environment (mirrors paper-prism's config.py)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

log = logging.getLogger("news_curator.config")


@dataclass
class Config:
    sink: str  # "local" | "firestore"
    output_dir: str
    firestore_project: str | None
    firestore_database: str | None
    coarse_threshold: float
    cluster_distance_threshold: float
    top_k_per_category: int
    story_limit_per_category: int
    content_ready_topic: str | None = None

    @property
    def content_ready_enabled(self) -> bool:
        """Whether __main__.py should announce a finished run on Pub/Sub.

        Mirrors paper-prism's Config.content_ready_enabled: a SINK=local run
        produced no Firestore documents, so there is nothing a downstream
        consumer could read. main.py (the Cloud Run push entrypoint) does not
        consult this — it always writes to Firestore, so it always announces
        when canonical stories were selected.
        """
        return bool(self.content_ready_topic and self.firestore_project and self.sink == "firestore")


def load_config() -> Config:
    load_dotenv()

    return Config(
        sink=os.getenv("SINK", "local").strip().lower(),
        output_dir=os.getenv("OUTPUT_DIR", "output"),
        firestore_project=os.getenv("GOOGLE_CLOUD_PROJECT", "").strip() or None,
        # Empty -> the "(default)" database. Set to "feed-mind-db" in prod —
        # see the root CLAUDE.md's "database id must match in four places".
        firestore_database=os.getenv("FIRESTORE_DATABASE", "").strip() or None,
        # Below this cosine similarity to every coarse anchor, an article is
        # "uncategorized" and excluded from clustering (design doc §4.2).
        # Design doc §4.2 originally specified 0.28, but that was never
        # validated against this anchor text + MiniLM combination end to end
        # — the push subscription silently 403'd for months (see this
        # package's CLAUDE.md), so the first real run wasn't until
        # 2026-11-09. At 0.28 the best-anchor score across a 300-article
        # real sample topped out at 0.2782 — literally zero articles ever
        # classified, so every run reprocessed the same (growing) backlog
        # forever. 0.15 was picked by sampling 300 real pending articles:
        # best-anchor score p50=0.166, p75=0.218 — this clears the median
        # while still rejecting genuine non-news/off-taxonomy items (~46%
        # stayed uncategorized in that sample, which is expected per design
        # doc §4.2 — there is deliberately no `tech` anchor).
        coarse_threshold=float(os.getenv("COARSE_THRESHOLD", "0.15")),
        # Agglomerative clustering cutoff tau (design doc §4.4), complete
        # linkage — every pairwise distance within a cluster must clear this.
        # The doc flagged this as the number most likely to need tuning, and
        # 0.22 needed it: real same-event articles from different outlets
        # (verified against a live cross-outlet duplicate — three headlines
        # all covering one Trump-Xi-Putin trilateral) sat at cosine distance
        # 0.35-0.58, so almost nothing ever merged (1,327 of 1,339 IN/politics
        # stories over two months were single-article "clusters" — see
        # services/news-curator/CLAUDE.md). 0.4 was picked by sweeping
        # thresholds against a real day of 109 India-general articles: it
        # merges genuine duplicates (three-way Jensen Huang coverage, two
        # outlets' wording of the same plane crash) without yet merging
        # distinct stories, which starts happening at 0.55 (unrelated
        # election stories, a cricket final merged with a football final).
        cluster_distance_threshold=float(os.getenv("CLUSTER_DISTANCE_THRESHOLD", "0.4")),
        # Every cluster's canonical article gets a text summary (design doc
        # §4.6 update — see services/summarizer/CLAUDE.md's NEWS_STORIES
        # section). This only caps audio_eligible per coarse category, which
        # services/summarizer respects unless FEEDMIND_TTS=local, where the
        # cap doesn't apply. Raised from 5 to 10 alongside that change.
        top_k_per_category=int(os.getenv("TOP_K_PER_CATEGORY", "10")),
        # Standing cap on stories/(country, coarse_category) — see
        # pipeline.py's prune_category call and store.py's docstring on it.
        # Without this, every cluster that ever got written stays until its
        # 90-day TTL, so a category's displayed count grows roughly
        # linearly with days-since-the-pipeline-started rather than staying
        # at "today's top stories."
        story_limit_per_category=int(os.getenv("STORY_LIMIT_PER_CATEGORY", "20")),
        # Owned by services/summarizer, not this service — see events.py and
        # the root CLAUDE.md's "The Pub/Sub topic is owned by its consumer".
        content_ready_topic=os.getenv("CONTENT_READY_TOPIC", "feedmind-content-ready").strip() or None,
    )
