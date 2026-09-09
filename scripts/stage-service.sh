#!/usr/bin/env bash
# Assemble one service's deploy directory: its own files plus feedmind_core.
#
#   scripts/stage-service.sh <service-name>      # prints the staged path
#
# Why this exists: `gcloud functions deploy --source=X` uploads X and nothing
# else. feedmind_core lives at packages/feedmind-core/, outside every service
# directory, so it would simply be absent from the deployed function. Staging
# copies it in beside main.py, where a plain `import feedmind_core` finds it.
#
# The alternative — publishing the package to Artifact Registry and pinning a
# version per service — was rejected for this project: it adds a registry, auth
# for Cloud Build, and a publish step before every deploy, in exchange for
# version skew we do not want. Copying means all five functions always run the
# same core, and a local edit deploys immediately.
#
# .build/ is a build artifact. It is gitignored and rebuilt from scratch here.
set -euo pipefail

SERVICE="${1:?usage: stage-service.sh <service-name>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/services/$SERVICE"
CORE="$ROOT/packages/feedmind-core/feedmind_core"
BUILD="$SRC/.build"

[[ -d "$SRC"  ]] || { echo "no such service: services/$SERVICE" >&2; exit 1; }
[[ -f "$SRC/main.py" ]] || { echo "services/$SERVICE has no main.py" >&2; exit 1; }
[[ -d "$CORE" ]] || { echo "core package missing: $CORE" >&2; exit 1; }

rm -rf "$BUILD"
mkdir -p "$BUILD"

# Service files: everything except the build dir itself and local-only cruft.
# requirements.txt must already be current — deploy.sh regenerates it first.
rsync -a \
    --exclude '.build/' \
    --exclude '.venv/' \
    --exclude '__pycache__/' \
    --exclude 'uv.lock' \
    --exclude 'pyproject.toml' \
    --exclude '*.pyc' \
    "$SRC"/ "$BUILD"/

# The shared package, minus its own caches.
rsync -a --exclude '__pycache__/' --exclude '*.pyc' "$CORE" "$BUILD"/

[[ -f "$BUILD/requirements.txt" ]] || {
    echo "no requirements.txt in the staged build — run scripts/lock-all.sh" >&2
    exit 1
}
# requirements.txt must not try to pip-install the path dependency; the copy
# above is how the package gets there. lock-all.sh strips it, so this is a
# guard against a hand-edited file.
if grep -qE '^(feedmind-core|\.\./|-e )' "$BUILD/requirements.txt"; then
    echo "requirements.txt references feedmind-core as a package." >&2
    echo "Regenerate it with scripts/lock-all.sh." >&2
    exit 1
fi

echo "$BUILD"
