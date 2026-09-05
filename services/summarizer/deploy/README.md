# Deploying `feedmind_audio.py` to Cloud Functions

A runbook. Two scripts, run in order; only the second is run again after that.

```bash
./deploy/setup.sh      # once per project - APIs, service accounts, IAM, topic
./deploy/deploy.sh     # every code or config change
./deploy/publish.sh    # trigger a run by hand, any time
```

Run them from the **repo root**, not from this directory. Every setting lives in [`config.sh`](config.sh) and can be overridden from the environment, so a one-off deploy to a scratch project needs no edits:

```bash
PROJECT_ID=my-scratch REGION=europe-west1 ./deploy/deploy.sh
```

---

## How it is triggered

The function runs when a **Pub/Sub message** says there is new content — not on a clock.

```
FeedMind run ends ──publish──► feedmind-content-ready ──Eventarc──► feedmind-audio
```

Only the producing pipeline knows when its run actually finished. A schedule can only guess: too early and there is nothing to summarize, too late and the audio is stale. FeedMind publishes as its last step, once every article is safely in Firestore — announcing any earlier would race the consumer that reads that collection.

One topic carries both pipelines; the message says which:

| Publisher | Message | Runs | Status |
|---|---|---|---|
| `feed-mind` | `{"process_doc": "RSS_FEED"}` | the latest RSS batch | **wired up** |
| `paper-prism-job` | `{"process_doc": "RESEARCH_PAPERS"}` | the latest run per category | **wired up** |

An **empty message is valid** and means the default: the latest RSS batch.

Both producers publish only after their own writes have landed — FeedMind after every article is in `processed_articles`, paper-prism after the sink has written every lens to `runs`. This function reads those collections, so announcing any earlier would race it.

Neither producer's deploy manages the topic or its IAM. The topic belongs to whoever reads it, so `setup.sh` here creates it and grants both service accounts `roles/pubsub.publisher` — **run it before either publisher's first run**, or they will log a permission error (and only that: their own runs still succeed).

| Producer | Publishes when | Skips when |
|---|---|---|
| `feed-mind` | articles were delivered | zero delivered, or `ENABLE_CONTENT_READY_EVENTS = False` |
| `paper-prism-job` | at least one paper was written | zero papers, or `SINK` isn't `firestore`, or `CONTENT_READY_TOPIC` is empty |

---

## What gets deployed, and what changes on the way

`main.py` wraps `feedmind_audio.main()` in a gen2 CloudEvent function. It only translates a message into argv, so the CLI and the deployment cannot drift apart.

Three things from the local setup cannot come along:

| Local | Why it can't deploy | Replaced by |
|---|---|---|
| `pyttsx3` | The runtime has no speech engine, and buildpacks can't `apt-get` one | `FEEDMIND_TTS=cloud` → Google Text-to-Speech |
| `ffmpeg` | Same — no way to install a binary | Nothing. The TTS API returns MP3 directly |
| local Ollama | `localhost:11434` doesn't exist in the cloud | Ollama Cloud via `LLM_*` |

Everything else — the scrape, the spaCy condense, the Firestore and Storage writes — is the same code taking the same path.

---

## Prerequisites

**1. The gcloud CLI, authenticated.**

```bash
gcloud --version                    # install: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project feed-mind
```

**2. Permissions.** These scripts enable APIs, create service accounts, edit project IAM, create a topic and deploy. Project **Owner** covers it. Without Owner you need at least `serviceusage.serviceUsageAdmin`, `iam.serviceAccountAdmin`, `resourcemanager.projectIamAdmin`, `iam.serviceAccountUser`, `cloudfunctions.developer`, `run.admin`, `pubsub.admin`, `secretmanager.admin` and `storage.admin`.

**3. Billing enabled** on the project.

**4. The audio bucket exists.** `setup.sh` warns rather than creating it, because the public-read grant is a decision worth making deliberately. `feedmind_audio.py` writes `https://storage.googleapis.com/<bucket>/<blob>` URLs into Firestore, and those only resolve for anonymous readers:

