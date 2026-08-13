# paper-prism — P2 deployment

Deploys the pipeline as a **Cloud Run Job** triggered weekly by **Cloud
Scheduler**, reading its Gemini key from **Secret Manager**, writing to
**Firestore**, under **least-privilege service accounts**. See PRD §5–§7.

> These are imperative `gcloud` scripts to get you running (roadmap P2).
> Infrastructure is formalized in **Terraform** in P4 — at which point these
> scripts are superseded.

## Prerequisites

- `gcloud` installed and authenticated (`gcloud auth login`), billing enabled.
- A GCP project id.
- Your AI Studio **Gemini API key**.

## Steps

```bash
cd pipeline/deploy

export PROJECT_ID=your-project-id
export REGION=us-central1          # optional, this is the default
export GEMINI_API_KEY=xxxxxxxx     # AI Studio key

# 1. One-time: APIs, Firestore, Artifact Registry, service accounts, IAM, secret
./01-setup.sh

# 2. Build (Cloud Build -> linux/amd64) and push the image
./02-build-push.sh

# 3. Configure non-secret env (the interest profiles) and deploy the Job
cp env.yaml.example env.yaml       # edit PROFILE_* and GOOGLE_CLOUD_PROJECT
./03-deploy-job.sh

# 4. Smoke test: run the Job once, watch it write Firestore
gcloud run jobs execute paper-prism-job --region "$REGION" --wait

# 5. Schedule it weekly
./04-scheduler.sh
```

## What gets created

| Resource | Name | Notes |
|---|---|---|
| Artifact Registry repo | `paper-prism` | holds the ONNX-slim image |
| Cloud Run Job | `paper-prism-job` | 2Gi/2vCPU, 900s timeout, 1 retry, scale-to-zero |
| Job service account | `paper-prism-job@…` | `datastore.user` + accessor on the secret only |
| Scheduler service account | `paper-prism-scheduler@…` | `run.invoker` on the job only |
| Secret | `gemini-api-key` | mounted as `GEMINI_API_KEY` |
| Scheduler job | `paper-prism-weekly` | `0 9 * * 1` (Mon 09:00) |

## Cost posture

A weekly ~3–5 min run at 2 vCPU / 2 GiB is on the order of ~2,400 vCPU-seconds
and ~4,800 GiB-seconds per month — a rounding error against the Cloud Run free
grant (180k vCPU-s / 360k GiB-s). Everything else sits in free tiers. See PRD §1.3.

## Notes

- **Secrets never touch env.yaml.** The Gemini key lives only in Secret Manager;
  `env.yaml` holds the profiles and tunables. Do not commit a real `env.yaml`.
- **Model is baked into the image** (`Dockerfile` prefetch + `HF_HUB_OFFLINE=1`),
  so the scheduled job has no runtime dependency on HuggingFace.
- **Idempotent:** re-running any script updates in place.
