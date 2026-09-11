FeedMind — Deployment runbook: India/US news pipeline
======================================================

Covers the work built in this session: services/india-news-ingest,
services/us-news-ingest, services/news-curator, the NEWS_STORIES pipeline
in services/summarizer, the stories table in the BigQuery archive, and the
country toggle in apps/web. Nothing in this list has been run yet — follow
it in order, top to bottom. Each step names the thing it depends on from
the step above it.


0. Sanity check (safe, no infra change)
----------------------------------------
./scripts/test-all.sh && uvx ruff check .
gcloud config get-value project   # confirm you're pointed at feed-mind


1. Firestore rules + composite index — deploy first
----------------------------------------------------
The `stories` composite index (country, coarse_category, run_date, rank)
should be live before real data starts flowing, so the News tab never shows
a broken query mid-rollout. Composite indexes take a few minutes to build
asynchronously.

firebase deploy --only firestore:rules,firestore:indexes

# check build status:
gcloud firestore indexes composite list --database=feed-mind-db --project=feed-mind


2. Re-run the shared FeedMind infra setup (idempotent)
---------------------------------------------------------
Creates the new feedmind-news-ingested topic (the only genuinely new shared
resource).

./scripts/setup-feedmind-infra.sh


3. Deploy the three affected FeedMind Cloud Functions
--------------------------------------------------------
./scripts/deploy-feedmind.sh ingest              # picks up the topstories.yaml retirement
./scripts/deploy-feedmind.sh india-news-ingest   # new
./scripts/deploy-feedmind.sh us-news-ingest      # new

Each call also wires its own Cloud Scheduler job (17:30 CT and 04:00 CT
respectively) — no separate --schedulers pass needed.


4. Deploy services/news-curator (Cloud Run)
----------------------------------------------
cd services/news-curator
export PROJECT_ID=feed-mind
./deploy/01-setup.sh          # creates news-curator's SA + push SA; checks the doorbell topic exists (step 2)
./deploy/02-build-push.sh     # Cloud Build -> Artifact Registry
./deploy/03-deploy-service.sh
./deploy/04-push-subscription.sh   # wires the Pub/Sub push subscription — needs the service URL, hence last
cd ../..


5. Grant news-curator publisher rights on feedmind-content-ready
----------------------------------------------------------------
services/summarizer/deploy/setup.sh grants this — but only to service
accounts that already exist. Since news-curator@... was just created in
step 4, re-run it now.

cd services/summarizer
export PROJECT_ID=feed-mind
./deploy/setup.sh


6. Redeploy services/summarizer
------------------------------------
Picks up the NEWS_STORIES collector.

./deploy/deploy.sh
cd ../..


7. BigQuery migration — check this before redeploying archive
---------------------------------------------------------------
archival.py's ensure_dataset_and_tables only CREATES tables, never alters
existing ones (its own docstring says so). The `stories` table is brand
new, so it will be created correctly with `country` included — no action
needed. But if feedmind_archive.articles ALREADY EXISTS from a prior
deploy, the archive job's MERGE will start failing on the new `country`
column unless you add it first.

# Only if this table already exists — check first:
bq show feed-mind:feedmind_archive.articles

# If it exists, add the column before redeploying archive:
bq query --use_legacy_sql=false \
  'ALTER TABLE `feed-mind.feedmind_archive.articles` ADD COLUMN IF NOT EXISTS country STRING'

Then redeploy:

./scripts/deploy-feedmind.sh archive


8. Rebuild and redeploy apps/web
-------------------------------------
cd apps/web
npm run build          # prod mode: firestore data source, real Firebase keys
firebase deploy --only hosting
cd ..


9. Smoke test end to end
-----------------------------
gcloud scheduler jobs run feedmind-india-news-ingest-job --location=us-central1 --project=feed-mind
gcloud scheduler jobs run feedmind-us-news-ingest-job --location=us-central1 --project=feed-mind

gcloud functions logs read feedmind-india-news-ingest --gen2 --region=us-central1 --limit=50
gcloud functions logs read feedmind-us-news-ingest --gen2 --region=us-central1 --limit=50
gcloud run services logs read news-curator --region=us-central1 --project=feed-mind --limit=50
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=50

Then check: `stories` docs appearing in the Firestore console,
is_canonical/story_id stamped on processed_articles, and finally the
India/US toggle on the deployed web app.


Open item (deferred, not part of this rollout)
---------------------------------------------------
Splitting feedmind-audio into two independent deployments for Ollama quota
isolation between the tech-blogs and news-story summarization batches was
discussed and deferred ("leave it as is for now"). This runbook keeps that
as one shared deployment. Revisit separately if needed.
