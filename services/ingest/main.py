"""
main.py — feedmind-ingest: fetch every feed group into Firestore, then ring the
Telegram notifier's doorbell.

One function, three feed groups, one schedule (08:00 daily):

    news.yaml        the digest feeds  -> stored telegram_status=pending
    topstories.yaml  general news      -> stored telegram_status=skipped
    youtube.yaml     channel uploads   -> youtube_videos, no summarization

The groups are separate YAML files rather than one list because they behave
differently — only `news` goes to Telegram, only the RSS groups are summarized,
and only they wake the AI-summary service. Each file is validated on load by
the same loader, so a typo fails the cold start instead of looking like "no new
articles today".

**Delivery is a different function.** This stores articles and publishes to
`feedmind-telegram-ready`; feedmind-telegram-notifier formats and sends. The
message is a doorbell carrying no articles — the notifier queries Firestore for
`telegram_status == "pending"` — so a dropped message costs a delay rather than
articles, and a Telegram outage cannot cost us an ingest.

The doorbell rings **once per run, after every group**, not once per group.
Each group is run with `announce=False` and the publishing happens here.
"""

import json
import logging

import functions_framework
from feedmind_core import runner, serviceconfig

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("feedmind-ingest")

# Loaded at import so a malformed config fails the cold start loudly.
#
# Order is deliberate: YouTube first because it is the cheapest group (7 fetches,
# no summarization) and the one whose web-reader tab degrades most visibly if a
# day is missed — its "Latest" is an ingest batch, so a skipped run is a visible
# gap rather than staleness. News runs last because it is the group that absorbs
# a partial run harmlessly: anything not stored is simply not deduplicated, and
# tomorrow's run picks it up. The soft-timeout guard in the runner is what makes
# this ordering matter at all; on a normal day every group completes.
GROUPS = [
    serviceconfig.load_beside(__file__, "youtube.yaml"),
    serviceconfig.load_beside(__file__, "topstories.yaml"),
    serviceconfig.load_beside(__file__, "news.yaml"),
]


def _run(dry_run: bool = False) -> dict:
    summary = {"service": "feedmind-ingest", "groups": {}}
    telegram_pending = 0
    content_stored = 0

    for cfg in GROUPS:
        if cfg.kind == serviceconfig.KIND_YOUTUBE:
            counters = runner.run_youtube_ingest(cfg, dry_run=dry_run, announce=False)
            stored = counters["videos_stored"]
        else:
            counters = runner.run_rss_ingest(cfg, dry_run=dry_run, announce=False)
            stored = counters["articles_stored"]

        summary["groups"][cfg.service] = counters
        if cfg.deliver_telegram:
            telegram_pending += stored
        if cfg.content_ready:
            content_stored += stored

    summary["telegram_pending"] = telegram_pending
    summary["content_stored"] = content_stored

    # Published last, after every group's writes. Both consumers read Firestore,
    # so announcing earlier would race them to documents that do not exist yet.
    # Both are best-effort: the articles are already stored, and failing the run
    # to signal a Pub/Sub problem would re-fetch every feed on the retry.
    _announce(telegram_pending, content_stored, summary, dry_run=dry_run)

    logger.info(json.dumps({"message": "Ingest run complete", **summary}))
    return summary


def _announce(telegram_pending: int, content_stored: int, summary: dict, *,
              dry_run: bool) -> None:
    """
    Ring the doorbell once, for the whole run.

    Nothing is published when nothing was stored: waking the notifier to find an
    empty pending set would mean a Telegram message with no articles in it, and
    waking the summarizer buys a cold start and no work.
    """
    if telegram_pending <= 0 and content_stored <= 0:
        logger.info("Nothing stored — no downstream events published")
        return

    if dry_run:
        if telegram_pending:
            print(f"--- WOULD RING TELEGRAM DOORBELL ({telegram_pending} pending)")
        if content_stored:
            print(f"--- WOULD PUBLISH CONTENT-READY ({content_stored} stored)")
        return

    from feedmind_core import events

    if telegram_pending > 0:
        events.publish_telegram_ready("feedmind-ingest", telegram_pending)
    if content_stored > 0:
        events.publish_content_ready(content_stored, run_summary=summary)


@functions_framework.http
def ingest(request):
    """Invoked by Cloud Scheduler over authenticated HTTPS POST, daily at 08:00."""
    return (json.dumps(_run()), 200, {"Content-Type": "application/json"})


if __name__ == "__main__":
    # Local dry run: fetches and summarizes for real, writes and publishes
    # nothing.  uv run python main.py
    print(json.dumps(_run(dry_run=True), indent=2))
