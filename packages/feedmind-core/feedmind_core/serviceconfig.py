"""
serviceconfig.py — load a service's `feeds.yaml` into a typed config object.

Each ingest service owns one YAML file listing the URLs it fetches and what to
do with them. That file, plus a Cloud Scheduler cron, *is* the service — the
Python entry point beside it is a dozen lines that load this and call the
runner.

Why data instead of a Python module: adding a feed used to mean editing a
constant that every component imported, so a typo in one feed list could break
an unrelated function at import time. A YAML file is loaded by exactly one
service, validated on load, and changing it cannot affect anything else.

Schema (see any service's feeds.yaml for a worked example):

    service: feedmind-news-ingest   # informational; appears in logs
    kind: rss                       # rss | youtube
    summarize: sumy                 # sumy | gemini | none
    deliver_telegram: true          # mark articles PENDING and ring the doorbell
    content_ready: true             # wake feed-mind-summarizer for AI summary/audio
    feeds:
      - name: Hugging Face Papers
        url: https://huggingface.co/blog/feed.xml
        category: academic          # required for rss, ignored for youtube
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

KIND_RSS = "rss"
KIND_YOUTUBE = "youtube"
_KINDS = (KIND_RSS, KIND_YOUTUBE)

SUMMARIZE_SUMY = "sumy"
SUMMARIZE_GEMINI = "gemini"
SUMMARIZE_NONE = "none"
_SUMMARIZERS = (SUMMARIZE_SUMY, SUMMARIZE_GEMINI, SUMMARIZE_NONE)


class ConfigError(ValueError):
    """Raised on a malformed or missing service config.

    Deliberately fatal. A config typo that silently produced an empty feed list
    would look exactly like "no new articles today" in the logs, and could go
    unnoticed for weeks.
    """


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    category: str = ""


@dataclass(frozen=True)
class ServiceConfig:
    service: str
    kind: str
    feeds: tuple[Feed, ...]
    summarize: str = SUMMARIZE_SUMY
    deliver_telegram: bool = False
    content_ready: bool = False
    static_links: tuple[dict, ...] = field(default_factory=tuple)

    @property
    def categories(self) -> tuple[str, ...]:
        seen = {}
        for feed in self.feeds:
            if feed.category:
                seen[feed.category] = None
        return tuple(seen)


def load(path: str | Path) -> ServiceConfig:
    """Read and validate a service config. Raises ConfigError on anything wrong."""
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping")

    service = raw.get("service")
    if not service:
        raise ConfigError(f"{path}: 'service' is required")

    kind = raw.get("kind", KIND_RSS)
    if kind not in _KINDS:
        raise ConfigError(f"{path}: kind must be one of {_KINDS}, got {kind!r}")

    summarize = raw.get("summarize", SUMMARIZE_SUMY)
    if summarize not in _SUMMARIZERS:
        raise ConfigError(f"{path}: summarize must be one of {_SUMMARIZERS}, got {summarize!r}")

    raw_feeds = raw.get("feeds") or []
    if not isinstance(raw_feeds, list) or not raw_feeds:
        raise ConfigError(f"{path}: 'feeds' must be a non-empty list")

    feeds = []
    for index, entry in enumerate(raw_feeds):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: feeds[{index}] must be a mapping")
        name, url = entry.get("name"), entry.get("url")
        if not name or not url:
            raise ConfigError(f"{path}: feeds[{index}] needs both 'name' and 'url'")
        category = entry.get("category", "")
        # An RSS article with no category cannot be grouped into a digest
        # section, so it would silently vanish from the Telegram message.
        if kind == KIND_RSS and not category:
            raise ConfigError(f"{path}: feeds[{index}] ({name}) needs a 'category'")
        feeds.append(Feed(name=name, url=url, category=category))

    config = ServiceConfig(
        service=service,
        kind=kind,
        feeds=tuple(feeds),
        summarize=summarize,
        deliver_telegram=bool(raw.get("deliver_telegram", False)),
        content_ready=bool(raw.get("content_ready", False)),
        static_links=tuple(raw.get("static_links") or ()),
    )
    logger.info(
        "Loaded %s: kind=%s feeds=%d summarize=%s telegram=%s",
        config.service,
        config.kind,
        len(config.feeds),
        config.summarize,
        config.deliver_telegram,
    )
    return config


def load_beside(module_file: str, name: str = "feeds.yaml") -> ServiceConfig:
    """
    Load the config sitting next to a service's `main.py`.

    Resolving against `__file__` rather than the process cwd is what makes the
    same call work locally and in a deployed function, where the working
    directory is not the source directory.
    """
    return load(Path(module_file).resolve().parent / name)
