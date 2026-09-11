# Deploying `feedmind_audio.py` to Cloud Run

A runbook. Four scripts, run once in order; only `03` is run again after that.

```bash
./deploy/01-setup.sh              # once per project - APIs, Artifact Registry, SAs, IAM
./deploy/02-build-push.sh         # build + push the image (Cloud Build, so it's always linux/amd64)
./deploy/03-deploy-service.sh     # every code or config change
./deploy/04-push-subscription.sh  # once - wires the Pub/Sub push subscription
./deploy/publish.sh               # trigger a run by hand, any time
```

Run them from the **repo root**, not from this directory. Every setting lives in [`00-config.sh`](00-config.sh) and can be overridden from the environment, so a one-off deploy to a scratch project needs no edits:

```bash
PROJECT_ID=my-scratch REGION=europe-west1 ./deploy/03-deploy-service.sh
```

---

## How it is triggered

The service runs when a **Pub/Sub message** says there is new content — not on a clock.

```
FeedMind run ends ──publish──► feedmind-content-ready ──push──► feedmind-audio
```

Only the producing pipeline knows when its run actually finished. A schedule can only guess: too early and there is nothing to summarize, too late and the audio is stale. FeedMind publishes as its last step, once every article is safely in Firestore — announcing any earlier would race the consumer that reads that collection.

One topic carries three pipelines; the message says which:

| Publisher | Message | Runs | Status |
|---|---|---|---|
| `feed-mind` | `{"process_doc": "RSS_FEED"}` | the latest RSS batch | **wired up** |
| `paper-prism-job` | `{"process_doc": "RESEARCH_PAPERS"}` | the latest run per category | **wired up** |
| `news-curator` | `{"process_doc": "NEWS_STORIES"}` | every canonical article not yet summarized | **wired up** |

An **empty message is valid** and means the default: the latest RSS batch.

Each producer publishes only after its own writes have landed. This service reads those collections, so announcing any earlier would race it.

No publisher's own deploy manages the topic or its IAM. The topic belongs to whoever reads it, so `01-setup.sh` here only checks it exists and grants each producer's SA `roles/pubsub.publisher` — **run it before any publisher's first run**, or they will log a permission error (and only that: their own runs still succeed).

The topic itself (`feedmind-content-ready`) is created by the gen2-function-era `deploy/setup.sh` originally and now simply persists — nothing in the Cloud Run path creates topics, only subscriptions.

---

## What gets deployed, and what changes on the way

`main.py` wraps `feedmind_audio.main()` in a `functions-framework` CloudEvent handler, run standalone inside a Cloud Run container (not through Cloud Functions at all — see the Dockerfile). It only translates a message into argv, so the CLI and the deployment cannot drift apart.

Two things from the local setup work differently, deliberately kept as **both** options rather than one replacing the other:

| Local | On Cloud Run | Selected by |
|---|---|---|
| `pyttsx3` (macOS/Windows driver) | `espeak-ng`, invoked as a **direct subprocess** — not through pyttsx3. pyttsx3's Linux driver is not safe to call off the process's main thread, and `functions-framework`'s CloudEvent dispatch always runs the handler on a spawned thread. Confirmed the hard way (see Troubleshooting). | `FEEDMIND_TTS=local` |
| Google Text-to-Speech | unchanged | `FEEDMIND_TTS=cloud` (the deployed default) |

Both backends ship in the same image; flipping between them is a config update (`gcloud run services update ... --update-env-vars=FEEDMIND_TTS=...`), never a rebuild. See `../../../docs/feed-mind/tts-switch.md`.

**Local Ollama** still can't come along — the deployment points `LLM_*` at **Ollama Cloud** instead, which keeps the model catalogue familiar.

Everything else — the scrape, the spaCy condense, the Firestore and Storage writes — is the same code taking the same path.

---

## Prerequisites

**1. The gcloud CLI, authenticated.**

```bash
gcloud --version                    # install: https://cloud.google.com/sdk/docs/install
gcloud auth login
gcloud config set project feed-mind
```

