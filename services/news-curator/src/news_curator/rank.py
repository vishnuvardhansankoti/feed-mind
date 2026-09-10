"""Cluster scoring (design doc §4.5).

Score(c) = 0.50 * (|c| / N_papers)
         + 0.30 * mean over a in c of (1 - rss_rank(a) / len(feed_of(a)))
         + 0.20 * mean over a in c of cos(E(a), C_k)

Clusters sort descending within each coarse category; the top TOP_K_PER_CATEGORY
(config.py) are marked canonical (design doc §4.6).
"""

from __future__ import annotations

import numpy as np

from .anchors import N_PAPERS
from .models import CuratedArticle

CONSENSUS_WEIGHT = 0.50
PLACEMENT_WEIGHT = 0.30
SIMILARITY_WEIGHT = 0.20


def score_cluster(
    members: list[CuratedArticle], member_embeddings: np.ndarray, centroid: np.ndarray
) -> float:
    consensus = len(members) / N_PAPERS
    placement = sum(article.placement_score for article in members) / len(members)
    similarity = float((member_embeddings @ centroid).mean())

    return (
        CONSENSUS_WEIGHT * consensus
        + PLACEMENT_WEIGHT * placement
        + SIMILARITY_WEIGHT * similarity
    )


def pick_canonical(members: list[CuratedArticle]) -> CuratedArticle:
    """The cluster member with the most to say, so the one LLM call downstream
    (services/summarizer) has the most context.

    Design doc §4.6 picks by word count in the *scraped* body — this service
    never scrapes (design doc §7's dependency list has no HTTP/extraction
    library, deliberately: news-curator embeds title+description only). The
    longest RSS description is the closest available proxy at curation time;
    see this package's CLAUDE.md for the full reasoning. A single-member
    cluster has nothing to pick between.
    """
    if len(members) == 1:
        return members[0]
    return max(members, key=lambda article: len(article.snippet))
