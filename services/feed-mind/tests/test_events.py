import json

import pytest
from feedmind import config, events


class FakeFuture:
    def __init__(self, message_id="msg-1", error=None):
        self._message_id = message_id
        self._error = error

    def result(self, timeout=None):
        if self._error:
            raise self._error
        return self._message_id


class FakePublisher:
    """Records what was published instead of talking to Pub/Sub."""

    def __init__(self, error=None):
        self.calls = []
        self._error = error

    def publish(self, topic, data, **attributes):
        self.calls.append((topic, data, attributes))
        return FakeFuture(error=self._error)


@pytest.fixture
def publisher(monkeypatch):
    fake = FakePublisher()
    monkeypatch.setattr(events.pubsub_v1, "PublisherClient", lambda *a, **kw: fake)
    return fake


def test_publishes_when_articles_were_delivered(publisher):
    assert events.publish_content_ready(3) is True
    assert len(publisher.calls) == 1

    topic, data, attributes = publisher.calls[0]
    assert topic == (f"projects/{config.GCP_PROJECT_ID}/topics/{config.CONTENT_READY_TOPIC}")

    payload = json.loads(data.decode("utf-8"))
    assert payload["process_doc"] == config.CONTENT_READY_PROCESS_DOC
    assert payload["source"] == "feed-mind"
    assert payload["articles_delivered"] == 3
    assert payload["run_completed_at"]

    # Duplicated as attributes so a subscription can filter without decoding.
    assert attributes["process_doc"] == config.CONTENT_READY_PROCESS_DOC
    assert attributes["source"] == "feed-mind"


def test_run_summary_is_attached_when_given(publisher):
    events.publish_content_ready(1, run_summary={"feeds_checked": 12})

    _, data, _ = publisher.calls[0]
    assert json.loads(data.decode("utf-8"))["run_summary"] == {"feeds_checked": 12}


@pytest.mark.parametrize("delivered", [0, -1])
def test_skips_when_nothing_was_delivered(publisher, delivered):
    """Waking the consumer to find an empty batch costs a cold start for nothing."""
    assert events.publish_content_ready(delivered) is False
    assert publisher.calls == []


def test_skips_when_disabled(publisher, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_CONTENT_READY_EVENTS", False)
    assert events.publish_content_ready(5) is False
    assert publisher.calls == []


def test_publish_failure_is_swallowed(monkeypatch):
    """A run that delivered its articles must not fail at the announcement."""
    fake = FakePublisher(error=RuntimeError("pubsub is unreachable"))
    monkeypatch.setattr(events.pubsub_v1, "PublisherClient", lambda *a, **kw: fake)

    assert events.publish_content_ready(2) is False


def test_client_construction_failure_is_swallowed(monkeypatch):
    def explode(*a, **kw):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(events.pubsub_v1, "PublisherClient", explode)

    assert events.publish_content_ready(2) is False
