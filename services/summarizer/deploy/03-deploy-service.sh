#!/usr/bin/env bash
# Create/update the Cloud Run service. `run deploy` is create-or-update, so
# this is idempotent — re-run after any code or config change; it deploys a
# new revision over the old one with no downtime. Run ./04-push-subscription.sh
# only once you are ready to wire it to real traffic (see that script's own
# warning about the gen2 function still owning the topic).
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

# --set-secrets REPLACES the whole set on every deploy, so both secrets have to
# be named in one flag together — mounting one alone would silently unmount
# the other. VAPID is optional: naming a secret that does not exist fails the
# deploy outright, so it is only added once it exists.
SECRETS="LLM_API_KEY=${LLM_API_KEY_SECRET}:latest"
if gcloud secrets describe "$VAPID_PRIVATE_KEY_SECRET" --project="$PROJECT_ID" >/dev/null 2>&1; then
  SECRETS="${SECRETS},VAPID_PRIVATE_KEY=${VAPID_PRIVATE_KEY_SECRET}:latest"
else
  echo "note: ${VAPID_PRIVATE_KEY_SECRET} not found - deploying without push notifications"
fi

# FEEDMIND_TOPIC lets a batch too large for one request republish its own
# trigger message and continue in the next (see main.py::republish). Setting
# it during validation is safe as long as validation runs stay small
# (--dry-run / --limit) so republish never actually fires — a real republish
# would land on the shared topic, which the gen2 function is still subscribed
# to until cutover, and it would pick the message up too.
echo "==> Deploying Cloud Run service ${SERVICE_NAME}"
gcloud run deploy "$SERVICE_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --service-account="$SERVICE_SA" \
  --no-allow-unauthenticated \
  --memory="$MEMORY" \
  --cpu="$CPU" \
  --cpu-throttling \
  --concurrency="$CONCURRENCY" \
  --min-instances="$MIN_INSTANCES" \
  --max-instances="$MAX_INSTANCES" \
  --timeout="$TIMEOUT" \
  --set-env-vars="^|^FEEDMIND_TTS=${FEEDMIND_TTS_DEFAULT}|FEEDMIND_RATE=${TTS_RATE}|FEEDMIND_MAX_RUNTIME=${MAX_RUNTIME}|FEEDMIND_TOPIC=projects/${PROJECT_ID}/topics/${TOPIC_NAME}|LLM_API=${LLM_API}|LLM_BASE_URL=${LLM_BASE_URL}|LLM_MODEL=${LLM_MODEL}|LLM_MAX_TOKENS=${LLM_MAX_TOKENS}|VAPID_SUBJECT=${VAPID_SUBJECT}|GOOGLE_CLOUD_PROJECT=${PROJECT_ID}|FIRESTORE_DATABASE=${FIRESTORE_DATABASE}" \
  --set-secrets="$SECRETS"

echo "Deployed: ${SERVICE_NAME}"
echo
echo "Validate it directly first (no subscription wired yet) — get an identity"
echo "token and POST a full CloudEvent-shaped push (functions-framework's"
echo "cloudevent parser rejects a bare {message:{data:...}} body without the"
echo "ce-* headers and messageId/publishTime/subscription fields — found by"
echo "hand, not documented anywhere obvious):"
echo '  TOKEN=$(gcloud auth print-identity-token)'
echo "  URL=\$(gcloud run services describe ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID} --format='value(status.url)')"
echo '  MSG=$(printf "%s" '"'"'{"limit": 1, "force": true, "dry_run": true}'"'"' | base64)'
echo '  curl -i -X POST "$URL/" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \'
echo '    -H "ce-id: manual-1" -H "ce-specversion: 1.0" -H "ce-time: 2026-01-01T00:00:00.000Z" \'
echo '    -H "ce-type: google.cloud.pubsub.topic.v1.messagePublished" \'
echo "    -H \"ce-source: //pubsub.googleapis.com/projects/${PROJECT_ID}/topics/${TOPIC_NAME}\" \\"
echo '    -d "{\"message\": {\"data\": \"$MSG\", \"messageId\": \"manual-1\", \"publishTime\": \"2026-01-01T00:00:00.000Z\"}, \"subscription\": \"manual\"}"'
echo
echo "Then tail the logs:"
echo "  gcloud run services logs read ${SERVICE_NAME} --region=${REGION} --project=${PROJECT_ID} --limit=50"
echo
echo "Next (only at real cutover): ./04-push-subscription.sh"
