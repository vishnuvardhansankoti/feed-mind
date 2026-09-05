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

run "services/feed-mind (pytest)"   services/feed-mind   uv run --extra dev pytest -q
run "services/paper-prism (pytest)" services/paper-prism uv run --extra dev pytest -q
run "apps/web (vitest)"             apps/web             npm test

# services/summarizer has no test suite. Its entry points are exercised by hand
# with `./deploy/publish.sh RSS_FEED --limit 1 --force --dry-run`.
printf '\n\033[1m==> services/summarizer: no test suite (see README)\033[0m\n'

exit $fail
