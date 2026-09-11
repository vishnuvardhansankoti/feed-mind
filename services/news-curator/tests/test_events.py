"""Announcing a finished run (see events.py).

The Pub/Sub client is faked, so nothing here touches the network.
"""

import json
import sys
import types

import pytest
from news_curator import events
from news_curator.config import Config
from news_curator.models import CurationRunSummary


def _config(sink="firestore", project="feed-mind", topic="feedmind-content-ready"):
    return Config(
        sink=sink,
        output_dir="unused",
        firestore_project=project,
        firestore_database=None,
        coarse_threshold=0.28,
        cluster_distance_threshold=0.22,
        top_k_per_category=5,
        content_ready_topic=topic,
    )


def _summary(canonical=0, stories=0):
    return CurationRunSummary(canonical_selected=canonical, stories_written=stories)


class FakeFuture:
    def __init__(self, error=None):
        self._error = error

    def result(self, timeout=None):
        if self._error:
            raise self._error
        return "msg-1"


class FakePublisher:
    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def publish(self, topic, data, **attributes):
        self.calls.append((topic, data, attributes))
        return FakeFuture(self._error)


@pytest.fixture
def publisher(monkeypatch):
    """Install a fake `google.cloud.pubsub_v1` for the lazy import to find."""
    fake = FakePublisher()
    module = types.ModuleType("google.cloud.pubsub_v1")
    module.PublisherClient = lambda *a, **kw: fake
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", module)

    cloud = types.ModuleType("google.cloud")
    cloud.pubsub_v1 = module
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    return fake


def test_publishes_when_a_cluster_was_marked_canonical(publisher):
    summary = _summary(canonical=5, stories=25)
    assert events.publish_content_ready(_config(), summary) is True

    topic, data, attributes = publisher.calls[0]
    assert topic == "projects/feed-mind/topics/feedmind-content-ready"

    payload = json.loads(data.decode("utf-8"))
    assert payload["process_doc"] == "NEWS_STORIES"
    assert payload["source"] == "news-curator"
    assert payload["canonical_selected"] == 5
    assert payload["stories_written"] == 25

    assert attributes == {"process_doc": "NEWS_STORIES", "source": "news-curator"}


def test_skips_when_nothing_was_marked_canonical(publisher):
    """Waking the consumer for an empty batch costs a cold start for nothing."""
    assert events.publish_content_ready(_config(), _summary(canonical=0, stories=25)) is False
    assert publisher.calls == []


def test_skips_for_a_local_run(publisher):
    """A local tuning run writes JSON to disk — there is no consumer to tell."""
    assert events.publish_content_ready(_config(sink="local"), _summary(canonical=5)) is False
    assert publisher.calls == []


@pytest.mark.parametrize("missing", [{"topic": None}, {"project": None}])
def test_skips_when_unconfigured(publisher, missing):
    assert events.publish_content_ready(_config(**missing), _summary(canonical=5)) is False
    assert publisher.calls == []


def test_publish_failure_is_swallowed(monkeypatch):
    """The stories are already in Firestore; the run must not fail here."""
    fake = FakePublisher(error=RuntimeError("pubsub is unreachable"))
    module = types.ModuleType("google.cloud.pubsub_v1")
    module.PublisherClient = lambda *a, **kw: fake
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", module)
    cloud = types.ModuleType("google.cloud")
    cloud.pubsub_v1 = module
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)

    assert events.publish_content_ready(_config(), _summary(canonical=5)) is False


def test_content_ready_enabled_requires_firestore_sink():
    assert _config().content_ready_enabled is True
    assert _config(sink="local").content_ready_enabled is False
    assert _config(project=None).content_ready_enabled is False
    assert _config(topic=None).content_ready_enabled is False
