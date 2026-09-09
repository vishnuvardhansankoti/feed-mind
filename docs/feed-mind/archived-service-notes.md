# services/feed-mind

Guidance for working inside this service. The system-level view — the four
deployables, the shared Firestore database, the Pub/Sub handoff and the
cross-component schema contracts — is in the **root `CLAUDE.md`**; read that
first if you are changing anything another component reads.

## What this service is

FeedMind is a serverless RSS-to-Telegram pipeline deployed as a GCP Cloud Function (Gen 2). It runs daily via Cloud Scheduler: fetches 13 RSS feeds, deduplicates against Firestore, summarizes new articles, and pushes **batched Telegram messages grouped by category** (Academic / Industry / Cloud). The whole stack fits within GCP free-tier limits.

## Commands

All of these run from `services/feed-mind/` unless stated otherwise.

**Install dependencies:**
```bash
uv sync
```

**Run locally** (requires GCP Application Default Credentials):
```bash
uv run functions-framework --target=feedmind --debug
# then trigger with: curl -X POST http://localhost:8080
```

**Run tests:**
```bash
uv run pytest
# single test:
uv run pytest tests/test_config.py::test_rss_feeds_structure
```

**Lint** (config is the repo-root `ruff.toml`, shared by all services):
```bash
uvx ruff check .
```

**Deploy to GCP:**
```bash
./deploy.sh   # updates requirements.txt, deploys function, creates/updates scheduler job
```

**Trigger a manual run in GCP:**
```bash
gcloud scheduler jobs run feedmind-daily-trigger --location=us-central1 --project=feed-mind
```

**Trigger the BigQuery archive on demand:**
```bash
gcloud scheduler jobs run feedmind-archive-biweekly --location=us-central1 --project=feed-mind
```

**Dry-run the archive locally** (reads Firestore via ADC, writes nothing):
```bash
uv run python main.py archive
```

## Architecture

The pipeline is a single linear flow with no async or concurrency — articles for each feed are processed sequentially inside a 240-second soft timeout guard (5-minute hard Cloud Function limit). There is also an inner soft-timeout check per article to handle unexpectedly large feed backlogs.

```
main.py (HTTP trigger)
  └── load_all_secrets()              # secrets.py — GCP Secret Manager
  └── init_gemini() if ENABLE_GEMINI_SUMMARIES
  └── nltk.download() if Sumy mode    # downloads punkt to /tmp/nltk_data
  └── firestore.Client()              # shared across all feeds
  └── for each feed in RSS_FEEDS:
        └── fetch_feed()              # ingestion.py — feedparser, age-filtered
        └── for each article:
              └── is_duplicate()      # deduplication.py — single Firestore .get()
              └── summarize()         # Gemini (1-sentence), or
                  summarize_with_sumy() # Sumy LSA extractive (offline fallback)
              └── collect into category_items dict (not sent yet), or into
                  firestore_only_items if the feed has post_to_telegram=False
  └── for each category in category_items:
        └── build_category_messages() # notification.py — chunks into ≤4000-char messages
        └── send_message() per chunk  # httpx POST to Telegram
        └── mark_as_delivered()       # Firestore write ONLY after successful delivery
  └── for each article in firestore_only_items:
        └── mark_as_delivered()       # written directly — no Telegram step to gate on
```

**Key invariant:** for Telegram-bound articles, Firestore is written to **only after** successful delivery. Failed articles are not marked and will be retried on the next daily run.

