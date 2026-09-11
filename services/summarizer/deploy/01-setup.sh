#!/usr/bin/env bash
# One-time project setup for the Cloud Run deploy path: APIs, Artifact
# Registry, service accounts, IAM. Idempotent — safe to re-run.
#
# What this does NOT do: create feedmind-content-ready (the gen2 function's
# setup.sh already did, and the topic is owned by whoever reads it — see the
# root CLAUDE.md), the Firestore database, the storage bucket, or the LLM API
# key secret. It checks for them and tells you what is missing.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

echo "==> Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  texttospeech.googleapis.com \
  cloudbuild.googleapis.com \
  --project="$PROJECT_ID"

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION" --project="$PROJECT_ID" \
  2>/dev/null || echo "    repo already exists — skipping"

echo "==> Service accounts"
gcloud iam service-accounts create "$SERVICE_SA_NAME" \
  --display-name="FeedMind audio runtime (Cloud Run)" --project="$PROJECT_ID" \
  2>/dev/null || echo "    ${SERVICE_SA_NAME} already exists — skipping (shared with the gen2 function)"
gcloud iam service-accounts create "$PUSH_SA_NAME" \
  --display-name="FeedMind audio Pub/Sub push invoker" --project="$PROJECT_ID" \
  2>/dev/null || echo "    ${PUSH_SA_NAME} already exists — skipping (shared with the gen2 function's trigger SA)"

echo "==> Letting Pub/Sub mint OIDC tokens as ${PUSH_SA_NAME}"
# A push subscription's --push-auth-service-account only works if Pub/Sub's own
# service agent can impersonate that SA to mint the OIDC token it attaches to
# each push request. Without this, Cloud Run rejects every push with 403 "The
# request was not authenticated" — not a bad-token error, a NO-token error,
# because Pub/Sub silently can't mint one in the first place. `gcloud pubsub
# subscriptions create --push-auth-service-account` does NOT reliably set this
# up on its own (confirmed the hard way: this exact gap left news-curator's own
# push subscription 403ing on 100% of real deliveries, silently, since it was
# first deployed — found only by checking Cloud Run request logs directly).
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
gcloud iam service-accounts add-iam-policy-binding "$PUSH_SA" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="$PROJECT_ID" --quiet >/dev/null

echo "==> Service SA: Firestore read/write"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SERVICE_SA}" \
  --role="roles/datastore.user" --condition=None --quiet >/dev/null

echo "==> Service SA: audio bucket"
if gcloud storage buckets describe "gs://${BUCKET_NAME}" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets add-iam-policy-binding "gs://${BUCKET_NAME}" \
    --member="serviceAccount:${SERVICE_SA}" \
    --role="roles/storage.objectAdmin" --quiet >/dev/null
  echo "    granted objectAdmin on gs://${BUCKET_NAME}"
else
  echo "    WARNING: gs://${BUCKET_NAME} does not exist — see the gen2 function's setup.sh" >&2
fi

echo "==> Service SA: secrets"
if gcloud secrets describe "$LLM_API_KEY_SECRET" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding "$LLM_API_KEY_SECRET" \
    --project="$PROJECT_ID" --member="serviceAccount:${SERVICE_SA}" \
    --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
  echo "    granted secretAccessor on ${LLM_API_KEY_SECRET}"
else
  echo "    WARNING: secret ${LLM_API_KEY_SECRET} does not exist — see the gen2 function's setup.sh" >&2
fi
if gcloud secrets describe "$VAPID_PRIVATE_KEY_SECRET" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets add-iam-policy-binding "$VAPID_PRIVATE_KEY_SECRET" \
    --project="$PROJECT_ID" --member="serviceAccount:${SERVICE_SA}" \
    --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
  echo "    granted secretAccessor on ${VAPID_PRIVATE_KEY_SECRET}"
else
  echo "    note: ${VAPID_PRIVATE_KEY_SECRET} does not exist — push notifications stay off"
fi

echo "==> Checking ${TOPIC_NAME}"
if gcloud pubsub topics describe "$TOPIC_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "    topic exists"
  echo "==> Publisher grants (own republish + the three producers)"
  for publisher in $PUBLISHER_SERVICE_ACCOUNTS $SERVICE_SA; do
    if gcloud iam service-accounts describe "$publisher" --project="$PROJECT_ID" >/dev/null 2>&1; then
      gcloud pubsub topics add-iam-policy-binding "$TOPIC_NAME" \
        --project="$PROJECT_ID" --member="serviceAccount:${publisher}" \
        --role="roles/pubsub.publisher" --quiet >/dev/null
      echo "    granted publisher to ${publisher}"
    else
      echo "    skipping ${publisher} — no such service account" >&2
    fi
  done
else
  echo "    WARNING: topic ${TOPIC_NAME} does not exist yet." >&2
  echo "    Run the gen2 function's ../deploy/setup.sh first — it owns this topic." >&2
fi

echo "Setup complete. Next: ./02-build-push.sh"
