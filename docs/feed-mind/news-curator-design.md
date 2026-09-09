# India News: ingest, cluster, rank

**Status:** designed, not built
**Date:** 2026-09-09
**Scope:** one new ingest service, one new curation service, one collection, plus
changes to `services/summarizer`, `services/archive`, `apps/web` and the deploy
scripts.

Supersedes `prd-new.md` wherever the two disagree; every divergence is recorded
in §10. The system-level view is in the root [`CLAUDE.md`](../../CLAUDE.md).

---

## 1. Problem

`services/ingest` currently carries `topstories.yaml` — a single Times of India
RSS feed, ingested on the 08:00 run, stored with `telegram_status=skipped` and
read by the web app's "Top Stories" tab. It is one newspaper, unranked, and
undeduplicated.

The goal is a proper newspaper pipeline: five Indian publications, articles
grouped into events across outlets, classified into fixed categories, ranked
within each category, and only the best few paid for with an LLM call and a
text-to-speech render.

Three constraints shape everything below.

**Volume.** The five feeds carry ~223 items per run (measured 2026-09-08: TOI 47,
The Hindu 60, Business Standard 5, Economic Times 51, Hindu BusinessLine 60).

**Cost.** `webscraper/cloud_speech.py` defaults to `en-US-Neural2-F`, free to 1M
characters/month and ~$16/M after. Summarizing and voicing all 223 articles daily
is ~6.7M chars/month, roughly **$90/month** — against a repo whose stated premise
is that it fits inside free-tier limits.

**Duplication.** Five papers covering one event produce five articles with five
different URLs, so `store.py::is_duplicate` — a SHA-256 of the URL — cannot see
them as related. Cross-outlet dedup is the feature that makes the volume
tractable at all.

---

## 2. Design at a glance

```
                     ┌── general.yaml    TOI top stories (47), The Hindu (60)
Scheduler ─17:30 CT──▶ india-news-ingest
                     └── business.yaml   BS (5), ET (51), BLine (60)
                               │
                               │  ~223 docs → processed_articles
                               │  telegram_status=skipped, content_ready=false
                               ▼
                     feedmind-news-ingested       (doorbell, no payload)
                               │
                               ▼
                         news-curator             embed → classify → cluster → rank
                               │                  ONNX MiniLM on CPU, no torch
                               │  writes `stories`; marks top-5/category canonical
                               ▼
                     feedmind-content-ready       (existing topic, third producer)
                               │
                               ▼
                     feedmind-audio (existing)    scrape → spaCy condense → LLM → TTS
                               │
                               ▼
                     ai_summary / audio_url  →  apps/web (new Stories view)
```

**Curation runs before the LLM, not after.** This is the single most consequential
decision in the document; §3.1 explains why.

---

## 3. Decisions and rationale

### 3.1 Curation precedes summarization

The obvious wiring is to hang the curator off the *end* of the existing pipeline —
ingest, summarize, voice, then cluster — because that is purely additive and
touches none of the existing Pub/Sub wiring.

It is also the one ordering that makes the whole exercise pointless. The reason to
cluster is to summarize only one article per event; if clustering happens after
summarization, all 223 articles have already been through the LLM and Cloud TTS
before anything discovers that three of them were the same story.

Nothing forces the late ordering, because **clustering does not need the scraped
article**. The embedding input is `f"{title}. {description}"`, and every one of
the five feeds ships a usable `<description>` (measured: TOI 170 chars, The Hindu
115, BS 182, ET 675, BLine 131). Waiting for the LLM summary would buy nothing
anyway — `embedder.py` truncates at `_MAX_TOKENS = 256`, about 1000 characters,
so the extra prose is discarded before it reaches the model.

| Ordering | LLM calls/day | TTS chars/month | Est. TTS cost |
|---|---|---|---|
| Cluster last | 223 | ~6.7M | ~$90/mo |
| Cluster first, top-10/category | ~100 | ~3M | ~$32/mo |
| **Cluster first, top-5/category** | **~25** | **~750k** | **free tier** |

### 3.2 Two feed groups, one service

