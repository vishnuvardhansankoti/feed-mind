"""Domain model — mirrors the Firestore schema in the design doc (§5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

# UTC+5:30, no DST. A 17:30 America/Chicago ingest run is already the next
# calendar day in India, and these are Indian papers — keying run_date on the
# publisher's day is the only reading that makes the date mean anything
# (design doc §5.2).
_IST_OFFSET = timedelta(hours=5, minutes=30)


def ist_run_date() -> str:
    """Today's date in India Standard Time, as YYYY-MM-DD."""
    return (datetime.now(UTC) + _IST_OFFSET).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class CuratedArticle:
    """One `processed_articles` document, as read by the curator.

    `rss_rank` / `feed_length` are NOT persisted fields — `services/india-news-
    ingest` does not capture per-article feed position (see this package's
    CLAUDE.md). They are derived in pipeline.py from `published_at` order
    within `feed_source`, which is the closest available proxy for editorial
    placement on a front-page snapshot feed.
    """

    article_id: str
    url: str
    title: str
    snippet: str
    feed_source: str
    feed_category: str
    published_at: str
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
class Cluster:
    """One event cluster within a single coarse category, before ranking."""

    coarse_category: str
    members: list[CuratedArticle]
    centroid: object  # np.ndarray; kept untyped so this module has no numpy import
    score: float = 0.0
    business_category: str | None = None
    rank: int = 0

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def sources(self) -> list[str]:
        seen: dict[str, None] = {}
        for article in self.members:
            seen[article.feed_source] = None
        return list(seen)


@dataclass
class Story:
    """One `stories` document (design doc §5.2)."""

    story_id: str
    coarse_category: str
    rank: int
    score: float
    cluster_size: int
    sources: list[str]
    canonical_article_id: str
    canonical: dict
    related_articles: list[dict]
    run_date: str  # YYYY-MM-DD, IST calendar date
    created_at: datetime
    expires_at: datetime
    business_category: str | None = None
    is_canonical_selected: bool = False
    ai_summary: str | None = None
    audio_url: str | None = None

    def to_dict(self) -> dict:
        return {
            "story_id": self.story_id,
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
