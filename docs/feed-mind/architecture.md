# FeedMind: five functions, one core package

How the RSS side of this repo is put together, and why. The system-level view
across all components is in the root [`CLAUDE.md`](../../CLAUDE.md).

## The shape

```
packages/          ┌─ services/ingest ────────────┐ 08:00
feedmind-core ─────┼─ services/telegram-notifier ─┤ Pub/Sub
(copied in at      └─ services/archive ───────────┘ 1st & 16th
 deploy time)
```

`services/ingest` runs three feed groups — `news.yaml`, `topstories.yaml`,
`youtube.yaml` — then rings the notifier's doorbell **once**, after all three
are stored. The groups are separate files because they behave differently: only
`news` goes to Telegram, only the RSS groups are summarized. The pipeline
itself lives once, in the package.

## Why it was split

The predecessor was a single 531-line `feedmind` function that fetched every
feed, summarized, sent Telegram messages and wrote Firestore. Three problems,
in order of how much they actually hurt:

1. **A Telegram failure cost the ingest.** Firestore was written only after
   delivery succeeded, so an outage meant the articles were re-fetched and
   re-summarized next run. This is the one that mattered, and it is why
   delivery is a separate function.
2. **Feed lists were code.** `config.RSS_FEEDS` was imported by every module, so
   adding a feed touched a file the archiver also depended on. They are data
   now, validated on load.

Ingest itself stayed a single function on a single 08:00 schedule — splitting it
per feed group bought separate cron entries and nothing else, at the cost of
three cold starts and three deploys.

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

**Delete the legacy resources first** — see
[`archived-gcp-resources.md`](archived-gcp-resources.md). The old `feedmind`
function and its `feedmind-daily-trigger` job also fire at 08:00, and leaving
them enabled splits the day's articles across two partial digests.

```bash
./scripts/setup-feedmind-infra.sh    # once: APIs, SAs, IAM, the topic
./scripts/deploy-feedmind.sh         # all three, plus Scheduler jobs
./scripts/deploy-feedmind.sh ingest
```

The notifier is deployed with `--max-instances=1` and a 600s ack deadline. Both
are load-bearing: Eventarc's 60s default is shorter than a digest run with a
backlog, and a redelivery mid-run would send the whole digest a second time.

`gcloud functions deploy --source` uploads one directory, and
`packages/feedmind-core` lives outside every service — so
`scripts/stage-service.sh` assembles a `.build/` directory per function with the
package copied in beside `main.py`. Publishing the package to Artifact Registry
was the alternative; it was rejected because it adds a registry, Cloud Build
auth and a publish-before-deploy step in exchange for version skew nobody wants.

## Adding a feed group

Drop a YAML file in `services/ingest/` and add it to `GROUPS` in `main.py`. The
core package's `tests/test_service_configs.py` walks `services/ingest/*.yaml`,
so it is validated with no test to write.

## Adding a whole ingest service on its own schedule

Only worth it if the new work genuinely needs a different cron or a different
timeout — otherwise it is a group.

1. `mkdir services/<name>` with its YAML, a `main.py` (copy `services/ingest`),
   a `pyproject.toml` naming the extras it needs, and a `.gcloudignore`.
2. Add it to the `SERVICES` table in `scripts/deploy-feedmind.sh`.
3. Add it to the loops in `scripts/lock-all.sh` and `scripts/test-all.sh`, and
   to the choice list in `.github/workflows/deploy-feedmind.yml`.
