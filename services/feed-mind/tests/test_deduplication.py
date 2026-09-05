from datetime import UTC, datetime

import pytest
from feedmind import config
from feedmind.deduplication import is_duplicate, mark_as_delivered
from feedmind.ingestion import Article


class FakeDocument:
    """Records writes instead of talking to Firestore."""

    def __init__(self, doc_id, exists=False):
        self.id = doc_id
        self.exists = exists
        self.written = None

    def get(self):
        return self

    def set(self, payload):
        self.written = payload


class FakeCollection:
    def __init__(self, name, existing_ids=()):
        self.name = name
        self._docs = {}
        self._existing_ids = set(existing_ids)

    def document(self, doc_id):
        if doc_id not in self._docs:
            self._docs[doc_id] = FakeDocument(doc_id, exists=doc_id in self._existing_ids)
        return self._docs[doc_id]


class FakeClient:
    def __init__(self, existing_ids=()):
        self.collections = {}
        self._existing_ids = existing_ids

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection(name, self._existing_ids)
        return self.collections[name]


def _article(snippet="Some fetched article prose."):
    return Article(
        article_id="abc123",
        url="https://example.com/post",
        title="A Title",
        snippet=snippet,
        feed_source="Example Feed",
        feed_category="industry",
        published_at=datetime.now(UTC).isoformat(),
    )


@pytest.fixture
def db():
    return FakeClient()


def _written(db):
    return db.collection(config.FIRESTORE_COLLECTION).document("abc123").written


def test_snippet_is_persisted(db):
    # Nothing in this pipeline reads snippet back; it is written so the BigQuery
    # archive has real text. A doc can only be archived with what lands here.
    mark_as_delivered(db, _article(), "A one-sentence summary.")

    assert _written(db)["snippet"] == "Some fetched article prose."


def test_empty_snippet_is_still_written(db):
    # Feeds with no summary/description yield "". The field must exist either
    # way so the archive schema does not have to distinguish missing from empty.
    mark_as_delivered(db, _article(snippet=""), "A summary.")

    assert _written(db)["snippet"] == ""


def test_existing_fields_are_unchanged(db):
    mark_as_delivered(db, _article(), "A one-sentence summary.")

    payload = _written(db)
    assert payload["article_id"] == "abc123"
    assert payload["url"] == "https://example.com/post"
    assert payload["title"] == "A Title"
    assert payload["summary"] == "A one-sentence summary."
    assert payload["feed_source"] == "Example Feed"
    assert payload["feed_category"] == "industry"
    assert payload["status"] == "delivered"
    # Firestore TTL requires a native datetime, not an ISO string.
    assert isinstance(payload["expires_at"], datetime)
    assert isinstance(payload["processed_at"], str)


def test_is_duplicate_reflects_document_existence():
    assert is_duplicate(FakeClient(existing_ids={"abc123"}), _article()) is True
    assert is_duplicate(FakeClient(), _article()) is False
