# FeedMind — Deployment runbook: India/US news pipeline

**Status: deployed.** Steps 0-9 below have all been run against the `feed-mind`
project. Kept as a historical record of what shipped and in what order, and as
the template for the next service this pipeline gets extended to.

Covers the work built in this session: `services/india-news-ingest`,
`services/us-news-ingest`, `services/news-curator`, the `NEWS_STORIES`
pipeline in `services/summarizer`, the `stories` table in the BigQuery
archive, and the country toggle in `apps/web`.

## 0. Sanity check (safe, no infra change)

```bash
./scripts/test-all.sh && uvx ruff check .
gcloud config get-value project   # confirm you're pointed at feed-mind
```

## 1. Firestore rules + composite index — deploy first

The `stories` composite index (`country`, `coarse_category`, `run_date`,
`rank`) should be live before real data starts flowing, so the News tab
never shows a broken query mid-rollout. Composite indexes take a few
minutes to build asynchronously.

```bash
firebase deploy --only firestore:rules,firestore:indexes

# check build status:
gcloud firestore indexes composite list --database=feed-mind-db --project=feed-mind
```

## 2. Re-run the shared FeedMind infra setup (idempotent)

Creates the new `feedmind-news-ingested` topic (the only genuinely new
shared resource).

```bash
./scripts/setup-feedmind-infra.sh
```

## 3. Deploy the three affected FeedMind Cloud Functions

```bash
./scripts/deploy-feedmind.sh ingest              # picks up the topstories.yaml retirement
./scripts/deploy-feedmind.sh india-news-ingest   # new
./scripts/deploy-feedmind.sh us-news-ingest      # new
```

Each call also wires its own Cloud Scheduler job (17:30 CT and 04:00 CT
respectively) — no separate `--schedulers` pass needed.

## 4. Deploy `services/news-curator` (Cloud Run)

```bash
cd services/news-curator
export PROJECT_ID=feed-mind
./deploy/01-setup.sh          # creates news-curator's SA + push SA; checks the doorbell topic exists (step 2)
./deploy/02-build-push.sh     # Cloud Build -> Artifact Registry
./deploy/03-deploy-service.sh
./deploy/04-push-subscription.sh   # wires the Pub/Sub push subscription — needs the service URL, hence last
cd ../..
```

## 5. Grant news-curator publisher rights on `feedmind-content-ready`

`services/summarizer/deploy/setup.sh` grants this — but only to service
accounts that already exist. Since `news-curator@...` was just created in
step 4, re-run it now.

```bash
cd services/summarizer
export PROJECT_ID=feed-mind
./deploy/setup.sh
```

## 6. Redeploy `services/summarizer`

Picks up the `NEWS_STORIES` collector.

```bash
./deploy/deploy.sh
cd ../..
```

## 7. BigQuery migration — check this before redeploying archive

`archival.py`'s `ensure_dataset_and_tables` only **creates** tables, never
alters existing ones (its own docstring says so). The `stories` table is
brand new, so it will be created correctly with `country` included — no
action needed. But if `feedmind_archive.articles` **already exists** from a
prior deploy, the archive job's `MERGE` will start failing on the new
`country` column unless you add it first.

```bash
# Only if this table already exists — check first:
bq show feed-mind:feedmind_archive.articles

# If it exists, add the column before redeploying archive:
bq query --use_legacy_sql=false \
  'ALTER TABLE `feed-mind.feedmind_archive.articles` ADD COLUMN IF NOT EXISTS country STRING'
```

Then redeploy:

```bash
./scripts/deploy-feedmind.sh archive
```

## 8. Rebuild and redeploy `apps/web`

```bash
cd apps/web
npm run build          # prod mode: firestore data source, real Firebase keys
firebase deploy --only hosting
cd ..
```

## 9. Smoke test end to end

```bash
gcloud scheduler jobs run feedmind-india-news-ingest-job --location=us-central1 --project=feed-mind
gcloud scheduler jobs run feedmind-us-news-ingest-job --location=us-central1 --project=feed-mind

gcloud functions logs read feedmind-india-news-ingest --gen2 --region=us-central1 --limit=50
gcloud functions logs read feedmind-us-news-ingest --gen2 --region=us-central1 --limit=50
gcloud run services logs read news-curator --region=us-central1 --project=feed-mind --limit=50
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=50
```

Then check: `stories` docs appearing in the Firestore console,
`is_canonical`/`story_id` stamped on `processed_articles`, and finally the
India/US toggle on the deployed web app.

## Post-deploy fix: `processed_articles` volume collision

Once step 3's `india-news-ingest`/`us-news-ingest` started writing real
volume, the "AI Cloud Blogs" tab (`academic`/`industry`/`cloud`) went empty.
`apps/web`'s `getNews()` reads the last 200 `processed_articles` docs by
`processed_at` with no `feed_category` filter — a query that was only ever
safe because that collection used to hold tech-blog docs exclusively.
India (~223 articles/run) and US (~88/run) news write into the *same*
collection at far higher volume, so their docs filled the entire 200-doc
window and pushed every tech-blog article out of it.

Fixed by scoping the query to `feed_category in [academic, industry, cloud]`
(`apps/web/src/lib/data.js::firestoreNews()`, `constants.js::NEWS_CATEGORY_RSS_CODES`),
plus the composite index that filter requires
(`infra/firebase/firestore.indexes.json`, `processed_articles`:
`feed_category` asc + `processed_at` desc). Both are deployed; the fix is
live. Anyone adding a fourth ingest service into `processed_articles` should
check this query isn't due for the same treatment again.

## Open item (deferred, not part of this rollout)

Splitting `feedmind-audio` into two independent deployments for Ollama
quota isolation between the tech-blogs and news-story summarization
batches was discussed and deferred ("leave it as is for now"). This
runbook keeps that as one shared deployment. Revisit separately if needed.
