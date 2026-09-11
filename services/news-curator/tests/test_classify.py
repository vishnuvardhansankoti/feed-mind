import numpy as np
import pytest
from news_curator.classify import classify_business, classify_coarse

CODES = ["politics", "global", "business", "sports", "culture"]


# One extra dimension (index 5) that no anchor occupies, so a vector can point
# "away from every anchor" — with only 5 dims spanned by the anchors
# themselves, any unit vector's largest single component is at least 1/sqrt(5)
# =~ 0.447 (pigeonhole), which is already above COARSE_THRESHOLD and would make
# "below every anchor" impossible to construct.
_DIM = 6


def _basis(index: int, dim: int = _DIM) -> np.ndarray:
    vec = np.zeros(dim, dtype=np.float32)
    vec[index] = 1.0
    return vec


ANCHOR_VECS = np.vstack([_basis(i) for i in range(len(CODES))])


def test_classify_coarse_picks_the_nearest_anchor():
    embeddings = np.vstack([_basis(2), _basis(0)])  # business, politics
    labels = classify_coarse(embeddings, ANCHOR_VECS, CODES, threshold=0.28)
    assert labels == ["business", "politics"]


def test_classify_coarse_below_threshold_is_uncategorized():
    # Points entirely along the one axis no anchor occupies: zero similarity
    # to every anchor, well under 0.28.
    away = _basis(5)
    labels = classify_coarse(away[None, :], ANCHOR_VECS, CODES, threshold=0.28)
    assert labels == ["uncategorized"]


def test_classify_coarse_empty_input():
    assert classify_coarse(np.zeros((0, _DIM)), ANCHOR_VECS, CODES, threshold=0.28) == []


@pytest.mark.parametrize("threshold,expected", [(0.5, "business"), (0.95, "uncategorized")])
def test_classify_coarse_threshold_is_a_hard_cutoff(threshold, expected):
    # Similarity to "business" is exactly 0.9 here.
    vec = 0.9 * _basis(2) + np.sqrt(1 - 0.81) * _basis(3)
    labels = classify_coarse(vec[None, :], ANCHOR_VECS, CODES, threshold=threshold)
    assert labels == [expected]


def test_classify_business_picks_the_nearest_anchor():
    business_codes = ["markets", "economy", "companies", "portfolio", "personal_finance"]
    business_vecs = np.vstack([_basis(i) for i in range(len(business_codes))])

    assert classify_business(_basis(0), business_vecs, business_codes) == "markets"
    assert classify_business(_basis(2), business_vecs, business_codes) == "companies"
