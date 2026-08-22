# Deploying `feedmind_audio.py` to Cloud Functions

A runbook. Three scripts, run in order; only the middle one is run again after that.

```bash
./deploy/setup.sh      # once per project - APIs, service accounts, IAM
./deploy/deploy.sh     # every code or config change
./deploy/schedule.sh   # once - the two Cloud Scheduler cron jobs
```

Run them from the **repo root**, not from this directory. Every setting lives in [`config.sh`](config.sh) and can be overridden from the environment, so a one-off deploy to a scratch project needs no edits:

```bash
PROJECT_ID=my-scratch REGION=europe-west1 ./deploy/deploy.sh
```

---

## What gets deployed, and what changes on the way

`main.py` wraps `feedmind_audio.main()` in a gen2 HTTP function. It only translates a request into argv, so the CLI and the deployment cannot drift apart.

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

**2. Permissions.** These scripts enable APIs, create service accounts, edit project IAM, deploy, and create scheduler jobs. Project **Owner** covers it. Without Owner you need at least `serviceusage.serviceUsageAdmin`, `iam.serviceAccountAdmin`, `resourcemanager.projectIamAdmin`, `iam.serviceAccountUser`, `cloudfunctions.developer`, `run.admin`, `cloudscheduler.admin`, `secretmanager.admin` and `storage.admin`.

**3. Billing enabled** on the project. Cloud Build, Cloud Run and Text-to-Speech all require it.

**4. The audio bucket exists.** `setup.sh` warns rather than creating it, because the public-read grant is a decision worth making deliberately. `feedmind_audio.py` writes `https://storage.googleapis.com/<bucket>/<blob>` URLs into Firestore, and those only resolve for anonymous readers:

```bash
gcloud storage buckets create gs://feed-mind-audio-summaries --location=us-central1
gcloud storage buckets add-iam-policy-binding gs://feed-mind-audio-summaries \
    --member=allUsers --role=roles/storage.objectViewer
```

> Note that `roles/storage.objectViewer` on `allUsers` also grants **listing** — anyone who knows the bucket name can enumerate every summary.

---

## Step 0 — Create the LLM API key secret

The one thing the scripts won't invent for you. Get a key from <https://ollama.com/settings/keys>:

```bash
printf '%s' "$YOUR_KEY" | gcloud secrets create feedmind-llm-api-key \
    --project=feed-mind --data-file=-
```

`printf` rather than `echo` — `echo` appends a newline, which becomes part of the key and produces a puzzling `401` at runtime.

Do this **before** `setup.sh`, which grants the runtime account access to it. If you create the secret afterwards, just re-run `setup.sh`.

To rotate the key later, add a version rather than replacing the secret — `deploy.sh` mounts `:latest`, so a redeploy is not even needed, only a new instance:

```bash
printf '%s' "$NEW_KEY" | gcloud secrets versions add feedmind-llm-api-key --data-file=-
```

---

## Step 1 — `./deploy/setup.sh`

Idempotent: every step either creates something or reports that it already exists, so re-running it after editing `config.sh` is safe.

| It does | Detail |
|---|---|
| Enables 10 APIs | functions, run, cloudbuild, artifactregistry, eventarc, scheduler, texttospeech, firestore, storage, secretmanager |
| Creates two service accounts | `feedmind-audio-fn` (runtime), `feedmind-audio-invoker` (scheduler) |
| Grants `roles/datastore.user` | project-wide — Firestore has no per-collection predefined role |
| Grants `roles/storage.objectAdmin` | scoped to the one bucket, not project-wide |
| Grants `roles/secretmanager.secretAccessor` | on the LLM key secret |

Two identities on purpose: "may invoke" and "may write" should be separate grants, so a leaked scheduler identity can't touch your data.

Text-to-Speech needs no IAM role — it authorizes on the caller's credentials plus the enabled API.

**Expect warnings** if the bucket or the secret don't exist yet. They tell you the exact command to fix each. Fix, then re-run.

---

## Step 2 — `./deploy/deploy.sh`

The first deploy takes **3–5 minutes** — Cloud Build installs spaCy and downloads the `en_core_web_sm` wheel. Later deploys are faster but not instant.

It fails fast on the two mistakes that otherwise surface as a confusing runtime error minutes in: a missing `main.py`, and an `LLM_BASE_URL` still pointing at localhost.

After deploying it grants the scheduler account `roles/run.invoker`. That happens here rather than in `setup.sh` because a gen2 function *is* a Cloud Run service, which doesn't exist until the first deploy.

