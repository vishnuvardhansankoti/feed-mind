"""
main.py — feedmind-archive: copy Firestore into BigQuery before its TTL fires.

Every source collection is on a TTL — 90 days for processed_articles and
youtube_videos, 45 for paper-prism's runs — so anything not copied out is
deleted permanently. This runs on the 1st and 16th: a 16-day maximum gap,
chosen against the 45-day TTL so a completely missed run still has ~29 days of
margin.

Its own function, separate from every ingest service, for two reasons: an
archival bug cannot break the daily digest, and it needs a 900s timeout that a
5-minute ingest function would not tolerate.

Four invariants that are easy to break by accident — full rationale in
docs/feed-mind/bigquery-archival-plan.md:

  1. Batch loads only. load_table_from_json is free; insert_rows_json
     (streaming) costs $0.01/200 MB with no free tier.
  2. MERGE, not append. ai_summary is written asynchronously by
     services/summarizer AFTER the document exists, so appending would freeze a
     NULL for anything archived before its summary landed.
  3. Full scan, no watermark. ~10k reads against a 50k/day free tier. Paying
     them is what makes the archive self-healing: a missed run needs no
     recovery, the next one just catches up.
  4. Every MERGE carries maximum_bytes_billed. BigQuery refuses the job rather
     than billing for it.
"""

import json
import logging
import time
from datetime import UTC, datetime

import functions_framework
from feedmind_core import archival, bigquery
from feedmind_core import settings as config
from feedmind_core.secrets import load_all_secrets
from feedmind_core.telegram import send_plain_message
from google.cloud import firestore

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("feedmind-archive")

# ---------------------------------------------------------------------------
# Archive entry point — Firestore → BigQuery
# ---------------------------------------------------------------------------
# Deployed as a *second* Cloud Function from this same source, on its own
# Scheduler job (1st and 16th of each month). Every source collection is on a
# TTL — 90 days for this repo's, 45 for paper-prism's `runs` — so anything not
# copied out is deleted permanently. See docs/bigquery-archival-plan.md.

# (table spec, Firestore collection, doc → rows). Papers are the one source
# where a single document becomes many rows, so every builder returns a list.
_ARCHIVE_SOURCES = (
    (
        archival.ARTICLES,
        config.FIRESTORE_COLLECTION,
        lambda doc_id, doc, at: [archival.article_row(doc_id, doc, at)],
    ),
    (
        archival.VIDEOS,
        config.FIRESTORE_YOUTUBE_COLLECTION,
        lambda doc_id, doc, at: [archival.video_row(doc_id, doc, at)],
    ),
    (
        archival.PAPERS,
        config.FIRESTORE_RUNS_COLLECTION,
        archival.paper_rows,
    ),
)


def _collect_rows(db, spec, collection_name, build_rows, archived_at):
    """
    Read every live document in one collection and reshape it into BigQuery rows.

    A full scan, deliberately: the live set is a few thousand documents against
    a 50,000/day free read allowance, run twice a month. Paying those reads buys
    an archive with no watermark and no cursor to corrupt — a missed run, a
    failed run or a late `ai_summary` is simply corrected by the next run.
    """
    rows = []
    docs_read = 0

    for snapshot in db.collection(collection_name).stream():
        docs_read += 1
        rows.extend(build_rows(snapshot.id, snapshot.to_dict() or {}, archived_at))

    return docs_read, archival.dedupe_by_key(rows, spec.key_fields)


