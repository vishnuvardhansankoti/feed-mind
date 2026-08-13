#!/usr/bin/env bash
# Build the image with Cloud Build (builds linux/amd64 in the cloud — avoids the
# Apple-Silicon arch mismatch a local `docker build` would produce) and push to
# Artifact Registry.
set -euo pipefail
cd "$(dirname "$0")"
source ./00-config.sh

# Build context is the pipeline/ directory (parent of deploy/).
echo "==> Cloud Build -> ${IMAGE}"
gcloud builds submit .. --tag "$IMAGE" --project "$PROJECT_ID"

echo "Image pushed: ${IMAGE}"
