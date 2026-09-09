# Firestore → BigQuery Archival Plan

**Status:** built, not yet deployed — `./deploy.sh` then trigger the first run (§6)
**Date:** 2026-08-29
**Scope:** `feed-mind` repo, plus one companion change to the daily pipeline

---

## 1. Problem

Three Firestore collections carry TTL policies that actively delete data:

| Collection | Written by | TTL field | TTL |
|---|---|---|---|
| `processed_articles` | `feed-mind` (this repo) | `expires_at` | 90 days |
| `youtube_videos` | `feed-mind` (this repo) | `expires_at` | 90 days |
| `runs` | `paper-prism` | `expire_at` | **45 days** |

TTL is **enabled today**, so this is live deletion, not a hypothetical. Anything past its window is already gone and unrecoverable.

The goal is a permanent, queryable copy in BigQuery to serve as the corpus for a future ML/LLM feature — which means preserving full text and stable IDs, not just counts.

Audio artifacts are explicitly out of scope. The `ai_summary` **text** is in scope.

---

## 2. Design at a glance

A second Cloud Function in this repo, `feedmind-archive`, on its own Cloud Scheduler job running the **1st and 16th of each month**. Each run reads *every live document* from all three sources and MERGEs them into three BigQuery tables.

```
Cloud Scheduler (0 4 1,16 * *)
  └── feedmind-archive  (Cloud Function Gen2, entry_point=archive)
        └── firestore.Client(feed-mind-db)
              ├── stream processed_articles   → rows
              ├── stream youtube_videos       → rows
              └── stream runs                 → unnest papers[] → rows
        └── for each table:
              ├── load_table_from_json() → staging table   (batch load, free)
              ├── MERGE staging INTO target ON <key>       (<100 MB scan, free)
              └── drop staging
        └── send_message()  → Telegram run report
```

Firestore TTL still does all deleting. **The archiver never writes to or deletes from Firestore.**

---

## 3. Decisions and rationale

### 3.1 Full scan every run, no watermark

Every run reads every live document rather than querying for "what's new."

**Why.** At ~50–100 articles/day over a 90-day TTL, the live set is roughly 5–9k documents; videos and runs add far less. A complete scan is ~10k Firestore reads against a **50k/day** free allowance, twice a month. The read savings from a watermark are worth nothing, and the watermark costs real correctness: a state document that can drift, a silent gap if a run fails after advancing the cursor, and range-query logic that has to straddle two different TTL field spellings.

**What this buys.** The archive is "the union of every document Firestore held while we were watching," and it self-heals. A missed run, a crashed run, a schema surprise, a late `ai_summary` — all corrected automatically on the next run, with no state to reconcile. The sibling `feed-mind-summarizer` already reads this way (`list(collection.stream())`).

**When it stops being right.** Roughly 100x current volume, where a single run would exceed the daily free read tier — and even then it is about $0.03 per run. Revisit if the feed list grows by an order of magnitude, not before.

### 3.2 MERGE, not append

Each run loads to a staging table and MERGEs on a stable key.

**Why.** `ai_summary` is written *asynchronously after* the article doc exists, by `feed-mind-summarizer` via `snapshot.reference.update()`. An append-only archive would freeze a `NULL` for any document copied before its summary landed. MERGE lets a later run backfill it. It also makes the whole job idempotent — re-running it, at any time, for any reason, is safe.

Batch loads are free and MERGE against a sub-100 MB table is far inside the 1 TiB/month free query tier, so this costs nothing over appending.

### 3.3 Papers flattened to one row per paper

**Why.** Papers are not documents. They live in a `papers` array inside `runs` docs (`paper-prism/CLAUDE.md:78`). For an ML corpus, one row per paper means one row per training item, with no `UNNEST` in every downstream query.

### 3.4 Typed columns plus a `raw` JSON safety net

Every table gets explicit typed columns *and* a `raw` JSON column holding the untouched Firestore document.

**Why.** This repo will now encode schema owned by two other repos (`paper-prism`, `feed-mind-summarizer`). Strict typing alone turns any upstream field addition into either a failed run or silently discarded data. With `raw`, an unanticipated field is merely *unpromoted* — still archived, still recoverable, promotable to a real column later. Storage is free at this scale, so the duplication costs nothing.

### 3.5 Schedule: 1st and 16th

`0 4 1,16 * *` — max gap 16 days.

