#!/usr/bin/env bash
# Shared configuration — sourced by the other deploy scripts.
# Override any value by exporting it before running (e.g. `PROJECT_ID=foo ./01-setup.sh`).
set -euo pipefail

export PROJECT_ID="${PROJECT_ID:?set PROJECT_ID feed-mind)}"
export REGION="${REGION:-us-central1}"

# Firestore database id. The pipeline writes runs/run_status here. Use a named
# (non-default) database; "(default)" is reserved for the auto-created one.
export FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-feed-mind-db}"

# Artifact Registry + image
export REPO="${REPO:-paper-prism}"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/paper-prism:latest"

# Cloud Run Job
export JOB_NAME="${JOB_NAME:-paper-prism-job}"
export JOB_SA_NAME="${JOB_SA_NAME:-paper-prism-job}"
export JOB_SA="${JOB_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Cloud Scheduler (least-privilege invoker, separate from the job SA)
export SCHEDULER_NAME="${SCHEDULER_NAME:-paper-prism-weekly}"
export SCHED_SA_NAME="${SCHED_SA_NAME:-paper-prism-scheduler}"
export SCHED_SA="${SCHED_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
export SCHEDULE="${SCHEDULE:-0 9 * * 1}"   # Mondays 09:00 (PRD cadence)
export TIMEZONE="${TIMEZONE:-Etc/UTC}"

# Secret Manager
export SECRET_NAME="${SECRET_NAME:-gemini-api-key}"

echo "config: project=${PROJECT_ID} region=${REGION} job=${JOB_NAME}"
