"""Firestore access: reading the curation backlog, writing `stories`.

Firestore reads are never mocked, in local mode or production — only the
*write* differs (LocalJsonSink vs FirestoreSink), same split as paper-prism's
sinks.py. That is what makes "run against a day of real ingested data with the
Firestore write disabled" (design doc §11, step 2) a config flag rather than a
separate code path.

No dependency on feedmind-core (see this package's CLAUDE.md) — the
collection name, curation_status values and Firestore database id are
re-declared here rather than imported.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Protocol

from .models import DEFAULT_COUNTRY, CuratedArticle, Story

log = logging.getLogger("news_curator.store")

PROCESSED_ARTICLES_COLLECTION = "processed_articles"
STORIES_COLLECTION = "stories"

# Must match feedmind_core.settings.CURATION_PENDING / CURATION_CLUSTERED byte
# for byte — services/india-news-ingest writes the first, this service reads
# it and writes the second. See the root CLAUDE.md's contracts table.
CURATION_PENDING = "pending"
CURATION_CLUSTERED = "clustered"


def fetch_pending_articles(db) -> list[CuratedArticle]:
    """Every article india-news-ingest or us-news-ingest has stored but this
    service has not yet clustered.

    A single-field equality filter with no order_by, deliberately — same
    reasoning as feedmind_core.store.fetch_pending_telegram: Firestore indexes
    single fields automatically, and a composite index would have to be
    deployed before this could run at all. It is also country-agnostic on
    purpose: one query returns both countries' backlog, and pipeline.py splits
    by `country` afterwards — see this package's CLAUDE.md.
    """
    from google.cloud.firestore_v1.base_query import FieldFilter

    docs = (
        db.collection(PROCESSED_ARTICLES_COLLECTION)
        .where(filter=FieldFilter("curation_status", "==", CURATION_PENDING))
        .stream()
    )

    articles: list[CuratedArticle] = []
    for snapshot in docs:
        doc = snapshot.to_dict() or {}
        if not doc.get("url") or not doc.get("title"):
            log.warning("Skipping unrenderable pending article: %s", snapshot.id)
            continue
        articles.append(
            CuratedArticle(
                article_id=doc.get("article_id", snapshot.id),
                url=doc["url"],
                title=doc["title"],
                snippet=doc.get("snippet", ""),
                feed_source=doc.get("feed_source", ""),
                feed_category=doc.get("feed_category", ""),
                published_at=doc.get("published_at", ""),
                # Absent only on docs written before this field existed —
                # India was the only country then, so absence means "IN".
                country=doc.get("country") or DEFAULT_COUNTRY,
            )
        )

    log.info("Pending curation articles fetched: %d", len(articles))
    return articles


class Sink(Protocol):
    def write_story(self, story: Story) -> None: ...
    def mark_clustered(
        self, article_id: str, story_id: str, is_canonical: bool, audio_eligible: bool
    ) -> None: ...


class LocalJsonSink:
    """Writes stories as JSON under ./output/stories/ and touches nothing else.

    This is what design doc §11 step 2 means by "Firestore write disabled" —
    `fetch_pending_articles` above still reads real data; only the outcome is
    diverted to disk so tau and the anchors can be tuned by reading it.
    """

    def __init__(self, output_dir: str = "output") -> None:
        self.stories_dir = os.path.join(output_dir, "stories")
        os.makedirs(self.stories_dir, exist_ok=True)

    def write_story(self, story: Story) -> None:
        path = os.path.join(self.stories_dir, f"{story.story_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(story.to_dict(), fh, indent=2, ensure_ascii=False, default=_json_default)
        log.info("wrote %s (%d sources)", path, len(story.sources))

    def mark_clustered(
        self, article_id: str, story_id: str, is_canonical: bool, audio_eligible: bool
    ) -> None:
        log.info(
            "(local) would mark %s: story_id=%s is_canonical=%s audio_eligible=%s",
            article_id, story_id, is_canonical, audio_eligible,
        )


class FirestoreSink:
    def __init__(self, db) -> None:
        self.db = db

    def write_story(self, story: Story) -> None:
        self.db.collection(STORIES_COLLECTION).document(story.story_id).set(story.to_dict())
        log.info("Firestore: stories/%s (%d sources)", story.story_id, len(story.sources))

    def mark_clustered(
        self, article_id: str, story_id: str, is_canonical: bool, audio_eligible: bool
    ) -> None:
        self.db.collection(PROCESSED_ARTICLES_COLLECTION).document(article_id).update(
            {
                "story_id": story_id,
                "is_canonical": is_canonical,
                "audio_eligible": audio_eligible,
                "curation_status": CURATION_CLUSTERED,
            }
        )


def build_sink(name: str, output_dir: str, db=None) -> Sink:
    if name == "firestore":
        if db is None:
            raise ValueError("SINK=firestore needs a Firestore client")
        return FirestoreSink(db)
    return LocalJsonSink(output_dir)


def build_firestore_client(project: str | None, database: str | None):
    from google.cloud import firestore

    kwargs: dict[str, str] = {}
    if project:
        kwargs["project"] = project
    if database:
        kwargs["database"] = database
    return firestore.Client(**kwargs)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    raise TypeError(f"not JSON serializable: {type(value)}")
