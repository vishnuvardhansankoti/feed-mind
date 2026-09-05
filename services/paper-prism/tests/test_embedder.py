"""Ranking math — pure numpy, no model download required."""

import numpy as np
from paper_prism.embedder import _mean_pool_normalize, rank_top_k


def test_rank_top_k_orders_by_cosine_descending():
    profile = np.array([1.0, 0.0], dtype=np.float32)
    candidates = np.array(
        [
            [0.0, 1.0],  # idx 0: orthogonal -> 0.0
            [1.0, 0.0],  # idx 1: identical  -> 1.0
            [0.7, 0.7],  # idx 2: partial    -> 0.7
        ],
        dtype=np.float32,
    )
    ranked = rank_top_k(profile, candidates, k=3)
    assert [idx for idx, _ in ranked] == [1, 2, 0]
    assert ranked[0][1] > ranked[1][1] > ranked[2][1]


def test_rank_top_k_clamps_k_to_available():
    profile = np.array([1.0, 0.0], dtype=np.float32)
    candidates = np.array([[1.0, 0.0]], dtype=np.float32)
    ranked = rank_top_k(profile, candidates, k=5)
    assert len(ranked) == 1


def test_rank_top_k_empty_returns_empty():
    profile = np.array([1.0, 0.0], dtype=np.float32)
    assert rank_top_k(profile, np.zeros((0, 2), dtype=np.float32), k=3) == []


def test_mean_pool_normalize_is_unit_length_and_masks_padding():
    # token 1 is real, token 2 is padding (mask 0) -> only the first is pooled.
    hidden = np.array([[[3.0, 4.0], [100.0, 100.0]]], dtype=np.float32)
    mask = np.array([[1, 0]], dtype=np.int64)
    out = _mean_pool_normalize(hidden, mask)
    np.testing.assert_allclose(np.linalg.norm(out, axis=1), [1.0], rtol=1e-5)
    # pooled == [3,4] normalized == [0.6, 0.8]
    np.testing.assert_allclose(out[0], [0.6, 0.8], rtol=1e-5)
