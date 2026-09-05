# FeedMind: five functions, one core package

How the RSS side of this repo is put together, and why. The system-level view
across all components is in the root [`CLAUDE.md`](../../CLAUDE.md).

## The shape

```
                  ┌─ services/news-ingest ────────┐ 08:00
packages/         ├─ services/topstories-ingest ──┤ 08:00
feedmind-core ────┼─ services/youtube-ingest ─────┤ 08:00
(copied in at     ├─ services/telegram-notifier ──┤ Pub/Sub
 deploy time)     └─ services/archive ────────────┘ 1st & 16th
```

Each service is a `feeds.yaml`, a Cloud Scheduler cron, and a `main.py` that
loads the config and calls the runner. The pipeline itself lives once, in the
package.

## Why it was split

The predecessor was a single 531-line `feedmind` function that fetched every
feed, summarized, sent Telegram messages and wrote Firestore. Three problems,
in order of how much they actually hurt:

1. **One schedule for everything.** YouTube ingest and the news digest had to
   run at the same time because they were the same function.
2. **A Telegram failure cost the ingest.** Firestore was written only after
   delivery succeeded, so an outage meant the articles were re-fetched and
   re-summarized next run.
3. **Feed lists were code.** `config.RSS_FEEDS` was imported by every module, so
   adding a feed touched a file the archiver also depended on.

## What changed, and what that cost

Splitting ingest from delivery **inverted the write ordering**, which was load-
bearing. The document has to exist before the notifier can read it, so
"document exists" no longer means "delivered". Delivery state became the
explicit `telegram_status` field, and the retry property was rebuilt on top of
it: the notifier queries for `pending` rather than trusting its trigger message,
so a dropped message, a crash or a Telegram outage costs a delay rather than
articles.

The full contract, including the three rules that keep it safe, is in the root
`CLAUDE.md` under "The Telegram delivery contract".

**What it cost:** one extra Firestore write per article, and the possibility of
a duplicate digest entry when delivery succeeds but the status flip does not.
Both were accepted deliberately — a repeated entry is a nuisance, a dropped one
is invisible.

## Deploying

```bash
./scripts/setup-feedmind-infra.sh    # once: APIs, SAs, IAM, the topic
./scripts/deploy-feedmind.sh         # all five, plus Scheduler jobs
./scripts/deploy-feedmind.sh news-ingest
```

`gcloud functions deploy --source` uploads one directory, and
`packages/feedmind-core` lives outside every service — so
`scripts/stage-service.sh` assembles a `.build/` directory per function with the
package copied in beside `main.py`. Publishing the package to Artifact Registry
was the alternative; it was rejected because it adds a registry, Cloud Build
auth and a publish-before-deploy step in exchange for version skew nobody wants.

## Adding a fourth ingest service

1. `mkdir services/<name>` with a `feeds.yaml`, a `main.py` (copy the shortest
   existing one), a `pyproject.toml` naming the extras it needs, and a
   `.gcloudignore`.
2. Add it to the `SERVICES` table in `scripts/deploy-feedmind.sh`.
3. Add it to the loops in `scripts/lock-all.sh` and `scripts/test-all.sh`, and
   to the choice list in `.github/workflows/deploy-feedmind.yml`.
4. `./scripts/lock-all.sh && ./scripts/test-all.sh`.

The core package's `tests/test_service_configs.py` walks `services/*/feeds.yaml`
automatically, so the new config is validated with no test to write.
