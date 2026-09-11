#!/usr/bin/env bash
# Shared configuration — sourced by the other deploy scripts.
# Override any value by exporting it before running (e.g. `PROJECT_ID=foo ./01-setup.sh`).
set -euo pipefail

export PROJECT_ID="${PROJECT_ID:?set PROJECT_ID (feed-mind)}"
export REGION="${REGION:-us-central1}"

# The one Firestore database every FeedMind component shares — see the root
# CLAUDE.md's "database id must match in four places". NOT a separate database
# like paper-prism's: this service reads and writes processed_articles, which
# lives here.
export FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-feed-mind-db}"

# Artifact Registry + image
export REPO="${REPO:-news-curator}"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/news-curator:latest"

# Cloud Run service (not a Job — design doc §3.3: Eventarc cannot target a Job
# directly, and this runs on an event, not a clock).
export SERVICE_NAME="${SERVICE_NAME:-news-curator}"
export SERVICE_SA_NAME="${SERVICE_SA_NAME:-news-curator}"
export SERVICE_SA="${SERVICE_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# The identity Pub/Sub uses to push to the service, separate from the runtime
# SA for the same reason feedmind-audio's TRIGGER_SA is separate — "may
# invoke" and "may write" are different grants.
export PUSH_SA_NAME="${PUSH_SA_NAME:-news-curator-invoker}"
export PUSH_SA="${PUSH_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# The topic this service subscribes to. Created by
# scripts/setup-feedmind-infra.sh on the publisher's side (services/india-news-
# ingest) — see that script and feedmind_core/settings.py::NEWS_INGESTED_TOPIC.
export NEWS_INGESTED_TOPIC="${NEWS_INGESTED_TOPIC:-feedmind-news-ingested}"
export PUSH_SUBSCRIPTION="${PUSH_SUBSCRIPTION:-news-curator-push}"

echo "config: project=${PROJECT_ID} region=${REGION} service=${SERVICE_NAME}"
