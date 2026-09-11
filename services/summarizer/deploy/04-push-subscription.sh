#!/usr/bin/env bash
# Wire the Pub/Sub push subscription to the deployed Cloud Run service.
#
# Run this ONLY at real cutover, after the gen2 Cloud Function has been
# deleted — not during side-by-side validation. Pub/Sub fans a message out to
# every subscription on a topic, so if the function's own (Eventarc-managed)
# subscription and this one both exist at once, every message gets processed
# twice, concurrently, by two runtimes that both rewrite the same Firestore
# documents wholesale. This script refuses to run while the function exists,
# rather than leaving that footgun to be remembered by hand.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

if gcloud functions describe feedmind-audio --gen2 \
    --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
  echo "REFUSING: the gen2 function feedmind-audio still exists." >&2
  echo "Delete it first (it is still subscribed to ${TOPIC_NAME} via Eventarc):" >&2
  echo "  gcloud functions delete feedmind-audio --gen2 --project=${PROJECT_ID} --region=${REGION}" >&2
  echo "Then re-run this script." >&2
  exit 1
fi

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" \
  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"

echo "==> Allowing ${PUSH_SA} to invoke ${SERVICE_NAME}"
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --region="$REGION" --project="$PROJECT_ID" \
  --member="serviceAccount:${PUSH_SA}" \
  --role="roles/run.invoker" --quiet >/dev/null

echo "==> Push subscription ${PUSH_SUBSCRIPTION} on ${TOPIC_NAME}"
if gcloud pubsub subscriptions describe "$PUSH_SUBSCRIPTION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud pubsub subscriptions update "$PUSH_SUBSCRIPTION" \
    --project="$PROJECT_ID" \
    --push-endpoint="${SERVICE_URL}/" \
    --push-auth-service-account="$PUSH_SA" \
    --ack-deadline="$ACK_DEADLINE"
else
  gcloud pubsub subscriptions create "$PUSH_SUBSCRIPTION" \
    --project="$PROJECT_ID" \
    --topic="$TOPIC_NAME" \
    --push-endpoint="${SERVICE_URL}/" \
    --push-auth-service-account="$PUSH_SA" \
    --ack-deadline="$ACK_DEADLINE"
fi

echo "Wired. Smoke test:"
echo "  gcloud pubsub topics publish ${TOPIC_NAME} --message='{\"limit\": 1, \"force\": true, \"dry_run\": true}' --project=${PROJECT_ID}"
echo "  gcloud run services logs read ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID} --limit=50"
echo
echo "If SERVICE_NAME was still the scratch name (feedmind-audio-run), redeploy"
echo "once more with SERVICE_NAME=feedmind-audio to reach the permanent name,"
echo "then re-run this script so the subscription points at the renamed service."
