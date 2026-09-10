# Product Requirements Document (PRD)

## 1. Overview & Problem Statement

The current news pipeline processes 45–50 articles daily from a single RSS feed through a sequential, two-step extraction and LLM summarization pipeline. Expanding this ingestion to 2–3 publications (100–150 articles daily) introduces duplicate event coverage, uneven article importance, and high LLM token costs if executed naively.

This system upgrades the pipeline with local dense embeddings and unsupervised clustering to deduplicate stories across publications, classify articles into fixed categories (Politics, Global, Business, Sports, Culture) without labeled data, compute an objective newsworthiness ranking, and synthesize canonical stories using a single-pass LLM execution model.

---

## 2. Goals & Success Metrics

### 2.1 Core Objectives

* **Cross-Source Deduplication:** Group overlapping stories across multiple newspapers into unified event clusters.
* **Automated Categorization:** Map every incoming article deterministically into one of five predefined categories without external classification API calls.
* **Editorial-Free Ranking:** Rank events within each category based on editorial consensus, placement, and semantic centrality.
* **Token & Cost Efficiency:** Reduce total LLM API calls by 30%–50% by summarizing only canonical representatives of multi-article clusters.

### 2.2 Key Performance Indicators (KPIs)

* **Pipeline Runtime:** Ingestion-to-storage processing completed in under 4 minutes for 150 daily articles.
* **Clustering Precision:** $\ge 90\%$ accuracy in grouping stories covering the identical real-world event.
* **Classification Accuracy:** $\ge 88\%$ agreement with human-assigned category tags.
* **Cost Cap:** Daily LLM operational costs maintained below $0.15/day across 150 scraped articles.

---

## 3. System Architecture & Processing Stages

| Stage | Module | Implementation | Input $\rightarrow$ Output |
| --- | --- | --- | --- |
| **1. Ingestion & Extraction** | Feed Ingestor | `feedparser` + `trafilatura` | RSS URLs $\rightarrow$ Clean markdown/text, title, published date, RSS index |
| **2. Vectorization** | Local Embedder | `sentence-transformers` (`all-MiniLM-L6-v2`) | Title + Lead Paragraph $\rightarrow$ 384-dimensional dense float vector |
| **3. Zero-Shot Classification** | Anchor Classifier | Cosine similarity matrix against 5 static category vectors | Article vector $\rightarrow$ Primary Category tag + Confidence score |
| **4. Event Clustering** | Deduplication Engine | Agglomerative Clustering (Cosine Distance $\le 0.22$) | Category vectors $\rightarrow$ Event cluster IDs (grouped stories) |
| **5. Algorithmic Ranking** | Ranking Engine | Weighted Consensus & Position Formula | Cluster items $\rightarrow$ Category-level ordinal rank score |
| **6. Synthesis & Storage** | LLM Processor | Low-cost reasoning LLM + Firestore SDK | Canonical article $\rightarrow$ Structured JSON $\rightarrow$ Firestore document |

---

## 4. Detailed Functional Requirements

### 4.1 Ingestion & Content Scrubbing

* The ingestion runner triggers on a cron schedule (e.g., 06:00 AM, 12:00 PM, 06:00 PM local time).
* Fetches entries from configured newspaper RSS feeds.
* Normalizes publication URLs, eliminates tracking query params (e.g., `utm_*`), and filters against existing Firestore document IDs to avoid re-scraping existing links.
* Scrapes full text using `trafilatura` with a 10-second timeout per page. Extracts:
* `title`: Normalized text title.
* `lead_paragraph`: First 2–3 non-empty paragraphs ($\approx 150$ words).
* `full_text`: Scrubbed article body.
* `rss_rank`: 0-indexed position in the original RSS feed.
* `source`: Newspaper identifier (e.g., `nyt`, `wsj`, `wapo`).



### 4.2 Local Dense Vectorization

