"""Zero-shot classification: nearest anchor by cosine similarity (design doc §4.2, §4.3).

Vectors are L2-normalized (embedder.py), so cosine similarity is a dot
product — no separate normalization step needed here.
"""

from __future__ import annotations

import numpy as np

from .anchors import BUSINESS_ANCHORS, COARSE_ANCHORS, UNCATEGORIZED


def classify_coarse(
    embeddings: np.ndarray, anchor_vecs: np.ndarray, anchor_codes: list[str], threshold: float
) -> list[str]:
    """Assign each row of `embeddings` to its nearest anchor, or UNCATEGORIZED.

    `anchor_vecs` / `anchor_codes` are parallel: row i of anchor_vecs is the
    embedding of COARSE_ANCHORS[anchor_codes[i]]. Passed in rather than
    recomputed so the caller embeds the (small, fixed) anchor set once.
    """
    if embeddings.shape[0] == 0:
        return []

    similarities = embeddings @ anchor_vecs.T  # (n, k)
    best_idx = np.argmax(similarities, axis=1)
    best_score = similarities[np.arange(len(best_idx)), best_idx]

    return [
        anchor_codes[idx] if score >= threshold else UNCATEGORIZED
        for idx, score in zip(best_idx, best_score, strict=True)
    ]


def classify_business(embedding: np.ndarray, anchor_vecs: np.ndarray, anchor_codes: list[str]) -> str:
    """Nearest business anchor for one (canonical article's) embedding.

    No threshold here — design doc §4.3 does not specify one for the detailed
    taxonomy; eligibility for a business sub-category is decided by the caller
    (coarse category + outlet, see anchors.BUSINESS_ELIGIBLE_SOURCES) before
    this is ever called.
    """
    similarities = anchor_vecs @ embedding
    return anchor_codes[int(np.argmax(similarities))]


def anchor_matrix(anchors: dict[str, str], embed_fn) -> tuple[np.ndarray, list[str]]:
    """Embed an anchor dict once; returns (vectors, codes) in matching order."""
    codes = list(anchors)
    vectors = embed_fn([anchors[code] for code in codes])
    return vectors, codes


def coarse_anchor_matrix(embed_fn) -> tuple[np.ndarray, list[str]]:
    return anchor_matrix(COARSE_ANCHORS, embed_fn)


def business_anchor_matrix(embed_fn) -> tuple[np.ndarray, list[str]]:
    return anchor_matrix(BUSINESS_ANCHORS, embed_fn)
