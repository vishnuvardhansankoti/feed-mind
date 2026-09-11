# services/summarizer

Guidance for working inside this service. The system-level view — the four
deployables, the shared Firestore database, the Pub/Sub handoff and the
cross-component schema contracts — is in the **root `CLAUDE.md`**; read that
first if you are changing anything another component reads.

## What this service is

`feedmind-audio`, a **Pub/Sub-triggered** Cloud Run service (a gen2 Cloud
Function until this was migrated — see "Cloud Run migration" below for why and
what it found). It is the only component with no schedule of its own: it wakes
when a producer says there is new content, scrapes each article or paper,
writes a longer LLM summary (`ai_summary`) back onto the existing Firestore
document, synthesizes speech, and uploads the MP3 to a public Cloud Storage
bucket (`audio_url`).

It is a **second writer to documents it does not own** — `processed_articles`
and `youtube_videos` belong to the FeedMind ingest services, `runs` to
`services/paper-prism`, `stories` to `services/news-curator`. It only ever
adds `ai_summary` / `audio_url` / `audio_generated_at`; it never creates or
deletes a document.

## Three pipelines, one topic

`--process-doc` selects which (`feedmind_audio.py::COLLECTORS`):

| | source | text | writes to |
|---|---|---|---|
| `RSS_FEED` (default) | latest-batch articles in `processed_articles` | scraped page | the article |
| `RESEARCH_PAPERS` | latest run per category in `runs` | stored abstract | the `papers` array entry |
| `NEWS_STORIES` | every `processed_articles` doc with `is_canonical=true` | scraped page | **both** the article and its `stories` doc (`story_id` on the article says which) |

`NEWS_STORIES` is the odd one out: the other two collect "the latest batch";
this one has no batch concept; instead it collects every canonical article not
yet summarized, because `services/news-curator` runs once a day and a
canonical article stays eligible until it has audio or its 90-day TTL removes
it. Its fallback text is `snippet` (the RSS description), not `summary` —
`services/india-news-ingest` runs `summarize: none`, so `summary` is always
empty for these articles. See `docs/feed-mind/news-curator-design.md` §6 rows
2-4 and `services/news-curator/CLAUDE.md`.

## Two entry points, one implementation

| | |
|---|---|
| `main.py::on_content_ready` | Pub/Sub — **this is what is deployed**, via `functions-framework --signature-type=cloudevent` (no underscore — the CLI flag and the `@functions_framework.cloud_event` decorator it maps to are spelled differently) running standalone inside the Cloud Run container (see Dockerfile) |
| `main.py::summarize_feed` | HTTP — kept for manual invocation, not what the container's `CMD` serves |
| `feedmind_audio.py` | all the pipeline logic; both entry points build argv and call its `main()` |
| `web-page-scraper.py` | the CLI, never called in the cloud (excluded by `.gcloudignore`/`.dockerignore`) |
| `webscraper/` | the package all of the above import |

Both entry points are deliberately thin wrappers that turn a request into the
argv `feedmind_audio.main` already understands, so the CLI and the deployed
service cannot drift apart. Keep it that way — logic added to `main.py` is
logic the CLI cannot exercise. `functions-framework` is not Cloud-Functions-
specific — it decodes a Pub/Sub push POST into the same CloudEvent shape
`main.py::decode_message` already expects, which is exactly why this code
needed no change to move from a gen2 Function to a Cloud Run container.

## The extraction path is standard library only

spaCy, pyttsx3 and the Google Cloud clients are imported **lazily**, so the
scraper still runs with none of them installed. Preserve that: a top-level
import of an optional dependency turns a graceful degradation into a hard
failure for every CLI user.

## Cloud Run migration: both TTS backends, one config switch