`general.yaml` (TOI + The Hindu) and `business.yaml` (BS + ET + BLine) are separate
files for the same reason `services/ingest` has three: they behave differently
downstream. Only the business group's articles are eligible for a detailed business
sub-category (§4.3). They are one *service* because they share a schedule and a
cold start, and splitting them would buy two cron entries and nothing else — the
same reasoning recorded in [`architecture.md`](architecture.md).

### 3.3 The curator is a Cloud Run service, not a Function or a Job

It needs `onnxruntime`, `numpy`, `scikit-learn` and a 90MB model download. A
512Mi Cloud Function is the wrong shape for that; `services/paper-prism` already
established the container pattern for exactly this model.

paper-prism is a Cloud Run **Job** on a cron. The curator is a Cloud Run
**service** with a Pub/Sub push subscription, because it is triggered by an event
rather than a clock and Eventarc cannot target a Job directly.

The alternative — a Job on its own Cloud Scheduler entry, 30 minutes after ingest —
is simpler infrastructure and no Pub/Sub at all, at the cost of a fixed delay and
a second place where the schedule lives. Worth revisiting if the push subscription
proves fiddly.

### 3.4 Clustering runs on the coarse taxonomy, across all five papers

prd-new §4.4 clusters within a category. With a split taxonomy — TOI's business
stories coarse-labelled `business`, the Economic Times' labelled `markets` — the
same RBI rate decision lands in two different categories, is never compared, and
is never deduplicated. TOI and ET are both Times Group titles that routinely run
the same copy, so that is the highest-overlap pair in the set.

So every article from all five papers is classified into the **coarse** taxonomy
first, and clustering runs within *that*. The detailed business code is assigned
to the resulting cluster afterwards (§4.3).

This also repairs the consensus term in the ranking formula. Clustering across all
five papers means `N_papers = 5`, so `|c| / N_papers` has real resolution; had the
general group clustered alone it would have been a binary 0.5 / 1.0 carrying the
largest weight in the score.

### 3.5 Publisher categories were considered and rejected

TOI and The Hindu both publish per-section RSS feeds, which would make
classification free and exact. They were evaluated and set aside in favour of the
top-stories feeds plus zero-shot classification, because the per-section feeds
raise the volume to ~550 articles/day across 13 feeds — roughly 4× the ranking
budget — and the front-page feed is itself an editorial signal that the `rss_rank`
term consumes.

Two findings from that evaluation are worth keeping:

- `https://timesofindia.indiatimes.com/rssfeeds/66949542.cms` (TOI Tech) is
  **abandoned** — newest item 2024-08-28, oldest 2024-03-11. It returns HTTP 200
  with 20 well-formed items and will do so forever. Do not add it.
- The Hindu's top-stories feed *does* carry `<category>` tags, but they are
  geographic (`Bengaluru`, `Bihar`, `Delhi`, `Editorial`) and useless as topics.
  TOI's carries none. Zero-shot classification is genuinely required here.

---

## 4. The curation pipeline

### 4.1 Vectorization

`sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, run on CPU via **ONNX
Runtime with no torch** — the implementation already exists at
`services/paper-prism/src/paper_prism/embedder.py`. Input text is
`f"{title}. {description}"`; vectors are mean-pooled and L2-normalized, so cosine
similarity is a dot product.

### 4.2 Zero-shot classification

Each article's vector is matched to the anchor with maximum cosine similarity.
Below **0.28**, the article is `uncategorized`.

prd-new's anchor sentences are US-written — "parliament", "United Nations",
"olympic". These are rewritten for Indian coverage, because the anchor text is the
*entire* classifier: there is no other tunable parameter and no labelled data.

| Code | Anchor description |
|---|---|
| `politics` | Indian government policy, Parliament and Lok Sabha proceedings, state assembly elections, political parties and alliances, legislation and bills, judiciary rulings, ministers and chief ministers, campaigns and voting |
| `global` | International affairs and geopolitics, foreign diplomacy and bilateral relations, the United Nations, cross-border military conflicts, global summits, trade agreements, foreign policy |
| `business` | Financial markets and stock indices, Sensex and Nifty, RBI monetary policy and interest rates, corporate earnings, mergers and acquisitions, inflation and GDP, startups and funding, banking |
| `sports` | Cricket matches and series, IPL, athletic competitions and tournaments, professional leagues, match scores, championships, player transfers, the Olympics |
| `culture` | Bollywood and regional cinema, film reviews and box office, television and streaming, music, celebrity news, arts, literature, theatre, food and lifestyle |

There is deliberately **no `tech` category**. `uncategorized` clusters are stored
but never sent to the LLM.

### 4.3 Detailed business sub-categories

A cluster is eligible when its coarse category is `business` **and** at least one
member came from Business Standard, the Economic Times or Hindu BusinessLine. The
canonical article is then matched against a second anchor set:

| Code | Anchor description |
|---|---|
| `markets` | Sensex and Nifty movements, equity trading, bonds, commodities, rupee exchange rates, IPOs, FII and DII flows, market outlook |
| `economy` | Macroeconomic data, GDP growth, inflation and CPI, RBI monetary policy and repo rates, fiscal deficit, the union budget, trade balance, employment data |
| `companies` | Corporate earnings and quarterly results, mergers and acquisitions, management changes, board decisions, expansion and capex, startup funding rounds |
| `portfolio` | Equity research and stock recommendations, buy and sell calls, target prices, mutual fund performance, portfolio allocation, investment analysis |
| `personal_finance` | Personal income tax, savings and fixed deposits, insurance, loans and EMIs, credit cards, retirement and pension planning, PPF and NPS |

A `business` cluster composed only of TOI and Hindu articles keeps the coarse code
and gets no detailed one. This is intentional: the general papers cover business
generally, and forcing them into `markets` vs `economy` would assert a precision
the source does not have.

### 4.4 Event clustering

Agglomerative hierarchical clustering, complete linkage, cosine distance
`d = 1 − cos`, cutoff **τ = 0.22**, run independently within each coarse category.
Singletons form clusters of size 1. τ is the number most likely to need tuning
against real output; prd-new §7 suggests the 0.20–0.25 range.

### 4.5 Ranking

```
Score(c) = 0.50 · (|c| / N_papers)
         + 0.30 · mean over a in c of (1 − rss_rank(a) / len(feed_of(a)))
         + 0.20 · mean over a in c of cos(E(a), C_k)
