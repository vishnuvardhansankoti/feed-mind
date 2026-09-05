#!/usr/bin/env bash
# Deploy one (or every) FeedMind Cloud Function.
#
#   ./scripts/deploy-feedmind.sh                     # all five
#   ./scripts/deploy-feedmind.sh news-ingest         # just one
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
# Schedules: all three ingests keep the 08:00 slot the single combined function
# used, so this restructure changes no behaviour on the first deploy. They are
# separate jobs now, so any of them can be moved with a one-line edit here.
# The notifier has no schedule — it wakes on the topic.
SERVICES=(
  "news-ingest|news_ingest|http|300s|0 8 * * *"
  "topstories-ingest|topstories_ingest|http|300s|0 8 * * *"
  "youtube-ingest|youtube_ingest|http|300s|0 8 * * *"
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
        trigger_args=(--trigger-topic "$TELEGRAM_TOPIC")
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

    rm -rf "$build"
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
echo "  gcloud scheduler jobs run feedmind-news-ingest-job --location=${REGION} --project=${PROJECT_ID}"
echo "Ring the notifier by hand:"
echo "  gcloud pubsub topics publish ${TELEGRAM_TOPIC} --message='{}' --project=${PROJECT_ID}"
