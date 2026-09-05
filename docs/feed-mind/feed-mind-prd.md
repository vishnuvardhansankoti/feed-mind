# FeedMind — Product Requirements Document

**Version:** 1.0  
**Status:** Draft  
**Author:** Product (via AI-assisted design session)  
**Date:** 2026-07-24  
**Audience:** Internal / Developer Use Only

---

## Table of Contents

1. [Product Overview & Goals](#1-product-overview--goals)
2. [System Architecture & Constraints](#2-system-architecture--constraints)
3. [Curated Data Sources](#3-curated-data-sources-rss-feeds)
4. [Functional Requirements](#4-functional-requirements)
5. [Non-Functional Requirements](#5-non-functional-requirements)
6. [Data Schema (Firestore)](#6-data-schema-firestore)
7. [Success Metrics & Logging](#7-success-metrics--logging)
8. [GCP Free Tier Cost Analysis](#8-gcp-free-tier-cost-analysis)
9. [Open Items & Future Considerations](#9-open-items--future-considerations)

---

## 1. Product Overview & Goals

### 1.1 High-Level Definition

**FeedMind** is a self-hosted, serverless RSS ingestion and AI-summarization pipeline running entirely on Google Cloud Platform (GCP). It monitors a curated list of 11 RSS feeds spanning academic AI/ML research, industry news, and cloud computing blogs. When new articles are discovered, it uses the **Gemini 2.0 Flash API** (Google AI Studio free tier) to generate concise, technical summaries and delivers them as individual messages to a **private Telegram bot**.

The system is designed for a single developer user. There is no frontend, no multi-tenancy, and no SLA beyond personal productivity.

### 1.2 Key Objectives

| Objective | Description |
|-----------|-------------|
| **Cost-Efficiency** | Operate at strict **$0/month** on GCP by staying within all relevant free tiers (Cloud Functions, Firestore, Cloud Scheduler, Secret Manager). Gemini API usage stays within the Google AI Studio free tier (1,500 req/day for `gemini-2.0-flash`). |
| **Automated Delivery** | No manual intervention required after initial deployment. The system wakes up once daily, ingests all feeds, deduplicates, summarizes, and delivers — fully autonomously. |
| **Low Operational Maintenance** | Stateless compute (Cloud Functions) with no servers, no containers to manage, and no databases to tune. Infrastructure is declarative and reproducible. |
| **Signal-to-Noise** | Only new, unseen articles are processed. Deduplication at the Firestore layer prevents duplicate Telegram notifications across all runs. |

### 1.3 Target Audience

Internal / Developer use only. One user, one Telegram bot, one GCP project. No external access, no user authentication UI, no onboarding flow.

---

## 2. System Architecture & Constraints

### 2.1 Architecture Overview

```
┌─────────────────────┐
│   Cloud Scheduler   │  (Daily cron trigger — 8 AM local time)
│   (Free Tier)       │
└────────┬────────────┘
         │ HTTPS POST (OIDC-authenticated)
         ▼
┌─────────────────────┐
│  Cloud Function     │  (Gen 2, Python 3.12, HTTP trigger)
│  Gen 2              │  (5-minute timeout, 256 MB memory)
│  (Free Tier)        │
└──────┬──────┬───────┘
       │      │
       │      │  Secret Access
       │      ▼
       │  ┌──────────────────┐
       │  │  Secret Manager  │  (Telegram Token, Chat ID, Gemini API Key)
       │  │  (Free Tier)     │
       │  └──────────────────┘
       │
       ├──► Fetch 11 RSS Feeds (feedparser over HTTPS)
       │
       ├──► ┌─────────────────┐
       │    │    Firestore    │  Deduplication check (Native Mode)
       │    │  (Free Tier)    │  Collection: `processed_articles`
       │    └─────────────────┘
       │
       ├──► ┌─────────────────┐
       │    │  Gemini 2.0     │  Summarization (Google AI Studio free tier)
       │    │  Flash API      │  Model: `gemini-2.0-flash`
       │    └─────────────────┘
       │
       └──► ┌─────────────────┐
            │  Telegram Bot   │  Individual message per new article
            │  API            │  (MarkdownV2, sequential delivery)
            └─────────────────┘
```

### 2.2 Stack Components

| Component | Service | Tier |
|-----------|---------|------|
| Trigger | GCP Cloud Scheduler | Free (3 jobs/month free) |
| Compute | GCP Cloud Functions Gen 2 (Python 3.12) | Free (2M invocations/month) |
| Deduplication DB | GCP Firestore Native Mode | Free (1 GiB storage, 50K reads/day, 20K writes/day) |
| AI Inference | Google AI Studio — `gemini-2.0-flash` | Free (1,500 req/day) |
| Notification | Telegram Bot API | Free |
| Secrets | GCP Secret Manager | Free (≤6 secret versions, ≤10K accesses/month) |

### 2.3 Guardrails & Constraints

#### Gemini API Free Tier
- **Model:** `gemini-2.0-flash` (via Google AI Studio API key)
- **Free tier limit:** 1,500 requests/day, 1M tokens/day
- **Constraint for this system:** With 11 feeds and a typical daily delta of 5–30 new articles, peak usage is well under 50 API calls/day — far below the limit.
- **Input truncation:** Article text is truncated to **2,000 characters** before sending to Gemini to minimize token usage and keep inference fast.

#### Cloud Functions Gen 2 (HTTP-triggered)
- **Max timeout for HTTP triggers:** 9 minutes. This PRD targets a **5-minute timeout** to allow sequential feed processing while keeping a safety margin.
- **Memory:** 256 MB (sufficient for feedparser + HTTP clients).
- **Concurrency:** Single-instance (1 request at a time is expected given daily cron).

#### Firestore Free Tier
- 50,000 document reads/day, 20,000 writes/day, 20,000 deletes/day.
- **Expected usage:** 11 feeds × ~20 articles = ~220 reads/day (dedup check) + ~30 writes/day (new articles). Well within free tier.

---

## 3. Curated Data Sources (RSS Feeds)

The following 11 RSS feeds are hardcoded in the application configuration. They are organized by category for readability in the codebase.

### 3.1 Academic / Research

| Source | RSS Feed URL |
|--------|-------------|
| arXiv — Machine Learning | `https://rss.arxiv.org/rss/cs.LG` |
| arXiv — Artificial Intelligence | `https://rss.arxiv.org/rss/cs.AI` |
| Hugging Face Daily Papers | `https://huggingface.co/blog/feed.xml` |

> **Note:** The original prompt referenced `http://arxiv.org` and `https://githubusercontent.com` as placeholder domains. The exact arXiv RSS feed paths (`/rss/cs.LG`, `/rss/cs.AI`) and the Hugging Face blog feed are the canonical URLs and should be used in implementation.

### 3.2 Industry News

| Source | RSS Feed URL |
|--------|-------------|
| OpenAI News | `https://openai.com/news/rss.xml` |
| Google DeepMind Blog | `https://deepmind.google/blog/rss.xml` |
| Microsoft Research Blog | `https://www.microsoft.com/en-us/research/feed/` |
| TechCrunch — AI | `https://techcrunch.com/category/artificial-intelligence/feed/` |

### 3.3 Cloud Computing

| Source | RSS Feed URL |
|--------|-------------|
| CNCF Blog | `https://www.cncf.io/blog/feed/` |
| AWS News Blog | `https://aws.amazon.com/blogs/aws/feed/` |
| Google Cloud Blog | `https://cloud.google.com/blog/rss` |
| Microsoft Azure Updates | `https://www.microsoft.com/en-us/azureupdate/feed` |

> **Implementation Note:** All feed URLs should be validated at startup. If a feed is unreachable (timeout or HTTP error), log the failure and continue processing remaining feeds — do not abort the entire run.

---

## 4. Functional Requirements

### 4.1 Trigger & Invocation

- **FR-01:** Cloud Scheduler invokes the Cloud Function via an authenticated HTTPS POST request once daily at **08:00 AM** (user's local timezone, configurable via Cloud Scheduler cron expression).
- **FR-02:** The Cloud Function must reject all requests that do not carry a valid Google-signed OIDC token. This is enforced at the Cloud Function IAM level (require authentication; do not allow `allUsers`).
- **FR-03:** Cloud Scheduler must use a dedicated GCP Service Account with the `roles/cloudfunctions.invoker` role to generate the OIDC token.

### 4.2 Secret Loading

- **FR-04:** At startup, the Cloud Function must load the following secrets from GCP Secret Manager using the `google-cloud-secret-manager` SDK:
  - `TELEGRAM_BOT_TOKEN` — Bot token from BotFather
  - `TELEGRAM_CHAT_ID` — Target chat ID for notifications
  - `GEMINI_API_KEY` — Google AI Studio API key for Gemini
- **FR-05:** If any secret fails to load, the function must log a critical error and exit immediately without processing any feeds.

### 4.3 Ingestion Engine

- **FR-06:** The function must iterate over all 11 configured RSS feed URLs sequentially.
- **FR-07:** Each feed is fetched using the `feedparser` Python library.
- **FR-08:** Each feed request must enforce a **10-second connection timeout**. If the feed cannot be fetched within 10 seconds, log a warning with the feed URL and source name, increment the failed-feeds counter, and proceed to the next feed.
- **FR-09:** For each feed entry, extract the following fields:
  - `article_id`: SHA-256 hash of the article URL (used as Firestore document ID)
  - `url`: Canonical article URL (`entry.link`)
  - `title`: Article title (`entry.title`)
  - `snippet`: First 2,000 characters of `entry.summary` or `entry.description` (whichever is non-empty), stripped of HTML tags
  - `published_at`: Parsed publication timestamp (ISO 8601); fall back to current UTC time if absent
  - `feed_source`: Human-readable source name (e.g., `"arXiv ML"`, `"AWS News Blog"`)
  - `feed_category`: One of `academic`, `industry`, `cloud`

### 4.4 Deduplication Logic

The deduplication check **must occur before any Gemini API call** to conserve API quota.

**Step-by-step deduplication flow:**

```
FOR each article IN feed_entries:
  1. Compute article_id = SHA-256(article.url)
  2. doc_ref = firestore.collection("processed_articles").document(article_id)
  3. snapshot = doc_ref.get()
  4. IF snapshot.exists:
       → SKIP this article (already processed)
       → Log: "SKIP [article_id] — already in Firestore"
       → continue to next article
  5. ELSE:
       → Proceed to Summarization Engine (FR-10)
```

- **FR-10:** The deduplication check is a Firestore document `.get()` operation — one read per article. This is the primary driver of Firestore read consumption.
- **FR-11:** The `processed_articles` Firestore document must be written **after** successful Telegram delivery (not before), to ensure failed deliveries can be retried on the next run.

### 4.5 Summarization Engine

- **FR-12:** For each new (non-deduplicated) article, call the Gemini API using the `google-generativeai` Python SDK.
- **FR-13:** The input text sent to Gemini must be the article's `snippet` field, already truncated to 2,000 characters (see FR-09). Do not send the full article body.
- **FR-14:** Use the following exact system prompt when initializing the Gemini model:

```
You are a highly technical AI research assistant summarizing content for a senior ML engineer.
Your task is to summarize the following article in exactly 3 concise bullet points.
Rules:
- Each bullet must be ≤20 words.
- Total summary must be ≤60 words.
- Use technical language. Do not oversimplify.
- Output ONLY the 3 bullet points in Markdown format (using • or -).
- Do NOT include a preamble, title, or closing statement.
```

- **FR-15:** If the Gemini API call fails (network error, rate limit, or non-200 response), log the error with the article ID, increment the failed-summarizations counter, and **skip sending a Telegram message** for that article. Do **not** write the article to Firestore (allowing retry on next run).
- **FR-16:** Gemini API calls must be made sequentially (not in parallel) to avoid overwhelming the free-tier rate limits.

### 4.6 Notification Delivery

- **FR-17:** For each successfully summarized article, send an individual Telegram message using the Telegram Bot API (`sendMessage` method).
- **FR-18:** Each Telegram message must be formatted using `parse_mode=MarkdownV2` with the following structure:

```
*[Article Title]*

• Bullet point one
• Bullet point two  
• Bullet point three

🔗 [Read More](https://article-url.com)
📰 Source: arXiv ML | 🏷️ Academic
```

- **FR-19:** Special characters in the article title and source must be escaped per Telegram's MarkdownV2 spec (`_`, `*`, `[`, `]`, `(`, `)`, `~`, `` ` ``, `>`, `#`, `+`, `-`, `=`, `|`, `{`, `}`, `.`, `!`).
- **FR-20:** After each Telegram API call, insert a **1-second delay** (`time.sleep(1)`) before processing the next article to respect Telegram's rate limit of 30 messages/second (conservative buffer).
- **FR-21:** If the Telegram API call fails, log the error and do **not** write the article to Firestore (allowing retry on next run). Increment the failed-deliveries counter.
- **FR-22:** Upon successful Telegram delivery, write the article document to Firestore (see Section 6 for schema).

---

## 5. Non-Functional Requirements

### 5.1 Security

| Requirement | Detail |
|-------------|--------|
| **NFR-S-01** | Cloud Function must be deployed with `--no-allow-unauthenticated`. All invocations require a valid OIDC token. |
| **NFR-S-02** | All secrets (Telegram token, Chat ID, Gemini API key) must be stored in GCP Secret Manager, never in source code, environment variables, or logs. |
| **NFR-S-03** | The Cloud Function's runtime service account must have only the minimum required IAM roles: `roles/secretmanager.secretAccessor`, `roles/datastore.user`. |
| **NFR-S-04** | No PII is stored. Firestore documents contain only article metadata (URL, title, timestamp, status). |

### 5.2 Cost Boundary

The system must operate at **$0/month** on GCP. The following table confirms free-tier alignment:

| Service | Free Tier Limit | Expected Daily Usage | Status |
|---------|----------------|---------------------|--------|
| Cloud Functions | 2M invocations/month | 1 invocation/day (30/month) | ✅ Free |
| Cloud Functions compute | 400K GB-seconds/month | ~0.5 GB-sec/day (15/month) | ✅ Free |
| Cloud Scheduler | 3 jobs/month free | 1 job | ✅ Free |
| Firestore reads | 50,000/day | ~220/day (11 feeds × ~20 articles) | ✅ Free |
| Firestore writes | 20,000/day | ~30/day | ✅ Free |
| Secret Manager versions | 6 free versions | 3 versions (3 secrets × 1 version each) | ✅ Free |
| Secret Manager accesses | 10,000/month free | 3/day × 30 = 90/month | ✅ Free |
| Gemini 2.0 Flash | 1,500 req/day | ≤50 req/day | ✅ Free |

- **NFR-C-01:** The implementation must not introduce any GCP service outside the above table without explicit sign-off.
- **NFR-C-02:** Firestore must not be used for logging or storing summaries — only for deduplication metadata — to keep write counts minimal.

### 5.3 Performance & Timeouts

- **NFR-P-01:** Cloud Function execution timeout must be set to **5 minutes** (`300s`).
- **NFR-P-02:** Each RSS feed fetch must have a **10-second per-request timeout**.
- **NFR-P-03:** The Gemini API client must use a **30-second timeout** per inference request.
- **NFR-P-04:** Sequential processing of all feeds and articles within the 5-minute window is acceptable for the expected volume. If a run exceeds 4 minutes and articles remain unprocessed, log a warning and exit gracefully (do not allow Cloud Functions to hard-timeout mid-write).

### 5.4 Reliability

- **NFR-R-01:** Any single feed failure must not abort the entire run. Errors must be isolated per feed source.
- **NFR-R-02:** Any single article's summarization failure must not abort delivery of subsequent articles.
- **NFR-R-03:** The system is idempotent by design: re-running after a partial failure will pick up articles that were not written to Firestore (because Firestore writes happen only after successful delivery).

---

## 6. Data Schema (Firestore)

### Collection: `processed_articles`

**Document ID:** SHA-256 hash of the article's canonical URL (hex-encoded string, 64 chars).

Using the URL hash as the document ID ensures:
1. O(1) deduplication check with a single `.get()` call (no queries needed).
2. Collision resistance — SHA-256 hash space is astronomically large.
3. Idempotency — re-processing the same URL always resolves to the same document.

### Document Structure

```json
{
  "article_id":       "a3f8c2...",           // string — SHA-256 of URL (same as document ID)
  "url":              "https://...",          // string — canonical article URL
  "title":            "Attention Is All...", // string — article title (raw, unescaped)
  "feed_source":      "arXiv ML",            // string — human-readable source name
  "feed_category":    "academic",            // string — enum: "academic" | "industry" | "cloud"
  "published_at":     "2026-07-24T08:00:00Z",// string — ISO 8601 UTC timestamp
  "processed_at":     "2026-07-24T08:03:12Z",// string — ISO 8601 UTC, when this doc was written
  "status":           "delivered"            // string — enum: "delivered" | "failed"
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `article_id` | `string` | SHA-256(url), hex-encoded. Redundant with doc ID but useful for queries. |
| `url` | `string` | The canonical article URL used to generate `article_id`. |
| `title` | `string` | Article title as extracted from the feed entry. |
| `feed_source` | `string` | Human-readable source label (e.g., `"AWS News Blog"`). |
| `feed_category` | `string` | Category: `"academic"`, `"industry"`, or `"cloud"`. |
| `published_at` | `string` | ISO 8601 UTC. Publication time from the feed entry; falls back to ingestion time. |
| `processed_at` | `string` | ISO 8601 UTC. Timestamp when this document was written to Firestore. |
| `status` | `string` | `"delivered"` — Telegram message sent successfully. `"failed"` — reserved for future use (currently failed articles are not written to Firestore). |

> **Note on `status`:** In the current design, only successfully delivered articles are written to Firestore (`status: "delivered"`). Articles that fail at summarization or Telegram delivery are not written, enabling natural retry on the next run. The `"failed"` enum value is reserved for a potential future explicit failure-logging mode.

---

## 7. Success Metrics & Logging

### 7.1 Structured Logging Requirements

All logs are written to **GCP Cloud Logging** using Python's `logging` module (Cloud Functions automatically captures stdout/stderr to Cloud Logging).

Each function invocation must emit the following structured log events:

#### Run Start
```json
{
  "severity": "INFO",
  "message": "FeedMind run started",
  "timestamp": "<ISO 8601>"
}
```

#### Per-Feed Result
```json
{
  "severity": "INFO",
  "message": "Feed processed",
  "feed_source": "arXiv ML",
  "feed_category": "academic",
  "entries_found": 25,
  "new_articles": 3,
  "skipped_duplicates": 22
}
```

On feed failure:
```json
{
  "severity": "WARNING",
  "message": "Feed fetch failed",
  "feed_source": "OpenAI News",
  "error": "ConnectionTimeout after 10s"
}
```

#### Per-Article Summarization
```json
{
  "severity": "INFO",
  "message": "Article summarized",
  "article_id": "a3f8c2...",
  "feed_source": "arXiv ML"
}
```

On failure:
```json
{
  "severity": "ERROR",
  "message": "Gemini summarization failed",
  "article_id": "a3f8c2...",
  "error": "<error message>"
}
```

#### Run Summary (final log line)
```json
{
  "severity": "INFO",
  "message": "FeedMind run complete",
  "feeds_checked": 11,
  "feeds_failed": 0,
  "new_articles_found": 8,
  "articles_summarized": 8,
  "articles_delivered": 7,
  "gemini_failures": 1,
  "telegram_failures": 0,
  "duration_seconds": 45.2
}
```

### 7.2 Key Metrics (Queryable in Cloud Logging)

Engineers can use Cloud Logging's **Log Explorer** with the following query to track system health:

```
resource.type="cloud_run_revision"
jsonPayload.message="FeedMind run complete"
```

Primary health indicators:
- `articles_delivered / new_articles_found` → Delivery success rate (target: ≥95%)
- `feeds_failed` → Feed availability (target: 0/day)
- `gemini_failures` → Inference reliability (target: 0/day)
- `duration_seconds` → Execution time trend (target: <240s to stay within 5-min timeout)

---

## 8. GCP Free Tier Cost Analysis

> **Target: $0.00/month total GCP cost.**

### Detailed Breakdown

**Assumptions:**
- 30 runs/month (once daily)
- Average 15 new articles/run (180 RSS entries processed, 15 new)
- Average 30 articles/feed entry processed per run (11 feeds × average 20 entries = 220 Firestore reads/run)

| Service | Metric | Monthly Volume | Free Limit | Overage Cost |
|---------|--------|---------------|------------|--------------|
| Cloud Functions | Invocations | 30 | 2,000,000 | $0.00 |
| Cloud Functions | Compute (256MB × 45s avg) | ~337 GB-sec | 400,000 GB-sec | $0.00 |
| Cloud Scheduler | Jobs | 1 | 3 | $0.00 |
| Firestore | Document reads | ~6,600 | 1,500,000 | $0.00 |
| Firestore | Document writes | ~450 | 600,000 | $0.00 |
| Secret Manager | Secret versions | 3 | 6 | $0.00 |
| Secret Manager | Access operations | 90 | 10,000 | $0.00 |
| Cloud Logging | Log ingestion | <1 MB | 50 GB | $0.00 |
| Gemini API | Requests | ~450 | 45,000 (1,500/day) | $0.00 |
| **TOTAL** | | | | **$0.00** |

---

## 9. Open Items & Future Considerations

| ID | Item | Priority |
|----|------|----------|
| OI-01 | **Validate exact RSS feed URLs** — Several feeds in the original spec used root domains (e.g., `openai.com`) rather than full RSS paths. The URLs in Section 3 are best-effort guesses and must be validated before deployment. | High |
| OI-02 | **Error alerting** — Currently, failures are only visible in Cloud Logging. A future enhancement could send a Telegram alert if a run has >2 Gemini failures. | Medium |
| OI-03 | **Article cap per run** — No hard cap is defined. If feed volumes spike (e.g., a major conference), a run could generate 50+ Telegram messages. A configurable max-articles-per-run guard should be considered. | Medium |
| OI-04 | **Firestore TTL** — Old deduplication records accumulate indefinitely. Consider adding a Firestore TTL policy to auto-delete records older than 90 days to keep the collection lean. | Low |
| OI-05 | **Local development / testing harness** — A `dry_run=True` mode that skips Telegram delivery and Firestore writes would accelerate development iteration. | Medium |
| OI-06 | **Timezone configuration** — The 8 AM trigger timezone must be confirmed and hardcoded into the Cloud Scheduler cron expression (Cloud Scheduler supports timezone-aware cron). | High |
