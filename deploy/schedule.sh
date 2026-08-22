#!/usr/bin/env bash
# Create (or update) the Cloud Scheduler jobs that drive the function.
#
#     ./deploy/schedule.sh
#
# Two jobs, one per source, because they want different arguments and because a
# failure in one should not stop the other from running:
#
#     feedmind-audio-rss      RSS_FEED         daily, RSS_SCHEDULE
#     feedmind-audio-papers   RESEARCH_PAPERS  daily, PAPERS_SCHEDULE
#
# Both authenticate with an OIDC token for SCHEDULER_SA, which deploy.sh gave
# run.invoker on the function. Times and cron expressions live in config.sh.

source "$(dirname "$0")/config.sh"
require_gcloud

URL="$(gcloud functions describe "$FUNCTION_NAME" \
    --gen2 --project="$PROJECT_ID" --region="$REGION" \
    --format='value(serviceConfig.uri)' 2>/dev/null)"

if [[ -z "$URL" ]]; then
    echo "Function ${FUNCTION_NAME} is not deployed in ${REGION}." >&2
    echo "Run ./deploy/deploy.sh first." >&2
    exit 1
fi

# The pipeline is slow - a whole batch, serially - and Cloud Scheduler stops
# waiting after this. The function keeps running to completion regardless; the
# deadline only decides how long the job waits before calling the attempt
# failed. Kept below TIMEOUT so a retry cannot overlap a still-running batch.
ATTEMPT_DEADLINE="${ATTEMPT_DEADLINE:-1800s}"

# ---------------------------------------------------------------------------
# `jobs create` fails on an existing job and `jobs update` fails on a missing
# one, so pick the verb by asking first. That keeps the script re-runnable.
upsert_job() {
    local name="$1" schedule="$2" body="$3" verb=create

    if gcloud scheduler jobs describe "$name" \
        --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
        verb=update
    fi

    echo "  ${verb} ${name}  (${schedule} ${SCHEDULE_TIMEZONE})"
    gcloud scheduler jobs "$verb" http "$name" \
        --project="$PROJECT_ID" \
        --location="$REGION" \
        --schedule="$schedule" \
        --time-zone="$SCHEDULE_TIMEZONE" \
        --uri="$URL" \
        --http-method=POST \
        --headers="Content-Type=application/json" \
        --message-body="$body" \
        --oidc-service-account-email="$SCHEDULER_SA" \
        --oidc-token-audience="$URL" \
        --attempt-deadline="$ATTEMPT_DEADLINE" \
        --max-retry-attempts=1 \
        --quiet >/dev/null
}

say "Scheduling against ${URL}"

upsert_job "${FUNCTION_NAME}-rss" "$RSS_SCHEDULE" \
    '{"process_doc": "RSS_FEED"}'

upsert_job "${FUNCTION_NAME}-papers" "$PAPERS_SCHEDULE" \
    '{"process_doc": "RESEARCH_PAPERS"}'

say "Scheduled"
echo "Run one now, without waiting for the cron:"
echo "  gcloud scheduler jobs run ${FUNCTION_NAME}-rss --location=${REGION}"
echo
echo "List them:"
echo "  gcloud scheduler jobs list --location=${REGION}"
echo
echo "If a job reports PERMISSION_DENIED, the scheduler account is missing"
echo "run.invoker - re-run ./deploy/deploy.sh, which grants it."
