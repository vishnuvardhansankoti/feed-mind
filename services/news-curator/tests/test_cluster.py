import numpy as np
from news_curator.cluster import centroid, cluster_indices


def test_empty_input():
    assert cluster_indices(np.zeros((0, 4)), distance_threshold=0.22) == []


def test_single_article_is_its_own_cluster():
    embeddings = np.array([[1.0, 0.0, 0.0, 0.0]])
    assert cluster_indices(embeddings, distance_threshold=0.22) == [[0]]


def test_near_duplicates_across_outlets_merge_into_one_cluster():
    # Same event, five-outlet coverage: near-identical embeddings.
    base = np.array([1.0, 0.0, 0.0])
    embeddings = np.vstack([base, base * 0.99 + np.array([0, 0.02, 0]), base])
    clusters = cluster_indices(embeddings, distance_threshold=0.22)
    assert len(clusters) == 1
    assert sorted(clusters[0]) == [0, 1, 2]


def test_unrelated_stories_stay_separate():
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])  # cosine distance 1.0 from a — well past tau
    clusters = cluster_indices(np.vstack([a, b]), distance_threshold=0.22)
    assert sorted(len(c) for c in clusters) == [1, 1]


def test_centroid_is_normalized_and_points_toward_the_members():
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
    c = centroid(embeddings, [0, 1])
    assert np.isclose(np.linalg.norm(c), 1.0)
    assert c[0] > 0 and c[1] > 0


def test_centroid_of_a_singleton_is_itself():
    embeddings = np.array([[0.6, 0.8]])  # already unit length
    c = centroid(embeddings, [0])
    assert np.allclose(c, embeddings[0])
