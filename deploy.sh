#!/usr/bin/env bash
# deploy.sh — Deploy FeedMind to GCP Cloud Functions Gen 2
#
# Prerequisites:
#   1. gcloud CLI installed and authenticated (gcloud auth login)
#   2. gcloud config set project YOUR_PROJECT_ID
#   3. Secrets already created in Secret Manager (see README.md)
#   4. APIs enabled: cloudfunctions, cloudscheduler, firestore, secretmanager
#
# Usage:
#   chmod +x deploy.sh
#   ./deploy.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — update these before running
# ---------------------------------------------------------------------------
PROJECT_ID="your-gcp-project-id"           # TODO: replace
REGION="us-central1"                       # TODO: update to your preferred region
FUNCTION_NAME="feedmind"
RUNTIME="python312"
ENTRY_POINT="feedmind"
MEMORY="256Mi"
TIMEOUT="300s"
SERVICE_ACCOUNT="feedmind-sa@${PROJECT_ID}.iam.gserviceaccount.com"

# Cloud Scheduler
SCHEDULER_JOB_NAME="feedmind-daily-trigger"
SCHEDULER_SCHEDULE="0 8 * * *"             # 8:00 AM every day
SCHEDULER_TIMEZONE="America/Chicago"       # TODO: update to your timezone

# ---------------------------------------------------------------------------
# Step 1: Enable required APIs
# ---------------------------------------------------------------------------
echo "==> Enabling required GCP APIs..."
gcloud services enable \
  cloudfunctions.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# Step 2: Create Service Account (if it doesn't exist)
# ---------------------------------------------------------------------------
echo "==> Creating service account: ${SERVICE_ACCOUNT}..."
gcloud iam service-accounts create feedmind-sa \
  --display-name="FeedMind Service Account" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (already exists — skipping)"

# ---------------------------------------------------------------------------
# Step 3: Grant minimum IAM roles to the Service Account
# ---------------------------------------------------------------------------
echo "==> Granting IAM roles..."

# Firestore read/write
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/datastore.user" \
  --quiet

# Secret Manager read
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet

# Cloud Logging write (included in the default CF runtime SA, but explicit here)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/logging.logWriter" \
  --quiet

# ---------------------------------------------------------------------------
# Step 4: Prepare dependencies and deploy
# ---------------------------------------------------------------------------
echo "==> Generating requirements.txt via uv..."
# GCP Cloud Functions requires a requirements.txt file. We use uv to generate it from pyproject.toml.
if ! command -v uv &> /dev/null; then
  echo "Error: uv is not installed. Please install it first: https://docs.astral.sh/uv/"
  exit 1
fi
uv pip compile pyproject.toml -o requirements.txt

echo "==> Deploying Cloud Function: ${FUNCTION_NAME}..."
gcloud functions deploy "${FUNCTION_NAME}" \
  --gen2 \
  --runtime="${RUNTIME}" \
  --region="${REGION}" \
  --source="." \
  --entry-point="${ENTRY_POINT}" \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --project="${PROJECT_ID}"

# Get the deployed function URL
FUNCTION_URL=$(gcloud functions describe "${FUNCTION_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT_ID}" \
  --format="value(serviceConfig.uri)")

echo "  Function URL: ${FUNCTION_URL}"

# ---------------------------------------------------------------------------
# Step 5: Create a dedicated invoker Service Account for Cloud Scheduler
# ---------------------------------------------------------------------------
SCHEDULER_SA="feedmind-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Creating scheduler service account: ${SCHEDULER_SA}..."
gcloud iam service-accounts create feedmind-scheduler \
  --display-name="FeedMind Scheduler Invoker" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "  (already exists — skipping)"

# Grant the scheduler SA permission to invoke the Cloud Function
gcloud functions add-invoker-policy-binding "${FUNCTION_NAME}" \
  --region="${REGION}" \
  --member="serviceAccount:${SCHEDULER_SA}" \
  --project="${PROJECT_ID}"

# ---------------------------------------------------------------------------
# Step 6: Create Cloud Scheduler job
# ---------------------------------------------------------------------------
echo "==> Creating Cloud Scheduler job: ${SCHEDULER_JOB_NAME}..."
gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --location="${REGION}" \
  --schedule="${SCHEDULER_SCHEDULE}" \
  --time-zone="${SCHEDULER_TIMEZONE}" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --oidc-service-account-email="${SCHEDULER_SA}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --project="${PROJECT_ID}" 2>/dev/null || \
gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
  --location="${REGION}" \
  --schedule="${SCHEDULER_SCHEDULE}" \
  --time-zone="${SCHEDULER_TIMEZONE}" \
  --uri="${FUNCTION_URL}" \
  --http-method=POST \
  --oidc-service-account-email="${SCHEDULER_SA}" \
  --oidc-token-audience="${FUNCTION_URL}" \
  --project="${PROJECT_ID}"

echo ""
echo "✅ FeedMind deployed successfully!"
echo "   Function URL : ${FUNCTION_URL}"
echo "   Scheduler    : ${SCHEDULER_JOB_NAME} — runs at ${SCHEDULER_SCHEDULE} (${SCHEDULER_TIMEZONE})"
echo ""
echo "To trigger a manual test run:"
echo "  gcloud scheduler jobs run ${SCHEDULER_JOB_NAME} --location=${REGION} --project=${PROJECT_ID}"
