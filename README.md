# feed-mind

A personal content pipeline on GCP: daily tech news to Telegram, a weekly
personalized arXiv digest, AI summaries with audio for both, and one web app to
read all of it. Four deployables, one GCP project, one Firestore database, $0/mo.

**Live:** https://feed-mind.web.app

## Components

| Path | What it is | Deployed as | Runs |
|---|---|---|---|
| [`apps/web`](apps/web) | Svelte 5 + Vite PWA. Reads Firestore straight from the browser — no backend, no request-path compute. | Firebase Hosting | on demand |
| [`services/feed-mind`](services/feed-mind) | RSS → dedupe → summarize → batched Telegram messages. Also the Firestore → BigQuery archive. | Cloud Functions gen2 `feedmind`, `feedmind-archive` | daily 08:00; archive 1st & 16th |
| [`services/paper-prism`](services/paper-prism) | arXiv → local ONNX embeddings → cosine top-k against a personal interest profile → Gemini summary. | Cloud Run Job `paper-prism-job` | Mondays 09:00 |
| [`services/summarizer`](services/summarizer) | Scrapes each item, writes a longer LLM summary and a spoken MP3 back onto the document. | Cloud Function gen2 `feedmind-audio` | Pub/Sub, when a producer finishes |

Supporting directories: [`infra/terraform`](infra/terraform) (the GCP stack),
`infra/firebase` (Firestore rules + indexes), [`docs/`](docs), `scripts/`.

## Quick start

```bash
./scripts/test-all.sh     # every suite (needs `npm ci` in apps/web the first time)
./scripts/lock-all.sh     # re-resolve all three Python services
uvx ruff check .          # repo-wide lint
```

Per-component setup lives in each component's own README:
[web](apps/web/README.md) ·
[feed-mind](services/feed-mind/README.md) ·
[paper-prism](services/paper-prism/README.md) ·
[summarizer](services/summarizer/README.md).

Local development against GCP needs Application Default Credentials:

```bash
gcloud auth application-default login
```

## Deploying

There is no repo-wide deploy — the four deployables have independent schedules,
runtimes and blast radii. Each has a manual GitHub Actions workflow:

| Workflow | Deploys |
|---|---|
| `deploy-feed-mind.yml` | `feedmind` |
| `deploy-paper-prism.yml` | `paper-prism-job` |
| `deploy-summarizer.yml` | `feedmind-audio` |
| `deploy-web.yml` | the web app |

All are `workflow_dispatch` only. Required secrets and variables are documented
in [`.github/workflows/README.md`](.github/workflows/README.md). The
`feedmind-archive` function and first-time Cloud Scheduler creation are not in
CI — run `services/feed-mind/deploy.sh` locally for those.

## Architecture

The components are joined only by the Firestore document schema and one Pub/Sub
topic — contracts that no compiler or test enforces. They are enumerated, with
what-to-change-together guidance, in [`CLAUDE.md`](CLAUDE.md).

This repository was formed by merging three separate repos (`feed-mind`,
`paper-prism`, `feed-mind-summarizer`); all of their history is preserved here.
