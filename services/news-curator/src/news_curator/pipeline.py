"""Pipeline orchestration: embed -> classify -> cluster -> rank -> select -> write.

The order matters and is the design doc's central decision (§3.1): clustering
happens on title+description, before anything is scraped or sent to an LLM, so
only the top canonical articles/day ever reach services/summarizer.

Classification runs across every pending article regardless of country — the
anchors are shared (see anchors.py). Clustering does not: it is scoped to
(country, coarse_category), so a US and an India article are never merged
into the same event just because both are "business" the same day. See this
package's CLAUDE.md country-isolation section.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from . import classify, rank
from . import cluster as clustering
from .anchors import BUSINESS_ELIGIBLE_SOURCES, N_PAPERS_BY_COUNTRY, UNCATEGORIZED
from .config import Config
from .embedder import Embedder
from .models import CuratedArticle, CurationRunSummary, Story, run_date_for
from .store import Sink

log = logging.getLogger("news_curator.pipeline")

STORY_RETENTION_DAYS = 90  # matches processed_articles — root CLAUDE.md's "everything is on a clock"


def _with_feed_rank(articles: list[CuratedArticle]) -> list[CuratedArticle]:
    """Derive rss_rank / feed_length per article — see CuratedArticle's docstring.

    Grouped by feed_source alone, not (country, feed_source): outlet names
    never collide between countries (see anchors.BUSINESS_ELIGIBLE_SOURCES'
    docstring), so this is already country-safe without the extra key.
    """
    by_source: dict[str, list[CuratedArticle]] = defaultdict(list)
    for article in articles:
        by_source[article.feed_source].append(article)

    ranked: list[CuratedArticle] = []
    for group in by_source.values():
        group.sort(key=lambda a: a.published_at, reverse=True)
        for index, article in enumerate(group):
            ranked.append(
                CuratedArticle(
                    article_id=article.article_id,
                    url=article.url,
                    title=article.title,
                    snippet=article.snippet,
                    feed_source=article.feed_source,
                    feed_category=article.feed_category,
                    published_at=article.published_at,
                    country=article.country,
                    rss_rank=index,
                    feed_length=len(group),
                )
            )
    return ranked


def _is_business_eligible(members: list[CuratedArticle]) -> bool:
    return any(article.feed_source in BUSINESS_ELIGIBLE_SOURCES for article in members)


def run(config: Config, embedder: Embedder, articles: list[CuratedArticle], sink: Sink) -> CurationRunSummary:
    summary = CurationRunSummary(articles_read=len(articles))
    if not articles:
        log.info("No pending articles — nothing to curate")
        return summary

    articles = _with_feed_rank(articles)
    embeddings = embedder.encode([a.embed_text for a in articles])

    coarse_vecs, coarse_codes = classify.coarse_anchor_matrix(embedder.encode)
    coarse_labels = classify.classify_coarse(embeddings, coarse_vecs, coarse_codes, config.coarse_threshold)

    business_vecs, business_codes = classify.business_anchor_matrix(embedder.encode)

    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(days=STORY_RETENTION_DAYS)

    # Clustering is scoped to (country, coarse_category), never coarse_category
    # alone — design doc §3.4 clusters across all of one country's papers so
    # e.g. TOI and ET can dedupe against each other, but a US and an India
    # article must never merge just because both are "business" the same day.
    # Countries are discovered from the batch rather than hardcoded, so a
    # country with nothing pending this run costs nothing.
    countries = sorted({a.country for a in articles})

    for country in countries:
        run_date = run_date_for(country)
        n_papers = N_PAPERS_BY_COUNTRY.get(country, N_PAPERS_BY_COUNTRY["IN"])

        for coarse_category in coarse_codes:
            indices = [
                i for i, (article, label) in enumerate(zip(articles, coarse_labels, strict=True))
                if article.country == country and label == coarse_category
            ]
            if not indices:
                continue

            category_embeddings = embeddings[indices]
            raw_clusters = clustering.cluster_indices(category_embeddings, config.cluster_distance_threshold)
            summary.clusters_by_category[f"{country}:{coarse_category}"] = len(raw_clusters)

            scored: list[tuple[float, list[int]]] = []
            for local_indices in raw_clusters:
                global_indices = [indices[i] for i in local_indices]
                members = [articles[i] for i in global_indices]
                member_vecs = embeddings[global_indices]
                centroid = clustering.centroid(embeddings, global_indices)
                score = rank.score_cluster(members, member_vecs, centroid, n_papers)
                scored.append((score, global_indices))

            scored.sort(key=lambda item: item[0], reverse=True)

            for position, (score, global_indices) in enumerate(scored, start=1):
                members = [articles[i] for i in global_indices]
                is_selected = position <= config.top_k_per_category
                canonical = rank.pick_canonical(members)

                business_category = None
                if coarse_category == "business" and _is_business_eligible(members):
                    canonical_idx = next(
                        gi for gi, a in zip(global_indices, members, strict=True)
                        if a.article_id == canonical.article_id
                    )
                    business_category = classify.classify_business(
                        embeddings[canonical_idx], business_vecs, business_codes
                    )

                story = Story(
                    story_id=f"{country.lower()}_{coarse_category}_{run_date}_{position:02d}",
                    country=country,
                    coarse_category=coarse_category,
                    business_category=business_category,
                    rank=position,
                    score=score,
                    cluster_size=len(members),
                    sources=[a.feed_source for a in _dedupe_by_source(members)],
                    canonical_article_id=canonical.article_id,
                    canonical={
                        "title": canonical.title,
                        "url": canonical.url,
                        "source": canonical.feed_source,
                        "published_at": canonical.published_at,
                    },
                    related_articles=[
                        {"source": a.feed_source, "url": a.url, "title": a.title}
                        for a in members
                        if a.article_id != canonical.article_id
                    ],
                    run_date=run_date,
                    created_at=created_at,
                    expires_at=expires_at,
                    is_canonical_selected=is_selected,
                )
                sink.write_story(story)
                summary.stories_written += 1
                if is_selected:
                    summary.canonical_selected += 1

                for article in members:
                    sink.mark_clustered(
                        article.article_id,
                        story.story_id,
                        is_canonical=is_selected and article.article_id == canonical.article_id,
                    )

    summary.articles_uncategorized = sum(1 for label in coarse_labels if label == UNCATEGORIZED)
    log.info(
        "Curation complete: read=%d uncategorized=%d stories=%d canonical=%d",
        summary.articles_read,
        summary.articles_uncategorized,
        summary.stories_written,
        summary.canonical_selected,
    )
    return summary


def _dedupe_by_source(members: list[CuratedArticle]) -> list[CuratedArticle]:
    seen: dict[str, CuratedArticle] = {}
    for article in members:
        seen.setdefault(article.feed_source, article)
    return list(seen.values())
