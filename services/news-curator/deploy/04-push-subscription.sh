#!/usr/bin/env bash
# Wire the Pub/Sub push subscription to the deployed Cloud Run service.
# Run after ./03-deploy-service.sh (needs its URL) and after
# scripts/setup-feedmind-infra.sh has created feedmind-news-ingested.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"

echo "==> Allowing ${PUSH_SA} to invoke ${SERVICE_NAME}"
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --region="$REGION" --project="$PROJECT_ID" \
  --member="serviceAccount:${PUSH_SA}" \
  --role="roles/run.invoker" --quiet >/dev/null

echo "==> Push subscription ${PUSH_SUBSCRIPTION} on ${NEWS_INGESTED_TOPIC}"
if gcloud pubsub subscriptions describe "$PUSH_SUBSCRIPTION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud pubsub subscriptions update "$PUSH_SUBSCRIPTION" \
    --project="$PROJECT_ID" \
    --push-endpoint="${SERVICE_URL}/" \
    --push-auth-service-account="$PUSH_SA" \
    --ack-deadline=600
else
  gcloud pubsub subscriptions create "$PUSH_SUBSCRIPTION" \
    --project="$PROJECT_ID" \
    --topic="$NEWS_INGESTED_TOPIC" \
    --push-endpoint="${SERVICE_URL}/" \
    --push-auth-service-account="$PUSH_SA" \
    --ack-deadline=600
fi

echo "Wired. Smoke test:"
echo "  gcloud pubsub topics publish ${NEWS_INGESTED_TOPIC} --message='{}' --project=${PROJECT_ID}"
echo "  gcloud run services logs read ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID} --limit=50"
