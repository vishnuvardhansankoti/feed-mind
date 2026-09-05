#!/usr/bin/env bash
# Run every test suite in the monorepo. Each component owns its own runner, so
# this is a loop over directories rather than one root-level pytest invocation.
#
#   ./scripts/test-all.sh
set -euo pipefail
cd "$(dirname "$0")/.."

fail=0
run() {  # run <label> <dir> <command...>
    printf '\n\033[1m==> %s\033[0m\n' "$1"
    local label="$1" dir="$2"; shift 2
    ( cd "$dir" && "$@" ) || { echo "  FAILED: $label" >&2; fail=1; }
}

# The FeedMind services are thin wrappers around feedmind-core; the suite that
# matters lives with the package, and it validates every service's feeds.yaml
# directly (tests/test_service_configs.py) rather than mocking one up.
run "packages/feedmind-core (pytest)" packages/feedmind-core uv run --quiet pytest -q
run "services/paper-prism (pytest)"   services/paper-prism   uv run --quiet --extra dev pytest -q
run "apps/web (vitest)"               apps/web               npm test

# No test suite: services/summarizer (exercised by ./deploy/publish.sh --dry-run)
# and the five FeedMind service entry points, which are a config load plus one
# runner call. Their import is smoke-tested here instead — that is what catches
# a service whose dependency extras are missing something it uses.
printf '\n\033[1m==> FeedMind service entry points (import smoke test)\033[0m\n'
for s in ingest telegram-notifier archive; do
    if ( cd "services/$s" && uv run --quiet python -c "import main" >/dev/null 2>&1 ); then
        echo "  ok: $s"
    else
        echo "  FAILED: services/$s does not import" >&2
        fail=1
    fi
done

exit $fail