```

with `N_papers = 5`. Clusters sort descending within each coarse category.

**The second term diverges from prd-new §4.5, which hardcodes a denominator of
50.** The feeds here are wildly uneven in length — Business Standard's holds 5
items against TOI's 47 — so under the literal formula every BS article scores
≥ 0.92 on editorial placement purely because its feed is short, a systematic
~0.13 score advantage unrelated to newsworthiness. Normalizing by the actual feed
length restores the term's meaning: position *within its own front page*.

### 4.6 Selection

The top **5 clusters per coarse category** are marked canonical, giving ~25
articles per run that receive the full `services/summarizer` treatment: scrape →
spaCy condense → LLM → Cloud TTS. `uncategorized` is excluded.

For a multi-article cluster the canonical article is the one with the most words
in its scraped body, per prd-new §4.6 — the most context for one LLM call.

Everything else is still written to `stories` with its title, RSS description,
sources and rank. It is browsable; it simply has no `ai_summary` and no audio.

---

## 5. Data model

### 5.1 `processed_articles` — unchanged shape, new writer

`india-news-ingest` writes through `feedmind_core.store.save_article` exactly as
the existing services do. `telegram_status` is `skipped` throughout — these feeds
never go to Telegram.

`snippet` continues to be persisted. This **overrides prd-new §6**, which
discards `full_text` after summarization: the root `CLAUDE.md` records that
`snippet` exists specifically so the BigQuery archive has real prose, and the
90-day TTL makes anything not captured at write time unrecoverable.

Two fields are added, both written by the curator:

| Field | Meaning |
|---|---|
| `story_id` | the cluster this article belongs to |
| `is_canonical` | selected for full summarization |

### 5.2 `stories` — new collection

```json
{
  "story_id": "business_20260909_03",
  "coarse_category": "business",
  "business_category": "markets",
  "rank": 3,
  "score": 0.842,
  "cluster_size": 3,
  "sources": ["Economic Times", "Business Standard", "Times of India"],
  "canonical_article_id": "<sha256 of canonical url>",
  "canonical": {
    "title": "RBI holds repo rate at 6.5% for the fifth straight review",
    "url": "https://...",
    "source": "Economic Times",
    "published_at": "2026-09-09T04:15:00Z"
  },
  "related_articles": [
    { "source": "Business Standard", "url": "https://...", "title": "..." }
  ],
  "ai_summary": null,
  "audio_url": null,
  "run_date": "2026-09-09",
  "created_at": "2026-09-09T00:05:32Z",
  "expires_at": "2026-12-08T00:05:32Z"
}
```

`story_id` is `{coarse_category}_{run_date}_{rank}`. **Cluster identity is not
stable across runs** — agglomerative clustering over a different article set
produces different groupings — so the id is scoped to a run date and must never
be treated as a durable handle on an event. prd-new §6's claim that re-running
"yields identical clusters and ranks" holds only for an identical input set.

`run_date` is the **IST** calendar date. A 17:30 America/Chicago run is already
the next day in India, and these are Indian papers; keying on the publisher's day
is the only reading that makes the dates mean anything.

`expires_at` is 90 days, matching `processed_articles`. Every collection in this
system is on a clock.

---

## 6. Contract changes

Each row is a place where changing one side silently breaks the other. All of
them belong in the root `CLAUDE.md` table.

| # | Change | Both sides |
|---|---|---|
| 1 | **New topic `feedmind-news-ingested`** | created in `scripts/setup-feedmind-infra.sh`, i.e. on the *publisher's* side — same exception as `feedmind-telegram-ready`, because both ends are FeedMind services and ingest will deploy before the curator exists |
| 2 | **`feedmind-content-ready` gains a third producer** | `services/summarizer/deploy/setup.sh` must grant `roles/pubsub.publisher` to the curator's service account; the topic is owned by its consumer |
| 3 | **The summarizer selects by curation** | it currently takes a `process_doc` type selector; it needs to process news articles where `is_canonical == true` and `ai_summary` is missing |
| 4 | **The summarizer becomes a writer to `stories`** | it should stamp `ai_summary` / `audio_url` onto the story doc as well as the article, so the web view is a single-collection read |
| 5 | **`stories` joins the archive** | `services/archive` and `packages/feedmind-core/archival.py` gain a fourth table |
| 6 | **`firestore.rules` + a composite index** | `stories` needs public read and an index on `coarse_category` + `rank`. Note that `fetch_pending_telegram` deliberately avoids composite indexes; this one is unavoidable and must be deployed *before* the curator's first write |
| 7 | **`apps/web`** | new `STORY_CATEGORIES` constant, new card component, new view. Existing `NEWS_CATEGORIES` tabs are untouched. Codes match with `===`, so the strings above are byte-for-byte load-bearing |
| 8 | **`topstories.yaml` retires** | it moves out of `services/ingest` into `general.yaml`. Existing `feed_category: top_stories` documents live on under their 90-day TTL, so the web app's Top Stories tab must keep working until they expire |

---

## 7. Dependencies

The curator gets its own `pyproject.toml`, `uv.lock` and Dockerfile, like every
other deployable. It needs `onnxruntime`, `tokenizers`, `numpy`, `scikit-learn`,
`huggingface_hub` and `google-cloud-firestore`. Deliberately **not** torch —
`services/paper-prism/CLAUDE.md` records why.

`embedder.py` is **copied**, not shared. `packages/feedmind-core` is
`requires-python >= 3.12` and cannot drop to 3.11 without unpinning the numpy that
sumy needs; paper-prism runs `python:3.11-slim`. Moving the embedder into the core
package would force paper-prism's image up, and the two projects already pin
different Firestore versions on purpose. The copy carries a pointer comment back
to the original. This is new debt on the pile the root `CLAUDE.md` already
records under "no shared library".

---

## 8. Deployment

| | |
|---|---|
| `india-news-ingest` | CF gen2, HTTP, `--no-allow-unauthenticated`, 300s. Cloud Scheduler `30 17 * * *`, `America/Chicago`. Added to the `SERVICES` table in `scripts/deploy-feedmind.sh`, staged by `scripts/stage-service.sh` like every other core consumer. |
| `news-curator` | Cloud Run service, own Dockerfile, Pub/Sub push subscription on `feedmind-news-ingested`. Own `deploy/` directory, following `services/paper-prism/deploy/`. |

`us-news-ingest` at 04:00 CT is deferred to a later iteration; no US feeds are
configured yet, and `serviceconfig.py` raises `ConfigError` on an empty feed list,
so it cannot be deployed as a stub.

---

## 9. Accepted tradeoffs

**One run per day loses most of the day's news.** These are front-page snapshots,
not archives. TOI's top-stories feed holds 47 items covering roughly the last few
hours; Business Standard's holds 5. A single 17:30 CT poll captures what is on
each front page at that instant and never sees the rest. This was chosen
deliberately — the product is a daily digest of what the papers led with, not
full coverage. Cadence is a Cloud Scheduler argument, so raising it to prd-new
§4.1's three runs a day is a config change, not a rewrite; the cost table in §3.1
scales linearly if that happens.

**Classification accuracy is unmeasured.** prd-new §2.2 sets a ≥88% agreement
target with human labels. There are no human labels, and none are planned. The
anchor sentences in §4.2 are the only lever, and the honest position is that the
first weeks of output are the evaluation.

**Clustering precision is likewise unmeasured**, and τ = 0.22 is inherited from
prd-new rather than tuned on Indian copy. A too-low τ shows duplicates; a too-high
τ merges unrelated stories within a category, which is the worse failure because
it silently drops an event.

**prd-new's 4-minute runtime KPI is not a target here.** §6 of that document
mandates a 1s per-domain scrape delay, which alone puts 223 sequential fetches
past 4 minutes. The curator itself — embedding 223 short texts on CPU — is
seconds. The scraping happens in `feedmind-audio`, which already handles long
batches by stopping at `MAX_RUNTIME` (450s) and republishing its own trigger.
That drain-across-invocations behaviour is not idempotent-batch, and it stays.

---

## 10. Divergences from `prd-new.md`

| prd-new | Here | Why |
|---|---|---|
| §3 `trafilatura` extraction | `services/summarizer/webscraper/` — fetch → spaCy condense → LLM | the repo's existing three-step path, already deployed and tuned |
| §3 no spaCy step | spaCy token condensation retained | it is what keeps LLM input under `max_input_chars` |
| §4.1 cron 3×/day | 1×/day, 17:30 CT | see §9 |
| §4.3 Politics/Global/Business/Sports/Culture, US-worded anchors | same five codes, anchor text rewritten for India | the anchors are the whole classifier |
| §4.3 five categories only | plus a detailed business sub-taxonomy for BS/ET/BLine | §4.3 |
| §4.4 cluster within final category | cluster within *coarse* category | otherwise the general and business papers can never dedup against each other (§3.4) |
| §4.5 `rss_rank / 50` | `rss_rank / len(feed)` | feed lengths range 5–60; the constant hands short feeds a systematic advantage (§4.5) |
| §4.6 score threshold bypasses LLM | fixed top-5 per category | predictable daily cost; a threshold's spend varies with the news |
| §5 `stories` + `daily_editions` | `stories` only, with `run_date` on each doc | a separate metadata collection duplicates what run logs already carry |
| §6 discard `full_text` | `snippet` persisted | the BigQuery archive is the reason it exists |
| §6 stateless idempotent batch | curator is idempotent; the summarizer is not | the summarizer's self-republishing drain predates this and is load-bearing |
| §2.2 $0.15/day, 4-min runtime, ≥88% accuracy | not adopted as targets | §9 |
| §1 "100–150 articles daily" | ~223 measured | the estimate predates these five feeds |

---

## 11. Build order

1. `services/india-news-ingest` with both YAML groups, publishing
   `feedmind-news-ingested`. Verifiable on its own: run it, count documents.
2. `services/news-curator` — embed, classify, cluster, rank, write `stories`.
   Run it against a day of real ingested data with the Firestore write disabled
   and read the output; τ and the anchor sentences get tuned here, before anything
   downstream depends on them.
3. Wire `feedmind-content-ready` and the summarizer's canonical selection
   (contract changes 2–4).
4. `apps/web` Stories view, `firestore.rules`, the composite index.
5. `services/archive` gains the `stories` table.
6. Retire `topstories.yaml` from `services/ingest`.
