# packages/feedmind-core

The pipeline every FeedMind ingest service shares. The system-level view is in
the **root `CLAUDE.md`**; read that first if you are changing anything another
component reads.

## What this is

    feeds.yaml -> fetch -> dedupe -> summarize -> Firestore -> announce

A service is a `feeds.yaml`, a Cloud Scheduler cron, and a `main.py` that loads
the config and calls `runner.run_rss_ingest` or `runner.run_youtube_ingest`.
Everything else is here. Adding a fourth ingest service is a directory, not a
code change — which is the whole reason this package exists.

| Module | Responsibility |
|---|---|
| `serviceconfig.py` | `feeds.yaml` → `ServiceConfig`, validated on load |
| `runner.py` | the ingest pipeline itself; both entry points |
| `models.py` | `Article`, `Video`. **Standard library only** |
| `ingestion.py` | feedparser wrappers; re-exports the models |
| `store.py` | Firestore reads/writes, incl. the notifier's queue |
| `summarization.py` | Gemini, and offline Sumy |
| `telegram.py` | message formatting and the Bot API call |
| `events.py` | Pub/Sub announcements |
| `secrets.py` | Secret Manager |
| `settings.py` | shared constants — **never feed lists** |
| `archival.py` | Firestore doc → BigQuery row; pure transforms |
| `bigquery.py` | archive dataset/table creation, load and MERGE |

## Three things that will bite you

**1. `models.py` must not import anything outside the standard library, and
lazy imports in `runner.py` must stay lazy.** Both exist to make the per-service
dependency extras work. The notifier installs `feedmind-core[telegram]` and has
no feedparser; youtube-ingest installs `[feeds]` and has no pubsub. A top-level
`from feedmind_core.ingestion import Article` in `store.py` or `telegram.py`
puts feedparser back in everybody's image, and the ImportError lands at cold
start rather than at deploy time. `scripts/test-all.sh` smoke-tests every
service's import for exactly this reason.

**2. Feed lists do not belong in `settings.py`.** They live in each service's
`feeds.yaml`. The old module was imported by everything, so a typo in one feed
list could break an unrelated function at import time. `tests/test_service_configs.py`
validates the real committed YAML files, so a bad feed URL fails in CI.

**3. `telegram_status` is the delivery contract.** `save_article` defaults to
`SKIPPED`, deliberately — a service that forgets to ask for delivery produces
articles the notifier ignores, rather than an unexpected Telegram flood. The
notifier acts on `fetch_pending_telegram`, never on the Pub/Sub message body,
which is what makes a dropped message cost a delay instead of articles.

`fetch_pending_telegram` is a single-field equality filter with **no
`order_by`** — Firestore indexes single fields automatically, but ordering on a
different field needs a composite index deployed before the notifier could run
at all. Sorting happens in Python.

## Commands

```bash
uv sync                    # the dev group carries every extra, so tests can import anything
uv run pytest -q
uvx ruff check .           # config is the repo-root ruff.toml
```

Consumers depend on this as an **editable** path dependency, so an edit here is
picked up by `uv run` in any service with no reinstall. It reaches a deployed
function by being copied — see `scripts/stage-service.sh`.

`requires-python` is `>=3.12` and cannot drop to 3.11 without unpinning numpy,
which sumy needs.
