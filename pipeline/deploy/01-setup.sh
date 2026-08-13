#!/usr/bin/env bash
# One-time project setup: APIs, Firestore, Artifact Registry, service accounts,
# IAM, and the Gemini secret. Idempotent — safe to re-run.
#
# Requires the Gemini key in the environment:  export GEMINI_API_KEY=...
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

: "${GEMINI_API_KEY:?export GEMINI_API_KEY before running (AI Studio key)}"

echo "==> Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com \
  cloudbuild.googleapis.com \
  --project "$PROJECT_ID"

echo "==> Firestore (native mode)"
gcloud firestore databases create \
  --location="$REGION" --type=firestore-native --project "$PROJECT_ID" \
  2>/dev/null || echo "    Firestore database already exists — skipping"

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION" --project "$PROJECT_ID" \
  2>/dev/null || echo "    repo already exists — skipping"

echo "==> Service accounts"
gcloud iam service-accounts create "$JOB_SA_NAME" \
  --display-name="paper-prism pipeline job" --project "$PROJECT_ID" \
  2>/dev/null || echo "    job SA exists — skipping"
gcloud iam service-accounts create "$SCHED_SA_NAME" \
  --display-name="paper-prism scheduler invoker" --project "$PROJECT_ID" \
  2>/dev/null || echo "    scheduler SA exists — skipping"

echo "==> Job SA: Firestore write (least privilege)"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${JOB_SA}" \
  --role="roles/datastore.user" --condition=None --quiet

echo "==> Gemini secret"
if gcloud secrets describe "$SECRET_NAME" --project "$PROJECT_ID" >/dev/null 2>&1; then
  printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add "$SECRET_NAME" \
    --data-file=- --project "$PROJECT_ID"
else
  printf '%s' "$GEMINI_API_KEY" | gcloud secrets create "$SECRET_NAME" \
    --data-file=- --replication-policy=automatic --project "$PROJECT_ID"
fi

echo "==> Job SA: accessor on the secret only (least privilege)"
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --member="serviceAccount:${JOB_SA}" \
  --role="roles/secretmanager.secretAccessor" --project "$PROJECT_ID" --quiet

echo "Setup complete."
