#!/usr/bin/env bash
# Settings shared by every script in this directory. Sourced, never run.
#
# Everything here can be overridden from the environment, so a one-off deploy to
# a scratch project needs no edits:
#
#     REGION=europe-west1 ./deploy/deploy.sh
#
# The GCP_* values must match the constants at the top of feedmind_audio.py.
# They are repeated rather than parsed out of the Python because gcloud needs
# them before the code ever runs.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-feed-mind}"
REGION="${REGION:-us-central1}"

FUNCTION_NAME="${FUNCTION_NAME:-feedmind-audio}"
ENTRY_POINT="${ENTRY_POINT:-on_content_ready}"
RUNTIME="${RUNTIME:-python311}"

# -- Trigger -----------------------------------------------------------------
# The function runs when a publisher says there is new content, not on a clock.
# Only the producing pipeline knows when its run finished, and a schedule could
# only ever guess at that - too early and there is nothing to summarize, too
# late and the audio is stale.
#
# One topic carries both modes; the message says which. See main.py.
#
#   feed-mind        publishes {"process_doc": "RSS_FEED"} at the end of its run
#   paper-prism-job  publishes {"process_doc": "RESEARCH_PAPERS"} at the end of
#                    its weekly run, having written the `runs` collection
TOPIC_NAME="${TOPIC_NAME:-feedmind-content-ready}"

# Service accounts allowed to publish to the topic, space separated. This is
# where the grant lives for both producers: the topic belongs to whoever reads
# it, so neither publisher's own deploy manages the binding.
PUBLISHER_SERVICE_ACCOUNTS="${PUBLISHER_SERVICE_ACCOUNTS:-feedmind-sa@${PROJECT_ID}.iam.gserviceaccount.com paper-prism-job@${PROJECT_ID}.iam.gserviceaccount.com}"

# spaCy holds its pipeline in memory and the LLM call is mostly waiting, so the
# function is memory-bound rather than CPU-bound. 1Gi fits en_core_web_sm with
# room to spare; drop to 512Mi only if you have watched it run.
MEMORY="${MEMORY:-1Gi}"
CPU="${CPU:-1}"

# 540s is a hard platform ceiling for an event-driven function - the 3600s an
# HTTP function may ask for is not available here, and gcloud rejects the deploy
# rather than clamping. There is no cost to reserving it: the function is billed
# for time used.
#
# A batch is a serial loop - scrape, LLM, synthesis, per item - at roughly a
# minute an article, so 540s covers about eight. Anything larger is handled by
# MAX_RUNTIME below rather than by being cut off mid-item.
TIMEOUT="${TIMEOUT:-540s}"

# When to stop starting new items, in seconds. Deliberately under TIMEOUT so the
# run ends by choosing to, between items, instead of being killed part-way
# through one - a kill between the upload and the Firestore write would leave an
# orphaned object in the bucket.
#
# On stopping early the function republishes its own trigger message, so a long
# batch drains across several invocations instead of silently truncating.
MAX_RUNTIME="${MAX_RUNTIME:-450}"

# One request at a time, one instance at a time. The pipeline writes to shared
# Firestore documents (the papers array is rewritten wholesale), so overlapping
# runs would fight each other.
CONCURRENCY="${CONCURRENCY:-1}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"

SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-feedmind-audio-fn}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com}"

# The identity Eventarc uses to deliver a message to the function. Kept separate
# from the runtime account so that "may invoke" and "may write" are different
# grants. Without this, Eventarc falls back to the Compute Engine default
# service account, which is over-privileged and shared with everything else in
# the project.
TRIGGER_SA_ID="${TRIGGER_SA_ID:-feedmind-audio-invoker}"
TRIGGER_SA="${TRIGGER_SA:-${TRIGGER_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com}"

BUCKET_NAME="${BUCKET_NAME:-feed-mind-audio-summaries}"
FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-feed-mind-db}"