```bash
gcloud storage buckets create gs://feed-mind-audio-summaries --location=us-central1
gcloud storage buckets add-iam-policy-binding gs://feed-mind-audio-summaries \
    --member=allUsers --role=roles/storage.objectViewer
```

> `roles/storage.objectViewer` on `allUsers` also grants **listing** — anyone who knows the bucket name can enumerate every summary.

---

## Step 0 — Create the LLM API key secret

The one thing the scripts won't invent for you. Get a key from <https://ollama.com/settings/keys>:

```bash
printf '%s' "$YOUR_KEY" | gcloud secrets create feedmind-llm-api-key \
    --project=feed-mind --data-file=-
```

`printf` rather than `echo` — `echo` appends a newline, which becomes part of the key and produces a puzzling `401` at runtime.

Do this **before** `setup.sh`, which grants the runtime account access to it. If you create the secret afterwards, just re-run `setup.sh`.

To rotate later, add a version rather than replacing the secret — `deploy.sh` mounts `:latest`, so no redeploy is needed, only a new instance:

```bash
printf '%s' "$NEW_KEY" | gcloud secrets versions add feedmind-llm-api-key --data-file=-
```

---

## Step 1 — `./deploy/setup.sh`

Idempotent: every step either creates something or reports that it already exists.

| It does | Detail |
|---|---|
| Enables 10 APIs | functions, run, cloudbuild, artifactregistry, eventarc, **pubsub**, texttospeech, firestore, storage, secretmanager |
| Creates two service accounts | `feedmind-audio-fn` (runtime), `feedmind-audio-invoker` (Eventarc delivery) |
| Grants `roles/datastore.user` | project-wide — Firestore has no per-collection predefined role |
| Grants `roles/storage.objectAdmin` | scoped to the one bucket |
| Grants `roles/secretmanager.secretAccessor` | on the LLM key secret |
| Grants `roles/eventarc.eventReceiver` | to the trigger account — Eventarc won't deliver without it |
| Creates the topic | `feedmind-content-ready`, 1-day message retention |
| Grants `roles/pubsub.publisher` | per topic, to `feedmind-sa`, `paper-prism-job` and the function's own runtime account |

Two identities on purpose: "may deliver an event" and "may write to Firestore" should be separate grants. Without an explicit trigger account, Eventarc falls back to the Compute Engine default service account, which is over-privileged and shared with everything else in the project.

The runtime account is a publisher because the function republishes its own trigger message when a batch needs another pass — see *Delivery semantics*.

Text-to-Speech needs no IAM role — it authorizes on the caller's credentials plus the enabled API.

**Expect warnings** if the bucket or the secret don't exist yet. They print the exact command to fix each.

---

## Step 2 — `./deploy/deploy.sh`

The first deploy takes **3–5 minutes** — Cloud Build installs spaCy and downloads the `en_core_web_sm` wheel.

It fails fast on a missing `main.py` and on an `LLM_BASE_URL` still pointing at localhost.

> **Converting an existing HTTP function.** A gen2 function's trigger type is fixed at creation — gcloud rejects an HTTP→Pub/Sub change in place. `deploy.sh` detects this, explains it, and prompts before deleting and recreating. The function is stateless, so every summary already in Firestore and Cloud Storage is untouched; only the (now unused) HTTPS URL changes. This is the one destructive step in these scripts.

After deploying it grants the trigger account `run.invoker`, then widens the push subscription's ack deadline — see below.

---

## Step 3 — Smoke test it

`dry_run` does everything except uploading and writing to Firestore, so it is safe against production data:

```bash
./deploy/publish.sh RSS_FEED --limit 1 --force --dry-run
```

Then watch it run:

```bash
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=50
```

Look for `triggered by message …` (Eventarc delivered), then `spaCy … condensed` (spaCy loaded), then `dry run - would upload` (synthesis worked). All three means the pipeline is healthy.

**Then run it for real, once**, before trusting the trigger:

