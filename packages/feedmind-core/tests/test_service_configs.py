"""Validate every real service feeds.yaml in the repo.

These replace the old tests that asserted on `config.RSS_FEEDS`. The feed lists
moved into per-service YAML, and the contracts they encode did not — so the
checks follow the data rather than being dropped.

Walking the actual services (instead of a fixture) is the point: a typo in a
committed feeds.yaml fails here, not at 8am in a Cloud Function cold start.
"""

from pathlib import Path

import pytest
import yaml
from feedmind_core import serviceconfig
from feedmind_core.telegram import _CATEGORY_META

# Feed categories the reader knows how to render. Duplicated by
# apps/web/src/lib/constants.js::NEWS_CATEGORIES, which keys its tabs off the
# same strings — including the inconsistent separators (open-source hyphenates,
# top_stories underscores), which must be preserved exactly on both sides. The
# reader matches with ===, so a "tidied" separator empties a tab silently.
KNOWN_CATEGORIES = {"academic", "industry", "cloud", "open-source", "top_stories"}

SERVICES_DIR = Path(__file__).resolve().parents[3] / "services"
FEED_CONFIGS = sorted(SERVICES_DIR.glob("*/feeds.yaml"))
NOTIFIER_CONFIG = SERVICES_DIR / "telegram-notifier" / "notifier.yaml"


def test_the_services_were_actually_found():
    """Guard against the glob silently matching nothing after a move.

    Without this, every parametrized test below would vacuously pass and the
    suite would report green while checking no configuration at all.
    """
    assert len(FEED_CONFIGS) >= 3, f"expected the ingest services under {SERVICES_DIR}"


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.parent.name)
def test_config_loads_and_validates(path):
    cfg = serviceconfig.load(path)
    assert cfg.service
    assert cfg.feeds


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.parent.name)
def test_feed_urls_are_http(path):
    for feed in serviceconfig.load(path).feeds:
        assert feed.url.startswith("http"), f"{feed.name}: {feed.url}"


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.parent.name)
def test_categories_are_known(path):
    cfg = serviceconfig.load(path)
    unknown = set(cfg.categories) - KNOWN_CATEGORIES
    assert not unknown, f"{cfg.service} uses categories the web reader has no tab for: {unknown}"


@pytest.mark.parametrize("path", FEED_CONFIGS, ids=lambda p: p.parent.name)
def test_every_category_has_telegram_header_metadata(path):
    """Without an entry the digest header falls back to a generic badge.

    Legible, but not the wording anyone intended — and easy to miss, since it
    renders fine.
    """
    cfg = serviceconfig.load(path)
    missing = set(cfg.categories) - set(_CATEGORY_META)
    assert not missing, f"{cfg.service}: no header metadata for {missing}"


def test_youtube_service_uses_youtube_feed_urls():
    cfg = serviceconfig.load(SERVICES_DIR / "youtube-ingest" / "feeds.yaml")
    assert cfg.kind == serviceconfig.KIND_YOUTUBE
    for feed in cfg.feeds:
        assert feed.url.startswith("https://www.youtube.com/feeds/videos.xml")


def test_exactly_one_service_delivers_to_telegram():
    """The doorbell has one ringer.

    More than one ingest publishing to feedmind-telegram-ready is not broken —
    the notifier queries Firestore, so it would simply run twice — but it would
    mean two digests a day, which is a decision to make on purpose rather than
    discover.
    """
    delivering = [
        serviceconfig.load(p).service
        for p in FEED_CONFIGS
        if serviceconfig.load(p).deliver_telegram
    ]
    assert delivering == ["feedmind-news-ingest"], delivering


def test_youtube_does_not_wake_the_summarizer():
    """services/summarizer has an RSS_FEED pipeline and a RESEARCH_PAPERS one.

    Neither reads youtube_videos, so a content_ready event from here would buy a
    cold start and nothing else.
    """
    cfg = serviceconfig.load(SERVICES_DIR / "youtube-ingest" / "feeds.yaml")
    assert cfg.content_ready is False


def test_notifier_static_links_use_known_categories():
    raw = yaml.safe_load(NOTIFIER_CONFIG.read_text())
    for link in raw.get("static_links", []):
        assert link["category"] in KNOWN_CATEGORIES
        assert link["url"].startswith("http")
        assert link["category"] in _CATEGORY_META


def test_notifier_category_order_is_renderable():
    raw = yaml.safe_load(NOTIFIER_CONFIG.read_text())
    unknown = set(raw.get("category_order", [])) - KNOWN_CATEGORIES
    assert not unknown, f"category_order names categories that cannot appear: {unknown}"
