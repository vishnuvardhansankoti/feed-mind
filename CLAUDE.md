# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

This is the **system-level** file: what the components are, what they share, and
what breaks when you change one without the others. Each component has its own
`CLAUDE.md` with the detail — read the nearest one for the code you are touching:

- `packages/feedmind-core/CLAUDE.md` — the pipeline the ingest services share
- `services/paper-prism/CLAUDE.md` — the weekly arXiv digest job
- `services/summarizer/CLAUDE.md` — AI summaries and audio
- `apps/web/CLAUDE.md` — the Svelte PWA that reads all of it

## What this is

A personal content pipeline: daily tech news to Telegram, a weekly personalized
arXiv digest, AI summaries with audio for both, and one web app to read them.
Eight deployables, one GCP project (`feed-mind`), one Firestore database
(`feed-mind-db`), all inside free-tier limits.

It was three separate repos until they were merged here. Everything below used
to be a **cross-repo** contract that no review could see both sides of; the
whole point of the monorepo is that each one is now a single diff.

## Layout

```
apps/web/                    Svelte 5 + Vite PWA -> Firebase Hosting
packages/feedmind-core/      shared: feed URLs -> Firestore (not deployed alone)
services/news-ingest/        CF gen2, 08:00 — the only Telegram publisher
services/topstories-ingest/  CF gen2, 08:00 — web reader only
services/youtube-ingest/     CF gen2, 08:00 — youtube_videos
services/telegram-notifier/  CF gen2, Pub/Sub — sends the digest
services/archive/            CF gen2, 1st & 16th — Firestore -> BigQuery
services/paper-prism/        Cloud Run Job: paper-prism-job (Mondays)
services/summarizer/         CF gen2: feedmind-audio (Pub/Sub triggered)
infra/terraform/             Terraform for the GCP stack
infra/firebase/              firestore.rules, firestore.indexes.json
firebase.json                MUST stay at the root — the CLI resolves paths from it
docs/                        per-component docs + setup guides
scripts/                     test-all, lock-all, stage-service, deploy-feedmind,
                             setup-feedmind-infra, setup-wif
```

The three ingest services all sit at 08:00, which is the slot the single
combined function used — so the split changed no behaviour. They are separate
Scheduler jobs now, so any of them can be moved by editing one line in
`scripts/deploy-feedmind.sh`.

## How the components fit together

```
Scheduler ─08:00─▶ news-ingest ───────┐  also ─▶ feedmind-telegram-ready ─┐
Scheduler ─08:00─▶ topstories-ingest ─┤                                   ▼
Scheduler ─08:00─▶ youtube-ingest ────┤                          telegram-notifier
Scheduler ─Mon ──▶ paper-prism-job ───┤                                   │
                                      ▼                        queries telegram_status
                        Firestore (feed-mind-db) ◀─────────────── == "pending", sends,
                                      │  ▲                          flips to "sent"
                                      │  │
                    ┌─────────────────┘  └──── ai_summary, audio_url
                    ▼                                    │
                 apps/web                          feedmind-audio
            (reads directly,                             ▲
             no backend)          feedmind-content-ready ─┘
                                   ▲          ▲
                          news/topstories   paper-prism

archive ─1st & 16th─▶ BigQuery (everything above, before it TTLs away)
```

**Ingest and delivery are separate functions on purpose.** The old single
function wrote Firestore only *after* Telegram accepted a message, so an outage
cost the ingest too. Now the articles are stored first and the notifier is told
afterwards — see the delivery contract below.

## Contracts that span components

Nothing below is checked by a compiler, a type, or a test. Each row is a place
where changing one side silently breaks the other — the difference now is that
both sides are in the same commit.

| Contract | Written by | Read by | Change together |
|---|---|---|---|
| `processed_articles` doc shape | `packages/feedmind-core/feedmind_core/store.py::save_article` | `apps/web/src/lib/data.js::getNews`, `ArticleCard.svelte` | both files |
| `youtube_videos` doc shape | `…/store.py::save_video` | `apps/web/src/lib/data.js`, `VideoFeed.svelte` | both files |
| `telegram_status` on an article | ingest services (via `save_article`) | `services/telegram-notifier` | see below — this one is load-bearing |
| `runs` / `run_status` doc shape | `services/paper-prism/src/paper_prism/models.py` | `apps/web/src/lib/data.js::normalizeRun` | both files |
| `ai_summary`, `audio_url`, `audio_generated_at` | `services/summarizer` | `apps/web` cards | all three writers' docs are affected |
| Category codes | each ingest service's `feeds.yaml` | `apps/web/src/lib/constants.js::NEWS_CATEGORIES` | both — matched with `===` |
| Pub/Sub message shape | both producers' `events.py` | `services/summarizer/main.py` | producer + consumer |
| Firestore database id | `FIRESTORE_DATABASE` (job + function env) | `VITE_FIRESTORE_DATABASE` (web, build-time) | **three** places, plus `firebase.json` |

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
| `pending` | stored, awaiting delivery | an ingest with `deliver_telegram: true` |
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

The cost is one extra Firestore write per article. `exactly_one_service_delivers_to_telegram`
in the core package's tests pins the "one ringer" assumption; more than one
publisher is not broken, but it means two digests a day, which should be a
decision rather than a discovery.

## The Pub/Sub topic is owned by its consumer

`feedmind-content-ready` is created by `services/summarizer/deploy/setup.sh`,
which also grants `roles/pubsub.publisher` to **both** producers' service
accounts. Neither producer's deploy manages that binding. Run the summarizer's
setup before either producer first publishes; until then their runs still
succeed and log a permission error, because publishing is best-effort by design
on both sides.

`feedmind-telegram-ready` is the exception, and deliberately so: it is created
by `scripts/setup-feedmind-infra.sh`, on the **publisher's** side. Producer and
consumer are both FeedMind services here, so there is no boundary to respect —
and news-ingest is very likely deployed before the notifier exists, so waiting
for the consumer to create it would mean the first digest goes nowhere.

## Retention: everything is on a clock

| Data | Lifetime | Mechanism |
|---|---|---|
| `runs`, `run_status` | 45 days | Firestore TTL on `expire_at` |
| `processed_articles`, `youtube_videos` | 90 days | Firestore TTL on `expires_at` |
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

./scripts/setup-feedmind-infra.sh  # once per project: APIs, SAs, IAM, the topic
./scripts/deploy-feedmind.sh       # all five FeedMind functions + their Scheduler jobs
./scripts/deploy-feedmind.sh news-ingest    # or just one
```

Per-component commands are in each component's own `CLAUDE.md`. Deploys are
per-component too — there is no repo-wide deploy, and that is deliberate: the
four deployables have independent schedules, runtimes and blast radii.

## Python dependencies

Every service has its own `pyproject.toml` and committed `uv.lock`. They are
**not** uv workspace members: `packages/feedmind-core` pins
`google-cloud-firestore==2.19.0` while `services/summarizer` needs `==2.28.1`,
and they deploy as separate artifacts that never share an interpreter, so one
shared resolution would force a version bump on somebody for no benefit.

The five FeedMind services share `feedmind-core` as an **editable path
dependency**, so an edit to the package is picked up by `uv run` in any service
with no reinstall. Each pulls only the extras it uses (`feeds`, `sumy`,
`gemini`, `telegram`, `events`, `archive`) — youtube-ingest ships 44 packages
where news-ingest ships 64. That only works because `models.py` is
standard-library-only and `runner.py`'s heavy imports are lazy; see
`packages/feedmind-core/CLAUDE.md`.

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
