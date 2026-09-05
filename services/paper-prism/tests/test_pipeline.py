"""Best-effort per-lens orchestration + expire_at stamping.

Uses fakes for arXiv/embedder/summarizer/sink so no network or model is touched.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
from paper_prism.config import Config
from paper_prism.models import Candidate, utc_run_date
from paper_prism.pipeline import Pipeline


def _config(retention_days=45, top_k=2):
    return Config(
        profiles={"AIML": "a", "NLP": "n", "CV": "c"},
        gemini_api_key=None,
        gemini_model="gemini-3.6-flash",
        sink="local",
        window_days=7,
        top_k=top_k,
        retention_days=retention_days,
        arxiv_page_size=100,
        arxiv_throttle_seconds=0.0,
        arxiv_max_pages=1,
        output_dir="unused",
        firestore_project=None,
    )


def _candidate(idx, cat):
    # Longer abstract == higher fake score (see FakeEmbedder), so idx drives rank.
    return Candidate(
        title=f"paper {idx}",
        abstract="x" * (idx + 1),
        arxiv_id=f"2508.0000{idx}",
        url=f"http://arxiv.org/abs/2508.0000{idx}",
        primary_category=cat,
        submitted=datetime(2026, 8, 13, tzinfo=UTC),
    )


class FakeArxiv:
    def __init__(self, per_lens, fail=()):
        self.per_lens = per_lens
        self.fail = set(fail)
        self.calls = []

    def fetch_lens(self, sources, window_days):
        self.calls.append(sources)
        if sources in self.fail:
            raise RuntimeError("boom")
        return self.per_lens.get(sources, [])


class FakeEmbedder:
    """1-D embeddings == text length, so dot product ranks longer text first."""

    def encode(self, texts, batch_size=32):
        return np.array([[float(len(t))] for t in texts], dtype=np.float32)


class FakeSummarizer:
    def summarize(self, title, abstract):
        return f"summary of {title}"


class CapturingSink:
    def __init__(self):
        self.runs = []
        self.status = None

    def write_run(self, doc):
        self.runs.append(doc)

    def write_status(self, status):
        self.status = status


def test_run_ranks_top_k_and_stamps_expire_at():
    per_lens = {
        ("cs.LG", "cs.AI"): [_candidate(i, "cs.LG") for i in range(3)],
        ("cs.CL",): [_candidate(i, "cs.CL") for i in range(3)],
        ("cs.CV",): [_candidate(i, "cs.CV") for i in range(3)],
    }
    sink = CapturingSink()
    cfg = _config(retention_days=45, top_k=2)
    pipe = Pipeline(cfg, FakeArxiv(per_lens), FakeEmbedder(), FakeSummarizer(), sink)

    status = pipe.run()

    assert status.has_failure is False
    assert len(sink.runs) == 3  # one doc per lens

    expected_expire = utc_run_date() + timedelta(days=45)
    for doc in sink.runs:
        assert doc.expire_at == expected_expire
        assert len(doc.papers) == 2  # clamped to top_k
        assert [p.rank for p in doc.papers] == [1, 2]
        # longest abstract (idx 2) ranks first
        assert doc.papers[0].title == "paper 2"
        assert doc.papers[0].summary == "summary of paper 2"
        # The arXiv abstract is carried through to the doc alongside the
        # Gemini summary, not consumed and discarded by ranking.
        assert doc.papers[0].abstract == "xxx"

    assert sink.status is not None
    assert sink.status.expire_at == expected_expire


def test_one_lens_failing_does_not_abort_the_others():
    per_lens = {
        ("cs.LG", "cs.AI"): [_candidate(0, "cs.LG")],
        ("cs.CV",): [_candidate(0, "cs.CV")],
    }
    sink = CapturingSink()
    arxiv = FakeArxiv(per_lens, fail={("cs.CL",)})  # NLP lens blows up
    pipe = Pipeline(_config(), arxiv, FakeEmbedder(), FakeSummarizer(), sink)

    status = pipe.run()

    assert status.has_failure is True
    cats = status.to_dict()["categories"]
    assert cats["AIML"]["status"] == "ok"
    assert cats["CV"]["status"] == "ok"
    assert cats["NLP"]["status"] == "skipped"
    assert cats["NLP"]["reason"] == "RuntimeError"
    # the failed lens wrote no run doc; the healthy ones did
    assert {d.category for d in sink.runs} == {"AIML", "CV"}


def test_empty_window_yields_a_lens_doc_with_no_papers():
    sink = CapturingSink()
    arxiv = FakeArxiv(per_lens={})  # every lens returns []
    pipe = Pipeline(_config(), arxiv, FakeEmbedder(), FakeSummarizer(), sink)

    status = pipe.run()

    assert status.has_failure is False
    assert len(sink.runs) == 3
    for doc in sink.runs:
        assert doc.papers == []
        assert doc.expire_at is not None
