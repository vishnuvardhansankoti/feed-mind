"""End-to-end pipeline test with a fake embedder — no ONNX model, no network.

The fake embedder maps known strings to hand-picked vectors in a 10-dim space:
dims 0-4 are the coarse anchors (politics, global, business, sports, culture,
in COARSE_ANCHORS' order), dims 5-9 are the business anchors (markets,
economy, companies, portfolio, personal_finance, in BUSINESS_ANCHORS' order).
Every anchor is a pure basis vector, so cosine similarity between an article
and an anchor is just that anchor's coordinate.
"""

from __future__ import annotations

import numpy as np
import pytest
from news_curator.anchors import BUSINESS_ANCHORS, COARSE_ANCHORS
from news_curator.config import Config
from news_curator.models import CuratedArticle
from news_curator.pipeline import run

DIM = 10


def _basis(*indices_and_weights: tuple[int, float]) -> np.ndarray:
    vec = np.zeros(DIM, dtype=np.float32)
    for index, weight in indices_and_weights:
        vec[index] = weight
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


# Anchor vectors: pure basis vectors in coarse-anchor order / business-anchor order.
_COARSE_CODES = list(COARSE_ANCHORS)  # ["politics", "global", "business", "sports", "culture"]
_BUSINESS_CODES = list(BUSINESS_ANCHORS)  # ["markets", "economy", "companies", ...]

_ANCHOR_VECTORS = {
    COARSE_ANCHORS[code]: _basis((i, 1.0)) for i, code in enumerate(_COARSE_CODES)
}
_ANCHOR_VECTORS.update(
    {BUSINESS_ANCHORS[code]: _basis((5 + i, 1.0)) for i, code in enumerate(_BUSINESS_CODES)}
)

# Article vectors, keyed by the exact embed_text pipeline.py will construct.
# A1/A2: the same RBI story, covered by two outlets -> should merge into one
#        "markets" cluster. A3: an unrelated business story ("companies").
#        A4: a sports story, alone in its coarse category. A5: nothing like
#        any anchor -> uncategorized.
_A1 = CuratedArticle(
    article_id="a1", url="https://example.com/a1", title="RBI holds repo rate",
    snippet="short.", feed_source="Economic Times", feed_category="business",
    published_at="2026-09-09T01:00:00Z",
)
_A2 = CuratedArticle(
    article_id="a2", url="https://example.com/a2", title="RBI keeps rates unchanged",
    snippet="A much longer writeup of the same monetary policy decision, with more detail.",
    feed_source="Business Standard", feed_category="business",
    published_at="2026-09-09T02:00:00Z",
)
_A3 = CuratedArticle(
    article_id="a3", url="https://example.com/a3", title="Startup raises Series B",
    snippet="A fintech startup closed a funding round.", feed_source="Hindu BusinessLine",
    feed_category="business", published_at="2026-09-09T03:00:00Z",
)
_A4 = CuratedArticle(
    article_id="a4", url="https://example.com/a4", title="India wins the T20 series",
    snippet="A cricket match report.", feed_source="Times of India", feed_category="general",
    published_at="2026-09-09T04:00:00Z",
)
_A5 = CuratedArticle(
    article_id="a5", url="https://example.com/a5", title="Ambiguous filler",
    snippet="Nothing in particular.", feed_source="The Hindu", feed_category="general",
    published_at="2026-09-09T05:00:00Z",
)

_ARTICLE_VECTORS = {
    _A1.embed_text: _basis((2, 0.8), (5, 0.6)),  # business + markets
    _A2.embed_text: _basis((2, 0.8), (5, 0.6)),  # identical -> merges with A1
    _A3.embed_text: _basis((2, 0.8), (7, 0.6)),  # business + companies, different cluster
    _A4.embed_text: _basis((3, 1.0)),            # pure sports
    _A5.embed_text: _basis((5, 1.0)),            # a business-subtopic axis, zero on every coarse axis
}


