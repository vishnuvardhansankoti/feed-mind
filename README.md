# FeedMind

A self-hosted, serverless RSS ingestion and AI-summarization pipeline running on GCP.

Ingests 11 RSS feeds (AI/ML research, industry news, cloud computing), summarizes new articles using **Gemini 3.5 Flash Lite** (or the offline **Sumy NLP** library), and pushes batched notifications to a private **Telegram bot** — once daily, at $0/month.

---

## Project Structure

```
feed-mind/
├── main.py             # Two Cloud Function entry points: feedmind (daily) and archive
├── feedmind/           # Core application package
│   ├── __init__.py
│   ├── config.py       # Feed URLs, constants, system prompt, BigQuery settings
│   ├── secrets.py      # GCP Secret Manager loader
│   ├── ingestion.py    # RSS feed fetching & parsing (feedparser)
│   ├── deduplication.py # Firestore dedup check & write
│   ├── summarization.py # Gemini AI & Sumy offline NLP summarization
│   ├── notification.py # Telegram batched message delivery
│   ├── events.py       # Pub/Sub announcement when a run finishes
│   ├── archival.py     # Firestore doc → BigQuery row shaping, table specs
│   └── bigquery.py     # Dataset/table creation, batch load + MERGE
├── docs/
│   └── bigquery-archival-plan.md  # Full design & rationale for the archive
├── tests/              # Unit tests
│   ├── __init__.py
│   └── test_config.py
├── pyproject.toml      # Python dependencies & config
└── deploy.sh           # One-shot GCP deployment script (both functions)
```

---

## Prerequisites

