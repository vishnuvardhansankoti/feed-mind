## Technical PRD: Dynamic Web-to-RSS Bridge Engine

### 1. Overview & Objectives

Many digital newspapers and media outlets do not publish native RSS or Atom feeds, or lock updates behind client-rendered single-page applications. This system provides an automated pipeline that periodically scrapes targeted web pages, extracts structured metadata (headlines, URLs, publication dates, summaries, authors), deduplicates items against an internal datastore, and serves validated RSS 2.0 and Atom feeds.

**Core Objectives:**

* Provide declarative, configuration-driven scrapers for static and JavaScript-rendered newspaper layouts.
* Normalize heterogeneous DOM data into standard syndication formats (`RSS 2.0`, `Atom 1.0`, `JSON Feed`).
* Prevent duplicate entries across feed runs using deterministic item fingerprinting.
* Maintain minimal resource overhead and adhere to respectful crawl politeness.

---

### 2. Architecture & Data Flow

The engine consists of four decoupled modules executed on a scheduled loop or an on-demand cache-refresh trigger:

```
[Target Newspaper] 
       │
       ▼
[1. Ingestion Layer] ──► (Static HTTP Client / Headless Browser Fallback)
       │
       ▼
[2. Parser & Normalizer] ──► (CSS/XPath Extraction + Heuristic Fallback)
       │
       ▼
[3. Deduplication & State] ──► (Key-Value State Store: SQLite / Redis)
       │
       ▼
[4. Feed Serializer] ──► (Valid RSS 2.0 / Atom Generator) ──► [HTTP Endpoint / Static S3/R2]

```

---

### 3. Functional Requirements

#### 3.1 Fetching & Execution Modes

* **Static HTTP Fetcher:** Issues standard HTTP `GET` requests with configurable headers (custom `User-Agent`, `Accept-Language`, compressed transfer encodings). Used for standard SSR/HTML pages.
* **Headless Dynamic Fetcher:** Spawns a headless browser instance (Chromium via Playwright/Puppeteer) when target sites require client-side JavaScript execution or hydrate via client-side frameworks.
* **Robots & Politeness:**
* Enforce domain-specific rate limits (default: minimum 1.5 seconds between requests).
* Exponential backoff on HTTP `429 Too Many Requests` or `503 Service Unavailable`.
* Configurable jitter on scheduled intervals to prevent synchronized traffic bursts.



#### 3.2 Declarative Target Configuration

Each newspaper target must be defined in a version-controlled YAML or JSON manifest:

```yaml
id: "the-morning-post"
name: "The Morning Post - National News"
url: "https://example.com/section/national"
fetch_strategy: "static" # "static" | "dynamic"
schedule: "*/30 * * * *" # Every 30 minutes
selectors:
  item_container: "article.story-card"
  title: "h2.headline a"
  link: "h2.headline a::attr(href)"
  summary: "p.summary, .excerpt"
  published_at: "time::attr(datetime), .byline time"
  author: ".byline span.author"
  image: "figure img::attr(src)"
fallbacks:
  use_sitemap: true
  sitemap_url: "https://example.com/sitemap-news.xml"

```

#### 3.3 Extraction & Heuristic Fallbacks

* **Primary Path:** Extract values using the configured CSS selectors or XPath expressions.
* **Automatic Base URL Resolution:** Automatically convert relative URIs (`/news/2026/world-event`) to absolute URLs based on the target document base.
* **Timestamp Normalizer:** Parse both ISO-8601 strings and relative human timestamps (e.g., `"2 hours ago"`, `"Yesterday"`, `"Updated 15m ago"`) into standard UTC `RFC 822` (for RSS) or `RFC 3339` (for Atom).
* **Open Graph / Meta Fallback:** If specific container elements are missing, attempt extraction from standard microdata tags (`og:title`, `og:description`, `article:published_time`).

#### 3.4 State Management & Deduplication

* Generate a deterministic GUID for every article:

$$\text{GUID} = \text{SHA-256}(\text{canonical\_url})$$


