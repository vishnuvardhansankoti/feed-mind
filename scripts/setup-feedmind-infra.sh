#!/usr/bin/env bash
# One-time (idempotent) infrastructure for the FeedMind services: APIs, service
# accounts, IAM, and the Pub/Sub topic the Telegram notifier is triggered by.
#
#   ./scripts/setup-feedmind-infra.sh
#
# Run this before the first ./scripts/deploy-feedmind.sh. Re-running is safe.
#
# Was services/feed-mind/deploy.sh, when one function did everything. The
# function deploys and Scheduler jobs moved to deploy-feedmind.sh; what is left
# here is the project-level setup that is shared by all five.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-feed-mind}"
REGION="${REGION:-us-central1}"
SERVICE_ACCOUNT="feedmind-sa@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="feedmind-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"
TELEGRAM_TOPIC="${TELEGRAM_TOPIC:-feedmind-telegram-ready}"

echo "==> Enabling APIs"
gcloud services enable \
  cloudfunctions.googleapis.com cloudbuild.googleapis.com run.googleapis.com \
  cloudscheduler.googleapis.com firestore.googleapis.com \
  secretmanager.googleapis.com bigquery.googleapis.com \
  pubsub.googleapis.com eventarc.googleapis.com \
  --project="$PROJECT_ID"

echo "==> Service accounts"
gcloud iam service-accounts create feedmind-sa \
  --display-name="FeedMind runtime" --project="$PROJECT_ID" 2>/dev/null \
  || echo "  (feedmind-sa exists)"
gcloud iam service-accounts create feedmind-scheduler \
  --display-name="FeedMind Scheduler invoker" --project="$PROJECT_ID" 2>/dev/null \
  || echo "  (feedmind-scheduler exists)"

echo "==> IAM"
# datastore.user       Firestore read/write (every service)
# secretmanager        Telegram + Gemini credentials
# logging.logWriter    explicit, though the runtime SA usually has it
# bigquery.*           the archiver creates tables, loads staging and MERGEs;
#                      dataEditor alone cannot start a job, hence jobUser
# pubsub.publisher     ingest -> telegram-ready, and -> content-ready
for role in roles/datastore.user roles/secretmanager.secretAccessor \
            roles/logging.logWriter roles/bigquery.dataEditor \
            roles/bigquery.jobUser roles/pubsub.publisher; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" --role="$role" --quiet >/dev/null
  echo "  ${role}"
done

echo "==> Pub/Sub topic ${TELEGRAM_TOPIC}"
# The notifier's trigger. Created here rather than by the notifier's own deploy
# because the PUBLISHER (services/ingest) may well be deployed first, and publishing
# to a topic that does not exist is one of the few failures the best-effort
# publish path cannot paper over.
#
# Note the direction differs from feedmind-content-ready, which is owned by its
# consumer in services/summarizer/deploy/setup.sh — that topic crosses a service
# boundary this script does not own.
gcloud pubsub topics create "$TELEGRAM_TOPIC" --project="$PROJECT_ID" 2>/dev/null \
  || echo "  (exists)"

echo
echo "Done. Next:"
echo "  ./scripts/deploy-feedmind.sh"
echo
echo "Two free-tier guards are NOT scripted (they need your billing account ID):"
echo "  1. Billing budget alert — Billing > Budgets & alerts, \$1 with 50/90/100% triggers"
echo "  2. BigQuery query quota — IAM & Admin > Quotas > 'Query usage per day'"
echo "  See docs/feed-mind/bigquery-archival-plan.md section 7.1"
