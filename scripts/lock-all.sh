#!/usr/bin/env bash
# Re-resolve every Python service and regenerate the requirements.txt each one
# deploys from.
#
#   ./scripts/lock-all.sh
#
# The three services are INDEPENDENT projects, not a uv workspace: they pin
# conflicting versions of the same libraries on purpose (feed-mind holds
# google-cloud-firestore==2.19.0 while the summarizer needs ==2.28.1), and they
# deploy as three separate artifacts that never share an interpreter.
#
# requirements.txt is a generated file in all three — edit pyproject.toml and
# re-run this. Cloud Functions and the paper-prism Dockerfile install from it.
set -euo pipefail
cd "$(dirname "$0")/.."

for s in feed-mind paper-prism summarizer; do
    printf '\n\033[1m==> services/%s\033[0m\n' "$s"
    ( cd "services/$s" \
      && uv lock \
      && uv pip compile pyproject.toml -o requirements.txt )
done

echo
echo "Done. Commit the uv.lock and requirements.txt changes together."