**2. Permissions.** These scripts enable APIs, create service accounts, edit project IAM, build and deploy a container, and create a Pub/Sub subscription. Project **Owner** covers it. Without Owner you need at least `serviceusage.serviceUsageAdmin`, `iam.serviceAccountAdmin`, `resourcemanager.projectIamAdmin`, `iam.serviceAccountUser`, `run.admin`, `pubsub.admin`, `secretmanager.admin`, `artifactregistry.admin`, `cloudbuild.builds.editor` and `storage.admin`.

**3. Billing enabled** on the project.

**4. The audio bucket exists.** `01-setup.sh` warns rather than creating it, because the public-read grant is a decision worth making deliberately. `feedmind_audio.py` writes `https://storage.googleapis.com/<bucket>/<blob>` URLs into Firestore, and those only resolve for anonymous readers:

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

Do this **before** `01-setup.sh`, which grants the runtime account access to it. If you create the secret afterwards, just re-run `01-setup.sh`.

To rotate later, add a version rather than replacing the secret — `03-deploy-service.sh` mounts `:latest`, so a new revision picks it up with no code change:

```bash
printf '%s' "$NEW_KEY" | gcloud secrets versions add feedmind-llm-api-key --data-file=-
```

---

## Step 1 — `./deploy/01-setup.sh`

Idempotent: every step either creates something or reports that it already exists.

| It does | Detail |
|---|---|
| Enables APIs | run, artifactregistry, pubsub, firestore, storage, secretmanager, texttospeech, cloudbuild |
| Creates the Artifact Registry repo | `feedmind-audio` |
| Creates two service accounts | `feedmind-audio-fn` (runtime), `feedmind-audio-invoker` (Pub/Sub push delivery) |
| Grants `roles/datastore.user` | project-wide — Firestore has no per-collection predefined role |
| Grants `roles/storage.objectAdmin` | scoped to the one bucket |
| Grants `roles/secretmanager.secretAccessor` | on the LLM key and (if it exists) VAPID key secrets |
| **Grants `roles/iam.serviceAccountTokenCreator`** | to Pub/Sub's own service agent, **on** `feedmind-audio-invoker` |
| Grants `roles/pubsub.publisher` | per topic, to `feedmind-sa`, `paper-prism-job`, `news-curator` and the service's own runtime account |

The `serviceAccountTokenCreator` grant is the one easy to miss and the one that fails silently: a Pub/Sub **push** subscription's `--push-auth-service-account` only actually works if Pub/Sub's service agent can mint an OIDC token *as* that account. Without this grant, `gcloud pubsub subscriptions create` still succeeds, the subscription looks healthy, and every single push then 403s with "The request was not authenticated" — not a bad-token error, a no-token error. This is not hypothetical: it was found by checking Cloud Run's raw request logs directly, after `news-curator`'s own push subscription had been silently failing on 100% of real deliveries since it was first deployed, with zero errors visible anywhere except that log.

Two identities on purpose: "may deliver a push" and "may write to Firestore" should be separate grants.

Text-to-Speech needs no IAM role — it authorizes on the caller's credentials plus the enabled API.

**Expect warnings** if the bucket, the topic, or the secret don't exist yet. They print the exact command to fix each.

---

## Step 2 — `./deploy/02-build-push.sh`

Builds with Cloud Build, not a local `docker build` — this guarantees a `linux/amd64` image regardless of whether you're on Apple Silicon, and avoids needing Docker installed locally at all.

The first build takes a few minutes — installing spaCy, downloading the `en_core_web_sm` wheel, and `apt-get install espeak-ng ffmpeg`.

---

## Step 3 — `./deploy/03-deploy-service.sh`

`gcloud run deploy` is create-or-update, so this is what you re-run after every code or config change — no downtime, a new revision takes over.

Prints a validation `curl` command afterward. Use it before wiring `04` — `functions-framework`'s CloudEvent parser needs a full push-shaped body (`ce-*` headers, `messageId`, `publishTime`, `subscription`), not just `{"message": {"data": ...}}`; a bare body 400s.

---

## Step 4 — `./deploy/04-push-subscription.sh`

Wires the push subscription. Grants `feedmind-audio-invoker` `roles/run.invoker` on the service, then creates or updates `feedmind-audio-push` on `feedmind-content-ready` with `--ack-deadline=600`.

---

## Step 5 — Smoke test it

`dry_run` does everything except uploading and writing to Firestore, so it is safe against production data:

