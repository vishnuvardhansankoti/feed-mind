# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

This is the **system-level** file: what the components are, what they share, and
what breaks when you change one without the others. Each component has its own
`CLAUDE.md` with the detail — read the nearest one for the code you are touching:

- `packages/feedmind-core/CLAUDE.md` — the pipeline the ingest services share
- `docs/feed-mind/archived-gcp-resources.md` — legacy GCP resources still to delete
- `services/india-news-ingest/CLAUDE.md` — five Indian publications' front pages
- `services/us-news-ingest/CLAUDE.md` — five US publications' front pages
- `services/news-curator/CLAUDE.md` — embed/classify/cluster/rank into `stories`, for both countries
- `services/paper-prism/CLAUDE.md` — the weekly arXiv digest job
- `services/summarizer/CLAUDE.md` — AI summaries and audio
- `apps/web/CLAUDE.md` — the Svelte PWA that reads all of it

## What this is

A personal content pipeline: daily tech news to Telegram, a weekly personalized
arXiv digest, a daily curated news digest for India and the US, AI summaries
with audio, and one web app to read all of it. Nine deployables, one GCP
project (`feed-mind`), one Firestore database (`feed-mind-db`), all inside
free-tier limits.

It was three separate repos until they were merged here. Everything below used
to be a **cross-repo** contract that no review could see both sides of; the
whole point of the monorepo is that each one is now a single diff.

## Layout

```
apps/web/                    Svelte 5 + Vite PWA -> Firebase Hosting
packages/feedmind-core/      shared: feed URLs -> Firestore (not deployed alone)
services/ingest/             CF gen2, 08:00 — news + YouTube + Knowledge Bytes
services/telegram-notifier/  CF gen2, Pub/Sub — sends the digest
services/archive/            CF gen2, 1st & 16th — Firestore -> BigQuery
services/india-news-ingest/  CF gen2, 17:30 CT — five Indian publications
services/us-news-ingest/     CF gen2, 04:00 CT — five US publications
services/news-curator/       Cloud Run service, Pub/Sub push — dedup + rank, both countries
services/paper-prism/        Cloud Run Job: paper-prism-job (Mondays)
services/summarizer/         Cloud Run: feedmind-audio (Pub/Sub push)
infra/terraform/             Terraform for the GCP stack
infra/firebase/              firestore.rules, firestore.indexes.json
firebase.json                MUST stay at the root — the CLI resolves paths from it
docs/                        per-component docs + setup guides
scripts/                     test-all, lock-all, stage-service, deploy-feedmind,
                             setup-feedmind-infra, setup-wif
```

`services/ingest` runs three feed groups on one 08:00 schedule. The groups are
separate YAML files rather than one list because they behave differently: only
`news` goes to Telegram, `news` and `knowledge_bytes` are both summarized and
wake the AI-summary service, `youtube` is neither. `knowledge_bytes.yaml`
fetches the tutorial-series RSS feeds published by the sibling `florilex` repo
(`https://florilex.web.app/<series>/rss.xml`) — each item's `<description>` is
already the lesson's own hand-written summary, so `summarize: none` here means
"skip Sumy/Gemini, use the feed's own text as `summary` directly," not "no
summary" — see `packages/feedmind-core/feedmind_core/runner.py::_summarize`.
Its articles carry no `curation_status`, so they flow through
`services/summarizer`'s default `RSS_FEED` pipeline exactly like `news.yaml`'s
articles, with no summarizer-side changes. It used to carry a different third
group, `topstories.yaml` (one Times of India feed, unranked); that moved to
`services/india-news-ingest` + `services/news-curator`, see
`docs/feed-mind/news-curator-design.md`. Articles already stored with
`feed_category=top_stories` keep their 90-day TTL and their web app tab — this
was a live retirement, not a cutover, so old and new content coexist until the
old rows expire.

## How the components fit together