**Status: migrated and live.** The gen2 Cloud Function is deleted; `deploy/
config.sh`/`setup.sh`/`deploy.sh`/`publish.sh` (no numeric prefix) went with
it. The numbered scripts (`00`-`04`) are the only deploy path now. Cutover was
validated side-by-side first — a scratch service (`feedmind-audio-run`) with
no subscription wired to the shared topic, confirmed working against real
production data, before the gen2 function was deleted and the Cloud Run
service redeployed under the permanent name.

**Why this needed a platform change, not just a code change:** `webscraper/
speech.py` (originally pyttsx3 + an ffmpeg transcode) and `webscraper/
cloud_speech.py` (the Cloud TTS API) already both existed — the CLI has always
used the former. A gen2 Cloud Function's buildpack cannot `apt-get` anything,
so the deployed function was hardcoded to `FEEDMIND_TTS=cloud`. A Cloud Run
container with a Dockerfile can install OS packages, which is the entire point
of the migration: avoiding Cloud TTS's 1M-character/month free tier without
giving up the option to fall back to it.

**Both backends ship in the same image.** `FEEDMIND_TTS` — already an
environment variable both `main.py` and `feedmind_audio.py` read — picks
between them with **no rebuild and no code change**:

```bash
gcloud run services update feedmind-audio --region=us-central1 --project=feed-mind \
    --update-env-vars=FEEDMIND_TTS=local   # or =cloud
```

See `docs/feed-mind/tts-switch.md`. The deploy defaults to `cloud` — zero
voice-quality change from before the migration; `local` is something you flip
to by hand when approaching the free-tier cap, and back once the month rolls
over.

**`local` does NOT use pyttsx3 on the deployed container — a real bug found
during cutover, not a design choice made up front.** The original plan was
`pyttsx3` + `espeak-ng`, matching the CLI's own local backend, and it looked
right in every test *except* the one that mattered: pyttsx3 initializes and
synthesizes fine in a plain `python3` process (verified with a disposable
Cloud Run Job) and fine in a local Docker container run directly, but silently
produces no output — no exception, just a missing file — when invoked through
the actual deployed service. Root cause, confirmed by instrumenting a real
deployment: `functions-framework`'s CloudEvent dispatch always runs the
handler on a spawned `ThreadPoolExecutor` thread, never the process's main
thread, and pyttsx3's Linux/espeak driver is not safe to call off the main
thread. `webscraper/speech.py::synthesize_wav` shells out to `espeak-ng`
directly as a subprocess instead — a subprocess has no thread-affinity
requirement, confirmed by calling it from an actual `ThreadPoolExecutor`
worker thread in a test. `feedmind_audio.py::synthesize()` branches on
`sys.platform`: Linux (the deployed container, always) uses the subprocess;
macOS/Windows (the CLI's own `--tts local`, always invoked from one main
thread, no problem there) still uses pyttsx3. **`pyttsx3` is consequently not
a dependency of this deployed image at all** — see `pyproject.toml`'s comment.

**A second real bug, unrelated to TTS: Pub/Sub push subscriptions need an
explicit IAM grant that `gcloud pubsub subscriptions create
--push-auth-service-account` does not reliably set up on its own.** Pub/Sub's
service agent needs `roles/iam.serviceAccountTokenCreator` on the push SA to
mint the OIDC token attached to each push request; without it, every push
403s with "The request was not authenticated" — not a bad-token error, a
no-token error, because Pub/Sub can't mint one. `deploy/01-setup.sh` grants
this now. It was missing here initially, and — found while chasing this down —
**also missing on `services/news-curator`'s identical push subscription,
which had been failing on 100% of real deliveries since it was first
deployed**, invisible anywhere except Cloud Run's raw HTTP request logs
(`gcloud run services logs read` never shows a request that never reached the
application). Both are fixed now; see that service's own `01-setup.sh`.

