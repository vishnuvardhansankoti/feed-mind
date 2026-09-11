"""Domain model — mirrors the Firestore schema in the design doc (§5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

# Country codes this service knows about. Not an enum: article/story docs
# carry these as plain strings (Firestore has no enum type), and a country
# this dict doesn't recognize falls back to India in run_date_for below —
# see DEFAULT_COUNTRY.
DEFAULT_COUNTRY = "IN"

# India has no DST, so a fixed UTC+5:30 offset is correct and cheap. The US
# does observe DST, so it needs a real zoneinfo entry rather than a fixed
# offset — a fixed -6:00 would be an hour wrong for half the year.
#
# Both ingest services already run in their target country's local morning-or-
# evening slot (17:30 America/Chicago for India, 04:00 America/Chicago for
# US), so in both cases "today in the publisher's zone" at curation time is
# unambiguous — see design doc §5.2 for why the publisher's day, not UTC or
# the curator's own clock, is the only run_date that means anything.
_COUNTRY_TZ = {
    "IN": timedelta(hours=5, minutes=30),
    "US": ZoneInfo("America/Chicago"),
}


def run_date_for(country: str, *, now: datetime | None = None) -> str:
    """Today's calendar date in `country`'s local time, as YYYY-MM-DD.

    An unrecognized country falls back to DEFAULT_COUNTRY rather than raising
    — a typo'd or future country code should degrade to "today in India", not
    take down a whole curation run over a date string.

    `now` is injectable (defaults to the real current time) so DST behavior
    around the US's spring/fall transitions is testable without waiting for
    the calendar to cooperate.
    """
    now = now or datetime.now(UTC)
    tz = _COUNTRY_TZ.get(country, _COUNTRY_TZ[DEFAULT_COUNTRY])
    if isinstance(tz, timedelta):
        return (now + tz).strftime("%Y-%m-%d")
    return now.astimezone(tz).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class CuratedArticle:
    """One `processed_articles` document, as read by the curator.

    `rss_rank` / `feed_length` are NOT persisted fields — neither ingest
    service captures per-article feed position (see this package's CLAUDE.md).
    They are derived in pipeline.py from `published_at` order within
    `feed_source`, which is the closest available proxy for editorial
    placement on a front-page snapshot feed.

    `country` IS persisted (by india-news-ingest / us-news-ingest's
    `extra_fields`), but a document written before the field existed has none
    — store.py defaults that case to DEFAULT_COUNTRY ("IN"), since India was
    the only country before this.
    """

    article_id: str
    url: str
    title: str
    snippet: str
    feed_source: str
    feed_category: str
    published_at: str
    country: str = DEFAULT_COUNTRY
    rss_rank: int = 0
    feed_length: int = 1

    @property
    def embed_text(self) -> str:
        """`f"{title}. {description}"` — design doc §4.1. Never the scraped body."""
        title = self.title.strip().rstrip(".")
        snippet = self.snippet.strip()
        return f"{title}. {snippet}" if snippet else title

    @property
    def placement_score(self) -> float:
        """1 - rss_rank/len(feed) — the ranking formula's editorial-placement term.

        Normalized by this article's own feed length (design doc §4.5), not a
        hardcoded 50: feeds here range 5-60 items, and a fixed denominator
        would hand every short feed a systematic score advantage unrelated to
        newsworthiness.
        """
        return 1.0 - (self.rss_rank / max(self.feed_length, 1))


@dataclass
class Story:
    """One `stories` document (design doc §5.2).

    `country` did not exist before the US pipeline; every India story written
    from here on carries it explicitly (unlike processed_articles, this
    collection has no pre-existing rows to stay silent-compatible with — see
    this package's CLAUDE.md country-isolation section).
    """

    story_id: str
    country: str
    coarse_category: str
    rank: int
    score: float
    cluster_size: int
    sources: list[str]
    canonical_article_id: str
    canonical: dict
    related_articles: list[dict]
    run_date: str  # YYYY-MM-DD, calendar date in the country's local time
    created_at: datetime
    expires_at: datetime
    business_category: str | None = None
    is_canonical_selected: bool = False
    ai_summary: str | None = None
    audio_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "story_id": self.story_id,
            "country": self.country,
            "coarse_category": self.coarse_category,
            "business_category": self.business_category,
            "rank": self.rank,
            "score": round(self.score, 4),
            "cluster_size": self.cluster_size,
            "sources": self.sources,
            "canonical_article_id": self.canonical_article_id,
            "canonical": self.canonical,
            "related_articles": self.related_articles,
            "ai_summary": self.ai_summary,
            "audio_url": self.audio_url,
            "run_date": self.run_date,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }


@dataclass
class CurationRunSummary:
    """Returned by pipeline.run() — what main.py logs and the CLI prints."""

    articles_read: int = 0
    articles_uncategorized: int = 0
    clusters_by_category: dict[str, int] = field(default_factory=dict)
    canonical_selected: int = 0
    stories_written: int = 0
