"""
bigquery.py — creating, loading and merging the archive tables.

Every write is a **batch load** into a throwaway staging table followed by a
MERGE into the real table.

Two things about that are deliberate and easy to undo by accident:

1. **Batch loads are free; streaming inserts are not.** `insert_rows_json()` is
   the streaming API and costs $0.01 per 200 MB with no free tier. A job that
   runs twice a month has no use for streaming's latency. Do not "simplify"
   `load_table_from_json` into `insert_rows_json`.

2. **MERGE, not append.** `ai_summary` is written to Firestore asynchronously
   *after* the document exists, by feed-mind-summarizer. An append-only archive
   would freeze a NULL for every document copied before its summary landed.
   MERGE lets a later run backfill it, and makes re-running the whole job at
   any time harmless.

See docs/bigquery-archival-plan.md for the full rationale.
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from feedmind import config
from feedmind.archival import TableSpec

logger = logging.getLogger(__name__)

# Safety net on staging tables. The happy path deletes them in a finally block;
# this is what cleans up after a hard-killed function so the dataset does not
# slowly fill with orphans.
STAGING_TABLE_TTL_HOURS = 6


def client() -> bigquery.Client:
    return bigquery.Client(project=config.GCP_PROJECT_ID)


def _table_id(spec: TableSpec) -> str:
    return f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}.{spec.name}"


def _schema(spec: TableSpec) -> list[bigquery.SchemaField]:
    return [bigquery.SchemaField(name, type_) for name, type_ in spec.columns]


def ensure_dataset_and_tables(bq: bigquery.Client, specs: list[TableSpec]) -> None:
    """
    Create the dataset and tables if they do not exist. Idempotent.

    Note this creates but never *alters*: adding a column to a TableSpec will
    not reshape a table that already exists, which needs an explicit schema
    update. That is survivable precisely because of the `raw` column — until the
    new column exists, the value is still archived inside `raw` rather than lost.
    """
    dataset = bigquery.Dataset(f"{config.GCP_PROJECT_ID}.{config.BQ_DATASET}")
    dataset.location = config.BQ_LOCATION
    bq.create_dataset(dataset, exists_ok=True)

    for spec in specs:
        table = bigquery.Table(_table_id(spec), schema=_schema(spec))
        # Partitioning and clustering are good practice here, not cost control:
        # the whole dataset is well under 100 MB and inside the free tier either
        # way. They keep queries cheap if the corpus ever grows.
        table.time_partitioning = bigquery.TimePartitioning(field=spec.partition_field)
        table.clustering_fields = list(spec.clustering_fields)
        bq.create_table(table, exists_ok=True)


def _merge_sql(spec: TableSpec, staging_id: str) -> str:
    """
    Build the MERGE for one table from its spec.

    Every identifier comes from our own TableSpec constants, never from document
    data, so string interpolation here carries no injection risk.
    """
    on_clause = " AND ".join(f"T.`{field}` = S.`{field}`" for field in spec.key_fields)
    non_key = [c for c in spec.column_names if c not in spec.key_fields]
    updates = ", ".join(f"`{c}` = S.`{c}`" for c in non_key)
    columns = ", ".join(f"`{c}`" for c in spec.column_names)
    values = ", ".join(f"S.`{c}`" for c in spec.column_names)

    return (
        f"MERGE `{_table_id(spec)}` AS T\n"
        f"USING `{staging_id}` AS S\n"
        f"ON {on_clause}\n"
        f"WHEN MATCHED THEN UPDATE SET {updates}\n"
        f"WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values})"
    )


def archive_table(bq: bigquery.Client, spec: TableSpec, rows: list[dict]) -> int:
    """
    Load `rows` into a staging table and MERGE them into `spec`'s table.

    Returns the number of rows affected (inserted + updated) by the MERGE.
    Raises on failure — the caller decides whether one failed table should stop
    the run.
    """
    if not rows:
        logger.info("Nothing to archive for table=%s", spec.name)
        return 0

    staging_id = f"{_table_id(spec)}_staging_{uuid4().hex[:8]}"

    try:
        load_job = bq.load_table_from_json(
            rows,
            staging_id,
            job_config=bigquery.LoadJobConfig(
                schema=_schema(spec),
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            ),
        )
        load_job.result()

        staging = bq.get_table(staging_id)
        staging.expires = datetime.now(UTC) + timedelta(hours=STAGING_TABLE_TTL_HOURS)
        bq.update_table(staging, ["expires"])

        # maximum_bytes_billed makes BigQuery reject the job before running it
        # if it would scan more than the cap, rather than running it and
        # billing. It is the only hard enforcement of the free tier in this
        # code path — everything else is arithmetic that happens to come out
        # under the limit.
        merge_job = bq.query(
            _merge_sql(spec, staging_id),
            job_config=bigquery.QueryJobConfig(
                maximum_bytes_billed=config.BQ_MAX_BYTES_BILLED,
            ),
        )
        merge_job.result()

        affected = merge_job.num_dml_affected_rows or 0
        logger.info(
            "Archived table=%s staged_rows=%d affected_rows=%d billed_bytes=%d",
            spec.name,
            len(rows),
            affected,
            merge_job.total_bytes_billed or 0,
        )
        return affected

    finally:
        bq.delete_table(staging_id, not_found_ok=True)


def dataset_bytes(bq: bigquery.Client, specs: list[TableSpec]) -> int:
    """
    Total bytes stored across the archive tables.

    Read from table metadata, which is a free API call — not a query, and not
    billed. Storage is the one free-tier limit here that only ever grows:
    queries and loads reset monthly, bytes kept do not. A table that does not
    exist yet contributes nothing.
    """
    total = 0
    for spec in specs:
        try:
            total += bq.get_table(_table_id(spec)).num_bytes or 0
        except NotFound:
            continue
    return total
