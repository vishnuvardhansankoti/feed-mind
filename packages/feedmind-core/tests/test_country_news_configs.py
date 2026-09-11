"""Validate services/india-news-ingest's and services/us-news-ingest's feeds.yaml.

Kept separate from test_service_configs.py rather than folded into its
FEED_CONFIGS glob: that module's KNOWN_CATEGORIES and telegram-header-metadata
checks are specific to the original ingest family's Telegram digest / web
reader tabs, and these two services' categories are neither — their articles
never reach Telegram, and their real categorization happens later, in
services/news-curator's coarse_category (see
docs/feed-mind/news-curator-design.md §4.2), not in feed_category here.

One file for both country services rather than two near-identical ones: the
per-service checks are structurally identical (never Telegram, never
content_ready, summarize: none, http urls) — only the expected outlet names
differ, and that lives in ELIGIBLE_BUSINESS_OUTLETS below.
"""

from pathlib import Path

import pytest
from feedmind_core import serviceconfig

SERVICES_DIR = Path(__file__).resolve().parents[3] / "services"

SERVICE_DIRS = {
    "india-news-ingest": SERVICES_DIR / "india-news-ingest",
    "us-news-ingest": SERVICES_DIR / "us-news-ingest",
}

# news_curator.anchors.BUSINESS_ELIGIBLE_SOURCES matches feed_source (==
# `name:` in business.yaml) byte-for-byte — see that module's docstring and
# the root CLAUDE.md contracts table.
ELIGIBLE_BUSINESS_OUTLETS = {
    "india-news-ingest": {"Business Standard", "Economic Times", "Hindu BusinessLine"},
    "us-news-ingest": {"CNBC", "MarketWatch", "Fortune"},
}

FEED_CONFIGS = sorted(
    (path, service)
    for service, service_dir in SERVICE_DIRS.items()
    for path in service_dir.glob("*.yaml")
)


def test_the_configs_were_actually_found():
    """Guard against the glob silently matching nothing after a move."""
    assert len(FEED_CONFIGS) == 4, (
        f"expected general.yaml + business.yaml under each of {sorted(SERVICE_DIRS)}"
    )


@pytest.mark.parametrize("path,service", FEED_CONFIGS, ids=lambda x: getattr(x, "stem", x))
def test_config_loads_and_validates(path, service):
    cfg = serviceconfig.load(path)
    assert cfg.service
    assert cfg.feeds


@pytest.mark.parametrize("path,service", FEED_CONFIGS, ids=lambda x: getattr(x, "stem", x))
def test_feed_urls_are_http(path, service):
    for feed in serviceconfig.load(path).feeds:
        assert feed.url.startswith("http"), f"{feed.name}: {feed.url}"


@pytest.mark.parametrize("path,service", FEED_CONFIGS, ids=lambda x: getattr(x, "stem", x))
def test_never_delivers_to_telegram_or_content_ready(path, service):
    """These feeds never go to Telegram, and never wake services/summarizer
    directly — services/news-curator selects the top few/day that do, later.
    """
    cfg = serviceconfig.load(path)
    assert cfg.deliver_telegram is False
    assert cfg.content_ready is False


@pytest.mark.parametrize("path,service", FEED_CONFIGS, ids=lambda x: getattr(x, "stem", x))
def test_summarizes_none(path, service):
    """Curation embeds title+description straight off the feed (design doc
    §3.1) — there is nothing for an ingest-time summarizer to do.
    """
    cfg = serviceconfig.load(path)
    assert cfg.summarize == serviceconfig.SUMMARIZE_NONE


@pytest.mark.parametrize("service", sorted(SERVICE_DIRS))
def test_business_yaml_uses_the_curator_eligible_outlet_names(service):
    cfg = serviceconfig.load(SERVICE_DIRS[service] / "business.yaml")
    names = {feed.name for feed in cfg.feeds}
    assert names == ELIGIBLE_BUSINESS_OUTLETS[service]