```bash
./deploy/publish.sh RSS_FEED --limit 1 --force --dry-run
```

Then watch it run:

```bash
gcloud run services logs read feedmind-audio --region=us-central1 --project=feed-mind --limit=50
```

Look for `triggered by message …` (the push was delivered and authenticated), then `spaCy … condensed` (spaCy loaded), then `dry run - would upload` (synthesis worked). All three means the pipeline is healthy.

If the push never arrives at all, check the raw HTTP status on Cloud Run's request logs, not just `services logs read` (which only shows what the *application* printed, not 403s that never reached it):

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="feedmind-audio" AND httpRequest.status!=200' \
    --project=feed-mind --limit=10
```

**Then run it for real, once**, before trusting the trigger:

```bash
./deploy/publish.sh RSS_FEED --limit 1
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

Real Pub/Sub delivery (via `gcloud pubsub topics publish` or a producer's own publish) already sends the full push envelope with correct `ce-*` headers — only a hand-rolled `curl` against the service URL directly needs them added manually (see `03-deploy-service.sh`'s printed validation command).

| Field | Flag |
|---|---|
| `process_doc` | `--process-doc` (`RSS_FEED` \| `RESEARCH_PAPERS` \| `NEWS_STORIES`) |
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

**A batch too large for one pass continues in the next.** Cloud Run's own request-timeout ceiling is much higher than a gen2 function's, but it doesn't help here — the push subscription's own ack-deadline cap is still **600 seconds**, and CPU is only allocated during request processing, so nothing can continue after the response is returned regardless. At roughly a minute an article, `TIMEOUT` (540s) covers about eight.

Rather than truncate, the run stops itself at `MAX_RUNTIME` (450s), **between items** so every uploaded object has its matching Firestore write, exits `3`, and republishes its own trigger message. The next pass skips whatever now has an `audio_url` and takes the next slice. A large batch therefore drains across several invocations.

This cannot loop: continuation only follows a pass that completed at least one item, so no progress means no continuation.

**Timeouts are ordered so a slow run is never redelivered.** `MAX_RUNTIME` (450s) < `TIMEOUT` (540s) < `ACK_DEADLINE` (600s). The service always ends on its own deadline before Pub/Sub concludes the delivery failed.

**The service never nacks.** `on_content_ready` catches everything and returns normally (200/204). A batch that partly succeeded would otherwise redo the whole batch on redelivery, and the items it retried would be the ones least likely to succeed the second time. Failures are logged and tallied; the next run picks up whatever still lacks audio.

**One instance, one request at a time**, enforced two ways: Cloud Run's `--concurrency=1 --max-instances=1`, and separately, `functions-framework` dispatches each request on its own thread-pool thread regardless — which is exactly the mechanism behind the espeak-ng subprocess fix below, not something these flags alone would have prevented.

---

## Configuration

All in [`00-config.sh`](00-config.sh), all env-overridable.

