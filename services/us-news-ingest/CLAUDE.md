# services/us-news-ingest

Guidance for working inside this service. The system-level view is in the
**root `CLAUDE.md`**; read that first if you are changing anything another
component reads. Design source of truth: `../../docs/feed-mind/us-news-design.md`
(the divergences from India) and `../../docs/feed-mind/news-curator-design.md`
(the shared pipeline both countries feed).

## What this service is

`us-news-ingest`, an **HTTP-triggered** gen2 Cloud Function on its own Cloud
Scheduler cron (04:00 `America/Chicago` — overnight US news, ahead of both the
08:00 tech-blogs ingest and the 17:30 India-news ingest). It is
`services/india-news-ingest` with a different feed list and `country=US`
instead of `country=IN` — same `feedmind_core.runner` and
`feedmind_core.store.save_article` underneath, same doorbell topic, same
downstream curator.

## Why five real RSS feeds, not Google News

The obvious "just aggregate everything from one URL" choice — Google News RSS
(`news.google.com/rss`, one source, eight topics via `hl`/`gl`/`ceid`) — was
evaluated and rejected. Verified live before building this:

- **Item links don't resolve to the real article over plain HTTP.** Every
  `<link>` is `news.google.com/rss/articles/{opaque-token}?oc=5`. Following
  the redirect lands back on a client-rendered `news.google.com` SPA shell —
  there is no plain-HTTP path to the publisher's page. `services/summarizer`'s
  scraper does a plain fetch; it cannot follow this.
- **The `<description>` is not single-article text.** It's an HTML `<ol>` of
  ~3 sibling headlines from *different* outlets covering the same story —
  Google has already done a coarse cross-outlet bundle, for free, per item.
  Structurally nothing like TOI/Hindu's plain-text description that the
  embedding step (`f"{title}. {description}"`) needs.
- **`<title>` carries a `" - {Publisher}"` suffix** baked into the string.

Five real publisher feeds sidesteps all three: real article links, clean
plain-text descriptions, clean titles — the same assumptions
`services/india-news-ingest` already relies on.

## The five outlets, and why these five

| Group | Outlet | Verified (2026-09-10) |
|---|---|---|
| general | NPR News | 10 items, clean ~210-char description |
| general | CBS News | 30 items, clean ~226-char description |
| business | CNBC | 30 items, clean ~92-char description |
| business | MarketWatch | 10 items, clean ~75-char description |
| business | Fortune | 10 items, clean ~82-char description |

Rejected during the same evaluation:

- **AP News** — no working public RSS found (the common proxy mirror 403s;
  AP's own public feeds were retired some years back).
- **Reuters** — public RSS retired entirely; every candidate URL 404s.
- **Yahoo Finance** — items carry `title`/`link`/`pubDate`/`source` but **no
  per-item `<description>` at all**, so there is nothing to embed for
  classification.
- **Business Insider** (markets RSS) and **Forbes** (business RSS) — both
  return syndicated/unrelated content in their descriptions (stray
  `<link>`/CSS markup in one, Wordle-hint content in the other), not clean
  article text.

## Country isolation is the whole point of this service existing

`_EXTRA_FIELDS` stamps `country=US` on every article, alongside
`curation_status=pending` — the same `extra_fields` mechanism
`services/india-news-ingest` uses for `country=IN`. This is what lets one
shared `services/news-curator` cluster India and US articles into separate
events even when they land in the same coarse category (`business`, `sports`,
...) on the same day — see `services/news-curator/CLAUDE.md`'s
country-isolation section for the pipeline side of this contract.

**No new topic.** This publishes to the exact same `feedmind-news-ingested`
topic `india-news-ingest` uses — `news-curator`'s query
(`curation_status == "pending"`) already processes whatever is waiting
regardless of source, so a second topic would add IAM and infrastructure for
no behavioral difference.

## Commands

Run from `services/us-news-ingest/`.

```bash
uv sync
uv run python main.py               # local dry run: fetches for real, writes nothing
../../scripts/stage-service.sh us-news-ingest   # stage for deploy (copies feedmind_core in)
```

Deployed via `../../scripts/deploy-feedmind.sh us-news-ingest`. No new
`scripts/setup-feedmind-infra.sh` step is needed — the topic already exists
from `india-news-ingest`'s setup. `requirements.txt` is **generated** from
`pyproject.toml` (`../../scripts/lock-all.sh`); `uv.lock` is committed.
