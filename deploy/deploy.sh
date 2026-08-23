#!/usr/bin/env bash
# Deploy feedmind_audio.py as a gen2 Cloud Function.
#
#     ./deploy/deploy.sh
#
# Run ./deploy/setup.sh first, once per project. Re-run this after any code or
# config change; it deploys a new revision over the old one with no downtime.
#
# The function has no HTTP endpoint at all: it runs only when a message lands on
# TOPIC_NAME. Publish one by hand with ./deploy/publish.sh.

source "$(dirname "$0")/config.sh"
require_gcloud

cd "$(dirname "$0")/.."

# Fail early on the two mistakes that otherwise surface as a confusing runtime
# error several minutes into a deploy.
[[ -f main.py ]] || { echo "main.py is missing - run this from the repo." >&2; exit 1; }
# An event-driven function is capped at 540s. gcloud rejects anything higher
# rather than clamping, and does so several seconds into the deploy.
if (( ${TIMEOUT%s} > 540 )); then
    echo "TIMEOUT is ${TIMEOUT}, but an event-driven function cannot exceed 540s." >&2
    echo "Lower it in deploy/config.sh. For a batch that needs longer, leave" >&2
    echo "TIMEOUT at 540s and let MAX_RUNTIME (${MAX_RUNTIME}s) split the work" >&2
    echo "across invocations." >&2
    exit 1
fi

if (( ${MAX_RUNTIME%.*} >= ${TIMEOUT%s} )); then
    echo "MAX_RUNTIME (${MAX_RUNTIME}s) must be below TIMEOUT (${TIMEOUT})," >&2
    echo "or the run is killed before it can stop cleanly." >&2
    exit 1
fi

if [[ "$LLM_BASE_URL" == *localhost* || "$LLM_BASE_URL" == *127.0.0.1* ]]; then
    echo "LLM_BASE_URL points at localhost (${LLM_BASE_URL})." >&2
    echo "The function has no Ollama of its own; set a hosted provider in" >&2
    echo "deploy/config.sh or in the environment." >&2
    exit 1
fi

# A gen2 function's trigger type is fixed at creation. An HTTP function cannot
# be converted into an event-driven one in place - gcloud rejects the deploy -
# so a function left over from the HTTP era has to be removed first. This is the
# only destructive step in these scripts, hence the prompt.
EXISTING_TRIGGER="$(gcloud functions describe "$FUNCTION_NAME" \
    --gen2 --project="$PROJECT_ID" --region="$REGION" \
    --format='value(eventTrigger.eventType)' 2>/dev/null || true)"

if gcloud functions describe "$FUNCTION_NAME" --gen2 --project="$PROJECT_ID" \
        --region="$REGION" >/dev/null 2>&1 && [[ -z "$EXISTING_TRIGGER" ]]; then
    say "${FUNCTION_NAME} currently has an HTTP trigger"
    echo "Switching to Pub/Sub means deleting and recreating it. The function is"
    echo "stateless - every summary already written to Firestore and Cloud"
    echo "Storage is untouched - but its URL will change and it will be briefly"
    echo "absent."
    echo
    read -r -p "Delete and recreate ${FUNCTION_NAME}? [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

    gcloud functions delete "$FUNCTION_NAME" \
        --gen2 --project="$PROJECT_ID" --region="$REGION" --quiet
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
    --trigger-topic="$TOPIC_NAME" \
    --trigger-service-account="$TRIGGER_SA" \
    --service-account="$SERVICE_ACCOUNT" \
    --memory="$MEMORY" \
    --cpu="$CPU" \
    --timeout="$TIMEOUT" \
    --concurrency="$CONCURRENCY" \
    --max-instances="$MAX_INSTANCES" \
    --set-env-vars="^|^FEEDMIND_TTS=cloud|FEEDMIND_VOICE=${TTS_VOICE}|FEEDMIND_RATE=${TTS_RATE}|FEEDMIND_MAX_RUNTIME=${MAX_RUNTIME}|FEEDMIND_TOPIC=projects/${PROJECT_ID}/topics/${TOPIC_NAME}|LLM_API=${LLM_API}|LLM_BASE_URL=${LLM_BASE_URL}|LLM_MODEL=${LLM_MODEL}|LLM_MAX_TOKENS=${LLM_MAX_TOKENS}|GRPC_VERBOSITY=ERROR" \
    --set-secrets="LLM_API_KEY=${LLM_API_KEY_SECRET}:latest"

# ---------------------------------------------------------------------------
# A gen2 function is a Cloud Run service, so "who may call it" is a run.invoker
# binding on that service. Eventarc delivers as TRIGGER_SA, so that is the
# identity that needs it. Granted here rather than in setup.sh because the
# service does not exist until the first deploy.
say "Allowing ${TRIGGER_SA} to invoke it"
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
    --project="$PROJECT_ID" \
    --region="$REGION" \
    --member="serviceAccount:${TRIGGER_SA}" \
    --role="roles/run.invoker" \
    --quiet >/dev/null

# ---------------------------------------------------------------------------
# Eventarc creates the push subscription with a 60s ack deadline, which is far
# too short for a batch - Pub/Sub would redeliver while the first run is still
# going. Widen it to the push maximum. The subscription is named after the
# trigger, so it has to be looked up rather than assumed.
say "Widening the ack deadline to ${ACK_DEADLINE}s"
SUBSCRIPTION="$(gcloud pubsub subscriptions list \
    --project="$PROJECT_ID" \
    --filter="topic:${TOPIC_NAME}" \
    --format='value(name)' 2>/dev/null | head -1)"

if [[ -n "$SUBSCRIPTION" ]]; then
    gcloud pubsub subscriptions update "$SUBSCRIPTION" \
        --project="$PROJECT_ID" \
        --ack-deadline="$ACK_DEADLINE" \
        --quiet >/dev/null
    echo "  ${SUBSCRIPTION##*/}"
else
    echo "  WARNING: no subscription found on ${TOPIC_NAME} yet." >&2
    echo "  Eventarc may still be creating it; re-run this script in a minute." >&2
fi

say "Deployed"
echo "  triggered by messages on topic ${TOPIC_NAME}"
echo
echo "Smoke test it without writing anything:"
echo "  gcloud pubsub topics publish ${TOPIC_NAME} \\"
echo "    --message='{\"limit\": 1, \"force\": true, \"dry_run\": true}'"
echo
echo "Tail the logs:"
echo "  gcloud functions logs read ${FUNCTION_NAME} --gen2 --region=${REGION} --limit=50"
echo
echo "Then wire the publisher: see the FeedMind section of deploy/README.md"