```
                    ┌── news.yaml            -> telegram_status=pending
                    ├── youtube.yaml         -> youtube_videos
Scheduler ─08:00─▶ ingest
                    └── knowledge_bytes.yaml -> processed_articles (aiml/dsa/
                                                 system_design, from the
                                                 florilex repo's RSS)
                          │
                          │ once, after every group
                          ├──▶ feedmind-telegram-ready ──▶ telegram-notifier
                          │                                      │
                          ▼                          queries telegram_status
            Firestore (feed-mind-db) ◀──────────────── == "pending", sends,
                    │   ▲   ▲                             flips to "sent"
                    │   │   └──── paper-prism-job (Mondays)
                    │   └──────── ai_summary, audio_url
                    ▼                     ▲
                 apps/web            feedmind-audio
            (reads directly,              ▲
             no backend)   feedmind-content-ready ─┘

archive ─1st & 16th─▶ BigQuery (everything above, before it TTLs away)
```

**Ingest and delivery are separate functions on purpose.** The old single
function wrote Firestore only *after* Telegram accepted a message, so an outage
cost the ingest too. Now the articles are stored first and the notifier is told
afterwards — see the delivery contract below.

### The news pipeline: India and US, one curator

```
                     ┌── general.yaml    TOI + The Hindu
Scheduler ─17:30 CT──▶ india-news-ingest
                     └── business.yaml   BS + ET + Hindu BusinessLine
                               │  curation_status=pending, country=IN
                               │
                     ┌── general.yaml    NPR News + CBS News
Scheduler ─04:00 CT──▶ us-news-ingest
                     └── business.yaml   CNBC + MarketWatch + Fortune
                               │  curation_status=pending, country=US
                               ▼
                     feedmind-news-ingested       (one shared doorbell, no payload)
                               │
                               ▼
                         news-curator             embed → classify → cluster → rank,
                               │                  clustering scoped to (country, category)
                               │                  writes `stories`; marks top-5/(country,
                               │                  category) is_canonical, flips
                               ▼                  curation_status to "clustered"
                     feedmind-content-ready       (third producer, NEWS_STORIES)
                               │
                               ▼
                     feedmind-audio (existing)    scrape → LLM → TTS → both docs
                               │
                               ▼
                     ai_summary / audio_url  →  apps/web `#/stories` (India | US toggle)