class FakeEmbedder:
    def encode(self, texts: list[str]) -> np.ndarray:
        try:
            return np.vstack(
                [_ANCHOR_VECTORS[t] if t in _ANCHOR_VECTORS else _ARTICLE_VECTORS[t] for t in texts]
            )
        except KeyError as exc:
            raise AssertionError(f"test did not define a fake vector for: {exc}") from exc


class FakeSink:
    def __init__(self) -> None:
        self.stories = []
        self.clustered = []

    def write_story(self, story) -> None:
        self.stories.append(story)

    def mark_clustered(self, article_id, story_id, is_canonical, audio_eligible) -> None:
        self.clustered.append((article_id, story_id, is_canonical, audio_eligible))


@pytest.fixture
def config() -> Config:
    return Config(
        sink="local",
        output_dir="unused",
        firestore_project=None,
        firestore_database=None,
        coarse_threshold=0.28,
        cluster_distance_threshold=0.22,
        top_k_per_category=1,
    )


def test_no_articles_short_circuits(config):
    sink = FakeSink()
    summary = run(config, FakeEmbedder(), [], sink)
    assert summary.articles_read == 0
    assert sink.stories == []


def test_cross_outlet_duplicates_merge_and_outrank_a_singleton(config):
    sink = FakeSink()
    summary = run(config, FakeEmbedder(), [_A1, _A2, _A3, _A4, _A5], sink)

    business_stories = {s.story_id: s for s in sink.stories if s.coarse_category == "business"}
    assert len(business_stories) == 2  # {a1, a2} and {a3}

    top = next(s for s in business_stories.values() if s.rank == 1)
    assert top.cluster_size == 2
    assert {a["url"] for a in top.related_articles} | {top.canonical["url"]} == {_A1.url, _A2.url}

    # Every cluster's canonical article is marked is_canonical (gets a text
    # summary); top_k_per_category=1 only gates audio_eligible.
    top_canonical = next(c for c in sink.clustered if c[1] == top.story_id and c[2])
    assert top_canonical[3] is True  # rank 1 <= top_k_per_category=1

    runner_up = next(s for s in business_stories.values() if s.rank == 2)
    assert runner_up.cluster_size == 1
    runner_up_canonical = next(c for c in sink.clustered if c[1] == runner_up.story_id and c[2])
    assert runner_up_canonical[3] is False  # rank 2 > top_k_per_category=1

    assert summary.canonical_selected == 3  # every cluster's canonical article: business (2) + sports (1)


def test_canonical_is_the_longest_description(config):
    sink = FakeSink()
    run(config, FakeEmbedder(), [_A1, _A2], sink)

    story = sink.stories[0]
    # A2's snippet is longer than A1's — see the fixtures above.
    assert story.canonical_article_id == _A2.article_id
    assert story.related_articles == [{"source": _A1.feed_source, "url": _A1.url, "title": _A1.title}]


def test_business_subcategory_assigned_when_eligible(config):
    sink = FakeSink()
    run(config, FakeEmbedder(), [_A1, _A2, _A3], sink)

    by_id = {s.canonical_article_id: s for s in sink.stories}
    assert by_id[_A2.article_id].business_category == "markets"
    assert by_id[_A3.article_id].business_category == "companies"


def test_uncategorized_articles_are_excluded_and_counted(config):
    sink = FakeSink()
    summary = run(config, FakeEmbedder(), [_A5], sink)

    assert sink.stories == []
    assert summary.articles_uncategorized == 1


def test_sports_singleton_is_its_own_story(config):
    sink = FakeSink()
    run(config, FakeEmbedder(), [_A4], sink)

    assert len(sink.stories) == 1
    story = sink.stories[0]
    assert story.coarse_category == "sports"
    assert story.business_category is None
    assert story.canonical_article_id == _A4.article_id


