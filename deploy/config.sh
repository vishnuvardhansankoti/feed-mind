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
ENTRY_POINT="${ENTRY_POINT:-summarize_feed}"
RUNTIME="${RUNTIME:-python311}"

# spaCy holds its pipeline in memory and the LLM call is mostly waiting, so the
# function is memory-bound rather than CPU-bound. 1Gi fits en_core_web_sm with
# room to spare; drop to 512Mi only if you have watched it run.
MEMORY="${MEMORY:-1Gi}"
CPU="${CPU:-1}"

# A batch is a serial loop over every article in the day's feed, each one a
# scrape plus an LLM call plus a synthesis. 3600s is the gen2 HTTP ceiling and
# there is no cost to reserving it - the function is billed for time used.
TIMEOUT="${TIMEOUT:-3600s}"

# One request at a time, one instance at a time. The pipeline writes to shared
# Firestore documents (the papers array is rewritten wholesale), so overlapping
# runs would fight each other.
CONCURRENCY="${CONCURRENCY:-1}"
MAX_INSTANCES="${MAX_INSTANCES:-1}"

SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-feedmind-audio-fn}"
SERVICE_ACCOUNT="${SERVICE_ACCOUNT:-${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com}"

# The identity Cloud Scheduler uses to call the function. Kept separate from the
# runtime account so that "may invoke" and "may write" are different grants.
SCHEDULER_SA_ID="${SCHEDULER_SA_ID:-feedmind-audio-invoker}"
SCHEDULER_SA="${SCHEDULER_SA:-${SCHEDULER_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com}"

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
TTS_RATE="${TTS_RATE:-175}"

# -- Schedule ----------------------------------------------------------------
# FeedMind's own pipeline has to have finished before there is anything to
# summarize, so these run after it.
#
# America/Chicago rather than a fixed UTC offset, so the wall-clock times hold
# across the DST changeover instead of drifting an hour twice a year.
SCHEDULE_TIMEZONE="${SCHEDULE_TIMEZONE:-America/Chicago}"

# Daily at 08:15 CT.
RSS_SCHEDULE="${RSS_SCHEDULE:-15 8 * * *}"

# Mondays at 09:15 CT. An hour after the RSS run so the two cannot overlap -
# MAX_INSTANCES is 1, and a second request arriving mid-batch would queue
# against the scheduler's attempt deadline rather than run.
PAPERS_SCHEDULE="${PAPERS_SCHEDULE:-15 9 * * 1}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

require_gcloud() {
    command -v gcloud >/dev/null 2>&1 || {
        echo "gcloud is not on PATH - install the Google Cloud CLI first." >&2
        exit 1
    }
}
