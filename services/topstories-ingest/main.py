"""
main.py — topstories_ingest Cloud Function entry point.

Fetches general news for the web reader only. Articles are stored with
telegram_status=skipped, so the notifier never picks them up.

Deliberately thin. All of the pipeline lives in feedmind_core.runner, shared
with every other ingest service; what makes this service distinct is feeds.yaml
beside this file and the Cloud Scheduler cron that calls it. Adding a fourth
ingest service is a directory, not a code change.
"""

import json
import logging

import functions_framework
from feedmind_core import runner, serviceconfig

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

# Loaded at import so a malformed feeds.yaml fails the cold start loudly,
# rather than looking like "no new articles today" in the run summary.
CONFIG = serviceconfig.load_beside(__file__)


@functions_framework.http
def topstories_ingest(request):
    """Invoked by Cloud Scheduler over authenticated HTTPS POST."""
    summary = runner.run_rss_ingest(CONFIG)
    return (json.dumps(summary), 200, {"Content-Type": "application/json"})


if __name__ == "__main__":
    # Local dry run: fetches and summarizes for real, writes and publishes
    # nothing.  uv run python main.py
    print(json.dumps(runner.run_rss_ingest(CONFIG, dry_run=True), indent=2))
