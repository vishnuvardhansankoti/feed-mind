#!/usr/bin/env bash
# Re-resolve every Python project and regenerate the requirements.txt each
# deployed artifact installs from.
#
#   ./scripts/lock-all.sh
#
# The FeedMind services are independent uv projects that share one local path
# dependency, packages/feedmind-core. paper-prism and the summarizer are
# standalone and share nothing — they pin conflicting library versions on
# purpose and deploy as separate artifacts.
#
# requirements.txt is GENERATED everywhere. Edit pyproject.toml and re-run this.
set -euo pipefail
cd "$(dirname "$0")/.."

# --- The shared core -------------------------------------------------------
# Locked first: every FeedMind service resolves against it.
printf '\n\033[1m==> packages/feedmind-core\033[0m\n'
( cd packages/feedmind-core && uv lock )

# --- FeedMind services -----------------------------------------------------
# `uv export`, not `uv pip compile`: only export honours [tool.uv.sources], so
# only it can resolve the local path dependency and pull in the right extras.
#
# --no-emit-package feedmind-core drops the path line from the output. The
# package is not pip-installed in the deployed function at all — the deploy
# staging step copies the source in beside main.py — and a `file:///Users/...`
# line in requirements.txt would fail the Cloud Build every time.
for s in ingest telegram-notifier archive; do
    printf '\n\033[1m==> services/%s\033[0m\n' "$s"
    ( cd "services/$s" \
      && uv lock \
      && uv export --format requirements-txt \
                   --no-hashes --no-annotate --no-emit-project \
                   --no-emit-package feedmind-core \
                   -o requirements.txt )
done

# --- Standalone services ---------------------------------------------------
for s in paper-prism summarizer; do
    printf '\n\033[1m==> services/%s\033[0m\n' "$s"
    ( cd "services/$s" \
      && uv lock \
      && uv pip compile pyproject.toml -o requirements.txt )
done

echo
echo "Done. Commit the uv.lock and requirements.txt changes together."
