import numpy as np
from news_curator.models import CuratedArticle
from news_curator.rank import pick_canonical, score_cluster


def _article(article_id, snippet="", rss_rank=0, feed_length=1, feed_source="Outlet"):
    return CuratedArticle(
        article_id=article_id,
        url=f"https://example.com/{article_id}",
        title="Title",
        snippet=snippet,
        feed_source=feed_source,
        feed_category="general",
        published_at="2026-09-09T00:00:00Z",
        rss_rank=rss_rank,
        feed_length=feed_length,
    )


def test_score_cluster_matches_the_formula_by_hand():
    # N_PAPERS = 5 (anchors.py). One member, top of its feed, embedding
    # identical to the centroid: every term maxes out at 1.0.
    members = [_article("a1", rss_rank=0, feed_length=1)]
    member_vecs = np.array([[1.0, 0.0]])
    centroid = np.array([1.0, 0.0])

    score = score_cluster(members, member_vecs, centroid)
    assert np.isclose(score, 0.50 * (1 / 5) + 0.30 * 1.0 + 0.20 * 1.0)


def test_score_cluster_rewards_consensus_across_outlets():
    solo = [_article("a1")]
    solo_vecs = np.array([[1.0, 0.0]])

    pair = [_article("a1"), _article("a2", feed_source="Other Outlet")]
    pair_vecs = np.array([[1.0, 0.0], [1.0, 0.0]])

    centroid = np.array([1.0, 0.0])
    assert score_cluster(pair, pair_vecs, centroid) > score_cluster(solo, solo_vecs, centroid)


def test_score_cluster_rewards_editorial_placement():
    top_of_feed = [_article("a1", rss_rank=0, feed_length=50)]
    bottom_of_feed = [_article("a1", rss_rank=49, feed_length=50)]
    vecs = np.array([[1.0, 0.0]])
    centroid = np.array([1.0, 0.0])

    assert score_cluster(top_of_feed, vecs, centroid) > score_cluster(bottom_of_feed, vecs, centroid)


def test_pick_canonical_is_the_only_option_for_a_singleton():
    only = _article("a1", snippet="short")
    assert pick_canonical([only]) is only


def test_pick_canonical_picks_the_longest_description():
    short = _article("a1", snippet="short")
    long = _article("a2", snippet="a much longer description with more to work with")
    assert pick_canonical([short, long]) is long
