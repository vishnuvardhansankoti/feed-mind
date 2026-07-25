# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

FeedMind is a serverless RSS-to-Telegram pipeline deployed as a GCP Cloud Function (Gen 2). It runs daily via Cloud Scheduler: fetches 11 RSS feeds, deduplicates against Firestore, summarizes new articles with Gemini, and sends one Telegram message per article. The whole stack fits within GCP free-tier limits.

## Commands

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

**Lint:**
```bash
uv run ruff check .
uv run ruff format .
```

**Deploy to GCP:**
```bash
./deploy.sh   # updates requirements.txt, deploys function, creates/updates scheduler job
```

**Trigger a manual run in GCP:**
```bash
gcloud scheduler jobs run feedmind-daily-trigger --location=us-central1 --project=feed-mind
```

## Architecture

The pipeline is a single linear flow with no async or concurrency — articles for each feed are processed sequentially inside a 240-second soft timeout guard (5-minute hard Cloud Function limit).

```
main.py (HTTP trigger)
  └── load_all_secrets()          # secrets.py — GCP Secret Manager
  └── init_gemini()               # summarization.py — one model instance per run
  └── firestore.Client()          # shared across all feeds
  └── for each feed in RSS_FEEDS:
        └── fetch_feed()          # ingestion.py — feedparser, age-filtered, returns Article list
        └── for each article:
              └── is_duplicate()  # deduplication.py — single Firestore .get()
              └── summarize()     # summarization.py — Gemini, returns None on failure
              └── send_message()  # notification.py — httpx POST to Telegram
              └── mark_as_delivered()  # deduplication.py — write to Firestore ONLY after success
```

**Key invariant:** Firestore is written to **only after** both summarization and Telegram delivery succeed. Failed articles are not marked and will be retried on the next daily run.

**Article identity:** `article_id` is SHA-256 of the article URL, used as the Firestore document ID in the `processed_articles` collection.

## Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `feedmind/config.py` | All constants: feed list, GCP project ID, Firestore names, model name, timeouts, system prompt |
| `feedmind/secrets.py` | Loads `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY` from GCP Secret Manager at startup |
| `feedmind/ingestion.py` | Fetches/parses RSS via feedparser; produces `Article` dataclass; filters articles older than `MAX_ARTICLE_AGE_DAYS` |
| `feedmind/deduplication.py` | Checks and writes to Firestore collection `processed_articles` |
| `feedmind/summarization.py` | Wraps `google-generativeai` SDK; prompt constructed from `Article.title` + `Article.snippet` |
| `feedmind/notification.py` | Formats Telegram MarkdownV2 message; posts via httpx; sleeps 1s between calls for rate limiting |

## Configuration before deploying

Before first deploy, update these values in `feedmind/config.py` and `deploy.sh`:
- `GCP_PROJECT_ID` — your GCP project ID (currently `"feed-mind"`)
- `SCHEDULER_TIMEZONE` in `deploy.sh` — currently `"America/Chicago"`
- Validate the 11 RSS feed URLs in `config.RSS_FEEDS` — some may need verification

Secrets must exist in GCP Secret Manager: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY`.

## Local ADC requirement

Local runs require Application Default Credentials with access to Secret Manager and Firestore:
```bash
gcloud auth application-default login
```

The `requirements.txt` at repo root is **generated** (by `deploy.sh` via `uv pip compile`) for GCP deployment — don't hand-edit it. The source of truth for dependencies is `pyproject.toml`.
