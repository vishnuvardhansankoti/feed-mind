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
# and the FeedMind entry points, which are a config load plus a runner call.
#
# Instead each service is probed in ITS OWN venv — the one carrying only its
# dependency extras — for every module its runtime can reach. `import main` on
# its own is not enough and never was: the heavy imports in runner.py and
# main.py are deliberately lazy, so a missing extra stays invisible until an
# article is actually summarized. That is exactly how a module-level
# `import google.generativeai` in summarization.py reached production and broke
# the first run of feedmind-ingest, which installs no gemini extra.
#
# Anything added to a lazy import path must be added here too.
probe() {  # probe <service> <python-source>
    if ( cd "services/$1" && uv run --quiet python -c "$2" >/dev/null 2>&1 ); then
        echo "  ok: $1"
    else
        echo "  FAILED: services/$1 — a runtime import is missing from its extras" >&2
        ( cd "services/$1" && uv run --quiet python -c "$2" 2>&1 | tail -3 ) >&2
        fail=1
    fi
}

printf '\n\033[1m==> FeedMind services (runtime import probe)\033[0m\n'

probe ingest '
import main
# runner._summarize / _init_summarizer
from feedmind_core.summarization import summarize_with_sumy, init_gemini
# runner.run_rss_ingest / run_youtube_ingest
from feedmind_core.ingestion import fetch_feed, fetch_youtube_feed
# main._announce
from feedmind_core import events
from feedmind_core.store import is_duplicate, save_article, save_video
'

probe telegram-notifier '
import main
from feedmind_core.store import fetch_pending_telegram, mark_telegram_sent
from feedmind_core.telegram import build_category_messages, send_message
'

probe archive '
import main
from feedmind_core import archival, bigquery
from feedmind_core.telegram import send_plain_message
'


exit $fail