The function is deployed `--no-allow-unauthenticated`. The only callers are the scheduler jobs and anyone holding `run.invoker`.

---

## Step 3 — Smoke test it

`deploy.sh` prints this at the end with the URL filled in. `dry_run` does everything except uploading and writing to Firestore, so it is safe to run against production data:

```bash
URL=$(gcloud functions describe feedmind-audio --gen2 --region=us-central1 \
      --format='value(serviceConfig.uri)')

curl -X POST "$URL" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H 'Content-Type: application/json' \
  -d '{"limit": 1, "force": true, "dry_run": true}'
```

A healthy response is the dry-run marker for one item. Progress goes to stderr and lands in Cloud Logging:

```bash
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=50
```

Look for the `spaCy … condensed` line (spaCy loaded), then `dry run - would upload` (synthesis worked). If both appear, the whole pipeline is functioning.

**Then run it for real, once**, before trusting the schedule:

```bash
curl -X POST "$URL" -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H 'Content-Type: application/json' -d '{"limit": 1}'
```

---

## Step 4 — `./deploy/schedule.sh`

Creates or updates two jobs — separate so a failure in one doesn't stop the other:

| Job | Mode | Default schedule | Cron |
|---|---|---|---|
| `feedmind-audio-rss` | `RSS_FEED` | daily, 08:15 CT | `15 8 * * *` |
| `feedmind-audio-papers` | `RESEARCH_PAPERS` | Mondays, 09:15 CT | `15 9 * * 1` |

Both authenticate with an OIDC token for the invoker account. Times are `America/Chicago` — a named zone rather than a fixed UTC offset, so they hold across the DST changeover — and must fall **after** FeedMind's own pipeline has run, since there is nothing to summarize before it does.

The hour between them is deliberate: `MAX_INSTANCES` is 1, so a papers run arriving mid-RSS-batch would queue against the scheduler's attempt deadline rather than run.

> **A weekly papers job only ever covers one run.** `RESEARCH_PAPERS` mode collects *the latest run per category* — not everything since the last invocation. If FeedMind produces runs on days other than Monday, those papers are never summarized; nothing backfills them. Daily (`15 9 * * *`) is the schedule that matches how the mode selects work. Keep it weekly only if FeedMind itself runs weekly.

`ATTEMPT_DEADLINE` is 1800s, deliberately under the 3600s function timeout so a retry can't overlap a batch still running. The function keeps running to completion regardless; the deadline only decides how long the job waits before calling the attempt failed.

```bash
gcloud scheduler jobs run feedmind-audio-rss --location=us-central1   # run now
gcloud scheduler jobs list --location=us-central1
gcloud scheduler jobs pause feedmind-audio-rss --location=us-central1
```

---

## Invoking it by hand

A JSON body or query string maps onto the CLI flags. Precedence: **body > query string > `FEEDMIND_*` environment defaults**.

| Field | Flag |
|---|---|
| `process_doc` | `--process-doc` (`RSS_FEED` \| `RESEARCH_PAPERS`) |
| `category` | `--category` (papers only) |
| `article_id` | `--article-id` — an `article_id`, or an `arxiv_id` |
| `limit` | `--limit` |
| `force` | `--force` — redo items that already have audio |
| `dry_run` | `--dry-run` |
| `timeout`, `provider`, `model`, `select_ratio`, `voice`, `rate`, `tts` | the matching flag |

```bash
-d '{"process_doc": "RESEARCH_PAPERS", "category": "CV", "limit": 5}'
```

The response body is the list of audio URLs — the same thing the CLI prints to stdout.

**A run that finds nothing to do returns 200, not an error.** The pipeline is scheduled, so most invocations legitimately have no new items. Only "every item failed" returns 500, which is what makes Cloud Scheduler retry.

---

## Configuration

All in [`config.sh`](config.sh), all env-overridable.

