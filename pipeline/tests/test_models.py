"""Domain model + Firestore schema shaping (incl. the expire_at TTL field)."""

from datetime import datetime, timezone

from paper_prism.models import (
    Candidate,
    Paper,
    RunDocument,
    RunStatus,
    utc_run_date,
)

RUN_DATE = datetime(2026, 8, 13, tzinfo=timezone.utc)
EXPIRE = datetime(2026, 9, 27, tzinfo=timezone.utc)  # +45d


def test_run_document_doc_id_is_date_and_category():
    doc = RunDocument(category="AIML", run_date=RUN_DATE)
    assert doc.doc_id == "2026-08-13_AIML"


def test_run_document_to_dict_omits_expire_at_when_unset():
    doc = RunDocument(category="NLP", run_date=RUN_DATE, papers=[])
    assert "expire_at" not in doc.to_dict()


def test_run_document_to_dict_includes_expire_at_when_set():
    paper = Paper(rank=1, title="t", arxiv_id="1", url="u", score=0.123456)
    doc = RunDocument(
        category="CV", run_date=RUN_DATE, papers=[paper], expire_at=EXPIRE
    )
    out = doc.to_dict()
    assert out["expire_at"] == EXPIRE
    assert out["id"] == "2026-08-13_CV"
    # score is rounded to 4 dp on serialization
    assert out["papers"][0]["score"] == 0.1235


def test_run_status_marks_and_detects_failure():
    status = RunStatus(run_date=RUN_DATE)
    status.mark_ok("AIML", 3)
    assert status.has_failure is False
    status.mark_skipped("NLP", reason="RuntimeError")
    assert status.has_failure is True
    d = status.to_dict()
    assert d["categories"]["AIML"] == {"status": "ok", "paper_count": 3}
    assert d["categories"]["NLP"] == {"status": "skipped", "reason": "RuntimeError"}


def test_run_status_to_dict_expire_at_optional():
    assert "expire_at" not in RunStatus(run_date=RUN_DATE).to_dict()
    assert RunStatus(run_date=RUN_DATE, expire_at=EXPIRE).to_dict()["expire_at"] == EXPIRE


def test_candidate_embed_text_joins_title_and_abstract():
    c = Candidate(
        title="  Title  ",
        abstract="  Body  ",
        arxiv_id="2508.01234",
        url="http://x",
        primary_category="cs.LG",
        submitted=RUN_DATE,
    )
    assert c.embed_text == "Title\nBody"


def test_utc_run_date_is_midnight_utc():
    d = utc_run_date()
    assert d.tzinfo == timezone.utc
    assert (d.hour, d.minute, d.second, d.microsecond) == (0, 0, 0, 0)
