"""Announcing a finished run (see events.py).

The Pub/Sub client is faked, so nothing here touches the network.
"""

import json
import sys
import types

import pytest
from paper_prism import events
from paper_prism.config import Config
from paper_prism.models import RunStatus, utc_run_date


def _config(sink="firestore", project="feed-mind", topic="feedmind-content-ready"):
    return Config(
        profiles={"AIML": "a", "NLP": "n", "CV": "c"},
        gemini_api_key=None,
        gemini_model="gemini-3.6-flash",
        sink=sink,
        window_days=7,
        top_k=3,
        retention_days=45,
        arxiv_page_size=100,
        arxiv_throttle_seconds=0.0,
        arxiv_max_pages=1,
        output_dir="unused",
        firestore_project=project,
        content_ready_topic=topic,
    )


def _status(**categories):
    status = RunStatus(run_date=utc_run_date())
    for category, count in categories.items():
        if count is None:
            status.mark_skipped(category, reason="Boom")
        else:
            status.mark_ok(category, count)
    return status


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


# ---------------------------------------------------------------------------
def test_papers_written_counts_only_successful_lenses():
    status = _status(AIML=3, NLP=None, CV=2)
    assert events.papers_written(status) == 5


def test_publishes_when_papers_were_written(publisher):
    status = _status(AIML=3, CV=2)
    assert events.publish_content_ready(_config(), status) is True

    topic, data, attributes = publisher.calls[0]
    assert topic == "projects/feed-mind/topics/feedmind-content-ready"

    payload = json.loads(data.decode("utf-8"))
    assert payload["process_doc"] == "RESEARCH_PAPERS"
    assert payload["source"] == "paper-prism"
    assert payload["papers_written"] == 5
    assert payload["run_date"] == status.doc_id
    assert payload["categories"]["AIML"]["paper_count"] == 3

    assert attributes == {"process_doc": "RESEARCH_PAPERS", "source": "paper-prism"}


def test_skips_when_no_papers_were_written(publisher):
    """Waking the consumer for an empty batch costs a cold start for nothing."""
    assert events.publish_content_ready(_config(), _status(AIML=0)) is False
    assert publisher.calls == []


def test_skips_when_every_lens_failed(publisher):
    assert events.publish_content_ready(_config(), _status(AIML=None, CV=None)) is False
    assert publisher.calls == []


def test_skips_for_a_local_run(publisher):
    """A local run writes JSON to disk — there is no consumer to tell."""
    assert events.publish_content_ready(_config(sink="local"), _status(AIML=3)) is False
    assert publisher.calls == []


@pytest.mark.parametrize("missing", [{"topic": None}, {"project": None}])
def test_skips_when_unconfigured(publisher, missing):
    assert events.publish_content_ready(_config(**missing), _status(AIML=3)) is False
    assert publisher.calls == []


def test_publish_failure_is_swallowed(monkeypatch):
    """The papers are already in Firestore; the run must not fail here."""
    fake = FakePublisher(error=RuntimeError("pubsub is unreachable"))
    module = types.ModuleType("google.cloud.pubsub_v1")
    module.PublisherClient = lambda *a, **kw: fake
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", module)
    cloud = types.ModuleType("google.cloud")
    cloud.pubsub_v1 = module
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)

    assert events.publish_content_ready(_config(), _status(AIML=3)) is False


def test_missing_client_library_is_swallowed(monkeypatch):
    """The image installs google-cloud-pubsub; a local checkout may not have it."""
    monkeypatch.setitem(sys.modules, "google.cloud.pubsub_v1", None)

    assert events.publish_content_ready(_config(), _status(AIML=3)) is False


def test_content_ready_enabled_requires_firestore_sink():
    assert _config().content_ready_enabled is True
    assert _config(sink="local").content_ready_enabled is False
    assert _config(project=None).content_ready_enabled is False
    assert _config(topic=None).content_ready_enabled is False
