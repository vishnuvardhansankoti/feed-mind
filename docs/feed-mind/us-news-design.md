# US News: a second country through the same pipeline

**Status:** built; not yet deployed
**Date:** 2026-09-10
**Scope:** one new ingest service (`services/us-news-ingest`), country-scoping
added to the existing `services/news-curator`, a `country` field on
`processed_articles`/`stories`, a country toggle in `apps/web`, and a
`country` column on the BigQuery `articles`/`stories` archive tables.

This is an addendum to
[`news-curator-design.md`](news-curator-design.md), not a replacement — that
document stays India-specific and is the source of truth for the pipeline
shape (embed → classify → cluster → rank → select), the coarse taxonomy, and
the ranking formula. This document covers only what changes to run a second
country through the same pipeline. The system-level view is in the root
[`CLAUDE.md`](../../CLAUDE.md).

---

## 1. The source pivot: Google News, evaluated and rejected

The obvious design for "US news, one source, all the categories" is Google
News RSS (`news.google.com/rss`), which aggregates eight topics
(`WORLD`/`NATION`/`BUSINESS`/`TECHNOLOGY`/`ENTERTAINMENT`/`SCIENCE`/`SPORTS`/`HEALTH`)
behind `hl`/`gl`/`ceid` query parameters from one URL. It was evaluated live
before committing to a design and rejected on two independent grounds:

1. **Item links do not resolve to the real article over plain HTTP.** Every
   `<link>` is `news.google.com/rss/articles/{opaque-token}?oc=5`. Following
   the redirect (verified with `curl -L`) lands back on another
   `news.google.com` URL serving a client-rendered SPA shell — there is no
   plain-HTTP path to the publisher's page. `services/summarizer`'s scraper
   does a plain fetch; it cannot follow this without a headless browser, which
   this repo has no infrastructure for and no free-tier story to run daily.
2. **The `<description>` is not single-article text.** It is an HTML `<ol>` of
   roughly three sibling headlines from *different* outlets covering the same
   story — Google has already done a coarse cross-outlet bundle, for free, per
   item. This is structurally nothing like the plain-text description the
   embedding step (`f"{title}. {description}"`) needs, and there is no clean
   way to recover single-article text from it.

(A third, minor issue: `<title>` carries a `" - {Publisher}"` suffix baked
into the string.)

Five real publisher RSS feeds — the exact same shape `india-news-ingest`
already uses — sidesteps both blocking issues: real article links, clean
plain-text descriptions. The cost is Google's convenience: five outlets to
pick and verify by hand, same as the India design's own §1.

### The five outlets

| Group | Outlet | Verified (2026-09-10) |
|---|---|---|
| general | NPR News | 10 items, clean ~210-char description |
| general | CBS News | 30 items, clean ~226-char description |
| business | CNBC | 30 items, clean ~92-char description |
| business | MarketWatch | 10 items, clean ~75-char description |
| business | Fortune | 10 items, clean ~82-char description |

Rejected during the same evaluation: **AP News** (no working public RSS —
common proxies 403, AP's own feeds were retired), **Reuters** (public RSS
retired entirely, every candidate URL 404s), **Yahoo Finance** (items carry no
per-item `<description>` at all — nothing to embed), **Business Insider**
markets RSS and **Forbes** business RSS (both return syndicated/unrelated
content — stray CSS markup in one, Wordle-hint content in the other — not
clean article text).

---

## 2. Design at a glance

```
                     ┌── general.yaml    NPR News + CBS News
Scheduler ─04:00 CT──▶ us-news-ingest
                     └── business.yaml   CNBC + MarketWatch + Fortune
                               │  curation_status=pending, country=US
                               ▼
                     feedmind-news-ingested       (same topic india-news-ingest uses)
                               │
                               ▼
                         news-curator             same service, same taxonomy,
                               │                  clustering scoped to (country, category)
                               ▼
                          `stories` (country field added; story_id gets a country prefix)
```

`us-news-ingest` is `india-news-ingest` with a different feed list, a
different schedule, and `country=US` instead of `country=IN` in its
`extra_fields`. See `services/us-news-ingest/CLAUDE.md` for exactly what is
identical and what differs.

---

## 3. Decisions and rationale

### 3.1 Schedule: 04:00 America/Chicago

Overnight US news, ahead of both the existing 08:00 tech-blogs ingest and the
17:30 India-news ingest — three distinct times of day. This was the original
design doc's own stub value (§8: "`us-news-ingest` at 04:00 CT is deferred to
a later iteration"), kept rather than revisited, and it happens to spread
Ollama Cloud usage (`services/summarizer`'s LLM step, shared by all three
ingest pipelines) across the day rather than clustering it.

### 3.2 Taxonomy: reused as-is, not extended

Google News' eight topics were the original motivation to consider adding
`technology`/`science`/`health` categories. Once Google News was dropped as
the source, so was the reason to extend the taxonomy — US news reuses the
exact same five coarse categories and anchor text India uses
(`news_curator/anchors.py::COARSE_ANCHORS`), and the same detailed business
sub-taxonomy, with CNBC/MarketWatch/Fortune added to
`BUSINESS_ELIGIBLE_SOURCES` alongside India's three outlets. One flat set is
safe because outlet names never collide between countries.

### 3.3 One shared news-curator, one shared `stories` collection

Considered and rejected: a fully separate `us-news-curator` service and a
separate `us_stories` collection, mirroring the ingest-side symmetry. Rejected
for the same reason the summarizer split was deferred in an earlier
conversation — it doubles the deployed surface area and duplicates the
clustering/ranking code across two services for no behavioral gain. Instead:

