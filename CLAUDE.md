# CLAUDE.md

Guidance for Claude Code (claude.ai/code) working in this repository.

This is the **system-level** file: what the components are, what they share, and
what breaks when you change one without the others. Each component has its own
`CLAUDE.md` with the detail — read the nearest one for the code you are touching:

- `services/feed-mind/CLAUDE.md` — RSS → Telegram, and the BigQuery archive
- `services/paper-prism/CLAUDE.md` — the weekly arXiv digest job
- `services/summarizer/CLAUDE.md` — AI summaries and audio
- `apps/web/CLAUDE.md` — the Svelte PWA that reads all of it

## What this is

A personal content pipeline: daily tech news to Telegram, a weekly personalized
arXiv digest, AI summaries with audio for both, and one web app to read them.
Four deployables, one GCP project (`feed-mind`), one Firestore database
(`feed-mind-db`), all inside free-tier limits.

It was three separate repos until they were merged here. Everything below used
to be a **cross-repo** contract that no review could see both sides of; the
whole point of the monorepo is that each one is now a single diff.

## Layout

```
apps/web/              Svelte 5 + Vite PWA -> Firebase Hosting
services/feed-mind/    CF gen2: feedmind (daily), feedmind-archive (1st & 16th)
services/paper-prism/  Cloud Run Job: paper-prism-job (Mondays)
services/summarizer/   CF gen2: feedmind-audio (Pub/Sub triggered)
infra/terraform/       Terraform for the GCP stack
infra/firebase/        firestore.rules, firestore.indexes.json
firebase.json          MUST stay at the root — the CLI resolves paths from it
docs/                  per-component docs + setup guides
scripts/               test-all.sh, lock-all.sh, setup-wif.sh
```

## How the four components fit together

```
Cloud Scheduler ──daily──▶ feedmind ──────┐
                                          ├──▶ Firestore (feed-mind-db) ──▶ apps/web
Cloud Scheduler ──weekly─▶ paper-prism-job┘         ▲                        (reads
                                                    │                     directly,
        both publish {"process_doc": ...} to        │                    no backend)
        the feedmind-content-ready topic            │
                    │                               │
                    ▼                               │
              feedmind-audio ──── ai_summary, audio_url
                    │
                    └──▶ Cloud Storage (public bucket) ── MP3s

feedmind-archive ──1st & 16th──▶ BigQuery (everything above, before it TTLs away)
```

## Contracts that span components

Nothing below is checked by a compiler, a type, or a test. Each row is a place
where changing one side silently breaks the other — the difference now is that
both sides are in the same commit.

| Contract | Written by | Read by | Change together |
|---|---|---|---|
| `processed_articles` doc shape | `services/feed-mind/feedmind/deduplication.py::mark_as_delivered` | `apps/web/src/lib/data.js::getNews`, `ArticleCard.svelte` | both files |
| `youtube_videos` doc shape | `…/deduplication.py::save_video` | `apps/web/src/lib/data.js`, `VideoFeed.svelte` | both files |
| `runs` / `run_status` doc shape | `services/paper-prism/src/paper_prism/models.py` | `apps/web/src/lib/data.js::normalizeRun` | both files |
| `ai_summary`, `audio_url`, `audio_generated_at` | `services/summarizer` | `apps/web` cards | all three writers' docs are affected |
| Category codes | `services/feed-mind/feedmind/config.py::RSS_FEEDS` | `apps/web/src/lib/constants.js::NEWS_CATEGORIES` | both — matched with `===` |
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

## The Pub/Sub topic is owned by its consumer

`feedmind-content-ready` is created by `services/summarizer/deploy/setup.sh`,
which also grants `roles/pubsub.publisher` to **both** producers' service
accounts. Neither producer's deploy manages that binding. Run the summarizer's
setup before either producer first publishes; until then their runs still
succeed and log a permission error, because publishing is best-effort by design
on both sides.

## Retention: everything is on a clock

| Data | Lifetime | Mechanism |
|---|---|---|
| `runs`, `run_status` | 45 days | Firestore TTL on `expire_at` |
| `processed_articles`, `youtube_videos` | 90 days | Firestore TTL on `expires_at` |
| BigQuery archive | forever | `feedmind-archive`, 1st & 16th |

This is why `services/feed-mind`'s `snippet` field is written but never read
back by any pipeline, and why the archive does a **full scan with no
watermark**: paying ~10k reads against a 50k/day free tier is what makes the
archive self-healing, so a missed run needs no recovery. See
`docs/feed-mind/bigquery-archival-plan.md`.

## Commands

```bash
./scripts/test-all.sh     # every suite: feed-mind + paper-prism pytest, web vitest
./scripts/lock-all.sh     # re-resolve all three Python services, regenerate requirements.txt
uvx ruff check .          # repo-wide, config in ruff.toml
```

Per-component commands are in each component's own `CLAUDE.md`. Deploys are
per-component too — there is no repo-wide deploy, and that is deliberate: the
four deployables have independent schedules, runtimes and blast radii.

## Python dependencies: three projects, not a workspace

Each service has its own `pyproject.toml` and its own committed `uv.lock`. They
are **not** uv workspace members. They pin conflicting versions of the same
libraries on purpose — `services/feed-mind` holds
`google-cloud-firestore==2.19.0` while `services/summarizer` needs `==2.28.1` —
and they deploy as separate artifacts that never share an interpreter, so one
shared resolution would force a version bump on somebody for no benefit.

`requirements.txt` is a **generated** file in all three. Edit `pyproject.toml`
and run `scripts/lock-all.sh`; Cloud Functions and the paper-prism Dockerfile
install from the generated file.

## Known duplication, deliberately not fixed here

- **Two deploy paths for paper-prism.** `infra/terraform/` and
  `services/paper-prism/deploy/*.sh` provision the *same* resources. Pick one as
  source of truth — running both double-creates. This predates the monorepo.
- **Two CI auth mechanisms.** `deploy-feed-mind.yml` uses Workload Identity
  Federation; the other three use a service-account key. See
  `.github/workflows/README.md`.
- **No shared library.** The services each set up their own Firestore client and
  their own Telegram/notification helpers. Extracting a `libs/` package is the
  obvious next step and was kept out of the merge so that the move commits stay
  readable under `git log --follow`.
