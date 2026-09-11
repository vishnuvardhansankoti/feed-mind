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
ranks the articles `services/india-news-ingest` **and** `services/us-news-
ingest` write, then writes the `stories` collection and stamps `story_id` /
`is_canonical` back onto `processed_articles`. One shared deployment, one
shared collection, one shared taxonomy — see "Country isolation" below for how
the two countries stay apart within that.

All six steps of the original design doc's build order (§11) are built: this
service (steps 1-2), announcing finished runs to `services/summarizer` via
`events.py` (step 3), the `apps/web` Stories view (step 4), the
`services/archive` table (step 5), and `services/ingest`'s `topstories.yaml`
retirement (step 6, done ahead of the others at the user's request). The US
pipeline (`services/us-news-ingest` + country-scoping in this service) is a
second iteration on top of that — see `docs/feed-mind/us-news-design.md`. See
the two "deviates from the design doc" sections below for where the
implementation and the original (India-only) doc disagree.

## Country isolation

Classification is country-agnostic — the coarse/business anchors are shared,
so a US and an India article are classified against the exact same anchor
text. **Clustering is not**: `pipeline.py::run` scopes every cluster to
`(country, coarse_category)`, never `coarse_category` alone, so a US
"business" story and an India "business" story on the same day are never
merged just because both landed in the same coarse bucket. `story_id` carries
the country as a prefix (`us_business_2026-09-10_01` vs
`in_business_2026-09-10_01`) — without it, the two countries' doc IDs would
collide on the same category/date/rank.

`N_PAPERS_BY_COUNTRY` (`anchors.py`) replaces the single `N_PAPERS` constant
the original design used — the ranking formula's consensus term must be judged
against *that cluster's own* country's outlet count, never a shared or the
wrong country's. `models.py::run_date_for` is similarly per-country: India
uses a fixed UTC+5:30 offset (no DST), the US uses real `zoneinfo` for
`America/Chicago` (DST matters there — a fixed offset would be an hour wrong
half the year).

`country` on `processed_articles` is written by each ingest service's
`extra_fields` (`country="IN"` / `country="US"`), the same mechanism that
already carries `curation_status`. A document with no `country` field at all
predates the US pipeline entirely — `store.py::fetch_pending_articles` treats
that absence as `"IN"`, since India was the only country before this (see
`models.py::DEFAULT_COUNTRY`). `stories` documents have no such legacy case —
every one carries `country` explicitly, always.

## Pipeline order is the whole point

Embed → classify (coarse) → cluster (within a country's coarse category, across all of that country's papers) →
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

Both also call `events.publish_content_ready` after `pipeline.run()` — a
no-op for `__main__.py` unless you explicitly set `SINK=firestore`
(`Config.content_ready_enabled` gates on it), since a local tuning run has
nothing downstream to announce.

## Announcing to `services/summarizer`, not publishing content itself

`events.py` copies `services/paper-prism/src/paper_prism/events.py`'s pattern
rather than importing it (same reasoning as `embedder.py`: no shared
dependency). It publishes `{"process_doc": "NEWS_STORIES", ...}` to
`feedmind-content-ready` once per run, only when at least one cluster was
marked canonical — never per-story, so a run with 25 canonical stories wakes
`feedmind-audio` once, not 25 times.

**The topic is owned by `services/summarizer`, not here.** Its
`deploy/setup.sh` creates `feedmind-content-ready` and grants this service's
runtime SA (`news-curator@…`) `roles/pubsub.publisher` — see
`services/summarizer/deploy/config.sh`'s `PUBLISHER_SERVICE_ACCOUNTS`. Run
that setup before this service's first deploy; until then a run still
succeeds and `events.py` just logs a permission error, same as every other
producer in this repo.

`services/summarizer` finds the work via `is_canonical == true` on
`processed_articles` (a single-field filter, same trick as `curation_status`
above), not by reading the Pub/Sub message body — the message is a doorbell
that says "look now", exactly like `feedmind-news-ingested` and
`feedmind-telegram-ready`. It writes `ai_summary` / `audio_url` onto **both**
the article and its `stories` doc; see `services/summarizer/CLAUDE.md`.

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

**This subscription silently failed on 100% of real deliveries for months, up
until it was diagnosed and fixed alongside `services/summarizer`'s Cloud Run
migration.** `01-setup.sh` now grants Pub/Sub's service agent
`roles/iam.serviceAccountTokenCreator` on `news-curator-invoker` explicitly —
`gcloud pubsub subscriptions create --push-auth-service-account=...` does not
reliably set this up on its own, and without it every push 403s with "The
request was not authenticated," invisible in `gcloud run services logs read`
(which only shows what the application printed, never a request that never
reached it — the tell was in Cloud Run's raw `httpRequest.status=403` request
logs). See the root `CLAUDE.md`'s "A push subscription needs one more grant
than it looks like" and `services/summarizer/CLAUDE.md`'s "Cloud Run
migration" section for the full story. If curation output looks stale, check
this grant exists before assuming the pipeline itself is broken:

```bash
gcloud iam service-accounts get-iam-policy news-curator-invoker@<project>.iam.gserviceaccount.com
```

## Dependencies

`requirements.txt` is **generated** from `pyproject.toml`
(`../../scripts/lock-all.sh`); `uv.lock` is committed. Deliberately no torch —
`onnxruntime` + `tokenizers` do the embedding, `scikit-learn` does the
clustering. This is an independent uv project like paper-prism, not a
`feedmind-core` consumer.