```bash
./deploy/publish.sh RSS_FEED --limit 1
```

---

## Step 4 — Deploy the publishers

Both producers already carry the publishing code; they need redeploying to pick it up.

**FeedMind** (`packages/feedmind-core/feedmind_core/events.py`, called from the
ingest runner):

```bash
../../scripts/deploy-feedmind.sh
```

Publishing is best-effort — a Pub/Sub failure is logged, never raised, because failing a run that already delivered to Telegram would re-deliver every article on the retry. Disable it with `ENABLE_CONTENT_READY_EVENTS = False` in
`packages/feedmind-core/feedmind_core/settings.py`.

**paper-prism** (`services/paper-prism/src/paper_prism/events.py`, called from `__main__.py` after `pipeline.run()`). It has two deploy paths; use whichever this project treats as source of truth — running both double-creates:

```bash
cd ../../infra/terraform && terraform apply    # CONTENT_READY_TOPIC is in job_env
# or the gcloud path:
cd ../paper-prism/deploy && ./02-build-push.sh && ./03-deploy-job.sh
```

The gcloud path reads `env.yaml`; make sure `CONTENT_READY_TOPIC` is set there (it is in `env.yaml.example`). Same best-effort contract, plus one extra guard: it never publishes from a local run, because `SINK=local` writes JSON to disk and there is no consumer to tell.

Verify end to end after each producer's next run:

```bash
gcloud functions logs read feedmind --gen2 --region=us-central1 --limit=20 \
    | grep -i content-ready
gcloud run jobs executions list --job=paper-prism-job --region=us-central1 --limit=1
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=20
```

---

## Triggering it by hand

`./deploy/publish.sh` builds the JSON for you — any `feedmind_audio.py` flag passes through:

```bash
./deploy/publish.sh                                  # latest RSS batch
./deploy/publish.sh RESEARCH_PAPERS                  # latest papers
./deploy/publish.sh RESEARCH_PAPERS --category CV
./deploy/publish.sh RSS_FEED --limit 1 --dry-run
```

Or publish directly. Both a JSON body and attributes work; the body wins where they overlap:

```bash
gcloud pubsub topics publish feedmind-content-ready \
    --message='{"process_doc": "RESEARCH_PAPERS", "category": "CV", "limit": 5}'

gcloud pubsub topics publish feedmind-content-ready \
    --attribute=process_doc=RESEARCH_PAPERS,category=CV
```

| Field | Flag |
|---|---|
| `process_doc` | `--process-doc` (`RSS_FEED` \| `RESEARCH_PAPERS`) |
| `category` | `--category` (papers only) |
| `article_id` | `--article-id` — an `article_id`, or an `arxiv_id` |
| `limit` | `--limit` |
| `force` | `--force` — redo items that already have audio |
| `dry_run` | `--dry-run` |
| `timeout`, `provider`, `model`, `select_ratio`, `voice`, `rate`, `tts` | the matching flag |

A malformed message body is logged and treated as empty rather than failing — failing would only feed the identical message back through the retry.

---

## Delivery semantics

Worth understanding before something surprises you.

**Pub/Sub is at-least-once.** A message can be delivered more than once. That is safe here because the pipeline is idempotent: items that already have an `audio_url` are skipped before any scraping, so a duplicate mostly no-ops.

**A batch too large for one pass continues in the next.** An event-driven function is capped at **540 seconds** — the 3600s an HTTP function may request is simply not available, and gcloud rejects the deploy rather than clamping. At roughly a minute an article, that covers about eight.

Rather than truncate, the run stops itself at `MAX_RUNTIME` (450s), **between items** so every uploaded object has its matching Firestore write, exits `3`, and republishes its own trigger message. The next pass skips whatever now has an `audio_url` and takes the next slice. A large batch therefore drains across several invocations.

This cannot loop: continuation only follows a pass that completed at least one item, so no progress means no continuation.