* Computes vector representations locally on CPU/memory without calling paid embedding APIs.
* **Model:** `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions, runtime $\approx 15\text{ms}$ per title+lead on CPU).
* **Text Construct:** `f"{title}. {lead_paragraph}"`.

### 4.3 Zero-Shot Anchor Classification

* The system defines static anchor descriptions for each category:
* **Politics:** *"Government policy, domestic legislation, elections, parliament, political campaigns, party disputes, voting, and executive regulations."*
* **Global:** *"International affairs, geopolitics, foreign diplomacy, United Nations, cross-border military conflicts, global summits, and foreign policy."*
* **Business:** *"Financial markets, macroeconomic data, corporate earnings, interest rates, central banks, stocks, mergers, acquisitions, and inflation."*
* **Sports:** *"Athletic competitions, tournaments, professional leagues, match scores, championships, player contracts, and olympic events."*
* **Culture:** *"Arts, literature, cinema, film reviews, music releases, museum exhibitions, theatre, celebrity news, and culinary culture."*


* Pre-computes normalized embeddings $C_k \in \mathbb{R}^{384}$ for each category $k \in \{1, \dots, 5\}$.
* Matches each article vector $E(a)$ to category $k$ with the maximum cosine similarity:

$$\text{Category}(a) = \arg\max_{k} \left( \frac{E(a) \cdot C_k}{\Vert{}E(a)\Vert{} \Vert{}C_k\Vert{}} \right)$$


* If $\max_k(\text{cosine}) < 0.28$, the article is flagged as `Uncategorized` and reviewed in the LLM fallback step.

### 4.4 Unsupervised Cross-Outlet Story Clustering

* Runs within each identified category to group articles covering the same event.
* **Algorithm:** Agglomerative Hierarchical Clustering with complete linkage.
* **Distance Metric:** Cosine distance metric ($d = 1 - \text{cosine\_similarity}$).
* **Threshold:** Distance cutoff of $\tau = 0.22$. Pairwise distance below $\tau$ indicates identical news events.
* Output assigns a deterministic `cluster_id` to every article. Singleton articles form a cluster of size 1.

### 4.5 Algorithmic Ranking Engine

Within each category, clusters are scored using a normalized heuristic based on cross-outlet consensus, editorial placement, and semantic category centrality:

$$Score(c) = w_1 \cdot \left(\frac{\vert{}c\vert{}}{N_{\text{papers}}}\right) + w_2 \cdot \left(\frac{1}{\vert{}c\vert{}} \sum_{a \in c} \left(1 - \frac{\text{rss\_rank}(a)}{50}\right)\right) + w_3 \cdot \left(\frac{1}{\vert{}c\vert{}} \sum_{a \in c} \text{Sim}(E(a), C_k)\right)$$

* **Weights:** $w_1 = 0.50$ (Consensus), $w_2 = 0.30$ (Editorial feed priority), $w_3 = 0.20$ (Semantic relevance).
* Clusters are sorted in descending order by $Score(c)$ to produce the category rank (1 to $N$).

### 4.6 Canonical Article Selection & LLM Summarization

* For multi-article clusters ($\vert{}c\vert{} > 1$), select the **canonical article** $a^*$ with the maximum word count in `full_text` to capture the most context.
* Send only the canonical article to the LLM.
* **LLM Schema Specification:** The call must use JSON Structured Outputs:
```json
{
  "summary": "String (3 concise sentences highlighting core development and implications)",
  "key_takeaways": ["String (Key point 1)", "String (Key point 2)"],
  "impact_rating": "Integer (1-5 scale: 1=niche interest, 5=major historical/systemic shift)"
}

```


* Clusters of size 1 with low ranking score ($Score(c) < 0.20$) can bypass the LLM entirely to conserve API limits, storing only their lead paragraphs.

---

## 5. Data Model & Firestore Schema

### Collection: `daily_editions/{YYYY-MM-DD}`

Metadata document tracking execution stats, total articles scraped, cluster count, and runtime.

### Collection: `stories` (Individual Clusters)

```json
{
  "story_id": "pol_20261024_cluster_01",
  "category": "Politics",
  "rank": 1,
  "score": 0.842,
  "cluster_size": 3,
  "sources": ["nyt", "wsj", "wapo"],
  "canonical_article": {
    "title": "Senate Passes Bipartisan Clean Energy Infrastructure Bill",
    "url": "https://...",
    "source": "nyt",
    "published_at": "2026-10-24T10:15:00Z"
  },
  "related_articles": [
    { "source": "wsj", "url": "https://...", "title": "Energy Bill Clears Senate Floor" },
    { "source": "wapo", "url": "https://...", "title": "Senate Reaches Compromise on Energy Package" }
  ],
  "llm_output": {
    "summary": "The US Senate approved a $40B infrastructure measure focusing on clean energy transmission grids. The bill passed with an 8-vote bipartisan margin after extensive negotiations over permit reform. The legislation now moves to the House for final approval.",
    "key_takeaways": [
      "Passed 58-42 with eight cross-party votes.",
      "Allocates $40B toward high-voltage regional power line modernization."
    ],
    "impact_rating": 4
  },
  "created_at": "2026-10-24T12:05:32Z"
}

```

---

## 6. Non-Functional & Operational Requirements

* **Stateless Processing:** The pipeline runs as an idempotent batch job. Re-running the pipeline for a specific timestamp yields identical clusters and ranks.
* **Fault Tolerance:** If a single newspaper's RSS feed fails or returns a 4xx/5xx status, the pipeline continues processing remaining feeds and logs an alert.
* **Rate Limiting:** Web scraping requests enforce a 1-second delay per domain with rotating User-Agent headers to avoid IP blocks.
* **Storage Optimization:** Raw article bodies (`full_text`) are discarded after clustering and summarization; only titles, links, summaries, and vector metadata persist in Firestore.

---

## 7. Execution Phases & Milestones

* **Phase 1 (Week 1):** Ingestion enhancement (multi-feed support, canonical link scrubbing) and integration of local vectorization using `all-MiniLM-L6-v2`.
* **Phase 2 (Week 2):** Zero-shot cosine category assignment and tuning Agglomerative Clustering thresholds ($\tau = 0.20$ to $0.25$) on real-world news feeds.
* **Phase 3 (Week 3):** Ranking score integration, canonical selection logic, and single-pass JSON-structured LLM prompt implementation.
* **Phase 4 (Week 4):** Firestore batch migration, schema testing, and end-to-end automated deployment via cron runner.