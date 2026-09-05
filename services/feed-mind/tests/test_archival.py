import json
from datetime import UTC, datetime, timedelta, timezone

from feedmind import archival

ARCHIVED_AT = "2026-08-29T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Table specs
# ---------------------------------------------------------------------------


def test_every_spec_partitions_and_clusters_on_real_columns():
    # A partition or clustering field that is not a column fails at table
    # creation — on the first run, in production, twice a month.
    for spec in (archival.ARTICLES, archival.VIDEOS, archival.PAPERS):
        assert spec.partition_field in spec.column_names
        for field in spec.clustering_fields:
            assert field in spec.column_names


def test_every_spec_keys_on_real_columns():
    for spec in (archival.ARTICLES, archival.VIDEOS, archival.PAPERS):
        assert spec.key_fields
        for field in spec.key_fields:
            assert field in spec.column_names


def test_every_spec_carries_a_raw_safety_net():
    # `raw` is what keeps an upstream field addition unpromoted rather than lost.
    for spec in (archival.ARTICLES, archival.VIDEOS, archival.PAPERS):
        assert "raw" in spec.column_names


# ---------------------------------------------------------------------------
# Timestamp coercion
# ---------------------------------------------------------------------------


def test_iso_string_timestamp_is_preserved():
    assert archival.to_timestamp("2026-08-29T10:30:00+00:00") == "2026-08-29T10:30:00+00:00"


def test_native_datetime_is_converted():
    # paper-prism stores run_date as a datetime; this repo stores ISO strings.
    value = datetime(2026, 8, 29, 10, 30, tzinfo=UTC)
    assert archival.to_timestamp(value) == "2026-08-29T10:30:00+00:00"


def test_naive_datetime_is_treated_as_utc_not_local():
    # Guessing the local zone would silently shift every timestamp by the
    # deploy machine's offset.
    assert archival.to_timestamp(datetime(2026, 8, 29, 10, 30)) == "2026-08-29T10:30:00+00:00"