**Timeouts are ordered so a slow run is never redelivered.** `MAX_RUNTIME` (450s) < `TIMEOUT` (540s) < `ACK_DEADLINE` (600s). The function always ends on its own deadline before Pub/Sub concludes the delivery failed. `deploy.sh` widens the ack deadline from Eventarc's 60s default, which would otherwise expire mid-batch.

**The function never nacks.** `on_content_ready` catches everything and returns normally. A batch that partly succeeded would otherwise redo the whole batch on redelivery, and the items it retried would be the ones least likely to succeed the second time. Failures are logged and tallied; the next run picks up whatever still lacks audio.

---

## Configuration

All in [`config.sh`](config.sh), all env-overridable.

| Variable | Default | Notes |
|---|---|---|
| `PROJECT_ID` | `feed-mind` | |
| `REGION` | `us-central1` | |
| `FUNCTION_NAME` | `feedmind-audio` | |
| `ENTRY_POINT` | `on_content_ready` | The CloudEvent handler in `main.py` |
| `TOPIC_NAME` | `feedmind-content-ready` | |
| `PUBLISHER_SERVICE_ACCOUNTS` | `feedmind-sa`, `paper-prism-job` | Space separated; granted per topic |
| `ACK_DEADLINE` | `600` | Seconds. The push-subscription maximum |
| `MESSAGE_RETENTION` | `1d` | A week-late summary is of no use |
| `RUNTIME` | `python311` | Matches the local `.venv` |
| `MEMORY` | `1Gi` | spaCy's pipeline is the floor |
| `TIMEOUT` | `540s` | **Hard ceiling for an event-driven function.** Billed for time used, not reserved |
| `MAX_RUNTIME` | `450` | Seconds. Stop starting items and continue in a new invocation |
| `CONCURRENCY` / `MAX_INSTANCES` | `1` / `1` | Papers mode rewrites the whole `papers` array — overlapping runs would clobber each other |
| `LLM_API` | `openai` | Ollama Cloud speaks the OpenAI wire format |
| `LLM_BASE_URL` | `https://ollama.com/v1` | → `POST /v1/chat/completions` |
| `LLM_MODEL` | `gpt-oss:120b` | |
| `LLM_MAX_TOKENS` | `1200` | Headroom for `gpt-oss`'s reasoning, not longer output |
| `LLM_API_KEY_SECRET` | `feedmind-llm-api-key` | Mounted as `LLM_API_KEY` |
| `TTS_VOICE` | `en-US-Neural2-F` | `gcloud text-to-speech voices list` |
| `TTS_RATE` | `175` | Words per minute |

The Ollama Cloud catalogue is public and needs no key:

```bash
curl -s https://ollama.com/v1/models | jq -r '.data[].id' | sort
```

To run exactly what the function will run, before spending a deploy on it:

