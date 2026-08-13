"""Domain model — mirrors the Firestore schema in the PRD (section 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# Lens definition: display category code -> the arXiv source categories it draws
# from. Source sets are disjoint, so a paper's *primary* arXiv category maps it
# to at most one lens (this is how cross-listing dedup is resolved).
LENSES: dict[str, tuple[str, ...]] = {
    "AIML": ("cs.LG", "cs.AI"),
    "NLP": ("cs.CL",),
    "CV": ("cs.CV",),
}


@dataclass
class Paper:
    """A single ranked paper within a lens."""

    rank: int
    title: str
    arxiv_id: str
    url: str
    score: float
    summary: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "rank": self.rank,
            "title": self.title,
            "arxiv_id": self.arxiv_id,
            "url": self.url,
            "score": round(float(self.score), 4),
            "summary": self.summary,
        }


@dataclass
class Candidate:
    """A fetched paper before ranking (carries the text used for embedding)."""

    title: str
    abstract: str
    arxiv_id: str
    url: str
    primary_category: str
    submitted: datetime

    @property
    def embed_text(self) -> str:
        return f"{self.title.strip()}\n{self.abstract.strip()}"


@dataclass
class RunDocument:
    """One document in the `runs` collection: (run, category)."""

    category: str
    run_date: datetime
    papers: list[Paper] = field(default_factory=list)

    @property
    def doc_id(self) -> str:
        # Deterministic ID: YYYY-MM-DD_<CATEGORY> — re-runs overwrite cleanly.
        return f"{self.run_date.strftime('%Y-%m-%d')}_{self.category}"

    def to_dict(self) -> dict:
        return {
            "id": self.doc_id,
            "run_date": self.run_date,
            "category": self.category,
            "papers": [p.to_dict() for p in self.papers],
        }


@dataclass
class RunStatus:
    """The `run_status` document: per-lens outcome for freshness + alerting."""

    run_date: datetime
    categories: dict[str, dict] = field(default_factory=dict)

    @property
    def doc_id(self) -> str:
        return self.run_date.strftime("%Y-%m-%d")

    def mark_ok(self, category: str, paper_count: int) -> None:
        self.categories[category] = {"status": "ok", "paper_count": paper_count}

    def mark_skipped(self, category: str, reason: str) -> None:
        self.categories[category] = {"status": "skipped", "reason": reason}

    @property
    def has_failure(self) -> bool:
        return any(c["status"] != "ok" for c in self.categories.values())

    def to_dict(self) -> dict:
        return {
            "id": self.doc_id,
            "run_date": self.run_date,
            "categories": self.categories,
        }


def utc_run_date() -> datetime:
    """Run date truncated to midnight UTC (drives the deterministic doc IDs)."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)
