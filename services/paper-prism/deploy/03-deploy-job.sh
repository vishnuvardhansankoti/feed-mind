#!/usr/bin/env bash
# Create/update the Cloud Run Job (scale-to-zero, cron-triggered later).
# `run jobs deploy` is create-or-update, so this is idempotent.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

if [[ ! -f env.yaml ]]; then
  echo "ERROR: env.yaml not found. Copy env.yaml.example -> env.yaml and edit the profiles." >&2
  exit 1
fi

echo "==> Deploying Cloud Run Job ${JOB_NAME}"
gcloud run jobs deploy "$JOB_NAME" \
  --image="$IMAGE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --service-account="$JOB_SA" \
  --env-vars-file=env.yaml \
  --set-secrets="GEMINI_API_KEY=${SECRET_NAME}:latest" \
  --memory=2Gi \
  --cpu=2 \
  --max-retries=1 \
  --task-timeout=900s

echo "Job deployed. Run once manually with:"
echo "  gcloud run jobs execute ${JOB_NAME} --region ${REGION} --project ${PROJECT_ID} --wait"
