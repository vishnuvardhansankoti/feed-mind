from datetime import UTC, datetime

import pytest
from feedmind_core import settings as config
from feedmind_core.ingestion import Article
from feedmind_core.store import is_duplicate, save_article


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
    save_article(db, _article(), "A one-sentence summary.")

    assert _written(db)["snippet"] == "Some fetched article prose."


def test_empty_snippet_is_still_written(db):
    # Feeds with no summary/description yield "". The field must exist either
    # way so the archive schema does not have to distinguish missing from empty.
    save_article(db, _article(snippet=""), "A summary.")

    assert _written(db)["snippet"] == ""


def test_existing_fields_are_unchanged(db):
    save_article(db, _article(), "A one-sentence summary.")

    payload = _written(db)
    assert payload["article_id"] == "abc123"
    assert payload["url"] == "https://example.com/post"
    assert payload["title"] == "A Title"
    assert payload["summary"] == "A one-sentence summary."
    assert payload["feed_source"] == "Example Feed"
    assert payload["feed_category"] == "industry"
    # "stored", not the old "delivered": this write no longer implies anything
    # about Telegram delivery, which telegram_status tracks separately.
    assert payload["status"] == "stored"
    assert payload["telegram_status"] == config.TELEGRAM_SKIPPED
    # Firestore TTL requires a native datetime, not an ISO string.
    assert isinstance(payload["expires_at"], datetime)
    assert isinstance(payload["processed_at"], str)


def test_is_duplicate_reflects_document_existence():
    assert is_duplicate(FakeClient(existing_ids={"abc123"}), _article()) is True
    assert is_duplicate(FakeClient(), _article()) is False


# ---------------------------------------------------------------------------
# Telegram delivery state
# ---------------------------------------------------------------------------
# The pipeline used to write a document only after Telegram accepted it, so
# "document exists" meant "delivered". Ingest and delivery are separate
# functions now, so that state is an explicit field — and these tests are what
# stop it from silently regressing to always-pending or always-sent.


def test_save_article_defaults_to_skipped(db):
    """The safe default: a service that forgets to ask for delivery gets none.

    The opposite default would turn a config omission into an unexpected
    Telegram flood.
    """
    save_article(db, _article(), "summary")
    payload = db.collection(config.FIRESTORE_COLLECTION).document("abc123").written
    assert payload["telegram_status"] == config.TELEGRAM_SKIPPED


def test_save_article_marks_pending_when_asked(db):
    save_article(db, _article(), "summary", telegram_status=config.TELEGRAM_PENDING)
    payload = db.collection(config.FIRESTORE_COLLECTION).document("abc123").written
    assert payload["telegram_status"] == config.TELEGRAM_PENDING


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class FakeQuery:
    """Captures the filter/limit a query was built with, then replays rows."""

    def __init__(self, rows):
        self._rows = rows
        self.filters = []
        self.limit_value = None

    def where(self, filter=None):  # noqa: A002 - matches the Firestore kwarg
        self.filters.append(filter)
        return self

    def limit(self, n):
        self.limit_value = n
        return self

    def stream(self):
        return iter(self._rows)


class QueryableCollection(FakeCollection):
    def __init__(self, name, rows):
        super().__init__(name)
        self.query = FakeQuery(rows)

    def where(self, filter=None):  # noqa: A002
        return self.query.where(filter=filter)


def _pending_db(rows):
    client = FakeClient()
    client.collections[config.FIRESTORE_COLLECTION] = QueryableCollection(
        config.FIRESTORE_COLLECTION, rows
    )
    return client


def test_fetch_pending_returns_articles_oldest_first():
    """Ordering happens in Python, not Firestore.

    An order_by on published_at alongside the telegram_status filter would
    need a composite index deployed before the notifier could run at all.
    """
    rows = [
        FakeSnapshot("b", {"article_id": "b", "url": "https://e.com/b", "title": "B",
                           "summary": "s2", "published_at": "2026-01-02T00:00:00+00:00"}),
        FakeSnapshot("a", {"article_id": "a", "url": "https://e.com/a", "title": "A",
                           "summary": "s1", "published_at": "2026-01-01T00:00:00+00:00"}),
    ]
    from feedmind_core.store import fetch_pending_telegram

    items = fetch_pending_telegram(_pending_db(rows), limit=50)
    assert [article.article_id for article, _summary in items] == ["a", "b"]
    assert [summary for _article, summary in items] == ["s1", "s2"]


def test_fetch_pending_skips_unrenderable_documents():
    """A doc with no url/title can never be sent.

    Kept in the queue it would be re-read on every single run forever, so it is
    dropped from the batch rather than stranding the notifier.
    """
    rows = [
        FakeSnapshot("ok", {"article_id": "ok", "url": "https://e.com/ok", "title": "Fine",
                            "published_at": "2026-01-01T00:00:00+00:00"}),
        FakeSnapshot("bad", {"article_id": "bad", "title": "No URL"}),
        FakeSnapshot("worse", {"article_id": "worse", "url": "https://e.com/x"}),
    ]
    from feedmind_core.store import fetch_pending_telegram

    items = fetch_pending_telegram(_pending_db(rows))
    assert [article.article_id for article, _ in items] == ["ok"]


def test_fetch_pending_applies_the_limit():
    from feedmind_core.store import fetch_pending_telegram

    db = _pending_db([])
    fetch_pending_telegram(db, limit=7)
    assert db.collections[config.FIRESTORE_COLLECTION].query.limit_value == 7


class FakeBatch:
    def __init__(self):
        self.updates = []
        self.commits = 0

    def update(self, ref, payload):
        self.updates.append((ref.id, payload))

    def commit(self):
        self.commits += 1


class BatchingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.batches = []

    def batch(self):
        b = FakeBatch()
        self.batches.append(b)
        return b


def test_mark_sent_flips_status():
    from feedmind_core.store import mark_telegram_sent

    db = BatchingClient()
    assert mark_telegram_sent(db, ["a", "b"]) == 2
    assert db.batches[0].updates == [
        ("a", {"telegram_status": config.TELEGRAM_SENT}),
        ("b", {"telegram_status": config.TELEGRAM_SENT}),
    ]
    assert db.batches[0].commits == 1


def test_mark_sent_chunks_at_the_firestore_batch_limit():
    """Firestore rejects a batch over 500 writes; a backlog can exceed that."""
    from feedmind_core.store import mark_telegram_sent

    db = BatchingClient()
    assert mark_telegram_sent(db, [str(i) for i in range(1201)]) == 1201
    assert [len(b.updates) for b in db.batches] == [500, 500, 201]
