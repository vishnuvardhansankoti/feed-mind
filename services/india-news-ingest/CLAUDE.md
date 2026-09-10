# services/india-news-ingest

Guidance for working inside this service. The system-level view is in the
**root `CLAUDE.md`**; read that first if you are changing anything another
component reads. Design source of truth:
`../../docs/feed-mind/news-curator-design.md`.

## What this service is

`india-news-ingest`, an **HTTP-triggered** gen2 Cloud Function on its own
Cloud Scheduler cron (17:30 `America/Chicago` — already the next day in India).
It fetches five Indian publications' front pages, dedupes by URL, and stores
every article to `processed_articles` exactly like `services/ingest` does —
same `feedmind_core.runner` and `feedmind_core.store.save_article` underneath.

It is deliberately dumb: no classification, no cross-outlet dedup, no LLM call.
That is `services/news-curator`'s job, and it runs *before* summarization on
purpose — see the design doc §3.1 for why the ordering is the whole point.

## Two feed groups, why separate

```
general.yaml   TOI + The Hindu                              -> ~106 articles
business.yaml  Business Standard + Economic Times + BLine    -> ~117 articles
```

Split because only `business.yaml`'s outlets are eligible for the curator's
detailed business sub-taxonomy (design doc §4.3) — a cluster made only of
`general.yaml` articles keeps the coarse `business` code. They share a
schedule and a cold start, so one *service* with two YAML files, same
reasoning as `services/ingest`'s three groups.

Both groups run `summarize: none`: curation embeds `title. description`
straight from the RSS feed (`Article.snippet`), never the scraped article, so
there is nothing to summarize at ingest time. This also means neither group
needs the `sumy` or `gemini` extras — see `pyproject.toml`.

## The doorbell: `feedmind-news-ingested`, not `feedmind-content-ready`

Every article is stored `telegram_status=skipped` (never sent to Telegram) and
`curation_status=pending` (`feedmind_core.settings.CURATION_PENDING`, passed
through `runner.run_rss_ingest`'s `extra_fields`). After both groups finish,
`main.py` publishes once to `feedmind-news-ingested` — a doorbell with no
payload, same shape as `feedmind-telegram-ready` — which `services/news-curator`
listens on via a Pub/Sub push subscription.

This is **not** `feedmind-content-ready`. That topic wakes
`services/summarizer` directly; publishing there from here would mean every
one of the ~223 articles a day gets an LLM call and a Cloud TTS render before
anything has deduplicated them across outlets — the exact cost problem the
curator exists to avoid (design doc §1, §3.1's cost table).

`curation_status` is this service's own bookkeeping field, not a
system-wide contract: it exists so `services/news-curator` can find its
backlog with a single-field equality filter (`== "pending"`, no composite
index needed — same trick as `fetch_pending_telegram`), the same way
`telegram_status` lets the notifier find its own. The curator flips it to
`"clustered"` once `story_id` / `is_canonical` are written.

## Commands

Run from `services/india-news-ingest/`.

```bash
uv sync
uv run python main.py               # local dry run: fetches for real, writes nothing
../../scripts/stage-service.sh india-news-ingest   # stage for deploy (copies feedmind_core in)
```

Deployed via `../../scripts/deploy-feedmind.sh india-news-ingest`, once
`../../scripts/setup-feedmind-infra.sh` has created the `feedmind-news-ingested`
topic. `requirements.txt` is **generated** from `pyproject.toml`
(`../../scripts/lock-all.sh`); `uv.lock` is committed.