archive ─1st & 16th─▶ BigQuery `stories`/`articles` tables (country column, nullable on articles)
```

Both ingest services publish to the same topic and are handled by the same
`news-curator` deployment — a `country` field (not a second service, second
collection, or second topic) is what keeps the two countries' clustering,
ranking and `story_id`s apart. See `docs/feed-mind/us-news-design.md` for the
full rationale, including why Google News RSS was evaluated and rejected as
the US source.

All six steps of the original (India-only) design doc's build order (§11) are
built; the US pipeline is a second iteration on top of that. See
`docs/feed-mind/news-curator-design.md` for the original design,
`docs/feed-mind/us-news-design.md` for what changed to add a second country,
`services/news-curator/CLAUDE.md` for the country-isolation mechanics and the
two places the implementation deviates from the original doc (canonical
selection has no scraped body to rank by; `rss_rank` is derived from
`published_at` order, not the literal feed position), and
`apps/web/CLAUDE.md`'s Stories section for what the reader does and does not
do yet (no bookmarking, no follow/unfollow — those are natural follow-ups,
not omissions to fix reflexively; a Latest/Archive split now exists, same
one-query-backs-both-views shape as News and Videos).

## Contracts that span components

Nothing below is checked by a compiler, a type, or a test. Each row is a place
where changing one side silently breaks the other — the difference now is that
both sides are in the same commit.

| Contract | Written by | Read by | Change together |
|---|---|---|---|
| `processed_articles` doc shape | `packages/feedmind-core/feedmind_core/store.py::save_article` | `apps/web/src/lib/data.js::getNews`, `ArticleCard.svelte` | both files |
| `youtube_videos` doc shape | `…/store.py::save_video` | `apps/web/src/lib/data.js`, `VideoFeed.svelte` | both files |
| `telegram_status` on an article | `services/ingest` (via `save_article`) | `services/telegram-notifier` | see below — this one is load-bearing |
| `runs` / `run_status` doc shape | `services/paper-prism/src/paper_prism/models.py` | `apps/web/src/lib/data.js::normalizeRun` | both files |
| `ai_summary`, `audio_url`, `audio_generated_at` | `services/summarizer` | `apps/web` cards | all three writers' docs are affected |
| Category codes | `services/ingest/*.yaml` | `apps/web/src/lib/constants.js::NEWS_CATEGORIES` (news.yaml) / `::KNOWLEDGE_CATEGORIES` (knowledge_bytes.yaml) | both — matched with `===`, and the two web constants must never share a code since both query the same `processed_articles` collection |
| Pub/Sub message shape | both producers' `events.py` | `services/summarizer/main.py` | producer + consumer |
| Firestore database id | `FIRESTORE_DATABASE` (job + function env) | `VITE_FIRESTORE_DATABASE` (web, build-time) | **three** places, plus `firebase.json` |
| `curation_status` on an article | `services/india-news-ingest`, `services/us-news-ingest` (via `save_article`'s `extra` param) | `services/news-curator` | see `services/news-curator/CLAUDE.md` — `news-curator` re-declares the two string values by hand, since it does not depend on `feedmind-core` |
| `feed_source` names in both countries' `business.yaml` | those files' `name:` fields | `services/news-curator/src/news_curator/anchors.py::BUSINESS_ELIGIBLE_SOURCES` | all three — matched exactly, not with `===`, but just as byte-for-byte |
| `country` on an article / story | `services/india-news-ingest`, `services/us-news-ingest` (via `extra`); `services/news-curator` on `stories` | `services/news-curator`, `apps/web/src/lib/data.js::getStories`, `packages/feedmind-core/feedmind_core/archival.py` | see `services/news-curator/CLAUDE.md`'s country-isolation section — a missing value on an *article* means "IN" (India predates this field); a missing value in the *archive* is left NULL, never guessed, because most `processed_articles` rows have no country concept at all |
| `stories` doc shape | `services/news-curator/src/news_curator/models.py::Story` | `services/summarizer/feedmind_audio.py` (writes `ai_summary`/`audio_url` back onto it), `apps/web/src/lib/data.js::normalizeStory`, `packages/feedmind-core/feedmind_core/archival.py::story_row` | all four files |
| `is_canonical` / `story_id` / `audio_eligible` on an article | `services/news-curator` (via a direct Firestore `.update()`, not `save_article`) | `services/summarizer/feedmind_audio.py::collect_news_stories` | both — the field names are the whole selection query; `is_canonical` gates summarization, `audio_eligible` separately gates audio under `FEEDMIND_TTS=cloud` only |
| Story category codes | `services/news-curator/src/news_curator/anchors.py::COARSE_ANCHORS` | `apps/web/src/lib/constants.js::STORY_CATEGORIES` | both — matched with `===`, independent of `NEWS_CATEGORIES` |

Two of these deserve spelling out because the failure is silent:

**Category codes are not internally consistent.** `open-source` hyphenates,
`top_stories` underscores. `apps/web` matches them with `===`, so "tidying" a
separator on either side empties a tab with no error anywhere.
`constants.test.js` pins both spellings.

**The database id must match in four places.** The browser reads Firestore
directly, so a mismatch does not error — it silently reads an empty `(default)`
database. `firebase.json` pins `"database": "feed-mind-db"` for the same reason:
without it, `firebase deploy` writes rules to `(default)` *and creates* it.

## The Telegram delivery contract

The one contract worth reading in full, because it replaced an invariant that
used to be enforced by ordering.

**Before:** a document was written to Firestore only after Telegram accepted the
message, so "the document exists" meant "it was delivered", and a failure meant
no document and a retry next run.

**Now:** ingest writes the document, then rings a doorbell; the notifier is a
different function and reads Firestore, so the document must exist first. State
is explicit:

| `telegram_status` | Meaning | Set by |
|---|---|---|
| `pending` | stored, awaiting delivery | a feed group with `deliver_telegram: true` |
| `sent` | Telegram accepted it | the notifier, after all chunks succeed |
| `skipped` | this feed never goes to Telegram | everything else — **the default** |

Three rules keep this safe, and all three are easy to break:

1. **The Pub/Sub message is a doorbell, not a payload.** It carries no articles.
   The notifier queries `telegram_status == "pending"` and acts on that, so a
   dropped message costs a delay. Put the articles in the message and losing it
   loses them.
2. **`save_article` defaults to `skipped`.** A service that forgets to ask for
   delivery produces articles the notifier ignores, rather than an unannounced
   Telegram flood. Do not flip this default.
3. **The notifier marks a category sent all-or-nothing.** A partial send leaves
   the whole category pending and the next run re-sends it. That risks a
   duplicate entry, never a silent hole — a repeated entry is a nuisance, a
   dropped one is invisible.

The cost is one extra Firestore write per article.

A fourth rule lives in the deploy script rather than the code:
**`feedmind-telegram-notifier` is deployed with `--max-instances=1` and a 600s
ack deadline.** Eventarc's default 60s deadline is shorter than a digest run
with a backlog (`telegram.py` sleeps 1s after every message), so Pub/Sub would
redeliver mid-run; a second instance would find the batch still `pending` and
send the whole digest again. Capping instances makes a redelivery queue behind
the running run instead of racing it. Removing either guard reintroduces a
concurrent duplicate digest.

## The Pub/Sub topic is owned by its consumer

`feedmind-content-ready` was created by `services/summarizer/deploy/01-
setup.sh` (originally `setup.sh`, from the gen2-Cloud-Function era — see that
service's CLAUDE.md), which also grants `roles/pubsub.publisher` to all three
producers' service accounts (`feedmind-sa`, `paper-prism-job`, `news-
curator`). No producer's deploy manages that binding. Run the summarizer's
setup before a producer first publishes; until then its runs still succeed
and log a permission error, because publishing is best-effort by design on
every side.

## A push subscription needs one more grant than it looks like

Every Cloud Run service in this repo that receives Pub/Sub via a **push**
subscription (`services/news-curator`, `services/summarizer`) needs its push
service account granted `roles/iam.serviceAccountTokenCreator` **by Pub/Sub's
own service agent** — without it, Pub/Sub cannot mint the OIDC token a push
request is authenticated with, and every delivery 403s with "The request was
not authenticated." This is not automatic: `gcloud pubsub subscriptions
create --push-auth-service-account=...` does not reliably set it up on its
own. Both services' `01-setup.sh` grant it explicitly now — but this was
missing for months on `news-curator`'s subscription, which failed on 100% of
real deliveries the whole time, invisibly: `gcloud run services logs read`
only shows what the *application* printed, never a request that never reached
it. The tell is in Cloud Run's raw HTTP request logs
(`httpRequest.status=403`), not the service's own log stream. If a new
Cloud Run service ever needs a push subscription, grant this up front rather
than discovering it the same way.

`feedmind-telegram-ready` is the exception, and deliberately so: it is created
by `scripts/setup-feedmind-infra.sh`, on the **publisher's** side. Producer and
consumer are both FeedMind services here, so there is no boundary to respect —
and `services/ingest` is very likely deployed before the notifier exists, so
waiting for the consumer to create it would mean the first digest goes nowhere.

`feedmind-news-ingested` follows the same exception, for the same reason:
`scripts/setup-feedmind-infra.sh` creates it, `services/india-news-ingest`
**and** `services/us-news-ingest` both publish to it, and `services/news-
curator` subscribes via Pub/Sub push (not Eventarc — see that service's
CLAUDE.md §3.3 reasoning). One shared topic for both countries — see
`docs/feed-mind/us-news-design.md` §3.4 for why a second one was not added.

## Retention: everything is on a clock

| Data | Lifetime | Mechanism |
|---|---|---|
| `runs`, `run_status` | 45 days | Firestore TTL on `expire_at` |
| `processed_articles`, `youtube_videos`, `stories` | 90 days | Firestore TTL on `expires_at` |
| BigQuery archive | forever | `feedmind-archive`, 1st & 16th |

This is why `packages/feedmind-core`'s `snippet` field is written but never read
back by any pipeline, and why the archive does a **full scan with no
watermark**: paying ~10k reads against a 50k/day free tier is what makes the
archive self-healing, so a missed run needs no recovery. See
`docs/feed-mind/bigquery-archival-plan.md`.

## Commands

```bash
./scripts/test-all.sh              # every suite, plus a per-service import smoke test
./scripts/lock-all.sh              # re-resolve every Python project, regenerate requirements.txt
uvx ruff check .                   # repo-wide, config in ruff.toml

./scripts/setup-feedmind-infra.sh  # once per project: APIs, SAs, IAM, both topics
./scripts/deploy-feedmind.sh       # all five FeedMind functions + their Scheduler jobs
./scripts/deploy-feedmind.sh ingest         # or just one
```

`services/news-curator` is not in `deploy-feedmind.sh` — it is a Cloud Run
service with its own numbered `deploy/*.sh` scripts, following the
`services/paper-prism` pattern rather than the Cloud Functions one. See
`services/news-curator/CLAUDE.md`.

Per-component commands are in each component's own `CLAUDE.md`. Deploys are
per-component too — there is no repo-wide deploy, and that is deliberate: the
deployables have independent schedules, runtimes and blast radii.

## Python dependencies

Every service has its own `pyproject.toml` and committed `uv.lock`. They are
**not** uv workspace members: `packages/feedmind-core` pins
`google-cloud-firestore==2.19.0` while `services/summarizer` needs `==2.28.1`,
and they deploy as separate artifacts that never share an interpreter, so one
shared resolution would force a version bump on somebody for no benefit.

The five FeedMind services share `feedmind-core` as an **editable path
dependency**, so an edit to the package is picked up by `uv run` in any service
with no reinstall. Each pulls only the extras it uses (`feeds`, `sumy`,
`gemini`, `telegram`, `events`, `archive`) — the notifier ships 47 packages
where the ingest ships 64, and `india-news-ingest` / `us-news-ingest` ship
fewer still (`[feeds, events]` — no `sumy`/`gemini`, since neither summarizes
anything at ingest time). That only works because `models.py` is
standard-library-only and `runner.py`'s heavy imports are lazy; see
`packages/feedmind-core/CLAUDE.md`.

`services/news-curator` is **not** one of the four: like `services/paper-prism`,
it is a standalone `uv` project with no `feedmind-core` dependency at all — see
its own CLAUDE.md for why (no torch, a different Firestore pin, a copied
`embedder.py`).

**Cloud Functions uploads only `--source`**, so the path dependency cannot
reach a deployed function through pip. `scripts/stage-service.sh` copies
`feedmind_core` into a `.build/` directory beside `main.py` instead, and
`scripts/lock-all.sh` exports each `requirements.txt` with
`--no-emit-package feedmind-core` so pip never tries to resolve a local path
that will not exist in the build.

`requirements.txt` is a **generated** file everywhere. Edit `pyproject.toml` and
run `scripts/lock-all.sh`.

## Reaching pre-merge history

All 59 commits from the three original repos are here, imported with
`git subtree`. But **`git log --follow` does not traverse the import**: a
subtree merge re-parents content under a prefix rather than recording a rename,
so a path-limited log of `apps/web/...` stops at the relocate commit.

`git blame` *does* traverse it correctly — it reaches the original commit at the
original path — so line-level archaeology works normally. For a file's full
commit list, go through the import merge's second parent:

```bash
PP=$(git log --grep="Add '_import/paper-prism/'" --format=%H)
git log --oneline $PP^2 -- web/src/lib/data.js        # pre-merge path
```

The same works for the summarizer with `Add '_import/summarizer/'`.

## Known duplication, deliberately not fixed here

- **Two deploy paths for paper-prism.** `infra/terraform/` and
  `services/paper-prism/deploy/*.sh` provision the *same* resources. Pick one as
  source of truth — running both double-creates. This predates the monorepo.
- **Two CI auth mechanisms.** `deploy-feedmind.yml` uses Workload Identity
  Federation; the other three use a service-account key. See
  `.github/workflows/README.md`.
- **No shared library.** The services each set up their own Firestore client and
  their own Telegram/notification helpers. Extracting a `libs/` package is the
  obvious next step and was kept out of the merge so that the move commits stay
  readable under `git log --follow`.
