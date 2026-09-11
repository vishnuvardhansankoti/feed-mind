#!/usr/bin/env bash
# Build the image with Cloud Build (builds linux/amd64 in the cloud — avoids
# the Apple-Silicon arch mismatch a local `docker build` would produce, same
# reasoning as services/news-curator) and push to Artifact Registry.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

# Build context is the service root (parent of deploy/) — what actually goes
# into the image is governed by ../.gcloudignore, which already excludes
# deploy/, .venv/, __pycache__/, README.md and web-page-scraper.py from the
# gen2-function era; nothing there needed to change for Cloud Run.
echo "==> Cloud Build -> ${IMAGE}"
gcloud builds submit .. --tag "$IMAGE" --project="$PROJECT_ID"

echo "Image pushed: ${IMAGE}"
echo "Next: ./03-deploy-service.sh"
