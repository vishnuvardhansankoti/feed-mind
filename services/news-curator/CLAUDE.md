# services/news-curator

Guidance for working inside this service. The system-level view is in the
**root `CLAUDE.md`**; read that first if you are changing anything another
component reads. Design source of truth:
`../../docs/feed-mind/news-curator-design.md` — code comments reference its
sections (e.g. "design doc §4.5").

## What this service is

A Cloud Run **service** (not a Job — Eventarc cannot target a Job directly,
and this needs to run on an event, not a clock) with a Pub/Sub **push**
subscription on `feedmind-news-ingested`. It embeds, classifies, clusters and
ranks `services/india-news-ingest`'s articles, then writes the `stories`
collection and stamps `story_id` / `is_canonical` back onto
`processed_articles`.

**Scope of what is built here (steps 1-2 of the design doc's build order,
§11):** the curation pipeline itself, run either from a real Pub/Sub push
(`main.py`) or by hand against real Firestore data for tuning
(`__main__.py`). **Not built yet:** wiring `feedmind-content-ready` so
`services/summarizer` picks up canonical stories (§11 step 3), the
`apps/web` Stories view (step 4), or the `services/archive` table (step 5).
Until step 3 lands, `stories` documents exist with `ai_summary: null` and
`audio_url: null` forever — that is expected, not a bug.

## Pipeline order is the whole point

Embed → classify (coarse) → cluster (within coarse, across all 5 papers) →
rank → select top-K/category. This runs entirely on `title. description` —
never the scraped article body, never an LLM call. See design doc §3.1 for
the cost math this protects: clustering after summarization would mean every
one of ~223 articles/day gets an LLM call and a Cloud TTS render before
anything discovers three of them were the same story.

## `embedder.py` is copied, not shared

Byte-for-byte from `services/paper-prism/src/paper_prism/embedder.py`, with a
pointer comment at the top. This service does not depend on `feedmind-core`
(no torch anywhere in this pipeline; a different Firestore version pin than
the FeedMind family) and paper-prism runs `python:3.11-slim` while
`feedmind-core` requires `>=3.12` — see design doc §7 and the root
`CLAUDE.md`'s "no shared library" note. Fix a bug in one copy, fix it in both.

## Two places this deviates from the design doc, and why

**`rss_rank` is derived, not read.** The ranking formula (design doc §4.5)
needs each article's position in its own feed and that feed's length.
`services/india-news-ingest` does not persist per-article feed position — only
a single `extra_fields` dict per ingest run, applied uniformly (see that
service's CLAUDE.md) — so `pipeline.py::_with_feed_rank` derives it instead:
group the fetched batch by `feed_source`, sort by `published_at` descending,
and use the index. For a front-page snapshot feed this is a reasonable proxy
for editorial placement, but it is not the literal RSS document order the
design doc describes.

**Canonical selection uses description length, not scraped-body word count.**
Design doc §4.6 picks a cluster's canonical article by word count in the
*scraped* body. This service never scrapes — §7's dependency list has no
HTTP/extraction library, deliberately, because clustering runs before
anything is fetched. `rank.py::pick_canonical` uses the longest RSS
description instead, the only per-article "how much is there to work with"
signal available at curation time.

## `curation_status` is a two-service contract, not a `feedmind-core` one

`services/india-news-ingest` stamps `curation_status="pending"` on every
article it stores (via `feedmind_core.runner.run_rss_ingest`'s
`extra_fields`). This service queries `processed_articles` for that value —
a single-field equality filter, no composite index needed, same trick as
`fetch_pending_telegram` — and flips it to `"clustered"` once `story_id` /
`is_canonical` are written. Because this service does not import
`feedmind-core`, both string values are hardcoded in `store.py` rather than
imported from `feedmind_core.settings`. **Keep them in sync by hand** if
either changes.

## `main.py` vs `__main__.py`

Both run the same `pipeline.run()`. They differ only in where the fetch
query's *output* goes and how they are invoked:

| | invoked by | sink |
|---|---|---|
| `main.py` | Cloud Run, on a Pub/Sub push | always Firestore — no local mode in production |
| `__main__.py` (`python -m news_curator`) | you, by hand | `SINK` env var, default `local` (JSON under `./output/stories/`) |

`fetch_pending_articles` always reads real Firestore in both — only the
*write* is diverted for local tuning. This is what design doc §11 step 2 means
by "run it against a day of real ingested data with the Firestore write
disabled": τ (`CLUSTER_DISTANCE_THRESHOLD`) and the anchor sentences in
`anchors.py` are tuned by reading `./output/stories/*.json` from a real batch,
without touching the `stories` collection or `processed_articles`.

## Commands

Run from `services/news-curator/`.

```bash
uv sync --extra dev
cp .env.example .env             # edit GOOGLE_CLOUD_PROJECT etc. to read real data
uv run python -m news_curator    # SINK=local by default — writes JSON, not Firestore
uv run pytest                    # pythonpath=src comes from pyproject.toml
uvx ruff check .                 # config is the repo-root ruff.toml
```

**Deploy:** `deploy/00-config.sh` (sourced by the rest, needs `PROJECT_ID`) →
`01-setup.sh` (APIs, Artifact Registry, SAs, IAM — checks for, but does not
create, `feedmind-news-ingested`) → `02-build-push.sh` → `03-deploy-service.sh`
→ `04-push-subscription.sh` (needs the service URL, hence last). All
idempotent. Run `../../scripts/setup-feedmind-infra.sh` first if
`feedmind-news-ingested` does not exist yet — it is owned by the publisher's
side, not this service's setup.

## Dependencies

`requirements.txt` is **generated** from `pyproject.toml`
(`../../scripts/lock-all.sh`); `uv.lock` is committed. Deliberately no torch —
`onnxruntime` + `tokenizers` do the embedding, `scikit-learn` does the
clustering. This is an independent uv project like paper-prism, not a
`feedmind-core` consumer.
