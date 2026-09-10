#!/usr/bin/env bash
# One-time project setup: APIs, Artifact Registry, service accounts, IAM.
# Idempotent — safe to re-run.
#
# What this does NOT do: create the feedmind-news-ingested topic (that is
# services/india-news-ingest's / scripts/setup-feedmind-infra.sh's job — the
# topic is owned by the publisher, see the root CLAUDE.md) or the Firestore
# database (FeedMind proper owns it). It checks for the topic and tells you
# what is missing.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

echo "==> Enabling APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  cloudbuild.googleapis.com \
  --project "$PROJECT_ID"

echo "==> Artifact Registry repo"
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker --location="$REGION" --project "$PROJECT_ID" \
  2>/dev/null || echo "    repo already exists — skipping"

echo "==> Service accounts"
gcloud iam service-accounts create "$SERVICE_SA_NAME" \
  --display-name="news-curator runtime" --project "$PROJECT_ID" \
  2>/dev/null || echo "    service SA exists — skipping"
gcloud iam service-accounts create "$PUSH_SA_NAME" \
  --display-name="news-curator Pub/Sub push invoker" --project "$PROJECT_ID" \
  2>/dev/null || echo "    push SA exists — skipping"

echo "==> Service SA: Firestore read/write"
# datastore.user is the narrowest predefined role that covers both reading
# processed_articles and writing stories; there is no per-collection role.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SERVICE_SA}" \
  --role="roles/datastore.user" --condition=None --quiet

echo "==> Checking ${NEWS_INGESTED_TOPIC}"
if gcloud pubsub topics describe "$NEWS_INGESTED_TOPIC" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "    topic exists"
else
  echo "    WARNING: topic ${NEWS_INGESTED_TOPIC} does not exist yet." >&2
  echo "    Run ../../../scripts/setup-feedmind-infra.sh (creates it on the" >&2
  echo "    publisher's side) before ./04-push-subscription.sh." >&2
fi

echo "Setup complete. Next: ./02-build-push.sh"
