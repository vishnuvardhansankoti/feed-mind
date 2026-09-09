# feed-mind

A personal content pipeline on GCP: daily tech news to Telegram, a weekly
personalized arXiv digest, AI summaries with audio for both, and one web app to
read all of it. Six deployables, one GCP project, one Firestore database, $0/mo.

**Live:** https://feed-mind.web.app

## Components

| Path | What it is | Deployed as | Runs |
|---|---|---|---|
| [`apps/web`](apps/web) | Svelte 5 + Vite PWA. Reads Firestore straight from the browser — no backend, no request-path compute. | Firebase Hosting | on demand |
| [`packages/feedmind-core`](packages/feedmind-core) | The shared pipeline: feed URLs in, Firestore documents out. Not deployed on its own — copied into each function at deploy time. | — | — |
| [`services/ingest`](services/ingest) | Three feed groups → dedupe → summarize → Firestore: news (marked pending for Telegram), top stories (web reader only) and YouTube uploads. Publishes the doorbell once when all three are stored. | CF gen2 `feedmind-ingest` | daily 08:00 |
| [`services/telegram-notifier`](services/telegram-notifier) | Reads everything marked pending, formats the digest by category, sends it. | CF gen2 `feedmind-telegram-notifier` | Pub/Sub, when an ingest finishes |
| [`services/archive`](services/archive) | Copies every collection into BigQuery before its TTL fires. | CF gen2 `feedmind-archive` | 1st & 16th |
| [`services/paper-prism`](services/paper-prism) | arXiv → local ONNX embeddings → cosine top-k against a personal interest profile → Gemini summary. | Cloud Run Job `paper-prism-job` | Mondays 09:00 |
| [`services/summarizer`](services/summarizer) | Scrapes each item, writes a longer LLM summary and a spoken MP3 back onto the document. | CF gen2 `feedmind-audio` | Pub/Sub, when a producer finishes |

A feed group is a YAML file in `services/ingest/` — its URLs plus what to do
with them. Adding one is a file plus a line in `main.py`'s `GROUPS`; adding a
whole ingest service on its own schedule is a directory, because the pipeline
itself lives in `feedmind-core`.

Supporting directories: [`infra/terraform`](infra/terraform) (the GCP stack),
`infra/firebase` (Firestore rules + indexes), [`docs/`](docs), `scripts/`.

## Quick start

```bash
./scripts/test-all.sh     # every suite (needs `npm ci` in apps/web the first time)
./scripts/lock-all.sh     # re-resolve every Python project
uvx ruff check .          # repo-wide lint
```

Per-component setup lives in each component's own README:
[web](apps/web/README.md) ·
[feedmind-core](packages/feedmind-core/README.md) ·
[paper-prism](services/paper-prism/README.md) ·
[summarizer](services/summarizer/README.md).
The FeedMind subsystem as a whole is documented in
[docs/feed-mind/README.md](docs/feed-mind/README.md).

Local development against GCP needs Application Default Credentials:

```bash
gcloud auth application-default login
```

## Deploying

There is no repo-wide deploy — the four deployables have independent schedules,
runtimes and blast radii. Each has a manual GitHub Actions workflow:

| Workflow | Deploys |
|---|---|
| `deploy-feedmind.yml` | any or all three FeedMind functions, plus their Scheduler jobs |
| `deploy-paper-prism.yml` | `paper-prism-job` |
| `deploy-summarizer.yml` | `feedmind-audio` |
| `deploy-web.yml` | the web app |

All are `workflow_dispatch` only. Required secrets and variables are documented
in [`.github/workflows/README.md`](.github/workflows/README.md).

Project-level setup — APIs, service accounts, IAM and the
`feedmind-telegram-ready` topic — is not in CI. Run it once, locally:

```bash
./scripts/setup-feedmind-infra.sh
./scripts/deploy-feedmind.sh                 # or: ./scripts/deploy-feedmind.sh ingest
```

## Architecture

The components are joined only by the Firestore document schema and one Pub/Sub
topic — contracts that no compiler or test enforces. They are enumerated, with
what-to-change-together guidance, in [`CLAUDE.md`](CLAUDE.md).

This repository was formed by merging three separate repos (`feed-mind`,
`paper-prism`, `feed-mind-summarizer`); all of their history is preserved here.