**Why not the 15th only**, as originally asked: that is a ~31-day gap against a **45-day** papers TTL, leaving 14 days of slack. One silent failure and research data is permanently lost. The 1st/16th cadence leaves ~29 days of margin and survives a completely missed run. Cron cannot express "every 15 days" anyway — `*/15` on day-of-month yields the 1st, 16th and 31st, a ragged 15/15/1 cycle.

### 3.6 Second function in this repo

Reuses `scripts/deploy-feedmind.sh`, `feedmind-sa`, and the core package's `settings.py`, `secrets.py` and `telegram.py`. Uses the 2nd of 3 free Scheduler jobs.

**Rejected:** GitHub Actions cron. Genuinely free, and WIF is already set up (`setup-wif.sh`) — but GitHub **silently disables scheduled workflows after 60 days without a commit**, and its cron is best-effort and frequently delayed. For a twice-monthly job protecting a 45-day TTL on a repo that may go quiet, that is a direct data-loss path.

**Rejected:** folding it into the daily ingest function. No new Scheduler job needed, but it runs inside the 300s hard limit and makes an archival bug capable of breaking the daily Telegram digest.

### 3.7 Telegram run report

Reuses `notification.send_message` and the bot token already in Secret Manager. One line per run: rows merged per table, or the error.

**Why it is not optional.** With a 16-day cadence against a 45-day TTL, this is the only thing between a broken run and permanent loss. It goes to a channel already read daily, so silence is noticeable in a way an alerting email is not.

---

## 4. Data model

Dataset `feedmind_archive`, US multi-region (confirmed). Tables never expire. Partitioning and clustering below are good practice, not cost-driven: the entire dataset is well under 100 MB.

**Deviation from the original plan: `raw` is a STRING holding JSON text, not BigQuery's native JSON type.** Loading into a JSON column via `load_table_from_json` has ambiguous behaviour around whether the value must be pre-serialized, and that only fails at runtime — in a job that runs twice a month against a 45-day TTL, in an environment I cannot test against before deploy. STRING loads unambiguously. The query ergonomics are near-identical: `JSON_VALUE(raw, '$.field')` and `JSON_EXTRACT_SCALAR` both accept STRING. If native JSON is wanted later it is a one-word change in the `TableSpec` plus a table migration.

### 4.1 `articles`

Source: `processed_articles`. MERGE key: `article_id`. Partition: `DATE(processed_at)`. Cluster: `feed_category`, `feed_source`.

| Column | Type | Source field | Notes |
|---|---|---|---|
| `article_id` | STRING | `article_id` | SHA-256 of URL; doc ID |
| `url` | STRING | `url` | |
| `title` | STRING | `title` | |
| `snippet` | STRING | `snippet` | Shipped — see §5. NULL for anything written before it |
| `summary` | STRING | `summary` | Sumy/Gemini one-liner |
| `ai_summary` | STRING | `ai_summary` | Written later by summarizer; nullable |
| `feed_source` | STRING | `feed_source` | |
| `feed_category` | STRING | `feed_category` | |
| `published_at` | TIMESTAMP | `published_at` | parsed from ISO string |
| `processed_at` | TIMESTAMP | `processed_at` | parsed from ISO string |
| `status` | STRING | `status` | |
| `raw` | STRING | whole doc | JSON text; safety net |
| `archived_at` | TIMESTAMP | — | set by archiver |

`audio_url` / `audio_generated_at` are deliberately **not** promoted to columns; they remain in `raw`.

### 4.2 `videos`

Source: `youtube_videos`. MERGE key: `video_id`. Partition: `DATE(processed_at)`. Cluster: `channel`.

Columns: `video_id`, `url`, `title`, `channel`, `thumbnail_url`, `published_at` (TIMESTAMP), `processed_at` (TIMESTAMP), `raw` (STRING, JSON text), `archived_at` (TIMESTAMP).

### 4.3 `papers`

Source: `papers[]` unnested from `runs` docs. Partition: `DATE(run_date)`. Cluster: `category`.

**MERGE key: `run_id` + `arxiv_id`** — sufficient and unique. `RunDocument.doc_id` is `YYYY-MM-DD_<CATEGORY>` (`paper-prism/pipeline/src/paper_prism/models.py:73-75`), so the run ID already encodes both date and category, and a paper appears at most once per run doc. No third key component is needed.

