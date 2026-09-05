"""
The MERGE is generated from a TableSpec and is otherwise only ever exercised
against real BigQuery, twice a month. These tests are the only place its shape
is checked before it runs in production.
"""

import pytest
from google.api_core.exceptions import NotFound

from feedmind import archival, bigquery, config

SPECS = (archival.ARTICLES, archival.VIDEOS, archival.PAPERS)


@pytest.fixture
def sql():
    return bigquery._merge_sql(archival.PAPERS, "proj.ds.papers_staging_abc")


def test_merge_matches_on_every_key_field(sql):
    assert "ON T.`run_id` = S.`run_id` AND T.`arxiv_id` = S.`arxiv_id`" in sql


def test_merge_updates_matched_rows(sql):
    # This is what backfills a late ai_summary onto an already-archived row.
    assert "WHEN MATCHED THEN UPDATE SET" in sql
    assert "`ai_summary` = S.`ai_summary`" in sql


def test_merge_never_updates_a_key_field(sql):
    # Assigning to a key inside MERGE is a BigQuery error.
    for field in archival.PAPERS.key_fields:
        assert (
            f"`{field}` = S.`{field}`"
            not in sql.split("WHEN NOT MATCHED")[0].split("UPDATE SET")[1]
        )


def test_merge_inserts_unmatched_rows(sql):
    assert "WHEN NOT MATCHED THEN INSERT" in sql


@pytest.mark.parametrize("spec", SPECS, ids=[s.name for s in SPECS])
def test_insert_lists_every_column_exactly_once(spec):
    generated = bigquery._merge_sql(spec, "proj.ds.staging")
    insert_clause = generated.split("WHEN NOT MATCHED THEN INSERT (")[1]
    columns, values = insert_clause.split(") VALUES (")
    values = values.rstrip().removesuffix(")")

    assert [c.strip().strip("`") for c in columns.split(",")] == list(spec.column_names)
    assert [v.strip().removeprefix("S.").strip("`") for v in values.split(",")] == list(
        spec.column_names
    )


@pytest.mark.parametrize("spec", SPECS, ids=[s.name for s in SPECS])
def test_merge_targets_the_configured_dataset(spec):
    generated = bigquery._merge_sql(spec, "proj.ds.staging")
    assert f"`{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.{spec.name}`" in generated


@pytest.mark.parametrize("spec", SPECS, ids=[s.name for s in SPECS])
def test_schema_covers_every_spec_column(spec):
    fields = bigquery._schema(spec)
    assert [f.name for f in fields] == list(spec.column_names)


def test_no_rows_skips_bigquery_entirely():
    # An empty collection must not create a staging table or run a query.
    class ExplodingClient:
        def __getattr__(self, name):
            raise AssertionError(f"BigQuery was called ({name}) with no rows to archive")

    assert bigquery.archive_table(ExplodingClient(), archival.ARTICLES, []) == 0


# ---------------------------------------------------------------------------
# Free-tier guardrails
# ---------------------------------------------------------------------------


class FakeJob:
    num_dml_affected_rows = 1
    total_bytes_billed = 1024

    def result(self):
        return self


class FakeTable:
    def __init__(self, num_bytes=0):
        self.num_bytes = num_bytes
        self.expires = None


class RecordingClient:
    """Captures the job configs so the guardrails can be asserted."""

    def __init__(self, table_bytes=None):
        self.query_configs = []
        self.deleted = []
        self._table_bytes = table_bytes or {}

    def load_table_from_json(self, rows, table_id, job_config=None):
        return FakeJob()

    def get_table(self, table_id):
        name = table_id.rsplit(".", 1)[-1]
        if name in self._table_bytes:
            return FakeTable(self._table_bytes[name])
        if "_staging_" in name:
            return FakeTable()
        raise NotFound(table_id)

    def update_table(self, table, fields):
        return table

    def query(self, sql, job_config=None):
        self.query_configs.append(job_config)
        return FakeJob()

    def delete_table(self, table_id, not_found_ok=False):
        self.deleted.append(table_id)


def test_merge_is_capped_at_the_free_tier_guardrail():
    # Without this the job runs and bills; with it BigQuery refuses up front.
    bq = RecordingClient()
    bigquery.archive_table(bq, archival.ARTICLES, [{"article_id": "a"}])

    assert bq.query_configs[0].maximum_bytes_billed == config.BQ_MAX_BYTES_BILLED


def test_guardrail_leaves_room_for_years_of_growth():
    # A cap that normal growth trips would turn a cost guard into data loss:
    # the archive would stop running. ~200 MB/year against a 10 GiB cap.
    assert config.BQ_MAX_BYTES_BILLED >= 50 * 200 * 1024**2


def test_staging_table_is_always_dropped():
    # An orphaned staging table would count against the 10 GiB storage tier.
    bq = RecordingClient()
    bigquery.archive_table(bq, archival.ARTICLES, [{"article_id": "a"}])
    assert len(bq.deleted) == 1
    assert "_staging_" in bq.deleted[0]


def test_staging_table_is_dropped_even_when_the_merge_fails():
    bq = RecordingClient()
    bq.query = lambda sql, job_config=None: (_ for _ in ()).throw(RuntimeError("merge blew up"))

    with pytest.raises(RuntimeError):
        bigquery.archive_table(bq, archival.ARTICLES, [{"article_id": "a"}])

    assert len(bq.deleted) == 1


def test_dataset_bytes_sums_existing_tables():
    bq = RecordingClient(table_bytes={"articles": 1000, "videos": 500})
    # `papers` does not exist yet — a missing table contributes nothing rather
    # than failing the run.
    assert bigquery.dataset_bytes(bq, list(SPECS)) == 1500


def test_dataset_bytes_is_zero_before_the_first_run():
    assert bigquery.dataset_bytes(RecordingClient(), list(SPECS)) == 0
