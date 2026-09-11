#!/usr/bin/env bash
# Create/update the Cloud Run service. `run deploy` is create-or-update, so
# this is idempotent. Run ./04-push-subscription.sh after the first deploy
# (needs the service URL, which does not exist before this).
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

echo "==> Deploying Cloud Run service ${SERVICE_NAME}"
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --service-account="$SERVICE_SA" \
  --no-allow-unauthenticated \
  --set-env-vars="SINK=firestore,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},FIRESTORE_DATABASE=${FIRESTORE_DATABASE}" \
  --memory=2Gi \
  --cpu=2 \
  --concurrency=1 \
  --max-instances=1 \
  --timeout=540s

echo "Deployed. Next: ./04-push-subscription.sh"
