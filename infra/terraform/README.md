# paper-prism — infrastructure (P4, Terraform)

Declares the whole GCP stack (PRD §6) plus the run-failure alerting (PRD §9a):

| Resource | What |
|---|---|
| `google_artifact_registry_repository` | image registry (`paper-prism`) |
| `google_firestore_database` + `google_firestore_index` | Firestore (named DB via `firestore_database`, default `feed-mind-db`) + TTL + the `category`+`run_date` composite index |
| `google_service_account` ×2 | least-privilege job SA + scheduler SA |
| `google_project_iam_member` | job SA → `datastore.user` |
| `google_secret_manager_secret` (+ version, + accessor) | Gemini key, accessor bound to job SA only |
| `google_cloud_run_v2_job` | the pipeline (2 vCPU / 2 GiB, 900s, 1 retry, secret-mounted key) |
| `google_cloud_run_v2_job_iam_member` | scheduler SA → `run.invoker` on the job |
| `google_cloud_scheduler_job` | weekly `0 9 * * 1` trigger |
| `google_logging_metric` + `google_monitoring_alert_policy` + `google_monitoring_notification_channel` | email alert on `RUN COMPLETED WITH FAILURES` |
| `google_firebase_hosting_site` | optional (off by default) |

## Prerequisites

- Terraform ≥ 1.5, `gcloud` authenticated (`gcloud auth application-default login`).
- A GCP project with billing enabled.
- The pipeline image **pushed** to Artifact Registry before first job execution
  (the repo is created by Terraform; build/push with
  `../pipeline/deploy/02-build-push.sh` or a CI step).

## Usage

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in values
# keep the key out of VCS — prefer an env var over the tfvars file:
export TF_VAR_gemini_api_key=xxxxxxxx

terraform init
terraform plan
terraform apply

# smoke test (also printed as an output):
gcloud run jobs execute paper-prism-job --region us-central1 --wait
```

## Alerting

The pipeline logs `RUN COMPLETED WITH FAILURES` whenever a lens is skipped or
fails (best-effort semantics, PRD §3.3/§8a). The log-based metric counts those
lines and the alert policy emails `alert_email` when the count exceeds zero in an
hour. Hard crashes that never reach that log line also surface as **failed Cloud
Run job executions** — add a second alert on
`run.googleapis.com/job/completed_execution_count{result="failed"}` if you want
belt-and-suspenders.

## Firebase Hosting

Off by default. Terraform can create the Hosting *site*
(`enable_firebase_hosting = true`), but content is still deployed with the
firebase CLI from the repo root:

```bash
firebase deploy --only hosting
firebase deploy --only firestore:rules,firestore:indexes
```

> Note: if you deployed `firestore.indexes.json` via the firebase CLI, that
> creates the same composite index this module declares. Manage the index in
> **one** place — either Terraform (`google_firestore_index`) or the CLI — not
> both.

## Named Firestore database

`var.firestore_database` (default `feed-mind-db`) selects the database the
pipeline writes to and the database/index/TTL resources manage; it's also passed
to the Cloud Run Job as `FIRESTORE_DATABASE`. If that database **already exists**
(created manually or by `pipeline/deploy/01b-setup-firestore-db.sh`), import it
before `apply` so Terraform adopts rather than recreates it:

```bash
terraform import google_firestore_database.db projects/PROJECT/databases/feed-mind-db
```

The web app must read the same database — set `VITE_FIRESTORE_DATABASE` in
`web/.env` to match.

## Relationship to the P2 `gcloud` scripts

`pipeline/deploy/*.sh` (P2) and this module create the **same resources** by two
different means. Terraform is the source of truth for P4+. If you already ran the
P2 scripts against a project, either tear those resources down first or
`terraform import` them before `apply`, so Terraform adopts rather than
duplicates them.
```