```bash
LLM_API=openai LLM_BASE_URL=https://ollama.com/v1 \
LLM_MODEL=gpt-oss:120b LLM_MAX_TOKENS=1200 LLM_API_KEY=... FEEDMIND_TTS=cloud \
    .venv/bin/python feedmind_audio.py --limit 1 --force --dry-run
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Published, but the function never runs | Trigger account missing `run.invoker` or `eventarc.eventReceiver` | Re-run `./deploy/setup.sh` then `./deploy/deploy.sh` |
| A producer logs "failed to publish content-ready event" | Its SA is missing `pubsub.publisher` | Re-run `./deploy/setup.sh` |
| paper-prism never publishes, no error | `SINK` isn't `firestore`, or `CONTENT_READY_TOPIC` is empty | Check `job_env` / `env.yaml` |
| The same batch runs twice | Ack deadline expired mid-batch | Expected — see *Delivery semantics*. Shorten the batch |
| Deploy fails: trigger cannot be changed | The function still has its HTTP trigger | `deploy.sh` prompts to recreate it; answer `y` |
| `401 Unauthorized` from `ollama.com` | Key wrong, or a trailing newline from `echo` | Add a new secret version with `printf`, then redeploy |
| `the model returned an empty summary` | Reasoning consumed the whole token budget | Raise `LLM_MAX_TOKENS` |
| Deploy aborts: "LLM_BASE_URL points at localhost" | `LLM_*` still on local Ollama | Set a hosted provider in `config.sh` |
| Firestore 404 pointing at the Datastore setup page | The database is **named**, not `(default)` | Already handled in code — check `FIRESTORE_DATABASE` |
| Build fails fetching `en_core_web_sm` | The wheel URL in `requirements.txt` must match the pinned spaCy minor version | Check the version pair |
| Deploy fails: "timeout ... cannot exceed 540 seconds" | `TIMEOUT` above the event-driven cap | Lower it; `deploy.sh` now checks this before calling gcloud |
| The batch keeps re-running | Normal — it is draining a slice at a time | Watch for `more to do` in the logs; it stops when nothing is left |
| Batch never finishes draining | Each pass fails before completing an item | No progress means no continuation; fix the per-item failure |
| Changes don't take effect | Editing `config.sh` alone changes nothing deployed | Re-run `./deploy/deploy.sh` |

```bash
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=100
gcloud pubsub topics list-subscriptions feedmind-content-ready
gcloud pubsub subscriptions describe <subscription> --format='value(ackDeadlineSeconds)'
gcloud run services describe feedmind-audio --region=us-central1
```

---

## Costs

Nothing here has a standing charge — no minimum instances, no provisioned concurrency, and an idle topic is free. You pay per run:

- **Text-to-Speech**, per character. Neural2 and Studio voices cost more than Standard; switching `TTS_VOICE` is the biggest lever.
- **Ollama Cloud**, per their pricing.
- **Cloud Functions / Run**, for time actually used. The 540s timeout reserves nothing; a batch that needs several passes costs the same as one long run, plus a cold start each time.
- **Cloud Storage**, for what accumulates. The bucket has a 90-day delete lifecycle.

---

## Teardown

```bash
gcloud functions delete feedmind-audio --gen2 --region=us-central1
gcloud pubsub topics delete feedmind-content-ready

gcloud iam service-accounts delete feedmind-audio-fn@feed-mind.iam.gserviceaccount.com
gcloud iam service-accounts delete feedmind-audio-invoker@feed-mind.iam.gserviceaccount.com
gcloud secrets delete feedmind-llm-api-key
```

Deleting the function removes its Eventarc trigger and the push subscription with it.

Stop both producers too, or they will keep publishing into a topic nobody reads: `ENABLE_CONTENT_READY_EVENTS = False` in `packages/feedmind-core/feedmind_core/settings.py` (or `content_ready: false` in each ingest service's `feeds.yaml`), and `CONTENT_READY_TOPIC=""` in paper-prism's `job_env` / `env.yaml`.

This leaves the bucket and Firestore alone — they hold data, and they belong to FeedMind rather than to this deployment.

---

## Files

| File | Job |
|---|---|
| `config.sh` | Every setting, sourced by the others. Not executable — it is sourced, never run |
| `setup.sh` | APIs, service accounts, IAM, topic. Idempotent |
| `deploy.sh` | `gcloud functions deploy`, the invoker binding, the ack deadline |
| `publish.sh` | Publishes a trigger message by hand |
| `../main.py` | `on_content_ready` (Pub/Sub, deployed) and `summarize_feed` (HTTP, kept) |
| `../requirements.txt` | Runtime deps, including the spaCy model from its release wheel |
| `../.gcloudignore` | Keeps `.venv/`, `.git/` and this directory out of the upload |

On the producer side, both follow the same shape:

| Repo | Publishes from | Called by | Topic setting |
|---|---|---|---|
| FeedMind ingests | `feedmind_core/events.py` | `runner.py`, last step | `feeds.yaml` / `settings.py` |
| `paper-prism` | `pipeline/src/paper_prism/events.py` | `__main__.py`, after `pipeline.run()` | `CONTENT_READY_TOPIC` env — `infra/run.tf` and `pipeline/deploy/env.yaml` |