def test_non_utc_timestamp_is_normalised_to_utc():
    value = datetime(2026, 8, 29, 10, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert archival.to_timestamp(value) == "2026-08-29T05:00:00+00:00"


def test_unparseable_timestamp_becomes_null_not_an_exception():
    # One bad field must not cost a whole run.
    assert archival.to_timestamp("not a date") is None
    assert archival.to_timestamp("") is None
    assert archival.to_timestamp(None) is None


# ---------------------------------------------------------------------------
# raw JSON
# ---------------------------------------------------------------------------


def test_raw_json_survives_datetimes():
    raw = archival.to_raw_json({"when": datetime(2026, 8, 29, tzinfo=UTC), "n": 1})
    assert json.loads(raw) == {"when": "2026-08-29T00:00:00+00:00", "n": 1}


def test_raw_json_is_stable_across_key_order():
    # Sorted keys mean an unchanged document serialises identically every run.
    assert archival.to_raw_json({"b": 1, "a": 2}) == archival.to_raw_json({"a": 2, "b": 1})


def test_raw_json_keeps_unknown_types_rather_than_raising():
    class Weird:
        def __str__(self):
            return "weird-value"

    assert json.loads(archival.to_raw_json({"x": Weird()})) == {"x": "weird-value"}


# ---------------------------------------------------------------------------
# Article rows
# ---------------------------------------------------------------------------


def _article_doc(**overrides):
    doc = {
        "article_id": "abc123",
        "url": "https://example.com/post",
        "title": "A Title",
        "snippet": "Body text.",
        "summary": "One sentence.",
        "feed_source": "Example Feed",
        "feed_category": "industry",
        "published_at": "2026-08-28T09:00:00+00:00",
        "processed_at": "2026-08-29T08:00:00+00:00",
        "status": "delivered",
    }
    doc.update(overrides)
    return doc


def test_article_row_has_exactly_the_spec_columns():
    row = archival.article_row("abc123", _article_doc(), ARCHIVED_AT)
    assert set(row) == set(archival.ARTICLES.column_names)


def test_article_row_maps_fields():
    row = archival.article_row("abc123", _article_doc(), ARCHIVED_AT)
    assert row["article_id"] == "abc123"
    assert row["snippet"] == "Body text."
    assert row["published_at"] == "2026-08-28T09:00:00+00:00"
    assert row["archived_at"] == ARCHIVED_AT


def test_missing_ai_summary_is_null_not_missing():
    # Written asynchronously by feed-mind-summarizer, and never at all for any
    # day that job failed. Its absence is normal, not an error.
    row = archival.article_row("abc123", _article_doc(), ARCHIVED_AT)
    assert row["ai_summary"] is None


def test_late_ai_summary_is_picked_up_on_a_later_run():
    row = archival.article_row("abc123", _article_doc(ai_summary="Spoken blurb."), ARCHIVED_AT)
    assert row["ai_summary"] == "Spoken blurb."


def test_article_id_falls_back_to_document_id():
    row = archival.article_row("doc-id-42", _article_doc(article_id=None), ARCHIVED_AT)
    assert row["article_id"] == "doc-id-42"


def test_article_row_keeps_unpromoted_fields_in_raw():
    row = archival.article_row("abc123", _article_doc(audio_url="gs://bucket/a.mp3"), ARCHIVED_AT)
    assert "audio_url" not in row
    assert json.loads(row["raw"])["audio_url"] == "gs://bucket/a.mp3"


# ---------------------------------------------------------------------------
# Video rows
# ---------------------------------------------------------------------------


def test_video_row_has_exactly_the_spec_columns():
    doc = {
        "video_id": "vid1",
        "url": "https://youtu.be/vid1",
        "title": "A Video",
        "channel": "Some Channel",
        "thumbnail_url": "https://i.ytimg.com/vi/vid1/hqdefault.jpg",
        "published_at": "2026-08-29T07:00:00+00:00",
        "processed_at": "2026-08-29T08:00:00+00:00",
    }
    row = archival.video_row("vid1", doc, ARCHIVED_AT)
    assert set(row) == set(archival.VIDEOS.column_names)
    assert row["channel"] == "Some Channel"


# ---------------------------------------------------------------------------
# Paper rows — the unnesting
# ---------------------------------------------------------------------------


def _run_doc(papers=None):
    return {
        "id": "2026-08-29_ML",
        "run_date": datetime(2026, 8, 29, tzinfo=UTC),
        "category": "ML",
        "papers": [
            {
                "rank": 1,
                "title": "Paper One",
                "arxiv_id": "2608.0001",
                "url": "https://arxiv.org/abs/2608.0001",
                "score": 0.9123,
                "summary": "Gemini blurb.",
                "abstract": "The authors show...",
            },
            {
                "rank": 2,
                "title": "Paper Two",
                "arxiv_id": "2608.0002",
                "url": "https://arxiv.org/abs/2608.0002",
                "score": 0.8,
                "summary": None,
                "abstract": "Another abstract.",
            },
        ]
        if papers is None
        else papers,
    }


def test_one_run_doc_becomes_one_row_per_paper():
    rows = archival.paper_rows("2026-08-29_ML", _run_doc(), ARCHIVED_AT)
    assert len(rows) == 2
    assert [r["arxiv_id"] for r in rows] == ["2608.0001", "2608.0002"]


def test_paper_row_has_exactly_the_spec_columns():
    row = archival.paper_rows("2026-08-29_ML", _run_doc(), ARCHIVED_AT)[0]
    assert set(row) == set(archival.PAPERS.column_names)


def test_paper_rows_carry_run_level_fields_onto_every_row():
    rows = archival.paper_rows("2026-08-29_ML", _run_doc(), ARCHIVED_AT)
    for row in rows:
        assert row["run_id"] == "2026-08-29_ML"
        assert row["run_date"] == "2026-08-29T00:00:00+00:00"
        assert row["category"] == "ML"


def test_paper_abstract_is_preserved():
    # Unlike articles, papers carry real prose upstream — it is the corpus.
    row = archival.paper_rows("2026-08-29_ML", _run_doc(), ARCHIVED_AT)[0]
    assert row["abstract"] == "The authors show..."


def test_null_gemini_summary_is_kept_as_null():
    row = archival.paper_rows("2026-08-29_ML", _run_doc(), ARCHIVED_AT)[1]
    assert row["summary"] is None


def test_paper_without_arxiv_id_is_dropped():
    # It cannot take part in the MERGE key; inventing one would create a row
    # that duplicates itself on every run.
    doc = _run_doc(papers=[{"rank": 1, "title": "No ID"}])
    assert archival.paper_rows("2026-08-29_ML", doc, ARCHIVED_AT) == []


def test_run_doc_without_papers_array_is_skipped():
    assert archival.paper_rows("2026-08-29_ML", {"category": "ML"}, ARCHIVED_AT) == []
    assert archival.paper_rows("2026-08-29_ML", {"papers": "nope"}, ARCHIVED_AT) == []


def test_non_dict_paper_entries_are_skipped():
    doc = _run_doc(papers=["just a string", {"arxiv_id": "2608.0003"}])
    rows = archival.paper_rows("2026-08-29_ML", doc, ARCHIVED_AT)
    assert [r["arxiv_id"] for r in rows] == ["2608.0003"]


def test_rank_and_score_are_coerced():
    doc = _run_doc(papers=[{"arxiv_id": "x", "rank": "3", "score": "0.5"}])
    row = archival.paper_rows("2026-08-29_ML", doc, ARCHIVED_AT)[0]
    assert row["rank"] == 3
    assert row["score"] == 0.5


def test_unusable_rank_and_score_become_null():
    doc = _run_doc(papers=[{"arxiv_id": "x", "rank": "first", "score": None}])
    row = archival.paper_rows("2026-08-29_ML", doc, ARCHIVED_AT)[0]
    assert row["rank"] is None
    assert row["score"] is None


# ---------------------------------------------------------------------------
# Dedupe
# ---------------------------------------------------------------------------


def test_dedupe_keeps_last_row_per_key():
    # BigQuery aborts a MERGE if one target row matches two source rows, so a
    # single duplicate would cost the whole table for that run.
    rows = [
        {"run_id": "r1", "arxiv_id": "a", "rank": 1},
        {"run_id": "r1", "arxiv_id": "a", "rank": 2},
        {"run_id": "r1", "arxiv_id": "b", "rank": 3},
    ]
    deduped = archival.dedupe_by_key(rows, ("run_id", "arxiv_id"))
    assert len(deduped) == 2
    assert {"run_id": "r1", "arxiv_id": "a", "rank": 2} in deduped


def test_dedupe_leaves_distinct_keys_alone():
    rows = [{"article_id": "a"}, {"article_id": "b"}]
    assert len(archival.dedupe_by_key(rows, ("article_id",))) == 2


def test_same_arxiv_id_in_different_runs_is_not_a_duplicate():
    # The same paper legitimately appears in two lenses or two weeks; run_id is
    # what keeps them separate rows.
    rows = [
        {"run_id": "2026-08-29_ML", "arxiv_id": "a"},
        {"run_id": "2026-08-29_NLP", "arxiv_id": "a"},
    ]
    assert len(archival.dedupe_by_key(rows, ("run_id", "arxiv_id"))) == 2
