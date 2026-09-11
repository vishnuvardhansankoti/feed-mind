# Cloud Run container. Replaces the gen2 Cloud Function's buildpack, which
# could not apt-get anything — the whole reason this migration exists is to
# get espeak-ng and ffmpeg onto the runtime at all, so the `local` TTS backend
# becomes a real option alongside `cloud`, switchable at request time with
# FEEDMIND_TTS — see docs/feed-mind/tts-switch.md.
#
# espeak-ng is invoked directly as a subprocess (webscraper/speech.py::
# synthesize_wav), NOT through pyttsx3. Validated by hand that pyttsx3's
# Linux driver silently fails when called off the process's main thread —
# which is exactly how functions-framework's CloudEvent dispatch always calls
# it (a spawned ThreadPoolExecutor thread, confirmed by instrumenting a real
# deployment) — with no exception, just no output file. A subprocess has no
# such thread-affinity requirement, so it is unaffected by which thread calls
# it. pyttsx3 is not a dependency of this image at all; see pyproject.toml.
FROM python:3.11-slim

RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    espeak-ng \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GRPC_VERBOSITY=ERROR

WORKDIR /app

# requirements.txt is GENERATED from pyproject.toml (scripts/lock-all.sh).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# functions-framework runs standalone as the HTTP server here — it is not
# Cloud-Functions-specific, and decodes a Pub/Sub push POST into the same
# CloudEvent shape main.py::decode_message already expects, so main.py is
# unchanged from the Cloud Functions era. It dispatches the handler on its
# own internal thread pool regardless of gunicorn worker/thread settings —
# see the espeak-ng note above for why that matters. One Cloud Run instance,
# one request at a time is still enforced at the Cloud Run layer (see
# deploy/00-config.sh CONCURRENCY=1), because the pipeline rewrites shared
# Firestore documents wholesale.
ENV PORT=8080
# --signature-type is `cloudevent` (no underscore) even though the Python
# decorator it maps to is `@functions_framework.cloud_event` — the CLI's own
# error message is the only place this spelling is documented.
CMD exec functions-framework --target=on_content_ready --signature-type=cloudevent --port=${PORT}
