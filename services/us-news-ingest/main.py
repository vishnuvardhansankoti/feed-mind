"""
main.py — us-news-ingest: fetch five US publications' front pages into
Firestore, then ring the news curator's doorbell.

One function, two feed groups, one schedule (04:00 America/Chicago daily —
overnight US news, well clear of both the 08:00 tech-blogs ingest and the
17:30 India-news ingest):

    general.yaml   NPR News + CBS News              -> ~40 articles
    business.yaml  CNBC + MarketWatch + Fortune      -> ~50 articles

Every article is stored `telegram_status=skipped` (these never go to Telegram)
and `curation_status=pending`, `country=US`. Nothing here classifies, dedupes
across outlets, or pays for an LLM call — that is services/news-curator's job,
the same pipeline india-news-ingest feeds, now scoped per country so a US
"business" cluster and an India "business" cluster never merge. See
services/news-curator/CLAUDE.md's country-isolation section and
docs/feed-mind/us-news-design.md.

Modeled on services/india-news-ingest/main.py, which is itself modeled on
services/ingest/main.py: same soft-timeout guard, same "announce once per run
after every group" doorbell pattern via feedmind_core.runner and
feedmind_core.events, so the three ingest services do not drift on the parts
they share.

A Google News RSS aggregator (news.google.com/rss, one source, eight topics)
was evaluated and rejected before this design: its item links do not resolve
to the real article over plain HTTP (client-rendered redirect, no path for
this repo's scraper), and its <description> is a pre-bundled HTML list of
~3 sibling headlines rather than usable single-article text. Five real
publisher feeds, same as India, sidesteps both problems.
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
logger = logging.getLogger("us-news-ingest")

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
# `country` is what lets one shared news-curator cluster India and US articles
# separately instead of merging a US business story into an India one just
# because both landed in the "business" coarse category the same day.
_EXTRA_FIELDS = {"curation_status": config.CURATION_PENDING, "country": "US"}


def _run(dry_run: bool = False) -> dict:
    summary = {"service": "us-news-ingest", "groups": {}}
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

    logger.info(json.dumps({"message": "us-news-ingest run complete", **summary}))
    return summary


def _announce(articles_stored: int, summary: dict, *, dry_run: bool) -> None:
    if articles_stored <= 0:
        logger.info("Nothing stored — no downstream event published")
        return

    if dry_run:
        print(f"--- WOULD RING NEWS-CURATOR DOORBELL ({articles_stored} stored)")
        return

    from feedmind_core import events

    # Same topic india-news-ingest rings — see feedmind_core.settings.NEWS_INGESTED_TOPIC.
    # news-curator processes whatever curation_status=="pending" backlog exists
    # regardless of which ingest service rang the doorbell, so one shared topic
    # is enough: no new topic, no new IAM grant.
    events.publish_news_ingested("us-news-ingest", articles_stored)


@functions_framework.http
def ingest(request):
    """Invoked by Cloud Scheduler over authenticated HTTPS POST, daily at 04:00 CT."""
    return (json.dumps(_run()), 200, {"Content-Type": "application/json"})


if __name__ == "__main__":
    # Local dry run: fetches for real, writes and publishes nothing.
    #   uv run python main.py
    print(json.dumps(_run(dry_run=True), indent=2))
