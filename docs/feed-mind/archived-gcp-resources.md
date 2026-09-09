# Archived: legacy GCP resources to delete

These exist **in GCP only** — nothing in this repo deploys them any more. They
are the pre-split single-function setup, replaced by `services/ingest`,
`services/telegram-notifier` and `services/archive`.

Delete them **before** running the new infra. If both the old daily trigger and
the new one are enabled, they both fire at 08:00 and split the day's articles
between them — the old function sends its own digest, the new one stores
articles for the notifier, and you get two partial digests.

## What to delete

| Resource | Kind | Replaced by |
|---|---|---|
| `feedmind` | Cloud Function gen2 | `feedmind-ingest` + `feedmind-telegram-notifier` |
| `feedmind-daily-trigger` | Cloud Scheduler job | `feedmind-ingest-job` |
| `feedmind-archive-biweekly` | Cloud Scheduler job | `feedmind-archive-job` |

**`feedmind-archive` (the function) is NOT on this list.** The new deploy script
keeps the same name, so it updates in place rather than creating a duplicate.
Only its *scheduler job* is renamed — leave both jobs enabled and the archive
runs twice on the 1st and 16th. That is harmless (the MERGE is idempotent) but
it doubles the Firestore read cost, ~20k against a 50k/day free tier.

## Order

```bash
PROJECT=feed-mind
REGION=us-central1

# 1. Stop the old daily run first. Reversible, and on its own this is enough to
#    make the cutover safe — everything below can wait until you have seen a
#    good digest from the new pipeline.
gcloud scheduler jobs pause feedmind-daily-trigger --location=$REGION --project=$PROJECT

# 2. Deploy the new pipeline and verify.
./scripts/setup-feedmind-infra.sh
./scripts/deploy-feedmind.sh
gcloud scheduler jobs run feedmind-ingest-job --location=$REGION --project=$PROJECT
gcloud functions logs read feedmind-telegram-notifier --gen2 --region=$REGION --limit=30

# 3. Only once a real digest has arrived, delete for good.
gcloud scheduler jobs delete feedmind-daily-trigger      --location=$REGION --project=$PROJECT
gcloud scheduler jobs delete feedmind-archive-biweekly   --location=$REGION --project=$PROJECT
gcloud functions delete feedmind --gen2 --region=$REGION --project=$PROJECT
```

## What is safe to leave alone

- **Service accounts** `feedmind-sa` and `feedmind-scheduler` — reused unchanged
  by the new functions.
- **Secrets** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GEMINI_API_KEY` — same.
- **The `feedmind-content-ready` topic** — still the summarizer's trigger, still
  published by `services/ingest` and `services/paper-prism`.
- **Firestore documents written by the old function.** They have no
  `telegram_status` field, so the notifier's `== "pending"` query ignores them
  entirely. No backfill is needed, and none should be done — they were already
  delivered.
- **BigQuery rows already archived.** They carry `status: "delivered"`; rows
  written from now on carry `status: "stored"`. That is how you tell which
  pipeline produced a row.
