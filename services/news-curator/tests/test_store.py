"""fetch_pending_articles's country defaulting and FirestoreSink.prune_category
— the two bits of logic in store.py worth a direct test (everything else is
exercised through pipeline.py's FakeSink in test_pipeline.py).
"""

from news_curator.store import FirestoreSink, fetch_pending_articles


class FakeReference:
    def __init__(self) -> None:
        self.deleted = False

    def delete(self) -> None:
        self.deleted = True


class FakeSnapshot:
    def __init__(self, doc_id, data):
        self.id = doc_id
        self._data = data
        self.reference = FakeReference()

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


def _story_doc(doc_id, run_date, score):
    return FakeSnapshot(
        doc_id, {"country": "IN", "coarse_category": "politics", "run_date": run_date, "score": score}
    )


def test_prune_category_evicts_by_run_date_not_score():
    # "old" outscores both others but is the oldest — it must still be the
    # one evicted, since rank.py's score has no recency term and a standing
    # cap that kept the highest score forever would freeze on stale news.
    old = _story_doc("old", "2026-09-01", score=0.9)
    mid = _story_doc("mid", "2026-09-05", score=0.1)
    new = _story_doc("new", "2026-09-10", score=0.05)
    db = FakeDB([old, mid, new])

    FirestoreSink(db).prune_category("IN", "politics", keep=2)

    assert old.reference.deleted is True
    assert mid.reference.deleted is False
    assert new.reference.deleted is False


def test_prune_category_is_a_no_op_under_the_cap():
    only = _story_doc("only", "2026-09-10", score=0.5)
    db = FakeDB([only])

    FirestoreSink(db).prune_category("IN", "politics", keep=20)

    assert only.reference.deleted is False
