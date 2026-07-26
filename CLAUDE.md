# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

FeedMind is a serverless RSS-to-Telegram pipeline deployed as a GCP Cloud Function (Gen 2). It runs daily via Cloud Scheduler: fetches 13 RSS feeds, deduplicates against Firestore, summarizes new articles, and pushes **batched Telegram messages grouped by category** (Academic / Industry / Cloud). The whole stack fits within GCP free-tier limits.

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
              └── collect into category_items dict (not sent yet)
  └── for each category in category_items:
        └── build_category_messages() # notification.py — chunks into ≤4000-char messages
        └── send_message() per chunk  # httpx POST to Telegram
        └── mark_as_delivered()       # Firestore write ONLY after successful delivery
```

**Key invariant:** Firestore is written to **only after** successful Telegram delivery. Failed articles are not marked and will be retried on the next daily run.

**Article identity:** `article_id` is SHA-256 of the article URL, used as the Firestore document ID in the `processed_articles` collection. Firestore documents include an `expires_at` field (90 days) for TTL-based auto-deletion.

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

## Module responsibilities

| Module | Responsibility |
|--------|---------------|
| `feedmind/config.py` | All constants: feed list, GCP project ID, Firestore names, model name, timeouts, feature flags, system prompt |
| `feedmind/secrets.py` | Loads `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY` from GCP Secret Manager at startup |
| `feedmind/ingestion.py` | Fetches/parses RSS via feedparser; produces `Article` dataclass; filters articles older than `MAX_ARTICLE_AGE_DAYS` |
| `feedmind/deduplication.py` | Checks and writes to Firestore `processed_articles`; writes `expires_at` for TTL |
| `feedmind/summarization.py` | `summarize()` for Gemini; `summarize_with_sumy()` for offline LSA extraction |
| `feedmind/notification.py` | `build_category_messages()` to chunk and format; `send_message()` to POST via httpx |

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

The `requirements.txt` at repo root is **generated** (by `deploy.sh` via `uv pip compile`) for GCP deployment — don't hand-edit it. The source of truth for dependencies is `pyproject.toml`.
