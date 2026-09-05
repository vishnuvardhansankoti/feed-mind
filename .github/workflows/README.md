# CI deploy workflows

Two **manual** (`workflow_dispatch`) workflows. Neither runs on push/PR — you
trigger them from the **Actions** tab → pick the workflow → **Run workflow**.

| Workflow | What it does | Underlying scripts |
|---|---|---|
| `deploy-pipeline.yml` | Cloud Build image → Artifact Registry → deploy Cloud Run Job (optionally wire Scheduler) | `pipeline/deploy/02-build-push.sh`, `03-deploy-job.sh`, `04-scheduler.sh` |
| `deploy-web.yml` | `npm ci` → `vite build` (firestore mode) → `firebase deploy --only hosting` | `firebase.json` (`web/dist`) |

## One-time setup

### 1. Service account + key

Create a deploy SA in the GCP project (`feed-mind`) and grant the roles both
workflows need:

- `roles/cloudbuild.builds.editor` — submit Cloud Build (pipeline)
- `roles/artifactregistry.writer` — push the image (pipeline)
- `roles/run.admin` — deploy the Cloud Run Job (pipeline)
- `roles/iam.serviceAccountUser` — act as the job/scheduler SAs (pipeline)
- `roles/cloudscheduler.admin` — only if you use `deploy_scheduler` (pipeline)
- `roles/firebasehosting.admin` — deploy Hosting (web)
- `roles/datastore.indexAdmin` + `roles/firebaserules.admin` — only if you use
  the web `also_deploy_rules` toggle

Generate a JSON key and paste its contents into the `GCP_SA_KEY` secret.

> A tighter alternative is Workload Identity Federation (no long-lived key) via
> `google-github-actions/auth` with `workload_identity_provider`. The key path
> above is the simplest for a solo project.

### 2. Repository secrets and variables

Settings → Secrets and variables → Actions.

**Secrets** (encrypted):

| Name | Value |
|---|---|
| `GCP_SA_KEY` | Full JSON of the deploy SA key |
| `PIPELINE_ENV_YAML` | Full contents of `pipeline/deploy/env.yaml` (profiles etc.) — it is gitignored, so the pipeline workflow reconstructs it from here |
| `VITE_FIREBASE_API_KEY` | Firebase web API key |
| `VITE_FIREBASE_APP_ID` | Firebase web app id |

**Variables** (plain text):

| Name | Value |
|---|---|
| `GCP_PROJECT_ID` | `feed-mind` |
| `VITE_FIREBASE_PROJECT_ID` | `feed-mind` |
| `VITE_FIRESTORE_DATABASE` | `feed-mind-db` (must match the pipeline's `FIRESTORE_DATABASE`) |

The Firebase web API key and app id are public (they ship in the client bundle),
but keeping them as secrets avoids printing them in build logs.