1. **GCP Project** with billing enabled (free tier is sufficient)
2. **gcloud CLI** installed: https://cloud.google.com/sdk/docs/install
3. **Telegram Bot** created via [@BotFather](https://t.me/botfather) — get your bot token and chat ID
4. **Gemini API Key** from [Google AI Studio](https://aistudio.google.com/app/apikey)
5. **Firestore** database created in Native Mode (GCP Console → Firestore → Create Database)

---

## Setup

### 1. Clone & configure

```bash
git clone <repo>
cd feed-mind
```

Edit `config.py`:
- Set `GCP_PROJECT_ID` to your GCP project ID
- Validate and update the RSS feed URLs in `RSS_FEEDS` (some may need real RSS paths)

### 2. Set up Firestore Database

This project uses Firestore to keep track of articles it has already seen (deduplication).

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your project.
3. In the navigation menu, go to **Firestore**.
4. Click **Create Database**.
5. Select **Native mode** (required for this project).
6. Choose a location (e.g., `nam5` for multi-region US or a specific region) and click **Create Database**.

### 3. Create secrets in Secret Manager

```bash
PROJECT_ID="your-gcp-project-id"

# Telegram Bot Token (from BotFather)
echo -n "YOUR_TELEGRAM_BOT_TOKEN" | \
  gcloud secrets create TELEGRAM_BOT_TOKEN --data-file=- --project=$PROJECT_ID

# Telegram Chat ID (your personal chat ID or group ID)
echo -n "YOUR_TELEGRAM_CHAT_ID" | \
  gcloud secrets create TELEGRAM_CHAT_ID --data-file=- --project=$PROJECT_ID

# Gemini API Key (from Google AI Studio)
echo -n "YOUR_GEMINI_API_KEY" | \
  gcloud secrets create GEMINI_API_KEY --data-file=- --project=$PROJECT_ID
```

> **Tip:** To find your Telegram Chat ID, send a message to your bot and call:
> `https://api.telegram.org/bot<TOKEN>/getUpdates`

### 4. Deploy

```bash
# Update PROJECT_ID and SCHEDULER_TIMEZONE in deploy.sh first
chmod +x deploy.sh
./deploy.sh
```

The script will:
- Enable all required GCP APIs (including BigQuery)
- Create a `feedmind-sa` service account with minimum IAM roles
- Deploy **two** Cloud Functions (Gen 2, authenticated only) from the same source:
  `feedmind` (daily digest) and `feedmind-archive` (Firestore → BigQuery)
- Create a `feedmind-scheduler` invoker service account
- Set up **two** Cloud Scheduler jobs — the daily digest at 8 AM, and the archive
  on the 1st and 16th at 4 AM

The archive half is covered in detail in
[Archive: Firestore → BigQuery](#archive-firestore--bigquery) below, including
the two free-tier guards the script deliberately does *not* create for you.

### 5. Test manually

```bash
gcloud scheduler jobs run feedmind-daily-trigger \
  --location=us-central1 \
  --project=your-gcp-project-id
```

Then check Cloud Logging:
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND jsonPayload.message="FeedMind run complete"' \
  --limit=5 \
  --project=your-gcp-project-id \
  --format=json
```

---

## Downstream: announcing a finished run

As its last step, FeedMind publishes to a Pub/Sub topic so downstream consumers
know new articles have landed. Today there is one consumer —
[`feed-mind-summarizer`](../feed-mind-summarizer), which turns those articles
into spoken summaries.

```
FeedMind run ends ──publish──► feedmind-content-ready ──► feedmind-audio
```

FeedMind is the only thing that knows when its run actually finished, so it
announces rather than leaving the consumer to guess with a schedule of its own.
The message is small — `process_doc` selects which consumer pipeline to run, the
rest is provenance:

```json
{"process_doc": "RSS_FEED", "source": "feed-mind", "articles_delivered": 7,
 "run_completed_at": "2026-08-23T13:15:04+00:00"}
```

Two deliberate behaviours in `feedmind/events.py`:

- **Nothing is published when no articles were delivered.** Waking the consumer
  to find an empty batch costs a cold start and buys nothing.
- **Publishing is best-effort.** A run that summarized and delivered has done
  its job; failing it because Pub/Sub was unreachable would turn a good run into
  a retried one, and the retry would re-deliver every article to Telegram.
  Errors are logged and swallowed.

Publishing happens after every article is written to Firestore — the consumer
reads that collection, so announcing any earlier would race it.

| Setting | In `feedmind/config.py` |
|---|---|
| `ENABLE_CONTENT_READY_EVENTS` | `True` — set `False` to stop announcing |
| `CONTENT_READY_TOPIC` | `feedmind-content-ready` |
| `CONTENT_READY_PROCESS_DOC` | `RSS_FEED` |

The topic itself, and `feedmind-sa`'s `roles/pubsub.publisher` grant on it, are
created by the consumer's `deploy/setup.sh` — the topic belongs to whoever reads
it. Run that before deploying this side, or the first publish will log a
permission error (and only that: the run still succeeds).

---

## Archive: Firestore → BigQuery

Every Firestore collection this pipeline touches is on a TTL — 90 days for
`processed_articles` and `youtube_videos`, **45 days** for paper-prism's `runs`.
Anything not copied out before then is deleted permanently. `feedmind-archive`
is the second Cloud Function that does the copying.

```
processed_articles ┐
youtube_videos     ├─ feedmind-archive (1st & 16th, 04:00) ─► BigQuery feedmind_archive
runs               ┘                                          articles / videos / papers
```

It is deployed **from the same source as the daily function**, with a different
entry point (`archive`) and its own timeout and Scheduler job. Separate functions
so an archival bug cannot break the daily digest, and so the archive can have a
15-minute timeout the 5-minute digest would not tolerate.

| | Daily digest | Archive |
|---|---|---|
| Function | `feedmind` | `feedmind-archive` |
| Entry point | `feedmind` | `archive` |
| Timeout | `300s` | `900s` |
| Scheduler job | `feedmind-daily-trigger` | `feedmind-archive-biweekly` |
| Schedule | `0 8 * * *` | `0 4 1,16 * *` |

The 1st/16th cadence is a 16-day maximum gap, chosen against the 45-day `runs`
TTL so that even a completely missed run leaves ~29 days of margin.

Every run reads **everything** and MERGEs — no watermark, no cursor. Running it
twice in a row is harmless, and a missed or failed run is corrected by simply
running it again.

### Step 1 — Dry-run it locally first

Running `main.py` with the `archive` argument reads Firestore and builds the rows
but writes nothing to BigQuery and sends no Telegram report:

```bash
uv run python main.py archive
```

Requires ADC with Firestore read access (`gcloud auth application-default login`).
You should see one `--- WOULD ARCHIVE N row(s) to <table> ---` line per table and
a `--- WOULD REPORT TO TELEGRAM ---` block. Three tables with plausible counts
means the shaping code agrees with what is actually in Firestore.

### Step 2 — Deploy

```bash
./deploy.sh
```

The same script deploys both functions. For the archive specifically it:

- enables `bigquery.googleapis.com`
- grants `feedmind-sa` **`roles/bigquery.dataEditor`** (the data) and
  **`roles/bigquery.jobUser`** (running load and query jobs) — both are needed,
  `dataEditor` alone cannot start a job
- deploys `feedmind-archive` with `--entry-point=archive --timeout=900s`
- grants `feedmind-scheduler` invoker on it
- creates or updates the `feedmind-archive-biweekly` Scheduler job with OIDC auth

Nothing to create by hand in BigQuery: the function calls
`ensure_dataset_and_tables()` on every run, so the `feedmind_archive` dataset
(US multi-region) and the three partitioned, clustered tables are created on
first use and skipped thereafter.

> `ensure_dataset_and_tables` creates but never **alters**. Adding a column to a
> `TableSpec` will not reshape a table that already exists — that needs an
> explicit schema update. Survivable meanwhile, because the value is still
> archived inside the `raw` JSON column.

### Step 3 — Run the first archive on demand

The Scheduler job is the only invoker, so trigger through it rather than curling
the URL:

```bash
gcloud scheduler jobs run feedmind-archive-biweekly \
  --location=us-central1 \
  --project=feed-mind
```

A successful run sends a Telegram report:

```text
FeedMind archive complete
articles: 412 rows from 412 docs
videos: 88 rows from 88 docs
papers: 240 rows from 30 docs
storage: 41.3 MB of 10.0 GB free tier
duration: 37.4s
```

The report is the failure detector, not decoration — papers have only ~14 days
of real slack, so two consecutive silent failures lose research data permanently.
A failed table shows as `<table>: ERROR — …` and the function returns HTTP 500,
while the other tables still archive.

### Step 4 — Verify the data landed

```bash
gcloud functions logs read feedmind-archive --gen2 --region=us-central1 --limit=50

bq ls --project_id=feed-mind feedmind_archive

bq query --use_legacy_sql=false --project_id=feed-mind \
  'SELECT "articles" AS t, COUNT(*) n FROM `feed-mind.feedmind_archive.articles`
   UNION ALL SELECT "videos", COUNT(*) FROM `feed-mind.feedmind_archive.videos`
   UNION ALL SELECT "papers", COUNT(*) FROM `feed-mind.feedmind_archive.papers`'
```

Row counts will **not** match Firestore exactly, and that is correct: the archive
never deletes, so it becomes a superset once upstream docs expire or a
paper-prism re-run overwrites a `runs` doc.

Expect a nonzero `ai_summary` null rate too. MERGE backfills summaries written
*late* by `feed-mind-summarizer`, but cannot invent ones never written at all.

### Step 5 — The two free-tier guards `deploy.sh` cannot create

Both need your billing account ID or a quota ID, so the script prints a reminder
instead of guessing. Neither costs anything:

1. **Billing budget alert** — Billing → Budgets & alerts → a $1 budget on the
   project with alerts at 50/90/100%. The catch-all for anything this design
   didn't anticipate, including services other than BigQuery.
2. **Custom BigQuery query quota** — IAM & Admin → Quotas →
   *BigQuery API: Query usage per day*, capped at e.g. 50 GiB/day. The archiver
   caps its own queries via `maximum_bytes_billed`; this caps **your ad-hoc
   ones**, which is the realistic path to a surprise bill on a dataset you
   intend to actually query.

### Archive configuration

In `feedmind/config.py`:

| Setting | Default | Notes |
|---|---|---|
| `BQ_DATASET` | `feedmind_archive` | |
| `BQ_LOCATION` | `US` | Multi-region. Fixed at dataset creation |
| `BQ_MAX_BYTES_BILLED` | 10 GiB | BigQuery rejects a MERGE that would scan more, before running it |
| `BQ_FREE_STORAGE_BYTES` | 10 GiB | Reported every run |
| `BQ_STORAGE_WARN_BYTES` | 8 GiB | Past this the report says `— APPROACHING LIMIT` |
| `ENABLE_ARCHIVE_TELEGRAM_REPORT` | `True` | Set `False` to archive silently |

In `deploy.sh`: `ARCHIVE_FUNCTION_NAME`, `ARCHIVE_ENTRY_POINT`,
`ARCHIVE_TIMEOUT`, `ARCHIVE_JOB_NAME`, `ARCHIVE_SCHEDULE`.

> **Do not switch the writes to `insert_rows_json()`.** That is the streaming
> API — $0.01 per 200 MB with no free tier. `bigquery.py` uses
> `load_table_from_json()` (batch loads, always free) deliberately; a twice-
> monthly job has no use for streaming's latency.

### Archive troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `403 … bigquery.jobs.create denied` | `feedmind-sa` missing `roles/bigquery.jobUser` | Re-run `./deploy.sh` |
| One table reports `ERROR —`, others succeed | Upstream field shape changed | Check `archival.py` against the collection; data is still in the `raw` column meanwhile |
| No Telegram report, but logs say complete | Secret loading failed, or the report is disabled | Check `ENABLE_ARCHIVE_TELEGRAM_REPORT` and the three secrets |
| `Query exceeded limit for bytes billed` | The 10 GiB `maximum_bytes_billed` cap tripped | This means a bug, not growth — investigate before raising it |
| Dataset slowly filling with `*_staging_*` tables | The function was hard-killed mid-run | They self-expire after 6 hours; if not, `bq rm` them |
| Papers row count dropped after a re-run | paper-prism overwrote a `runs` doc in place | Expected — BQ keeps the superset |

Full rationale for every decision above lives in
[`docs/bigquery-archival-plan.md`](docs/bigquery-archival-plan.md).

---

## Local Development

We use [uv](https://docs.astral.sh/uv/) for lightning-fast Python dependency management.

```bash
# Install dependencies and create a virtual environment automatically
uv sync

# Run locally using Functions Framework
# (requires Application Default Credentials: gcloud auth application-default login)
uv run functions-framework --target=feedmind --debug
```

Then trigger it:
```bash
curl -X POST http://localhost:8080
```

> For local runs, Application Default Credentials (ADC) are used automatically.
> Ensure your local ADC has access to Secret Manager and Firestore in your GCP project.

### Linting

```bash
# Check for lint errors
uv run ruff check .

# Auto-fix fixable lint errors
uv run ruff check --fix .
```

---

## Cost Analysis

| Service | Monthly Usage | Free Limit | Cost |
|---------|--------------|------------|------|
| Cloud Functions | 32 invocations | 2M/month | $0.00 |
| Cloud Scheduler | 2 jobs | 3 jobs | $0.00 |
| Firestore reads | ~6,600 + ~20K archive | 1.5M/month | $0.00 |
| Firestore writes | ~450 | 600K/month | $0.00 |
| Secret Manager | 90 accesses | 10K/month | $0.00 |
| Gemini 3.5 Lite (Optional) | ~450 req | 45K/month | $0.00 |
| BigQuery storage | <100 MB | 10 GiB/month | $0.00 |
| BigQuery loads + MERGE | ~6 loads, ~6 queries | loads free, 1 TiB queries | $0.00 |
| **Total** | | | **$0.00** |

Both Scheduler jobs together use 2 of the 3 free ones. The archive's Firestore
reads are a full scan of the live set twice a month — well inside the
**50K/day** read allowance.

---

## Telegram Message Format

Articles are now **batched by category** to reduce notification spam. Each daily run yields up to 3 messages (Academic, Industry, Cloud). 
Example:

```text
*🎓 Academic News*

• *Attention Is All You Need* — Introduces multi-head self-attention replacing recurrence in seq2seq models.
  🔗 Read More | 📰 arXiv ML

• *LoRA: Low-Rank Adaptation* — A new technique that freezes pre-trained model weights.
  🔗 Read More | 📰 Hugging Face Papers
```

---

## Open Items Before Production

- [ ] Validate all 11 RSS feed URLs return valid feeds
- [ ] Set correct timezone in `deploy.sh` (`SCHEDULER_TIMEZONE`)
- [ ] Replace `your-gcp-project-id` in `config.py` and `deploy.sh`
- [ ] Create Firestore database in Native Mode
- [ ] Create all 3 secrets in Secret Manager
- [ ] Dry-run the archive (`uv run python main.py archive`) before the first real run
- [ ] Set the billing budget alert and the custom BigQuery query quota — neither is scripted