| Variable | Default | Notes |
|---|---|---|
| `PROJECT_ID` | `feed-mind` | |
| `REGION` | `us-central1` | |
| `SERVICE_NAME` | `feedmind-audio` | The permanent name, reached after cutover — see `00-config.sh`'s header comment for the validate-then-cutover pattern used to get here |
| `TOPIC_NAME` | `feedmind-content-ready` | |
| `PUSH_SUBSCRIPTION` | `feedmind-audio-push` | |
| `PUBLISHER_SERVICE_ACCOUNTS` | `feedmind-sa`, `paper-prism-job`, `news-curator` | Space separated; granted per topic |
| `ACK_DEADLINE` | `600` | Seconds. The push-subscription maximum |
| `MESSAGE_RETENTION` | — | Set on the topic once, by the original gen2 setup |
| `MEMORY` / `CPU` | `1Gi` / `1` | spaCy's pipeline is the floor |
| `TIMEOUT` | `540s` | Not a hard Cloud Run ceiling, but still the binding one — see *Delivery semantics* |
| `MAX_RUNTIME` | `450` | Seconds. Stop starting items and continue in a new invocation |
| `CONCURRENCY` / `MAX_INSTANCES` / `MIN_INSTANCES` | `1` / `1` / `0` | Papers mode rewrites the whole `papers` array — overlapping runs would clobber each other. `MIN_INSTANCES=0` + CPU-only-during-request-processing (Cloud Run's default, set explicitly with `--cpu-throttling`) means no idle billing |
| `FEEDMIND_TTS_DEFAULT` | `cloud` | The deployed default; flip per `docs/feed-mind/tts-switch.md`, no redeploy needed |
| `LLM_API` | `openai` | Ollama Cloud speaks the OpenAI wire format |
| `LLM_BASE_URL` | `https://ollama.com/v1` | → `POST /v1/chat/completions` |
| `LLM_MODEL` | `gpt-oss:120b` | |
| `LLM_MAX_TOKENS` | `1200` | Headroom for `gpt-oss`'s reasoning, not longer output |
| `LLM_API_KEY_SECRET` | `feedmind-llm-api-key` | Mounted as `LLM_API_KEY` |
| `TTS_RATE` | `200` | Words per minute — shared by both backends, since both take a raw WPM value |

Deliberately **not** a `TTS_VOICE`/`FEEDMIND_VOICE` variable: `en-US-Neural2-F` is a Cloud-TTS-specific voice name with no equivalent on `espeak-ng`, so forcing one value onto both backends breaks whichever one it doesn't belong to (found the hard way — see Troubleshooting). `cloud_speech.py`'s own default already is that voice; `espeak-ng` uses its own default when none is given.

The Ollama Cloud catalogue is public and needs no key:

```bash
curl -s https://ollama.com/v1/models | jq -r '.data[].id' | sort
```

To run exactly what the service will run, before spending a deploy on it:

```bash
LLM_API=openai LLM_BASE_URL=https://ollama.com/v1 \
LLM_MODEL=gpt-oss:120b LLM_MAX_TOKENS=1200 LLM_API_KEY=... FEEDMIND_TTS=cloud \
    .venv/bin/python feedmind_audio.py --limit 1 --force --dry-run
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| **Pub/Sub push 403s, "The request was not authenticated"** | Pub/Sub's service agent lacks `roles/iam.serviceAccountTokenCreator` on the push SA — it silently cannot mint the OIDC token the push needs, so requests arrive with no auth at all, not a bad one | `01-setup.sh` grants this now; if debugging an older deploy, check `gcloud iam service-accounts get-iam-policy feedmind-audio-invoker@<project>.iam.gserviceaccount.com` for an empty policy |
| Published, but the service never runs, and Cloud Run's own request logs show nothing at all | The subscription's push endpoint is wrong, or it's still pointed at a torn-down scratch service | `gcloud pubsub subscriptions describe feedmind-audio-push --format='value(pushConfig.pushEndpoint)'` and compare against the live service URL |
| `FEEDMIND_TTS=local` fails every item with "The engine did not write ...aiff" and no exception | pyttsx3's Linux driver called off the main thread — `functions-framework` always dispatches on a spawned thread pool | Already fixed: `feedmind_audio.py::synthesize()` uses `webscraper.speech.synthesize_wav()` (a direct `espeak-ng` subprocess) on Linux, never pyttsx3, for exactly this reason |
| `FEEDMIND_TTS=local` fails with "No voice matches 'en-us-neural2-f'" | A `FEEDMIND_VOICE` env var carrying a Cloud-TTS-only voice name was forced onto both backends | Don't set `FEEDMIND_VOICE` at all — see *Configuration* above |
| Cloud Run deploy fails: "container failed to start and listen on the port" | `--signature-type=cloud_event` — the CLI flag is spelled `cloudevent`, no underscore, unlike the `@functions_framework.cloud_event` decorator it maps to | Check the Dockerfile `CMD` |
| A producer logs "failed to publish content-ready event" | Its SA is missing `pubsub.publisher` | Re-run `./deploy/01-setup.sh` |
| The same batch runs twice | Ack deadline expired mid-batch | Expected — see *Delivery semantics*. Shorten the batch |
| `401 Unauthorized` from `ollama.com` | Key wrong, or a trailing newline from `echo` | Add a new secret version with `printf`, then redeploy |
| `the model returned an empty summary` | Reasoning consumed the whole token budget | Raise `LLM_MAX_TOKENS` |
| Firestore 404 pointing at the Datastore setup page | The database is **named**, not `(default)` | Already handled in code — check `FIRESTORE_DATABASE` |
| The batch keeps re-running | Normal — it is draining a slice at a time | Watch for `more to do` in the logs; it stops when nothing is left |
| Batch never finishes draining | Each pass fails before completing an item | No progress means no continuation; fix the per-item failure |
| Changes don't take effect | Editing `00-config.sh` alone changes nothing deployed | Re-run `./deploy/03-deploy-service.sh` |

```bash
gcloud run services logs read feedmind-audio --region=us-central1 --project=feed-mind --limit=100
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="feedmind-audio" AND httpRequest.status!=200' --project=feed-mind --limit=20
gcloud pubsub topics list-subscriptions feedmind-content-ready --project=feed-mind
gcloud pubsub subscriptions describe feedmind-audio-push --project=feed-mind
gcloud run services describe feedmind-audio --region=us-central1 --project=feed-mind
```

---

## Costs

Nothing here has a standing charge — `MIN_INSTANCES=0`, CPU only allocated during request processing, and an idle topic is free. You pay per run:

- **Text-to-Speech**, per character, while `FEEDMIND_TTS=cloud` — 1M characters/month free, then billed. Flip to `local` (free, `espeak-ng`) when approaching that cap; see `docs/feed-mind/tts-switch.md`.
- **Ollama Cloud**, per their pricing.
- **Cloud Run**, for time actually used. The 540s timeout reserves nothing; a batch that needs several passes costs the same as one long run, plus a cold start each time.
- **Cloud Storage**, for what accumulates. The bucket has a 90-day delete lifecycle.

---

## Teardown

```bash
gcloud run services delete feedmind-audio --region=us-central1 --project=feed-mind
gcloud pubsub subscriptions delete feedmind-audio-push --project=feed-mind
gcloud pubsub topics delete feedmind-content-ready --project=feed-mind

gcloud iam service-accounts delete feedmind-audio-fn@feed-mind.iam.gserviceaccount.com
gcloud iam service-accounts delete feedmind-audio-invoker@feed-mind.iam.gserviceaccount.com
gcloud secrets delete feedmind-llm-api-key
```

Stop every producer too, or they will keep publishing into a topic nobody reads: `ENABLE_CONTENT_READY_EVENTS = False` in `packages/feedmind-core/feedmind_core/settings.py` (or `content_ready: false` in each ingest service's `feeds.yaml`), `CONTENT_READY_TOPIC=""` in paper-prism's `job_env` / `env.yaml`, and stop `news-curator`'s `events.py` from being called.

This leaves the bucket and Firestore alone — they hold data, and they belong to FeedMind rather than to this deployment.

---

## Files

| File | Job |
|---|---|
| `00-config.sh` | Every setting, sourced by the others. Not executable — it is sourced, never run |
| `01-setup.sh` | APIs, Artifact Registry, service accounts, IAM. Idempotent |
| `02-build-push.sh` | Cloud Build → Artifact Registry |
| `03-deploy-service.sh` | `gcloud run deploy` |
| `04-push-subscription.sh` | The `run.invoker` binding and the push subscription. Refuses to run while the old gen2 function still exists |
| `publish.sh` | Publishes a trigger message by hand |
| `../Dockerfile` | `python:3.11-slim` + `espeak-ng` + `ffmpeg`; `functions-framework` as the server |
| `../main.py` | `on_content_ready` (Pub/Sub, deployed) and `summarize_feed` (HTTP, kept) |
| `../requirements.txt` | Runtime deps, including the spaCy model from its release wheel |
| `../.gcloudignore` / `../.dockerignore` | Keep `.venv/`, `.git/`, `deploy/` and this directory out of the build |

On the producer side, all three follow the same shape:

| Producer | Publishes from | Called by | Topic setting |
|---|---|---|---|
| FeedMind ingests | `feedmind_core/events.py` | `runner.py`, last step | `feeds.yaml` / `settings.py` |
| `paper-prism` | `pipeline/src/paper_prism/events.py` | `__main__.py`, after `pipeline.run()` | `CONTENT_READY_TOPIC` env — `infra/run.tf` and `pipeline/deploy/env.yaml` |
| `news-curator` | `src/news_curator/events.py` | `pipeline.run()`, once per run with ≥1 canonical story | hardcoded `feedmind-content-ready` |
