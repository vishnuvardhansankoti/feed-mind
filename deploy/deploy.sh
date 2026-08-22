#!/usr/bin/env bash
# Deploy feedmind_audio.py as a gen2 Cloud Function.
#
#     ./deploy/deploy.sh
#
# Run ./deploy/setup.sh first, once per project. Re-run this after any code or
# config change; it deploys a new revision over the old one with no downtime.
#
# The function is private - no unauthenticated access - so the only callers are
# the scheduler jobs from ./deploy/schedule.sh and anyone holding run.invoker.

source "$(dirname "$0")/config.sh"
require_gcloud

cd "$(dirname "$0")/.."

# Fail early on the two mistakes that otherwise surface as a confusing runtime
# error several minutes into a deploy.
[[ -f main.py ]] || { echo "main.py is missing - run this from the repo." >&2; exit 1; }
if [[ "$LLM_BASE_URL" == *localhost* || "$LLM_BASE_URL" == *127.0.0.1* ]]; then
    echo "LLM_BASE_URL points at localhost (${LLM_BASE_URL})." >&2
    echo "The function has no Ollama of its own; set a hosted provider in" >&2
    echo "deploy/config.sh or in the environment." >&2
    exit 1
fi

say "Deploying ${FUNCTION_NAME} to ${PROJECT_ID}/${REGION}"

# --set-env-vars uses ^|^ as the delimiter so values containing commas (the
# prompt, say) survive. --set-secrets mounts the API key as an env var that
# webscraper/config.py picks up like any other.
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --runtime="$RUNTIME" \
    --source=. \
    --entry-point="$ENTRY_POINT" \
    --trigger-http \
    --no-allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --memory="$MEMORY" \
    --cpu="$CPU" \
    --timeout="$TIMEOUT" \
    --concurrency="$CONCURRENCY" \
    --max-instances="$MAX_INSTANCES" \
    --set-env-vars="^|^FEEDMIND_TTS=cloud|FEEDMIND_VOICE=${TTS_VOICE}|FEEDMIND_RATE=${TTS_RATE}|LLM_API=${LLM_API}|LLM_BASE_URL=${LLM_BASE_URL}|LLM_MODEL=${LLM_MODEL}|LLM_MAX_TOKENS=${LLM_MAX_TOKENS}|GRPC_VERBOSITY=ERROR" \
    --set-secrets="LLM_API_KEY=${LLM_API_KEY_SECRET}:latest"

# ---------------------------------------------------------------------------
# A gen2 function is a Cloud Run service, so "who may call it" is a run.invoker
# binding on that service. Granted here rather than in setup.sh because the
# service does not exist until the first deploy.
say "Allowing ${SCHEDULER_SA} to invoke it"
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker" \
    --quiet >/dev/null

URL="$(gcloud functions describe "$FUNCTION_NAME" \
    --gen2 --project="$PROJECT_ID" --region="$REGION" \
    --format='value(serviceConfig.uri)')"

say "Deployed"
echo "  ${URL}"
echo
echo "Smoke test it without writing anything:"
echo "  curl -X POST '${URL}' \\"
echo "    -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"limit\": 1, \"dry_run\": true, \"force\": true}'"
echo
echo "Tail the logs:"
echo "  gcloud functions logs read ${FUNCTION_NAME} --gen2 --region=${REGION} --limit=50"
echo
echo "Then set up the cron jobs: ./deploy/schedule.sh"