* If `canonical_url` is unstable or contains dynamic query parameters (e.g., `utm_*` trackers), clean the URL before hashing.
* Maintain a rolling historical window (e.g., 90 days or last 500 items per feed) in the state database to prevent old items from reappearing when their position changes on the homepage.

#### 3.5 Feed Generation & Output

* Output valid XML conforming to the **RSS 2.0** specification (`application/rss+xml`).
* Support conditional `GET` requests (`ETag` and `If-Modified-Since` headers) to minimize bandwidth on consuming feed readers.

---

### 4. Data Models

#### Internal Article Schema

```json
{
  "guid": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "feed_id": "the-morning-post",
  "title": "Global Accord Signed on Oceanic Conservation",
  "link": "https://example.com/national/ocean-accord-2026",
  "summary": "Delegates from 40 nations ratified the treaty late Tuesday evening.",
  "content_html": "<p>Full or excerpted text...</p>",
  "published_at": "2026-09-08T18:30:00Z",
  "author": "Jane Doe",
  "image_url": "https://example.com/images/accord.jpg",
  "created_at": "2026-09-08T19:00:15Z"
}

```

#### Database Entities (SQLite / Relational Schema)

| Table | Column | Type | Constraints |
| --- | --- | --- | --- |
| **`feeds`** | `id` | VARCHAR(64) | PRIMARY KEY |
|  | `name` | VARCHAR(255) | NOT NULL |
|  | `target_url` | TEXT | NOT NULL |
|  | `config_json` | TEXT | NOT NULL |
|  | `last_fetched_at` | TIMESTAMP | NULL |
|  | `status` | VARCHAR(32) | NOT NULL DEFAULT 'active' |
| **`articles`** | `guid` | VARCHAR(64) | PRIMARY KEY |
|  | `feed_id` | VARCHAR(64) | FOREIGN KEY (`feeds.id`) |
|  | `canonical_url` | TEXT | NOT NULL |
|  | `title` | TEXT | NOT NULL |
|  | `summary` | TEXT | NULL |
|  | `published_at` | TIMESTAMP | NOT NULL |
|  | `first_seen_at` | TIMESTAMP | NOT NULL DEFAULT CURRENT_TIMESTAMP |

---

### 5. Non-Functional Requirements

| Category | Requirement | Target Metric |
| --- | --- | --- |
| **Performance** | Static scraping cycle duration | < 800ms per target URL |
|  | Headless rendering cycle duration | < 4.5s per target page |
|  | Feed endpoint response latency (cached) | < 50ms (p95) |
| **Reliability** | Parser error tolerance | A single missing field must not abort extraction of other items |
|  | Consecutive failure circuit breaker | Disable target after 10 consecutive failures; emit notification |
| **Compliance** | User-Agent identification | Clear identifier with contact URL in user agent header |
| **Storage** | Footprint per 100 configured feeds | < 500 MB (pruning items older than 90 days) |

---

### 6. Edge Cases & Failure Mitigation

* **DOM Layout Shifts:** When newspapers redesign, CSS selectors fail silently (resulting in 0 items found).
* *Mitigation:* Alert if a scrape run yields 0 items when the target HTTP status is 200. Revert to a generic readability/heuristic engine (e.g., Mozilla Readability or metadata tags) until selectors are updated.


* **Paywalls & Soft Modals:** Newsletter pop-ups or paywall overlays that block rendering.
* *Mitigation:* In dynamic fetcher mode, inject blocking rules for third-party analytics and modal scripts, or parse server-rendered HTML payloads before client-side hydration scripts lock the DOM.


* **Dynamic Query Strings:** Newspapers embedding session tokens or click identifiers in article URLs (`?ref=home&session_id=123`).
* *Mitigation:* Apply canonical URL cleaning (stripping query parameters matching `utm_*`, `ref`, `source`, `session_id`) prior to generating item GUIDs.


* **Missing Publication Dates:** Articles without explicit timestamps.
* *Mitigation:* Fall back to the HTTP `Last-Modified` header, sitemap timestamp, or default to `first_seen_at` time in UTC.