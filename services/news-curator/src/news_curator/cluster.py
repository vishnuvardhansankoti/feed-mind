"""Event clustering (design doc §4.4).

Agglomerative hierarchical clustering, complete linkage, cosine distance
d = 1 - cos, cutoff tau = 0.22, run independently within each coarse category
(never across categories — a politics article and a business article never
compete for the same cluster regardless of how similar their embeddings are).
"""

from __future__ import annotations

import numpy as np
from sklearn.cluster import AgglomerativeClustering


def cluster_indices(embeddings: np.ndarray, distance_threshold: float) -> list[list[int]]:
    """Group row indices of `embeddings` into clusters.

    Returns a list of index lists, one per cluster, in no particular order —
    ranking (rank.py) decides the order that matters.

    scikit-learn's AgglomerativeClustering requires at least 2 samples; 0 or 1
    articles in a coarse category are handled directly rather than as an error,
    since a single front-page snapshot can easily leave a category with one
    story on a quiet day.
    """
    n = embeddings.shape[0]
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    model = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="complete",
        distance_threshold=distance_threshold,
    )
    labels = model.fit_predict(embeddings)

    groups: dict[int, list[int]] = {}
    for index, label in enumerate(labels):
        groups.setdefault(int(label), []).append(index)
    return list(groups.values())


def centroid(embeddings: np.ndarray, indices: list[int]) -> np.ndarray:
    """L2-normalized mean embedding of a cluster's members.

    Normalized so cos(E(a), C_k) in the ranking formula (design doc §4.5)
    stays a plain dot product, consistent with every other similarity in this
    service.
    """
    vectors = embeddings[indices]
    mean = vectors.mean(axis=0)
    norm = np.linalg.norm(mean)
    return mean / norm if norm > 1e-9 else mean
