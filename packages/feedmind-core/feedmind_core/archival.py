"""
archival.py — Firestore documents → BigQuery rows.

Pure transforms only: everything here takes plain dicts and returns plain
dicts, so the reshaping the archive depends on is testable without touching
Firestore or BigQuery. All client work lives in `bigquery.py`.

Four sources, four shapes:

    processed_articles  → one row per document
    youtube_videos      → one row per document
    runs                → one row per *paper*, unnested from the doc's papers[]
    stories             → one row per document, canonical.* flattened

Every table carries a `raw` column holding the untouched Firestore document as
JSON text. This repo now encodes schema owned by two other repos (paper-prism
writes `runs`, services/news-curator writes `stories`; feed-mind-summarizer
adds `ai_summary` to articles, papers and stories alike), and `raw` is what
keeps an upstream field addition merely *unpromoted* rather than lost — the
source docs are on 45- and 90-day TTLs, so a field we drop today is
unrecoverable tomorrow.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableSpec:
    """Everything that describes one archive table, in one place.

    `columns` is (name, BigQuery type) pairs. `bigquery.py` turns these into
    SchemaFields, generates the MERGE from them, and creates the table — so a
    new column is added here and nowhere else.
    """

    name: str
    columns: tuple[tuple[str, str], ...]
    key_fields: tuple[str, ...]
    partition_field: str
    clustering_fields: tuple[str, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(name for name, _type in self.columns)


ARTICLES = TableSpec(
    name="articles",
    columns=(
        ("article_id", "STRING"),
        ("url", "STRING"),
        ("title", "STRING"),
        ("snippet", "STRING"),
        ("summary", "STRING"),
        ("ai_summary", "STRING"),
        ("feed_source", "STRING"),
        ("feed_category", "STRING"),
        # NULL for every article outside the india-news-ingest/us-news-ingest
        # family (the original tech-blog feeds have no country concept at
        # all). NOT defaulted to "IN" here the way news-curator's live
        # pipeline defaults a missing field — that default exists so an old
        # India document without this field still gets clustered; baking the
        # same guess into the permanent archive would mislabel every
        # non-India tech-blog row as Indian.
        ("country", "STRING"),
        ("published_at", "TIMESTAMP"),
        ("processed_at", "TIMESTAMP"),
        ("status", "STRING"),
        ("raw", "STRING"),
        ("archived_at", "TIMESTAMP"),
    ),
    key_fields=("article_id",),
    partition_field="processed_at",
    clustering_fields=("feed_category", "feed_source"),
)

VIDEOS = TableSpec(
    name="videos",
    columns=(
        ("video_id", "STRING"),
        ("url", "STRING"),
        ("title", "STRING"),
        ("channel", "STRING"),
        ("thumbnail_url", "STRING"),
        ("published_at", "TIMESTAMP"),
        ("processed_at", "TIMESTAMP"),
        ("raw", "STRING"),
        ("archived_at", "TIMESTAMP"),
    ),
    key_fields=("video_id",),
    partition_field="processed_at",
    clustering_fields=("channel",),
)

# `run_id` is paper-prism's deterministic document ID, "YYYY-MM-DD_<CATEGORY>"
# (models.py::RunDocument.doc_id), so it already encodes both the date and the
# lens. A paper appears at most once per run document, which makes
# (run_id, arxiv_id) a sufficient key — no third component needed.
PAPERS = TableSpec(
    name="papers",
    columns=(
        ("run_id", "STRING"),
        ("run_date", "TIMESTAMP"),
        ("category", "STRING"),
        ("rank", "INTEGER"),
        ("arxiv_id", "STRING"),
        ("title", "STRING"),
        ("url", "STRING"),
        ("score", "FLOAT"),
        ("abstract", "STRING"),
        ("summary", "STRING"),
        ("ai_summary", "STRING"),
        ("raw", "STRING"),
        ("archived_at", "TIMESTAMP"),
    ),
    key_fields=("run_id", "arxiv_id"),
    partition_field="run_date",
    clustering_fields=("category",),
)

# `sources` and `related_articles` are JSON-encoded text, not BigQuery REPEATED
# columns — no other table here uses a repeated field, and `raw` already
# carries the untouched arrays for anything that needs them structured.
# `canonical.*` is flattened to top-level columns, same treatment as PAPERS
# unnesting a run doc's papers[] — just one level shallower.
STORIES = TableSpec(
    name="stories",
    columns=(
        ("story_id", "STRING"),
        ("country", "STRING"),
        ("coarse_category", "STRING"),
        ("business_category", "STRING"),
        ("rank", "INTEGER"),
        ("score", "FLOAT"),
        ("cluster_size", "INTEGER"),
        ("sources", "STRING"),
        ("canonical_article_id", "STRING"),
        ("canonical_title", "STRING"),
        ("canonical_url", "STRING"),
        ("canonical_source", "STRING"),
        ("canonical_published_at", "TIMESTAMP"),
        ("related_articles", "STRING"),
        ("ai_summary", "STRING"),
        ("audio_url", "STRING"),
        ("run_date", "TIMESTAMP"),
        ("created_at", "TIMESTAMP"),
        ("raw", "STRING"),
        ("archived_at", "TIMESTAMP"),
    ),
    key_fields=("story_id",),
    partition_field="run_date",
    # country leads: apps/web's country toggle means "give me one country's
    # stories" is the single most common filter this table will ever see.
    clustering_fields=("country", "coarse_category"),
)


# ---------------------------------------------------------------------------
# Coercion — a malformed value yields NULL, never an exception
# ---------------------------------------------------------------------------
# The archive runs twice a month against a 45-day TTL. One bad field in one
# document must not cost a whole run, so every coercion below degrades to None.


def _as_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime; convert an aware one. Never guesses local."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def to_timestamp(value) -> str | None:
    """
    Return an ISO-8601 UTC string BigQuery accepts as TIMESTAMP, or None.

    The two sources disagree on representation: this repo writes ISO strings
    (`datetime.now(UTC).isoformat()`) while paper-prism stores `run_date` as a
    native datetime, which Firestore returns as a datetime subclass. Both land
    here.
    """
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    if isinstance(value, str) and value:
        try:
            return _as_utc(datetime.fromisoformat(value)).isoformat()
        except ValueError:
            logger.warning("Unparseable timestamp, storing NULL: %r", value[:64])
            return None
    return None


def _text(value) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_default(value):
    if isinstance(value, datetime):
        return _as_utc(value).isoformat()
    return str(value)


def to_raw_json(doc: dict) -> str:
    """
    Serialize a Firestore document for the `raw` column.

    `sort_keys` keeps the text stable across runs so two archives of an
    unchanged document produce identical bytes — which makes diffing the column
    meaningful. Non-JSON Firestore types (datetimes, references, GeoPoints)
    degrade to strings rather than raising: a value we cannot type is still
    worth keeping.
    """
    return json.dumps(doc, default=_json_default, ensure_ascii=False, sort_keys=True)


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def article_row(doc_id: str, doc: dict, archived_at: str) -> dict:
    """Build one `articles` row. `ai_summary` is often absent — see module docs."""
    return {
        "article_id": _text(doc.get("article_id")) or doc_id,
        "url": _text(doc.get("url")),
        "title": _text(doc.get("title")),
        "snippet": _text(doc.get("snippet")),
        "summary": _text(doc.get("summary")),
        "ai_summary": _text(doc.get("ai_summary")),
        "feed_source": _text(doc.get("feed_source")),
        "feed_category": _text(doc.get("feed_category")),
        # Straight passthrough, no default — see the ARTICLES TableSpec comment.
        "country": _text(doc.get("country")),
        "published_at": to_timestamp(doc.get("published_at")),
        "processed_at": to_timestamp(doc.get("processed_at")),
        "status": _text(doc.get("status")),
        "raw": to_raw_json(doc),
        "archived_at": archived_at,
    }


def video_row(doc_id: str, doc: dict, archived_at: str) -> dict:
    """Build one `videos` row."""
    return {
        "video_id": _text(doc.get("video_id")) or doc_id,
        "url": _text(doc.get("url")),
        "title": _text(doc.get("title")),
        "channel": _text(doc.get("channel")),
        "thumbnail_url": _text(doc.get("thumbnail_url")),
        "published_at": to_timestamp(doc.get("published_at")),
        "processed_at": to_timestamp(doc.get("processed_at")),
        "raw": to_raw_json(doc),
        "archived_at": archived_at,
    }


def paper_rows(doc_id: str, doc: dict, archived_at: str) -> list[dict]:
    """
    Unnest one `runs` document into a row per paper.

    Papers are not documents — they live in an array on the run doc — so this is
    the one source where a single Firestore read becomes many BigQuery rows. A
    paper with no `arxiv_id` is dropped: it cannot take part in the MERGE key,
    and inventing one would create a row that duplicates itself every run.
    """
    papers = doc.get("papers")
    if not isinstance(papers, list):
        logger.warning("Run doc has no papers array, skipping: run_id=%s", doc_id)
        return []

    run_date = to_timestamp(doc.get("run_date"))
    category = _text(doc.get("category"))

    rows = []
    for paper in papers:
        if not isinstance(paper, dict):
            logger.warning("Skipping non-dict paper entry: run_id=%s", doc_id)
            continue

        arxiv_id = _text(paper.get("arxiv_id"))
        if not arxiv_id:
            logger.warning("Skipping paper with no arxiv_id: run_id=%s", doc_id)
            continue

        rows.append(
            {
                "run_id": doc_id,
                "run_date": run_date,
                "category": category,
                "rank": _int(paper.get("rank")),
                "arxiv_id": arxiv_id,
                "title": _text(paper.get("title")),
                "url": _text(paper.get("url")),
                "score": _float(paper.get("score")),
                "abstract": _text(paper.get("abstract")),
                "summary": _text(paper.get("summary")),
                "ai_summary": _text(paper.get("ai_summary")),
                "raw": to_raw_json(paper),
                "archived_at": archived_at,
            }
        )

    return rows


def story_row(doc_id: str, doc: dict, archived_at: str) -> dict:
    """Build one `stories` row. `ai_summary`/`audio_url` are often absent — see
    services/summarizer/CLAUDE.md's NEWS_STORIES pipeline, which fills them in
    asynchronously, same relationship as `articles.ai_summary`.
    """
    canonical = doc.get("canonical") or {}
    return {
        "story_id": _text(doc.get("story_id")) or doc_id,
        # Every `stories` document carries this explicitly (unlike articles,
        # this collection predates nothing — see this module's docstring and
        # services/news-curator/CLAUDE.md), so no default is needed here
        # either, just consistency with article_row's straight passthrough.
        "country": _text(doc.get("country")),
        "coarse_category": _text(doc.get("coarse_category")),
        "business_category": _text(doc.get("business_category")),
        "rank": _int(doc.get("rank")),
        "score": _float(doc.get("score")),
        "cluster_size": _int(doc.get("cluster_size")),
        "sources": to_raw_json(doc.get("sources") or []),
        "canonical_article_id": _text(doc.get("canonical_article_id")),
        "canonical_title": _text(canonical.get("title")),
        "canonical_url": _text(canonical.get("url")),
        "canonical_source": _text(canonical.get("source")),
        "canonical_published_at": to_timestamp(canonical.get("published_at")),
        "related_articles": to_raw_json(doc.get("related_articles") or []),
        "ai_summary": _text(doc.get("ai_summary")),
        "audio_url": _text(doc.get("audio_url")),
        "run_date": to_timestamp(doc.get("run_date")),
        "created_at": to_timestamp(doc.get("created_at")),
        "raw": to_raw_json(doc),
        "archived_at": archived_at,
    }


def dedupe_by_key(rows: list[dict], key_fields: tuple[str, ...]) -> list[dict]:
    """
    Collapse rows sharing a MERGE key, keeping the last.

    BigQuery aborts a MERGE outright if one target row matches more than one
    source row, so a single duplicate key would cost the entire table for that
    run. Article and video keys are document IDs and unique by construction;
    paper keys are assembled from an array's contents and are not.
    """
    unique: dict[tuple, dict] = {}
    for row in rows:
        unique[tuple(row.get(field) for field in key_fields)] = row

    dropped = len(rows) - len(unique)
    if dropped:
        logger.warning("Dropped %d duplicate row(s) on key %s", dropped, key_fields)

    return list(unique.values())
