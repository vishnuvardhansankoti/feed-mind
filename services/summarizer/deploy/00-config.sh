#!/usr/bin/env bash
# Shared configuration for the Cloud Run deploy scripts (01-04) — sourced,
# never run. This is the live deploy path — the gen2 Cloud Function this
# replaced has been deleted; see services/summarizer/CLAUDE.md's "Cloud Run
# migration" section for how the cutover went and what it found.
#
# Override any value by exporting it before running, e.g.:
#     REGION=europe-west1 ./03-deploy-service.sh
set -euo pipefail

export PROJECT_ID="${PROJECT_ID:-feed-mind}"
export REGION="${REGION:-us-central1}"
export FIRESTORE_DATABASE="${FIRESTORE_DATABASE:-feed-mind-db}"

# -- Artifact Registry + image ------------------------------------------------
export REPO="${REPO:-feedmind-audio}"
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/feedmind-audio:latest"

# -- Cloud Run service ---------------------------------------------------------
# The permanent name, reached after the cutover: validated first under a
# scratch name (feedmind-audio-run) with no subscription wired to the shared
# topic, then the gen2 function was deleted and this redeployed here. Override
# to a scratch name again if repeating that pattern for some future change —
# never point 04-push-subscription.sh at the shared topic from a second
# service while another one still owns a live subscription on it: Pub/Sub fans
# a message out to every subscription on a topic, so both would process the
# same batch at once and fight over the same Firestore documents.
export SERVICE_NAME="${SERVICE_NAME:-feedmind-audio}"
export SERVICE_SA_NAME="${SERVICE_SA_NAME:-feedmind-audio-fn}"
export SERVICE_SA="${SERVICE_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# The identity Pub/Sub uses to push to the service — separate from the runtime
# SA for the same reason the old TRIGGER_SA was: "may invoke" and "may write"
# are different grants. Reuses the gen2 function's existing invoker SA name
# rather than minting a new one, since it plays the same role.
export PUSH_SA_NAME="${PUSH_SA_NAME:-feedmind-audio-invoker}"
export PUSH_SA="${PUSH_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# -- Topic + subscription -------------------------------------------------------
# Owned here, not by the publishers — see config.sh and the root CLAUDE.md.
# Created already by the gen2 function's setup.sh; 01-setup.sh below only
# checks for it.
export TOPIC_NAME="${TOPIC_NAME:-feedmind-content-ready}"
export PUSH_SUBSCRIPTION="${PUSH_SUBSCRIPTION:-feedmind-audio-push}"
export PUBLISHER_SERVICE_ACCOUNTS="${PUBLISHER_SERVICE_ACCOUNTS:-feedmind-sa@${PROJECT_ID}.iam.gserviceaccount.com paper-prism-job@${PROJECT_ID}.iam.gserviceaccount.com news-curator@${PROJECT_ID}.iam.gserviceaccount.com}"

# -- Storage + secrets ----------------------------------------------------------
export BUCKET_NAME="${BUCKET_NAME:-feed-mind-audio-summaries}"
export LLM_API_KEY_SECRET="${LLM_API_KEY_SECRET:-feedmind-llm-api-key}"
export VAPID_PRIVATE_KEY_SECRET="${VAPID_PRIVATE_KEY_SECRET:-feedmind-vapid-private-key}"

# -- Runtime env vars -----------------------------------------------------------
# FEEDMIND_TTS defaults to `local` — free, unlike Cloud TTS's metered
# 1M-character/month tier. Flip to `cloud` if Piper's voice quality isn't
# good enough for some use, with:
#     gcloud run services update "$SERVICE_NAME" --region="$REGION" \
#         --project="$PROJECT_ID" --update-env-vars=FEEDMIND_TTS=cloud
# See docs/feed-mind/tts-switch.md.
export FEEDMIND_TTS_DEFAULT="${FEEDMIND_TTS_DEFAULT:-local}"

# No FEEDMIND_VOICE is set, deliberately — "en-US-Neural2-F" is a Cloud TTS
# voice *name*; Piper takes a model file path instead (and pyttsx3, the CLI's
# own macOS/Windows backend, has no voice by that name either), so forcing it
# unconditionally onto every backend fails every item the moment FEEDMIND_TTS
# flips to local. cloud_speech.py's own DEFAULT_VOICE already is
# "en-US-Neural2-F", so omitting --voice entirely gives Cloud TTS the exact
# same voice it always used, and lets Piper/pyttsx3 fall back to their own
# defaults (webscraper/speech.py::PIPER_DEFAULT_MODEL for Piper). Found by
# testing the real deployed service against real production data before
# wiring the real subscription.
export TTS_RATE="${TTS_RATE:-200}"

export LLM_API="${LLM_API:-openai}"
export LLM_BASE_URL="${LLM_BASE_URL:-https://ollama.com/v1}"
export LLM_MODEL="${LLM_MODEL:-gpt-oss:120b}"
export LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-1200}"
export VAPID_SUBJECT="${VAPID_SUBJECT:-mailto:shankotai@gmail.com}"

# -- Resource + concurrency shape ------------------------------------------------
# 2Gi, raised from 1Gi (2026-09) after a real local-TTS run OOM-killed the
# container mid-batch: "Memory limit of 1024 MiB exceeded with 1087 MiB used"
# — Piper's onnxruntime model pushed it over, on top of spaCy already loaded.
# Confirmed in production logs, not a guess; revisit if 2Gi is ever hit too.
export MEMORY="${MEMORY:-2Gi}"
export CPU="${CPU:-1}"

# Unchanged from the function: 540s request timeout, 450s self-stop so a long
# batch drains across invocations between items rather than being killed
# mid-item, 600s Pub/Sub push ack-deadline (its hard maximum). Cloud Run's own
# timeout ceiling is much higher (3600s), but that headroom is moot here — the
# push subscription's 600s ack-deadline cap is still the binding constraint,
# and CPU is only allocated during request processing (see --cpu-throttling
# below), so nothing can continue past the response anyway. See the root
# CLAUDE.md's Telegram-delivery-contract section for the same reasoning
# applied to a different service.
export TIMEOUT="${TIMEOUT:-540s}"
export MAX_RUNTIME="${MAX_RUNTIME:-450}"
export ACK_DEADLINE="${ACK_DEADLINE:-600}"

# One request at a time, one instance at a time — the pipeline rewrites shared
# Firestore documents wholesale (the papers array), so overlapping runs would
# fight each other. CPU allocated only during request processing (Cloud Run's
# default; spelled out explicitly rather than relied on) and MIN_INSTANCES=0
# are both explicit requirements for this migration, not carried over from the
# function — a gen2 function has no equivalent toggle for either.
export CONCURRENCY="${CONCURRENCY:-1}"
export MIN_INSTANCES="${MIN_INSTANCES:-0}"
export MAX_INSTANCES="${MAX_INSTANCES:-1}"

echo "config: project=${PROJECT_ID} region=${REGION} service=${SERVICE_NAME}"
