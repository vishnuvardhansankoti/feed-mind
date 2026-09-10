"""Validate services/india-news-ingest's feeds.yaml files.

Kept separate from test_service_configs.py rather than folded into its
FEED_CONFIGS glob: that module's KNOWN_CATEGORIES and telegram-header-metadata
checks are specific to the original ingest family's Telegram digest / web
reader tabs, and india-news-ingest's categories are neither — these articles
never reach Telegram, and their real categorization happens later, in
services/news-curator's coarse_category (see
docs/feed-mind/news-curator-design.md §4.2), not in feed_category here.
"""

from pathlib import Path

import pytest
from feedmind_core import serviceconfig

SERVICE_DIR = Path(__file__).resolve().parents[3] / "services" / "india-news-ingest"
FEED_CONFIGS = sorted(SERVICE_DIR.glob("*.yaml"))


def test_the_configs_were_actually_found():
    """Guard against the glob silently matching nothing after a move."""
    assert len(FEED_CONFIGS) == 2, f"expected general.yaml and business.yaml under {SERVICE_DIR}"


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.stem)
def test_config_loads_and_validates(path):
    cfg = serviceconfig.load(path)
    assert cfg.service
    assert cfg.feeds


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.stem)
def test_feed_urls_are_http(path):
    for feed in serviceconfig.load(path).feeds:
        assert feed.url.startswith("http"), f"{feed.name}: {feed.url}"


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.stem)
def test_never_delivers_to_telegram_or_content_ready(path):
    """These feeds never go to Telegram, and never wake services/summarizer
    directly — services/news-curator selects the ~25/day that do, later.
    """
    cfg = serviceconfig.load(path)
    assert cfg.deliver_telegram is False
    assert cfg.content_ready is False


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.stem)
def test_summarizes_none(path):
    """Curation embeds title+description straight off the feed (design doc
    §3.1) — there is nothing for an ingest-time summarizer to do.
    """
    cfg = serviceconfig.load(path)
    assert cfg.summarize == serviceconfig.SUMMARIZE_NONE


def test_business_yaml_uses_the_curator_eligible_outlet_names():
    """news_curator.anchors.BUSINESS_ELIGIBLE_SOURCES matches feed_source
    (== `name:` here) byte-for-byte — see that module's docstring and this
    repo's root CLAUDE.md contracts table.
    """
    cfg = serviceconfig.load(SERVICE_DIR / "business.yaml")
    names = {feed.name for feed in cfg.feeds}
    assert names == {"Business Standard", "Economic Times", "Hindu BusinessLine"}
