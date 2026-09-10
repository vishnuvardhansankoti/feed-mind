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
        coarse_threshold=float(os.getenv("COARSE_THRESHOLD", "0.28")),
        # Agglomerative clustering cutoff tau (design doc §4.4). The doc flags
        # this as the number most likely to need tuning against real output.
        cluster_distance_threshold=float(os.getenv("CLUSTER_DISTANCE_THRESHOLD", "0.22")),
        # Clusters marked canonical per coarse category (design doc §4.6).
        top_k_per_category=int(os.getenv("TOP_K_PER_CATEGORY", "5")),
    )