- One `news-curator` deployment subscribes to the same `feedmind-news-
  ingested` topic both ingest services publish to. Its query
  (`curation_status == "pending"`) was already source-agnostic; it needed no
  change to also be country-agnostic.
- A `country` field, written by each ingest service's `extra_fields`, is what
  keeps the two apart *inside* that one shared run — see §4.
- No new Pub/Sub topic, no new IAM grant, no new service account for the
  curation step.

### 3.4 No new topic for us-news-ingest

`news-curator`'s Pub/Sub push subscription listens on `feedmind-news-
ingested`. `us-news-ingest` publishes to that exact topic — not a new
`feedmind-us-news-ingested` — because the doorbell was always a "look now,"
never a "look for country X now." A second topic would add infrastructure
with no behavioral difference.

---

## 4. Country isolation inside `news-curator`

Classification is country-agnostic: the anchors are shared, so a US and an
India article are classified against the exact same anchor text, in the same
embedding batch. **Clustering is not.** `pipeline.py::run` scopes every
cluster to `(country, coarse_category)`, never `coarse_category` alone — a US
"business" story and an India "business" story on the same day must never
merge just because both landed in the same coarse bucket.

Three things had to become per-country rather than global constants:

| | Before (India only) | After |
|---|---|---|
| `N_PAPERS` (ranking's consensus term) | `5`, a flat constant | `N_PAPERS_BY_COUNTRY = {"IN": 5, "US": 5}` — a US cluster's consensus term must never be judged against India's outlet count or vice versa, even though both happen to be 5 today |
| `run_date` | `ist_run_date()`, fixed UTC+5:30 | `run_date_for(country)` — India stays a fixed offset (no DST), the US uses real `zoneinfo("America/Chicago")` (DST matters — a fixed offset would be an hour wrong for half the year) |
| `story_id` | `{coarse_category}_{run_date}_{rank}` | `{country}_{coarse_category}_{run_date}_{rank}` — without the prefix, a US and an India cluster in the same category on the same day collide on the same Firestore document ID |

`rss_rank` derivation (grouping by `feed_source`, sorting by `published_at`)
needed **no** country key added — outlet names never collide between
countries (`"CNBC"` vs `"Economic Times"`), so grouping by `feed_source` alone
was already country-safe.

### Backward compatibility

`processed_articles` documents written before this change (all India, since
US did not exist yet) have no `country` field at all.
`store.py::fetch_pending_articles` treats that absence as `"IN"` — India was
the only country before this, so the default is unambiguous. This is a
narrow, one-service convenience, not a system-wide default: the BigQuery
archive does **not** apply the same default (see §6) because most
`processed_articles` rows are tech-blog articles with no country concept at
all, and defaulting those to `"IN"` would mislabel them. `stories` documents
have no legacy case at all — every one has always carried `country`
explicitly, since the collection was introduced in the same build as this
change.

---

## 5. `apps/web`: a country toggle, not a new section

The renamed "News" tab (`#/stories`, curated stories) gains a second toggle
axis above the existing five category tabs: India | US, defaulting to India.
Both countries are fetched eagerly in one `getStories()` call — nested
`{country: {category: cards}}` — so switching the toggle is a client-side
re-slice, the same zero-refetch behavior switching a category tab already
has; there is no loading flicker on toggle.

This needed a second query axis, not a merged ranking: clustering is scoped
per country, so a "Business" category has two *independent* rankings — a US
one and an India one — that are not comparable on the same scale. Interleaving
them into one list would have required inventing a merge rule with no
principled answer. `apps/web`'s Firestore composite index on `stories` gained
`country` as its leading field to support the resulting per-(country,
category) query.

---

## 6. BigQuery archive

`country` was added as a column to both the `articles` and `stories` tables in
`packages/feedmind-core/feedmind_core/archival.py`. Both are **straight
passthrough, nullable** — deliberately not defaulted to `"IN"` the way
`news-curator`'s live query defaults a missing field for its own narrower
purpose. Most `articles` rows are tech-blog content (academic/industry/cloud/
open-source/`top_stories`) with no country concept at all; baking a default
into the permanent archival record would misrepresent every one of them as
Indian. `stories` needed no such care — every row has always carried the
field.

`stories`' clustering fields gained `country` as the leading column, ahead of
`coarse_category`: `apps/web`'s country toggle means "give me one country's
stories" is the single most common filter this table will ever see.

No change was needed to `services/archive/main.py` itself — it iterates
`TableSpec.columns` generically, so the new column is picked up automatically
by the existing job, unchanged. It still runs on the existing 1st-and-16th
schedule (`scripts/deploy-feedmind.sh`); that schedule was not changed as
part of this work.

---

## 7. What did not change

- `services/summarizer`'s `NEWS_STORIES` collector (`is_canonical == true` on
  `processed_articles`) needed no code change at all — the query was already
  country-agnostic, and picks up US canonical articles the moment
  `news-curator` marks them, exactly the same way it already does for India.
- No new Pub/Sub topic, no new Secret Manager secret, no new Firestore
  database, no new Ollama API key.
- The coarse taxonomy, the anchor text, the clustering algorithm (agglomerative,
  complete linkage, cosine distance, τ = 0.22), and the ranking formula's
  weights are all unchanged from `news-curator-design.md` — only their inputs
  became country-scoped.
