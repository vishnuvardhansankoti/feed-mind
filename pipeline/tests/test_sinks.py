"""LocalJsonSink round-trip + datetime serialization."""

import json
from datetime import datetime, timezone

from paper_prism.models import Paper, RunDocument, RunStatus
from paper_prism.sinks import LocalJsonSink, build_sink

RUN_DATE = datetime(2026, 8, 13, tzinfo=timezone.utc)
EXPIRE = datetime(2026, 9, 27, tzinfo=timezone.utc)


def test_build_sink_defaults_to_local(tmp_path):
    assert isinstance(build_sink("local", str(tmp_path), None), LocalJsonSink)
    assert isinstance(build_sink("anything-else", str(tmp_path), None), LocalJsonSink)


def test_local_sink_writes_run_with_iso_z_dates(tmp_path):
    sink = LocalJsonSink(str(tmp_path))
    doc = RunDocument(
        category="AIML",
        run_date=RUN_DATE,
        papers=[Paper(rank=1, title="t", arxiv_id="1", url="u", score=0.5)],
        expire_at=EXPIRE,
    )
    sink.write_run(doc)

    written = json.loads((tmp_path / "runs" / "2026-08-13_AIML.json").read_text())
    assert written["run_date"] == "2026-08-13T00:00:00Z"
    assert written["expire_at"] == "2026-09-27T00:00:00Z"
    assert written["papers"][0]["title"] == "t"


def test_local_sink_writes_status(tmp_path):
    sink = LocalJsonSink(str(tmp_path))
    status = RunStatus(run_date=RUN_DATE, expire_at=EXPIRE)
    status.mark_ok("AIML", 3)
    sink.write_status(status)

    written = json.loads((tmp_path / "run_status" / "2026-08-13.json").read_text())
    assert written["categories"]["AIML"]["paper_count"] == 3
    assert written["expire_at"] == "2026-09-27T00:00:00Z"
