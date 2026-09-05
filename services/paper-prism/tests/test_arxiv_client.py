"""arXiv Atom-parsing helpers (no network)."""

from datetime import UTC

from paper_prism.arxiv_client import (
    _clean,
    _parse_dt,
    _primary_category,
    _short_id,
)


def test_short_id_strips_abs_prefix_and_version():
    assert _short_id("http://arxiv.org/abs/2508.01234v1") == "2508.01234"
    assert _short_id("http://arxiv.org/abs/2508.01234") == "2508.01234"


def test_clean_collapses_whitespace():
    assert _clean("  a\n  b\t c ") == "a b c"


def test_parse_dt_handles_rfc3339_z():
    dt = _parse_dt("2026-08-10T09:00:00Z")
    assert dt is not None
    assert dt.tzinfo == UTC
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 8, 10, 9)


def test_parse_dt_returns_none_on_bad_input():
    assert _parse_dt("") is None
    assert _parse_dt(None) is None
    assert _parse_dt("not-a-date") is None


def test_primary_category_prefers_arxiv_primary_then_falls_back_to_tags():
    assert _primary_category({"arxiv_primary_category": {"term": "cs.LG"}}) == "cs.LG"
    assert _primary_category({"tags": [{"term": "cs.CL"}]}) == "cs.CL"
    assert _primary_category({}) == ""