def test_mark_clustered_flags_only_the_selected_canonical(config):
    sink = FakeSink()
    run(config, FakeEmbedder(), [_A1, _A2, _A3], sink)

    flags = {
        article_id: is_canonical
        for article_id, _story_id, is_canonical, _audio_eligible in sink.clustered
    }
    # {a1, a2}: only a2 (the canonical pick) is True.
    assert flags[_A1.article_id] is False
    assert flags[_A2.article_id] is True
    # {a3} is its own cluster's only member, so it is that cluster's
    # canonical pick too — is_canonical no longer depends on top_k_per_category.
    assert flags[_A3.article_id] is True

    audio_eligible = {
        article_id: audio_eligible
        for article_id, _story_id, _is_canonical, audio_eligible in sink.clustered
    }
    # {a3} is rank 2, below top_k_per_category=1: not eligible for audio.
    assert audio_eligible[_A3.article_id] is False


def test_story_id_encodes_country_category_run_date_and_rank(config):
    sink = FakeSink()
    run(config, FakeEmbedder(), [_A1, _A2, _A3], sink)

    ids = sorted(s.story_id for s in sink.stories)
    # _A1/_A2/_A3 default to country="IN" (CuratedArticle's default).
    assert ids[0].startswith("in_business_")
    assert ids[0].endswith("_01")
    assert ids[1].endswith("_02")


def test_story_carries_its_country(config):
    sink = FakeSink()
    run(config, FakeEmbedder(), [_A1, _A2], sink)
    assert sink.stories[0].country == "IN"


# ---------------------------------------------------------------------------
# Country isolation: a US and an India article must never share a cluster,
# even when they are otherwise identical (same coarse category, same vector).
# ---------------------------------------------------------------------------

_A1_US = CuratedArticle(
    article_id="a1-us", url="https://example.com/a1-us", title="Fed holds rates steady",
    snippet="short.", feed_source="CNBC", feed_category="business",
    published_at="2026-09-09T01:00:00Z", country="US",
)
_A2_US = CuratedArticle(
    article_id="a2-us", url="https://example.com/a2-us", title="Fed keeps rates unchanged",
    snippet="A much longer writeup of the same Fed decision, with more detail.",
    feed_source="MarketWatch", feed_category="business",
    published_at="2026-09-09T02:00:00Z", country="US",
)

# Deliberately the *same* vector A1/A2 (India) use, to prove country — not
# embedding distance — is what keeps the two apart.
_ARTICLE_VECTORS[_A1_US.embed_text] = _ARTICLE_VECTORS[_A1.embed_text]
_ARTICLE_VECTORS[_A2_US.embed_text] = _ARTICLE_VECTORS[_A2.embed_text]


def test_us_and_india_never_merge_even_with_identical_embeddings(config):
    sink = FakeSink()
    run(config, FakeEmbedder(), [_A1, _A2, _A1_US, _A2_US], sink)

    business_stories = [s for s in sink.stories if s.coarse_category == "business"]
    assert len(business_stories) == 2  # one IN cluster, one US cluster, never merged

    by_country = {s.country: s for s in business_stories}
    assert by_country["IN"].cluster_size == 2
    assert by_country["US"].cluster_size == 2
    assert by_country["IN"].story_id.startswith("in_business_")
    assert by_country["US"].story_id.startswith("us_business_")


def test_ranking_uses_each_countrys_own_outlet_count(config):
    # A US-only run and an India-only run of the *same shape* cluster score
    # identically only because anchors.N_PAPERS_BY_COUNTRY happens to be 5 for
    # both today — score_cluster still receives a country-specific n_papers,
    # not a shared global constant. See rank.py's test coverage for the case
    # where the counts differ.
    sink_in = FakeSink()
    run(config, FakeEmbedder(), [_A1, _A2], sink_in)

    sink_us = FakeSink()
    run(config, FakeEmbedder(), [_A1_US, _A2_US], sink_us)

    assert sink_in.stories[0].score == sink_us.stories[0].score