| Column | Type | Source | Notes |
|---|---|---|---|
| `run_id` | STRING | run doc ID | `YYYY-MM-DD_<CATEGORY>` |
| `run_date` | TIMESTAMP | `run_date` | already a datetime in Firestore |
| `category` | STRING | `category` | lens: ML / NLP / CV |
| `rank` | INT64 | `papers[].rank` | |
| `arxiv_id` | STRING | `papers[].arxiv_id` | |
| `title` | STRING | `papers[].title` | |
| `url` | STRING | `papers[].url` | |
| `score` | FLOAT64 | `papers[].score` | rounded to 4dp upstream |
| `abstract` | STRING | `papers[].abstract` | **real text**; nullable |
| `summary` | STRING | `papers[].summary` | Gemini blurb; null when that call failed |
| `ai_summary` | STRING | `papers[].ai_summary` | injected later by summarizer; nullable |
| `raw` | STRING | the paper object | JSON text; safety net |
| `archived_at` | TIMESTAMP | — | set by archiver |

The `run_status` collection is **not** archived.

---

## 5. Companion change: persist `snippet` — **shipped**

`mark_as_delivered` (now `feedmind_core.store.save_article`) previously wrote `article_id, url, title, feed_source, feed_category, summary, published_at, processed_at, expires_at, status`. The `snippet` — up to 2,000 chars of actual article text, already fetched and already used for summarization — was **discarded**, leaving a corpus of titles, one-sentence summaries and URLs. No prose. (Papers were never affected: `abstract` is persisted upstream.)

`"snippet": article.snippet` now goes into the `doc_ref.set()` payload. Firestore cost is roughly 200 KB/day against a 1 GiB free tier.

**It only affects articles written after it reaches production.** Nothing already in Firestore gained text, everything past its 90-day TTL is gone, and the change is inert until `./deploy.sh` runs. Every day between now and that deploy is another day of text-less rows.

---

## 6. Implementation status

Everything below the line is built and tested locally. Nothing is deployed.

- [x] **Persist `snippet`** (§5) — `feedmind/deduplication.py`, covered by `tests/test_deduplication.py`.
- [x] **`feedmind/archival.py`** — `TableSpec` definitions plus pure `article_row()` / `video_row()` / `paper_rows()` transforms and `dedupe_by_key()`. No GCP imports, so all of it is unit-tested (`tests/test_archival.py`).
- [x] **`feedmind/bigquery.py`** — `ensure_dataset_and_tables()`, `archive_table()` (batch load → staging → MERGE → drop). MERGE SQL is generated from the `TableSpec` and asserted in `tests/test_bigquery.py`.
- [x] **`archive` entry point in `main.py`** — orchestrates, isolates per-table failures, sends the Telegram report, returns a JSON summary in the same style as the `feedmind` handler.
- [x] **`config.py`** — `BQ_DATASET`, `BQ_LOCATION`, `FIRESTORE_RUNS_COLLECTION`, `ENABLE_ARCHIVE_TELEGRAM_REPORT`.
- [x] **`deploy.sh`** — enables `bigquery.googleapis.com`, grants `roles/bigquery.dataEditor` + `roles/bigquery.jobUser`, deploys `feedmind-archive` at a 900s timeout, creates the `feedmind-archive-biweekly` job at `0 4 1,16 * *`.
- [ ] **Deploy:** `./deploy.sh`. This is also what makes the `snippet` change live.
- [ ] **Dry run (optional):** `python main.py archive` reads Firestore with ADC and prints what it would write, touching neither BigQuery nor Telegram.
- [ ] **First run on demand:** `gcloud scheduler jobs run feedmind-archive-biweekly --location=us-central1 --project=feed-mind`. Deliberately the same path the schedule uses, so the first run proves the scheduled path rather than a different one.
- [ ] **Verify:** compare row counts per table against Firestore document counts (see §8.5 on why papers may legitimately exceed them); spot-check that `ai_summary` is populated where expected; run it a second time immediately and confirm the row counts are unchanged, which proves the MERGE is idempotent.

Memory note: each source is read, reshaped, loaded and discarded before the next one starts, so peak memory is one collection rather than all three.

---

## 7. Cost