**Per-feed Telegram opt-out:** each entry in `RSS_FEEDS` carries a fourth element, `post_to_telegram`. It is `True` for every feed except `TOI Top Stories`. When `False`, the feed is still fetched, deduplicated, summarized and persisted to Firestore (so `apps/web`'s News section keeps showing it) but its articles never appear in the batched Telegram messages.

**Article identity:** `article_id` is SHA-256 of the article URL, used as the Firestore document ID in the `processed_articles` collection. Firestore documents include an `expires_at` field (90 days) for TTL-based auto-deletion.

**`snippet` is written but never read back** by this pipeline — it exists so the planned BigQuery archive has real article text instead of titles and one-liners. The 90-day TTL makes anything not captured at write time unrecoverable, so don't drop it as an unused field. See `../../docs/feed-mind/bigquery-archival-plan.md`.

## Summarization modes

Controlled by `ENABLE_GEMINI_SUMMARIES` in `config.py` (currently `False`):

| Mode | Flag | Behaviour |
|------|------|-----------|
| **Sumy** (default) | `False` | Extractive 1-sentence summary via Sumy LSA + NLTK. No API calls, fully offline. NLTK data downloaded to `/tmp/nltk_data` at startup. |
| **Gemini** | `True` | Calls `gemini-3.5-flash-lite` for a ≤20-word generative sentence. Requires `GEMINI_API_KEY` secret. Respects `GEMINI_REQUEST_DELAY_S` between calls. |

When Gemini is enabled and fails for an article, it falls back gracefully (`None` return) — the article is skipped and retried next run. Sumy falls back to `article.title` on failure.

## Telegram message format

Articles are batched by category. Each category produces one or more messages chunked at `TELEGRAM_MAX_MESSAGE_LENGTH` (4000 chars):

```
*🎓 Academic News*

• *Title* — One-sentence summary.
  🔗 Read More | 📰 arXiv ML

• *Title 2* — Another summary.
  🔗 Read More | 📰 Hugging Face Papers
```

`build_category_messages(category, items)` in `notification.py` handles chunking and continuation headers (`*(Cont.)*`).

## The archive pipeline (second entry point)

`main.py::archive` is a **separate Cloud Function** deployed from this same source (`feedmind-archive`, entry point `archive`), on its own Scheduler job `feedmind-archive-biweekly` at `0 4 1,16 * *`. It exists because every source collection is on a TTL — 90 days for this service's `processed_articles` and `youtube_videos`, **45 days** for `services/paper-prism`'s `runs` — so anything not copied out is deleted permanently.

```
archive (HTTP trigger)
  └── load_all_secrets()               # best-effort; a failure only loses the report
  └── firestore.Client() + bigquery.client()
  └── ensure_dataset_and_tables()      # idempotent create, never alters
  └── for each of 3 sources:
        └── collection.stream()        # FULL scan — no watermark, by design
        └── archival.*_row()           # → BigQuery row dicts
        └── dedupe_by_key()
        └── bigquery.archive_table()   # batch load → staging → MERGE → drop staging
  └── send_plain_message()             # one-line run report to Telegram
```

**Four invariants that are easy to break by accident:**

1. **Batch loads only.** `load_table_from_json` is free; `insert_rows_json` (streaming) costs $0.01/200 MB with no free tier. A twice-monthly job has no use for streaming latency.
2. **MERGE, not append.** `ai_summary` is written to Firestore *asynchronously after* the doc exists, by `services/summarizer`. Appending would freeze a NULL for anything archived before its summary landed.
3. **Full scan, no watermark.** ~10k reads against a 50k/day free tier. Paying those reads is what makes the archive self-healing: a missed or failed run needs no recovery, the next run just catches up.
4. **Every MERGE carries `maximum_bytes_billed`** (`config.BQ_MAX_BYTES_BILLED`, 10 GiB). BigQuery refuses the job rather than billing for it. The cap is ~50x current size on purpose — a cap tight enough to trip on normal growth would convert a cost guard into data loss, since the archive would stop running. `require_partition_filter` is deliberately **not** set on these tables: the MERGE scans the whole target without a partition filter, so it would break the archiver.

`archival.py` holds only pure dict→dict transforms (no GCP imports) so the reshaping is unit-testable; `bigquery.py` holds all client work. Adding a column means editing one `TableSpec` — schema, MERGE and table creation are all generated from it. Note `ensure_dataset_and_tables` creates but never *alters*, so a new column needs a manual schema update on an existing table; until then the value is still captured in that table's `raw` column.

Full rationale, cost accounting and risks: `../../docs/feed-mind/bigquery-archival-plan.md`.

## Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `feedmind/config.py` | All constants: feed list (`(name, url, category, post_to_telegram)` tuples), GCP project ID, Firestore names, model name, timeouts, feature flags, system prompt |
| `feedmind/secrets.py` | Loads `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY` from GCP Secret Manager at startup |
| `feedmind/ingestion.py` | Fetches/parses RSS via feedparser; produces `Article` dataclass; filters articles older than `MAX_ARTICLE_AGE_DAYS` |
| `feedmind/deduplication.py` | Checks and writes to Firestore `processed_articles`; writes `expires_at` for TTL |
| `feedmind/summarization.py` | `summarize()` for Gemini; `summarize_with_sumy()` for offline LSA extraction |
| `feedmind/notification.py` | `build_category_messages()` to chunk and format; `send_message()` to POST via httpx; `send_plain_message()` for machine-generated text (escapes everything) |
| `feedmind/archival.py` | Archive `TableSpec`s + pure Firestore-doc → BigQuery-row transforms. No GCP imports |
| `feedmind/bigquery.py` | Dataset/table creation, staging loads and MERGE. All BigQuery client work |

## Configuration before deploying

Before first deploy, update these values in `feedmind/config.py` and `deploy.sh`:
- `GCP_PROJECT_ID` — your GCP project ID (currently `"feed-mind"`)
- `SCHEDULER_TIMEZONE` in `deploy.sh` — currently `"America/Chicago"`
- `ENABLE_GEMINI_SUMMARIES` — set to `True` to use Gemini instead of Sumy
- Validate the 13 RSS feed URLs in `config.RSS_FEEDS`

Secrets must exist in GCP Secret Manager: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`.

## Local ADC requirement

Local runs require Application Default Credentials with access to Secret Manager and Firestore:
```bash
gcloud auth application-default login
```

`requirements.txt` here is **generated** (by `deploy.sh`, or `scripts/lock-all.sh` for all three services at once) — don't hand-edit it. The source of truth is `pyproject.toml`, and `uv.lock` is committed. This service is an independent uv project, not a workspace member: it pins `google-cloud-firestore==2.19.0` while `services/summarizer` needs `==2.28.1`, and nothing forces those to agree.