**Timing budget is unchanged, on purpose.** Cloud Run's own request-timeout
ceiling is far higher than a gen2 Function's 540s hard cap, but that headroom
doesn't help here: the Pub/Sub **push** subscription's own ack-deadline cap is
still 600s regardless of what Cloud Run allows, and CPU is only allocated
during request processing (this migration's own requirement) — nothing can
continue after the response is returned. So `TIMEOUT` (540s), `MAX_RUNTIME`
(450s, so a long batch stops *between* items and republishes rather than being
killed mid-item — see `main.py::republish`), and `ACK_DEADLINE` (600s) all
carry over exactly as they were.

**Trigger wiring changed shape, not just target:** the gen2 function used an
Eventarc trigger (`--trigger-topic`); the Cloud Run service uses a direct
Pub/Sub **push subscription**, the same pattern `services/news-curator` uses —
own runtime SA + push SA + numbered deploy scripts.

## Runtime constraints that shaped the design

Full rationale is in `deploy/00-config.sh`, unusually heavily commented
because it encodes most of these. The ones easiest to break:

- **540s is at once a hard platform ceiling for a gen2 Function and the
  binding constraint on Cloud Run anyway.** On Cloud Run the platform's own
  timeout ceiling is much higher, but the Pub/Sub push ack-deadline's own 600s
  cap means going higher buys nothing — see "Cloud Run migration" above.
- **`MAX_RUNTIME` (450s) sits under `TIMEOUT` (540s) on purpose.** The run stops
  *between* items by choosing to, rather than being killed part-way through one
  — a kill between the upload and the Firestore write would orphan an object in
  the bucket. On stopping early it republishes its own trigger message, so a
  long batch drains across several invocations instead of truncating.
- **`ACK_DEADLINE` (600s) stays above `TIMEOUT`**, so the runtime is always
  killed by its own deadline before Pub/Sub concludes delivery failed and
  redelivers on top of a run that is still going.
- **One instance, one request at a time.** The pipeline rewrites shared
  documents wholesale (the `papers` array), so overlapping runs would fight.
  Cloud Run's `--concurrency=1` and `--max-instances=1` enforce this — but
  `functions-framework`'s own thread-pool dispatch (see the espeak-ng bug
  above) means "one request at a time" does NOT mean "on the main thread";
  code that cares about thread affinity has to handle that itself.
- **`--set-secrets` replaces the whole set on every deploy.** Both the LLM key
  and the VAPID key must be named in one flag; mounting one alone silently
  unmounts the other.
- **The Pub/Sub push service account needs `serviceAccountTokenCreator`
  granted on it explicitly** (see above) — this is not automatic, and the
  failure mode is a silent 403 invisible to normal log reading.

## The topic is owned here, not by the publishers

`feedmind-content-ready` persists from the gen2 function era (nothing in the
Cloud Run path creates topics, only subscriptions). `deploy/01-setup.sh`
grants `roles/pubsub.publisher` to all three producers' service accounts —
the topic belongs to whoever reads it, so no publisher's own deploy manages
that binding. Run `01-setup.sh` before a producer first publishes — until
then its runs still succeed and simply log a permission error.

## Commands

Run from `services/summarizer/`.

```bash
uv sync                                    # local venv

./deploy/publish.sh RSS_FEED --limit 1 --force --dry-run   # smoke test, writes nothing
./deploy/01-setup.sh                       # once per project
./deploy/02-build-push.sh                  # after any code or dependency change
./deploy/03-deploy-service.sh              # after any code or config change
./deploy/04-push-subscription.sh           # once — wires the push subscription
gcloud run services logs read feedmind-audio --region=us-central1 --project=feed-mind --limit=50
```

`requirements.txt` is **generated** from `pyproject.toml`
(`../../scripts/lock-all.sh`); `uv.lock` is committed. This is an independent uv
project — it pins `google-cloud-firestore==2.28.1` where `packages/feedmind-core`
pins `==2.19.0`, and nothing forces those to agree.

## No test suite

There isn't one. Changes are validated by the dry-run smoke test above and by
reading the logs of a real run. That is a real gap, not a considered decision.
