#!/usr/bin/env bash
# Deploy one (or every) FeedMind Cloud Function.
#
#   ./scripts/deploy-feedmind.sh                     # all five
#   ./scripts/deploy-feedmind.sh ingest              # just one
#   ./scripts/deploy-feedmind.sh --schedulers        # (re)create Scheduler jobs
#
# One script for all five because they differ only in name, trigger, timeout and
# schedule — everything else (staging the core package, the service account, the
# region) is identical, and five near-copies would drift.
#
# Prerequisites: ./scripts/setup-feedmind-infra.sh has been run once.
set -euo pipefail
cd "$(dirname "$0")/.."

PROJECT_ID="${PROJECT_ID:-feed-mind}"
REGION="${REGION:-us-central1}"
RUNTIME="${RUNTIME:-python312}"
MEMORY="${MEMORY:-512Mi}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-feedmind-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
SCHEDULER_SA="${SCHEDULER_SA:-feedmind-scheduler@${PROJECT_ID}.iam.gserviceaccount.com}"
TIMEZONE="${TIMEZONE:-America/Chicago}"
TELEGRAM_TOPIC="${TELEGRAM_TOPIC:-feedmind-telegram-ready}"

# service | entry point | trigger | timeout | schedule
#
# The notifier has no schedule — it wakes on TELEGRAM_TOPIC, published by the
# ingest run once all three feed groups are stored.
SERVICES=(
  "ingest|ingest|http|300s|0 8 * * *"
  "telegram-notifier|telegram_notifier|topic|300s|"
  "archive|archive|http|900s|0 4 1,16 * *"
)

deploy_one() {
    local name="$1" entry="$2" trigger="$3" timeout="$4"
    local fn="feedmind-${name}"

    echo "==> Staging ${fn}"
    local build
    build="$(scripts/stage-service.sh "$name")"

    echo "==> Deploying ${fn} (${trigger})"
    local trigger_args=(--trigger-http --no-allow-unauthenticated)
    if [[ "$trigger" == "topic" ]]; then
        # An event-driven function's trigger type is fixed at creation; gcloud
        # refuses to convert an existing HTTP function in place.
        #
        # --max-instances=1 is load-bearing, not tuning. Eventarc creates the
        # push subscription with a 60s ack deadline; a digest with a backlog can
        # outlast that (telegram.py sleeps 1s after every message), and Pub/Sub
        # would then redeliver while the first run is still going. A second
        # instance would query telegram_status=="pending", find the batch not yet
        # flipped to "sent", and send the entire digest again. Capping instances
        # makes the redelivery queue behind the running run instead of racing it.
        # The ack deadline is widened below for the same reason.
        trigger_args=(--trigger-topic "$TELEGRAM_TOPIC" --max-instances=1)
    fi

    gcloud functions deploy "$fn" \
        --gen2 \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --runtime="$RUNTIME" \
        --source="$build" \
        --entry-point="$entry" \
        --memory="$MEMORY" \
        --timeout="$timeout" \
        --service-account="$SERVICE_ACCOUNT" \
        "${trigger_args[@]}"

    if [[ "$trigger" == "topic" ]]; then
        widen_ack_deadline
    fi

    rm -rf "$build"
}

widen_ack_deadline() {
    # Eventarc's 60s default is shorter than a digest run with a backlog. 600s is
    # the maximum a push subscription allows, and it is kept above the function's
    # own timeout so the run is always killed by its deadline before Pub/Sub
    # concludes the delivery failed. The subscription is named after the trigger,
    # so it has to be looked up rather than assumed.
    local sub
    sub="$(gcloud pubsub subscriptions list --project="$PROJECT_ID" \
             --filter="topic:${TELEGRAM_TOPIC}" --format='value(name)' 2>/dev/null | head -1)"
    if [[ -n "$sub" ]]; then
        gcloud pubsub subscriptions update "$sub" --project="$PROJECT_ID" \
            --ack-deadline="${ACK_DEADLINE:-600}" --quiet >/dev/null
        echo "  ack deadline ${ACK_DEADLINE:-600}s on ${sub##*/}"
    else
        echo "  WARNING: no subscription on ${TELEGRAM_TOPIC} yet; re-run in a minute" >&2
    fi
}

wire_scheduler() {
    local name="$1" schedule="$2"
    [[ -n "$schedule" ]] || return 0          # the notifier has no schedule
    local fn="feedmind-${name}" job="feedmind-${name}-job"

    local url
    url="$(gcloud functions describe "$fn" --region="$REGION" --project="$PROJECT_ID" \
             --format='value(serviceConfig.uri)')"

    gcloud functions add-invoker-policy-binding "$fn" \
        --region="$REGION" --project="$PROJECT_ID" \
        --member="serviceAccount:${SCHEDULER_SA}" >/dev/null

    echo "==> Scheduler ${job}: ${schedule}"
    gcloud scheduler jobs create http "$job" \
        --location="$REGION" --project="$PROJECT_ID" \
        --schedule="$schedule" --time-zone="$TIMEZONE" \
        --uri="$url" --http-method=POST \
        --oidc-service-account-email="$SCHEDULER_SA" \
        --oidc-token-audience="$url" 2>/dev/null \
    || gcloud scheduler jobs update http "$job" \
        --location="$REGION" --project="$PROJECT_ID" \
        --schedule="$schedule" --time-zone="$TIMEZONE" \
        --uri="$url" --http-method=POST \
        --oidc-service-account-email="$SCHEDULER_SA" \
        --oidc-token-audience="$url"
}

SCHEDULERS_ONLY=false
TARGET=""
for arg in "$@"; do
    case "$arg" in
        --schedulers) SCHEDULERS_ONLY=true ;;
        *) TARGET="$arg" ;;
    esac
done

for row in "${SERVICES[@]}"; do
    IFS='|' read -r name entry trigger timeout schedule <<<"$row"
    [[ -z "$TARGET" || "$TARGET" == "$name" ]] || continue

    if [[ "$SCHEDULERS_ONLY" == true ]]; then
        wire_scheduler "$name" "$schedule"
    else
        deploy_one "$name" "$entry" "$trigger" "$timeout"
        wire_scheduler "$name" "$schedule"
    fi
done

echo
echo "Done. Trigger a run:"
echo "  gcloud scheduler jobs run feedmind-ingest-job --location=${REGION} --project=${PROJECT_ID}"
echo "Ring the notifier by hand:"
echo "  gcloud pubsub topics publish ${TELEGRAM_TOPIC} --message='{}' --project=${PROJECT_ID}"
