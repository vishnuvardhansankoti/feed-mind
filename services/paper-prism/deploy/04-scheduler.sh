#!/usr/bin/env bash
# Wire Cloud Scheduler to trigger the Cloud Run Job weekly, via a dedicated
# invoker service account scoped with roles/run.invoker on the job only.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

echo "==> Scheduler SA: run.invoker on ${JOB_NAME} (least privilege)"
gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
  --member="serviceAccount:${SCHED_SA}" \
  --role="roles/run.invoker" \
  --region="$REGION" --project="$PROJECT_ID" --quiet

RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

echo "==> Cloud Scheduler job ${SCHEDULER_NAME} (${SCHEDULE} ${TIMEZONE})"
if gcloud scheduler jobs describe "$SCHEDULER_NAME" \
     --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  ACTION=update
else
  ACTION=create
fi

gcloud scheduler jobs "$ACTION" http "$SCHEDULER_NAME" \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --schedule="$SCHEDULE" \
  --time-zone="$TIMEZONE" \
  --uri="$RUN_URI" \
  --http-method=POST \
  --oauth-service-account-email="$SCHED_SA"

echo "Scheduler ${ACTION}d. Force a run now with:"
echo "  gcloud scheduler jobs run ${SCHEDULER_NAME} --location ${REGION} --project ${PROJECT_ID}"