| Component | Usage | Free allowance | Cost |
|---|---|---|---|
| Firestore reads | ~20k/month | 50k/**day** | $0 |
| BigQuery batch loads | ~6/month | always free | $0 |
| BigQuery storage | <100 MB | 10 GiB/month | $0 |
| BigQuery MERGE queries | ~6 × <100 MB | 1 TiB/month | $0 |
| Cloud Scheduler | 2nd job | 3 free | $0 |
| Cloud Function | 24 invocations/year | 2M/month | $0 |
| Firestore writes (snippet) | unchanged count | 20k/day | $0 |

**The one trap:** BigQuery **streaming inserts are not free** — $0.01 per 200 MB, with no free tier. `insert_rows_json()` is the streaming API. This design uses `load_table_from_json()` (batch) exclusively. Anyone "optimizing" the archiver toward streaming is converting a free job into a billed one for no latency benefit a twice-monthly batch could use.

### 7.1 Staying inside the free tier

The table above is arithmetic — it says the archive *happens* to fit. These settings are what make it *stay* fitting.

**Enforced in code:**

| Guard | Where | What it does |
|---|---|---|
| `maximum_bytes_billed` = 10 GiB | `bigquery.py`, on every MERGE | BigQuery **rejects the job before running it** if it would scan more. A runaway MERGE fails loudly in the Telegram report instead of quietly billing. |
| Batch loads only | `bigquery.py` | `load_table_from_json`, never `insert_rows_json`. |
| Staging tables always dropped | `bigquery.py` `finally:` block | Orphans would count against the 10 GiB storage tier. A 6-hour table expiration is the backstop for a hard-killed function. |
| Storage reported every run | `main.py` run report | `X MB of 10.0 GB free tier`, with `— APPROACHING LIMIT` past 80%. Read from table metadata, which is a free API call, not a query. |

**Sizing the cap.** 10 GiB is roughly 50x the current archive. Growth is ~200 MB/year (the MERGE scans the whole target table each run, and the target only grows), so normal operation will not approach it for decades. That headroom is deliberate: **a cap tight enough to trip on real growth converts a cost guard into data loss**, because the archive simply stops running. Tripping this cap means a bug, not success.

**Not set, deliberately:** `require_partition_filter` on the tables. It would force every ad-hoc query to include a partition filter — good discipline — but the MERGE reads the whole target table without one, so enabling it breaks the archiver.

**Worth doing in the console (I can't script these safely — the quota IDs and your billing account ID aren't things I should guess):**

1. **Billing budget alert.** Billing → Budgets & alerts → a $1 budget on the project with alerts at 50/90/100%. This is the catch-all that catches anything this plan didn't anticipate, including services other than BigQuery. Free.
2. **Custom BigQuery query quota.** IAM & Admin → Quotas → *BigQuery API: Query usage per day*. Capping it at, say, 50 GiB/day makes it impossible for any query — yours, mine, or a Looker Studio dashboard left on auto-refresh — to eat the 1 TiB monthly allowance. This is the only guard that also covers queries the archiver never issues.

Of the two, the budget alert matters more: the archiver's own usage is bounded by `maximum_bytes_billed`, but **your ad-hoc querying of the corpus is not**, and that's the realistic path to a surprise bill on an ML dataset you intend to actually use.

---

## 8. Risks

1. **Papers have 14 days of real slack, not 45.** Two consecutive silent failures loses research data permanently. The Telegram report is the mitigation, not decoration.
2. **`ai_summary` nulls come in two kinds.** MERGE backfills summaries written *late*. It cannot fix summaries **never written** — `collect_articles` in `feed-mind-summarizer` only processes the single most recent `processed_at` date, so any day that job fails leaves those articles permanently unsummarized. Expect a nonzero null rate; it is not an archiver bug.
3. **Cross-component coupling.** The archiver encodes `services/paper-prism`'s `runs`/`papers` shape and `services/summarizer`'s field names. (Written when these were three separate repos; they are one now, so a breaking change is at least visible in a single diff.) A change in either surfaces as an archiver failure. The `raw` column caps the blast radius at "field not promoted" rather than "data lost."
4. **Field-name asymmetry:** `expires_at` (articles/videos) vs `expire_at` (runs). Harmless under full-scan, which is part of why full-scan was chosen — but it will bite anyone who later adds a "just filter on TTL" optimization.
5. **`runs` docs are overwritten in place.** `doc_id` is deterministic (`YYYY-MM-DD_<CATEGORY>`) and paper-prism re-runs overwrite cleanly, so a re-ranked re-run can replace the `papers` array. Because the archive never deletes, BigQuery may retain papers no longer present in Firestore. That is the desired behavior for an archive — but it means BQ is a superset of Firestore, not a mirror, and row counts will not match exactly after any upstream re-run.
6. **The archive can only contain what Firestore contains.** No amount of archiver work recovers the text that §5 has been discarding, or anything already past TTL.

---

## 9. Open items

- ~~Confirm BigQuery dataset location~~ — confirmed `US` multi-region.
- Set the billing budget alert and the custom query quota (§7.1). Neither is scripted.
- Confirm dataset name `feedmind_archive` and table names `articles` / `videos` / `papers`.