def _format_bytes(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024


def _archive_report(results: dict, errors: dict, storage_bytes: int, duration: float) -> str:
    """One scannable message. The failure case has to be obvious at a glance."""
    headline = "FeedMind archive complete" if not errors else "FeedMind archive FAILED"
    lines = [headline]

    for name, counts in results.items():
        lines.append(f"{name}: {counts['rows']} rows from {counts['docs_read']} docs")
    for name, message in errors.items():
        lines.append(f"{name}: ERROR — {message}")

    if storage_bytes:
        # Storage is the only free-tier limit that never resets, so the run
        # report is where its growth becomes visible.
        line = (
            f"storage: {_format_bytes(storage_bytes)} "
            f"of {_format_bytes(config.BQ_FREE_STORAGE_BYTES)} free tier"
        )
        if storage_bytes >= config.BQ_STORAGE_WARN_BYTES:
            line += " — APPROACHING LIMIT"
        lines.append(line)

    lines.append(f"duration: {duration}s")
    return "\n".join(lines)


@functions_framework.http
def archive(request):
    """
    HTTP-triggered Cloud Function. Copies all live Firestore docs to BigQuery.

    Idempotent by construction: every run reads everything and MERGEs, so
    running it twice in a row is harmless and running it late still catches up.
    Run locally (`python main.py archive`) it is a dry run — it reads Firestore
    and builds rows, but writes nothing.
    """
    is_local_run = request is None

    run_start = time.monotonic()
    logger.info(
        json.dumps(
            {
                "message": "FeedMind archive started",
                "timestamp": datetime.now(UTC).isoformat(),
                "dry_run": is_local_run,
            }
        )
    )

    # The report is best-effort infrastructure around the archive, not a
    # precondition for it: if secrets are unavailable we still copy the data and
    # simply lose the notification.
    telegram = None
    if config.ENABLE_ARCHIVE_TELEGRAM_REPORT and not is_local_run:
        try:
            secrets = load_all_secrets()
            telegram = (secrets["telegram_token"], secrets["telegram_chat_id"])
        except RuntimeError as exc:
            logger.error("Secret loading failed — archiving without a report: %s", exc)

    db = firestore.Client(project=config.GCP_PROJECT_ID, database=config.FIRESTORE_DATABASE)

    bq = None
    if not is_local_run:
        bq = bigquery.client()
        bigquery.ensure_dataset_and_tables(bq, [spec for spec, _c, _b in _ARCHIVE_SOURCES])

    archived_at = datetime.now(UTC).isoformat()
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for spec, collection_name, build_rows in _ARCHIVE_SOURCES:
        # One failing table must not cost the other two — archiving two of three
        # sources beats archiving none, and the run reports what it missed.
        try:
            docs_read, rows = _collect_rows(db, spec, collection_name, build_rows, archived_at)

            if is_local_run:
                print(f"--- WOULD ARCHIVE {len(rows)} row(s) to {spec.name} ---")
                affected = 0
            else:
                affected = bigquery.archive_table(bq, spec, rows)

            results[spec.name] = {
                "docs_read": docs_read,
                "rows": len(rows),
                "affected_rows": affected,
            }
        except Exception as exc:
            logger.exception("Archiving failed for table=%s", spec.name)
            errors[spec.name] = str(exc)

    # Free metadata call, never a query. Best-effort: a metadata hiccup must not
    # fail an archive that already succeeded.
    storage_bytes = 0
    if bq is not None:
        try:
            storage_bytes = bigquery.dataset_bytes(bq, [spec for spec, _c, _b in _ARCHIVE_SOURCES])
        except Exception:
            logger.warning("Could not read archive storage size", exc_info=True)

    duration = round(time.monotonic() - run_start, 2)
    summary_log = {
        "message": "FeedMind archive complete",
        "tables": results,
        "errors": errors,
        "storage_bytes": storage_bytes,
        "free_storage_bytes": config.BQ_FREE_STORAGE_BYTES,
        "duration_seconds": duration,
    }
    logger.info(json.dumps(summary_log))

    report = _archive_report(results, errors, storage_bytes, duration)
    if telegram:
        send_plain_message(telegram[0], telegram[1], report)
    elif is_local_run:
        print(f"--- WOULD REPORT TO TELEGRAM ---\n{report}\n--------------------------------")

    status = 500 if errors else 200
    return (json.dumps(summary_log), status, {"Content-Type": "application/json"})


if __name__ == "__main__":
    # Local run against real Firestore via ADC. Reads everything, writes to
    # BigQuery for real — there is no dry-run mode, so point it at a scratch
    # dataset if that matters.  uv run python main.py
    print("Running feedmind-archive locally...")
    archive(None)
