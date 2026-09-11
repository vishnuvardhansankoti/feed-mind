"""
main.py — india-news-ingest: fetch five Indian publications' front pages into
Firestore, then ring the news curator's doorbell.

One function, two feed groups, one schedule (17:30 America/Chicago daily —
already the next day in India, which is what services/news-curator's IST
`run_date` keys on):

    general.yaml   TOI + The Hindu                        -> ~107 articles
    business.yaml  Business Standard + ET + Hindu BusinessLine -> ~116 articles

Every article is stored `telegram_status=skipped` (these never go to Telegram)
and `curation_status=pending`. Nothing here classifies, dedupes across outlets,
or pays for an LLM call — that is services/news-curator's job, deliberately run
*before* summarization so only ~25 of these ~223 articles ever reach
services/summarizer. See docs/feed-mind/news-curator-design.md §3.1.

Modeled on services/ingest/main.py: same soft-timeout guard, same "announce
once per run after every group" doorbell pattern via feedmind_core.runner and
feedmind_core.events, so the two ingest services do not drift on the parts
they share.
"""

import json
import logging

import functions_framework
from feedmind_core import runner, serviceconfig
from feedmind_core import settings as config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
# See services/ingest/main.py for why this line, not just basicConfig, is what
# makes logger.info() reach Cloud Logging under the deployed gunicorn stack.
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("india-news-ingest")

# Loaded at import so a malformed config fails the cold start loudly.
GROUPS = [
    serviceconfig.load_beside(__file__, "general.yaml"),
    serviceconfig.load_beside(__file__, "business.yaml"),
]

# Written onto every stored document via runner.run_rss_ingest's extra_fields,
# so services/news-curator can find its own backlog with a single-field
# equality filter — the same shape as telegram_status. See
# feedmind_core.settings.CURATION_PENDING.
#
# `country` lets one news-curator cluster India and US articles separately —
# see services/news-curator/CLAUDE.md's country-isolation section. Docs
# written before this field existed have no `country` at all; news-curator
# treats that absence as "IN", since India was the only country before this.
_EXTRA_FIELDS = {"curation_status": config.CURATION_PENDING, "country": "IN"}


def _run(dry_run: bool = False) -> dict:
    summary = {"service": "india-news-ingest", "groups": {}}
    articles_stored = 0

    for cfg in GROUPS:
        counters = runner.run_rss_ingest(
            cfg, dry_run=dry_run, announce=False, extra_fields=_EXTRA_FIELDS
        )
        summary["groups"][cfg.service] = counters
        articles_stored += counters["articles_stored"]

    summary["articles_stored"] = articles_stored

    # Published last, after every group's writes — the curator reads Firestore,
    # so announcing earlier would race it to documents that do not exist yet.
    # Best-effort like every other doorbell in this repo: the articles are
    # already stored, and failing the run to signal a Pub/Sub problem would
    # re-fetch every feed on the retry.
    _announce(articles_stored, summary, dry_run=dry_run)

    logger.info(json.dumps({"message": "india-news-ingest run complete", **summary}))
    return summary


def _announce(articles_stored: int, summary: dict, *, dry_run: bool) -> None:
    if articles_stored <= 0:
        logger.info("Nothing stored — no downstream event published")
        return

    if dry_run:
        print(f"--- WOULD RING NEWS-CURATOR DOORBELL ({articles_stored} stored)")
        return

    from feedmind_core import events

    events.publish_news_ingested("india-news-ingest", articles_stored)


@functions_framework.http
def ingest(request):
    """Invoked by Cloud Scheduler over authenticated HTTPS POST, daily at 17:30 CT."""
    return (json.dumps(_run()), 200, {"Content-Type": "application/json"})


if __name__ == "__main__":
    # Local dry run: fetches for real, writes and publishes nothing.
    #   uv run python main.py
    print(json.dumps(_run(dry_run=True), indent=2))