# -- LLM ---------------------------------------------------------------------
# webscraper/config.py reads these four directly, which is what lets the
# function run with no config file on disk. The built-in default points at
# localhost Ollama and cannot work in the cloud, so a hosted provider is
# required here.
#
# Ollama Cloud is the closest hosted thing to the local Ollama the CLI uses:
# same model catalogue, so summaries come out in roughly the same voice. It
# speaks the OpenAI wire format, which means the `openai` adapter drives it and
# the `ollama` one is not involved - that adapter is for a native /api/chat
# endpoint, which is what a *local* Ollama serves.
#
# The base URL already carries /v1, which OpenAIAdapter leaves alone rather
# than appending a second one.
LLM_API="${LLM_API:-openai}"
LLM_BASE_URL="${LLM_BASE_URL:-https://ollama.com/v1}"

# Ollama Cloud hosts a fixed catalogue rather than whatever you have pulled
# locally, so this cannot mirror the CLI's llama3.2:latest. The catalogue is
# public and needs no key, so it can be checked at any time:
#
#     curl -s https://ollama.com/v1/models | jq -r '.data[].id' | sort
#
# gpt-oss:20b is the same family at roughly a fifth the size - worth trying,
# since a batch is a serial loop and every second is spent waiting on this.
LLM_MODEL="${LLM_MODEL:-gpt-oss:120b}"

# gpt-oss reasons before it answers, and the reasoning is drawn from the same
# budget. The package default of 300 is sized for a model that starts writing
# immediately; leaving it there risks the run ending in "the model returned an
# empty summary" after the thinking alone exhausts it. The summaries themselves
# are 2-3 sentences, so the extra room is headroom, not longer output.
LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-1200}"

# The API key is never passed as an environment variable on the command line -
# it lives in Secret Manager and is mounted at runtime as LLM_API_KEY, which
# webscraper/config.py picks up like any other override.
#
# Create it from https://ollama.com/settings/keys, then:
#
#     printf '%s' "$YOUR_KEY" | gcloud secrets create feedmind-llm-api-key \
#         --project="$PROJECT_ID" --data-file=-
#
# The name is deliberately provider-neutral - switching providers later is a
# new secret *version*, not a new secret.
LLM_API_KEY_SECRET="${LLM_API_KEY_SECRET:-feedmind-llm-api-key}"

# -- Speech ------------------------------------------------------------------
# See webscraper/cloud_speech.py. `gcloud text-to-speech voices list` shows the
# full catalogue; Neural2 and Studio voices cost more per character than Standard.
TTS_VOICE="${TTS_VOICE:-en-US-Neural2-F}"

# 200 rather than the 175 baseline, to match what the CLI produces: pyttsx3 with
# no --rate uses the macOS driver default of 200 WPM, and 175 here sounded
# noticeably slower by comparison.
#
# Measured on one 45-word summary through en-US-Neural2-F, so the multiplier is
# tuned to this voice; a different TTS_VOICE may want a different number:
#
#     local, pyttsx3 default    17.35s
#     TTS_RATE=175 (rate 1.00)  19.39s   12% slower
#     TTS_RATE=200 (rate 1.14)  16.94s    2% faster
TTS_RATE="${TTS_RATE:-200}"

# -- Pub/Sub delivery --------------------------------------------------------
# Deploying with --trigger-topic makes Eventarc create a push subscription. The
# ack deadline is how long Pub/Sub waits for the function before deciding the
# delivery failed and sending the message again; 600s is the maximum a push
# subscription allows.
#
# Kept above TIMEOUT (540s), so the function is always killed by its own
# deadline before Pub/Sub concludes the delivery failed. That ordering is what
# stops a slow run from being redelivered while it is still going.
ACK_DEADLINE="${ACK_DEADLINE:-600}"

# Messages Pub/Sub could not deliver are kept this long before being dropped.
# The default is 7 days; a day is plenty here, because a summary that is a week
# late is of no use to anyone and the next run supersedes it anyway.
MESSAGE_RETENTION="${MESSAGE_RETENTION:-1d}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

require_gcloud() {
    command -v gcloud >/dev/null 2>&1 || {
        echo "gcloud is not on PATH - install the Google Cloud CLI first." >&2
        exit 1
    }
}
