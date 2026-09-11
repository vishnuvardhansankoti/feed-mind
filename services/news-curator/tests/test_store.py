"""fetch_pending_articles's country defaulting — the one bit of new logic in
store.py worth a direct test (everything else is exercised through
pipeline.py's FakeSink in test_pipeline.py).
"""

from news_curator.store import fetch_pending_articles


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data

    def to_dict(self):
        return self._data


class FakeQuery:
    def __init__(self, docs):
        self._docs = docs

    def where(self, filter):
        return self

    def stream(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def where(self, filter):
        return FakeQuery(self._docs)


class FakeDB:
    def __init__(self, docs):
        self._docs = docs

    def collection(self, name):
        return FakeCollection(self._docs)


def _doc(doc_id, **overrides):
    base = {
        "article_id": doc_id,
        "url": f"https://example.com/{doc_id}",
        "title": "A title",
        "snippet": "",
        "feed_source": "Outlet",
        "feed_category": "general",
        "published_at": "2026-09-10T00:00:00Z",
    }
    base.update(overrides)
    return base


def test_country_is_read_from_the_document():
    db = FakeDB([FakeSnapshot("a1", _doc("a1", country="US"))])
    articles = fetch_pending_articles(db)
    assert articles[0].country == "US"


def test_missing_country_defaults_to_india():
    # Every document written before this field existed — India was the only
    # country then, so absence unambiguously means "IN".
    db = FakeDB([FakeSnapshot("a1", _doc("a1"))])
    articles = fetch_pending_articles(db)
    assert articles[0].country == "IN"


def test_empty_string_country_also_defaults_to_india():
    # `doc.get("country") or DEFAULT_COUNTRY` treats "" the same as missing —
    # a malformed write should not silently produce an uncountried article.
    db = FakeDB([FakeSnapshot("a1", _doc("a1", country=""))])
    articles = fetch_pending_articles(db)
    assert articles[0].country == "IN"


def test_unrenderable_documents_are_skipped():
    db = FakeDB([FakeSnapshot("bad", {"country": "US"})])  # no url/title
    assert fetch_pending_articles(db) == []