| Variable | Default | Notes |
|---|---|---|
| `PROJECT_ID` | `feed-mind` | |
| `REGION` | `us-central1` | |
| `FUNCTION_NAME` | `feedmind-audio` | Also the prefix for both scheduler jobs |
| `RUNTIME` | `python311` | Matches the local `.venv` |
| `MEMORY` | `1Gi` | spaCy's pipeline is the floor |
| `TIMEOUT` | `3600s` | The gen2 HTTP ceiling. Billed for time used, not reserved |
| `CONCURRENCY` / `MAX_INSTANCES` | `1` / `1` | Papers mode rewrites the whole `papers` array — overlapping runs would clobber each other |
| `LLM_API` | `openai` | Ollama Cloud speaks the OpenAI wire format |
| `LLM_BASE_URL` | `https://ollama.com/v1` | → `POST /v1/chat/completions` |
| `LLM_MODEL` | `gpt-oss:120b` | `gpt-oss:20b` is ~⅕ the size and much faster |
| `LLM_MAX_TOKENS` | `1200` | Headroom for `gpt-oss`'s reasoning, not longer output |
| `LLM_API_KEY_SECRET` | `feedmind-llm-api-key` | Mounted as `LLM_API_KEY` |
| `TTS_VOICE` | `en-US-Neural2-F` | `gcloud text-to-speech voices list` |
| `TTS_RATE` | `175` | Words per minute, converted to the API's multiplier |

The Ollama Cloud catalogue is public and needs no key:

```bash
curl -s https://ollama.com/v1/models | jq -r '.data[].id' | sort
```

To try the exact deployed configuration locally, before spending a deploy on it:

```bash
LLM_API=openai LLM_BASE_URL=https://ollama.com/v1 \
LLM_MODEL=gpt-oss:120b LLM_MAX_TOKENS=1200 LLM_API_KEY=... FEEDMIND_TTS=cloud \
    .venv/bin/python feedmind_audio.py --limit 1 --force --dry-run
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Scheduler job reports `PERMISSION_DENIED` | Invoker account missing `run.invoker` | Re-run `./deploy/deploy.sh` |
| `401 Unauthorized` from `ollama.com` | Key wrong, or a trailing newline from `echo` | Add a new secret version with `printf`, then redeploy |
| `the model returned an empty summary` | Reasoning consumed the whole token budget | Raise `LLM_MAX_TOKENS` |
| Deploy aborts: "LLM_BASE_URL points at localhost" | `LLM_*` still on local Ollama | Set a hosted provider in `config.sh` |
| Firestore 404 pointing at the Datastore setup page | The database is **named**, not `(default)` | Already handled in code — check `FIRESTORE_DATABASE` matches |
| Build fails fetching `en_core_web_sm` | The wheel URL in `requirements.txt` must match the pinned spaCy minor version | Check the version pair |
| Function hits the 3600s timeout | A large batch, serial, dominated by LLM latency | `gpt-oss:20b`, or split the work with `limit` |
| `Permission denied` deploying with `--service-account` | You lack `iam.serviceAccountUser` on the runtime account | Grant it, or use Owner |
| Changes don't take effect | Editing `config.sh` alone changes nothing deployed | Re-run `./deploy/deploy.sh` |

Logs, most useful first:

```bash
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=100
gcloud scheduler jobs describe feedmind-audio-rss --location=us-central1
gcloud run services describe feedmind-audio --region=us-central1
```

---

## Costs

Nothing here has a standing charge — no minimum instances, no provisioned concurrency. You pay per run:

- **Text-to-Speech**, per character. Neural2 and Studio voices cost more than Standard; switching `TTS_VOICE` is the biggest lever.
- **Ollama Cloud**, per their pricing.
- **Cloud Functions / Run**, for time actually used. The 3600s timeout reserves nothing.
- **Cloud Storage**, for what accumulates. The bucket has a 90-day delete lifecycle.

---

## Teardown

```bash
gcloud scheduler jobs delete feedmind-audio-rss    --location=us-central1
gcloud scheduler jobs delete feedmind-audio-papers --location=us-central1
gcloud functions delete feedmind-audio --gen2 --region=us-central1

gcloud iam service-accounts delete feedmind-audio-fn@feed-mind.iam.gserviceaccount.com
gcloud iam service-accounts delete feedmind-audio-invoker@feed-mind.iam.gserviceaccount.com
gcloud secrets delete feedmind-llm-api-key
```

This leaves the bucket and Firestore alone — they hold data, and they belong to FeedMind rather than to this deployment.

---

## Files

| File | Job |
|---|---|
| `config.sh` | Every setting, sourced by the other three. Not executable — it is sourced, never run |
| `setup.sh` | APIs, service accounts, IAM. Idempotent |
| `deploy.sh` | `gcloud functions deploy`, then the invoker binding |
| `schedule.sh` | Upserts one scheduler job per `--process-doc` mode |
| `../main.py` | HTTP entrypoint — request → argv → `feedmind_audio.main()` |
| `../requirements.txt` | Runtime deps, including the spaCy model from its release wheel |
| `../.gcloudignore` | Keeps `.venv/`, `.git/` and this directory out of the upload |
