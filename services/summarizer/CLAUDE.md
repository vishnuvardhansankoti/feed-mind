# services/summarizer

Guidance for working inside this service. The system-level view — the four
deployables, the shared Firestore database, the Pub/Sub handoff and the
cross-component schema contracts — is in the **root `CLAUDE.md`**; read that
first if you are changing anything another component reads.

## What this service is

`feedmind-audio`, a **Pub/Sub-triggered** gen2 Cloud Function. It is the only
component with no schedule of its own: it wakes when a producer says there is
new content, scrapes each article or paper, writes a longer LLM summary
(`ai_summary`) back onto the existing Firestore document, synthesizes speech,
and uploads the MP3 to a public Cloud Storage bucket (`audio_url`).

It is a **second writer to documents it does not own** — `processed_articles`
and `youtube_videos` belong to `services/feed-mind`, `runs` to
`services/paper-prism`. It only ever adds `ai_summary` / `audio_url` /
`audio_generated_at`; it never creates or deletes a document.

## Two entry points, one implementation

| | |
|---|---|
| `main.py::on_content_ready` | Pub/Sub — **this is what is deployed** |
| `main.py::summarize_feed` | HTTP — kept for manual invocation |
| `feedmind_audio.py` | all the pipeline logic; both entry points build argv and call its `main()` |
| `web-page-scraper.py` | the CLI, never called in the cloud (excluded by `.gcloudignore`) |
| `webscraper/` | the package all of the above import |

Both entry points are deliberately thin wrappers that turn a request into the
argv `feedmind_audio.main` already understands, so the CLI and the deployed
function cannot drift apart. Keep it that way — logic added to `main.py` is
logic the CLI cannot exercise.

## The extraction path is standard library only

spaCy, pyttsx3 and the Google Cloud clients are imported **lazily**, so the
scraper still runs with none of them installed. Preserve that: a top-level
import of an optional dependency turns a graceful degradation into a hard
failure for every CLI user.

## Runtime constraints that shaped the design

Full rationale is in `deploy/config.sh`, which is unusually heavily commented
because it encodes most of these. The ones easiest to break:

- **The deployed runtime has no speech engine and no `ffmpeg`.** That is why
  `webscraper/cloud_speech.py` exists and why the function sets
  `FEEDMIND_TTS=cloud`. `pyttsx3` is deliberately absent from `pyproject.toml`.
- **540s is a hard platform ceiling** for an event-driven function; gcloud
  rejects a higher timeout rather than clamping it. `deploy/deploy.sh` checks
  this before deploying.
- **`MAX_RUNTIME` (450s) sits under `TIMEOUT` (540s) on purpose.** The run stops
  *between* items by choosing to, rather than being killed part-way through one
  — a kill between the upload and the Firestore write would orphan an object in
  the bucket. On stopping early it republishes its own trigger message, so a
  long batch drains across several invocations instead of truncating.
- **`ACK_DEADLINE` (600s) stays above `TIMEOUT`**, so the function is always
  killed by its own deadline before Pub/Sub concludes delivery failed and
  redelivers on top of a run that is still going.
- **One instance, one request at a time.** The pipeline rewrites shared
  documents wholesale (the `papers` array), so overlapping runs would fight.
- **`--set-secrets` replaces the whole set on every deploy.** Both the LLM key
  and the VAPID key must be named in one flag; mounting one alone silently
  unmounts the other.

## The topic is owned here, not by the publishers

`deploy/setup.sh` creates `feedmind-content-ready` **and** grants
`roles/pubsub.publisher` to both producers' service accounts. Neither publisher's
own deploy manages that binding, because the topic belongs to whoever reads it.
Run `deploy/setup.sh` before either producer first publishes — until then their
runs still succeed and simply log a permission error.

## Commands

Run from `services/summarizer/`.

```bash
uv sync                                    # local venv
./deploy/publish.sh RSS_FEED --limit 1 --force --dry-run   # smoke test, writes nothing
./deploy/setup.sh                          # once per project
./deploy/deploy.sh                         # after any code or config change
gcloud functions logs read feedmind-audio --gen2 --region=us-central1 --limit=50
```

`requirements.txt` is **generated** from `pyproject.toml`
(`../../scripts/lock-all.sh`); `uv.lock` is committed. This is an independent uv
project — it pins `google-cloud-firestore==2.28.1` where `services/feed-mind`
pins `==2.19.0`, and nothing forces those to agree.

## No test suite

There isn't one. Changes are validated by the dry-run smoke test above and by
reading the logs of a real run. That is a real gap, not a considered decision.
