# CI deploy workflows

Four **manual** (`workflow_dispatch`) workflows — nothing runs on push or PR.
Trigger them from the **Actions** tab → pick the workflow → **Run workflow**.

| Workflow | Deploys | Underlying scripts |
|---|---|---|
| `deploy-feedmind.yml` | any or all three FeedMind functions, plus their Scheduler jobs | `scripts/deploy-feedmind.sh` |
| `deploy-paper-prism.yml` | Cloud Build image → Cloud Run Job `paper-prism-job` | `services/paper-prism/deploy/02..04-*.sh` |
| `deploy-summarizer.yml` | Cloud Function `feedmind-audio` (Pub/Sub) | `services/summarizer/deploy/deploy.sh` |
| `deploy-web.yml` | `vite build` → Firebase Hosting | `firebase.json` (`apps/web/dist`) |

`deploy-feedmind.yml` takes a `service` input — `all`, or one of `ingest`,
`telegram-notifier`, `archive`. It lints
and runs the core package's tests first, regenerates every `requirements.txt`
from `pyproject.toml`, then stages each function with `feedmind_core` copied in
beside `main.py` (Cloud Functions uploads only `--source`, and the shared
package lives outside every service directory).

**Not covered by CI:** project-level setup — APIs, service accounts, IAM and the
`feedmind-telegram-ready` topic. Run `scripts/setup-feedmind-infra.sh` once,
locally, before the first deploy.

## Two auth mechanisms, on purpose (for now)

`deploy-feedmind.yml` uses **Workload Identity Federation** — no long-lived key.
The other three use a **service-account JSON key** in `GCP_SA_KEY`, inherited
from paper-prism. Consolidating on WIF is worth doing, but was kept out of the
monorepo merge so a deploy failure would have one possible cause instead of two.

Note also that feed-mind's workflow reads `secrets.GCP_PROJECT_ID` while the
others read `vars.GCP_PROJECT_ID`. GitHub keeps secrets and variables in
separate namespaces, so both can hold the same name — but set **both**, and
standardize on `vars` when the auth consolidation happens.

## Repository secrets and variables

Settings → Secrets and variables → Actions.

**Secrets**

| Name | Used by | Value |
|---|---|---|
| `WIF_PROVIDER` | feed-mind | Full WIF provider resource name (see `scripts/setup-wif.sh`) |
| `WIF_SERVICE_ACCOUNT` | feed-mind | `feedmind-sa@feed-mind.iam.gserviceaccount.com` |
| `FUNCTION_SERVICE_ACCOUNT` | feed-mind | SA the function runs as (same as above) |
| `GCP_PROJECT_ID` | feed-mind | `feed-mind` |
| `GCP_REGION` | feed-mind | `us-central1` |
| `GCP_SA_KEY` | paper-prism, summarizer, web | Full JSON of the deploy SA key |
| `PIPELINE_ENV_YAML` | paper-prism | Contents of `services/paper-prism/deploy/env.yaml` — it is gitignored (it holds the interest profiles, which *are* the product), so the workflow reconstructs it |
| `VITE_FIREBASE_API_KEY` | web | Firebase web API key |
| `VITE_FIREBASE_APP_ID` | web | Firebase web app id |

**Variables**

| Name | Value |
|---|---|
| `GCP_PROJECT_ID` | `feed-mind` |
| `VITE_FIREBASE_PROJECT_ID` | `feed-mind` |
| `VITE_FIRESTORE_DATABASE` | `feed-mind-db` — must match the pipeline's `FIRESTORE_DATABASE` and the summarizer's |

The Firebase web API key and app id are public (they ship in the client bundle);
keeping them as secrets only avoids printing them in build logs.

### Roles the `GCP_SA_KEY` service account needs

- `roles/cloudbuild.builds.editor` — submit Cloud Build (paper-prism)
- `roles/artifactregistry.writer` — push the image (paper-prism)
- `roles/run.admin` — deploy the Cloud Run Job, and the Cloud Run service behind
  the gen2 function (paper-prism, summarizer)
- `roles/cloudfunctions.developer` — deploy the function (summarizer)
- `roles/pubsub.editor` — the Eventarc trigger and its subscription (summarizer)
- `roles/iam.serviceAccountUser` — act as the job/scheduler/runtime SAs
- `roles/cloudscheduler.admin` — only for paper-prism's `deploy_scheduler` toggle
- `roles/firebasehosting.admin` — deploy Hosting (web)
- `roles/datastore.indexAdmin` + `roles/firebaserules.admin` — only for the web
  `also_deploy_rules` toggle

## The `.env.prod` footgun

`deploy-web.yml` writes **`.env.prod`**, not `.env.production`. `npm run build`
is `vite build --mode prod`, and Vite loads `.env.<mode>` — with mode `prod` it
never reads `.env.production`. The workflow wrote the latter until the monorepo
merge, which meant the deployed bundle was built with **no** `VITE_*` values at
all. If the site ever renders with empty Firebase config, check this first.
