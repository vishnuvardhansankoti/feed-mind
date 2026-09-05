"""Cloud Function entrypoints - run feedmind_audio.py when content is ready.

Both entrypoints are thin wrappers: they turn an incoming request into the argv
that `feedmind_audio.main` already understands, run it, and report. All of the
pipeline logic stays in feedmind_audio.py, so the CLI and the deployed function
can never drift apart.

    on_content_ready(cloud_event)   Pub/Sub - what is deployed
    summarize_feed(request)         HTTP - kept for manual invocation

`on_content_ready` is the deployed one. FeedMind publishes to the topic when its
own run finishes, which is the only moment there is anything new to summarize -
a schedule could only ever guess at that. See deploy/README.md.

The message carries the arguments, as JSON in the body or as attributes:

    gcloud pubsub topics publish feedmind-content-ready \
        --message='{"process_doc": "RSS_FEED"}'

    gcloud pubsub topics publish feedmind-content-ready \
        --attribute=process_doc=RSS_FEED

An empty message is valid and means "the default": the latest RSS batch.

Progress goes to stderr and lands in Cloud Logging.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import os
import sys
from contextlib import redirect_stdout

import functions_framework

# The deployed runtime has no speech engine, so the Text-to-Speech API is the
# only backend that can work here. Set before feedmind_audio builds its parser,
# whose --tts default reads this.
os.environ.setdefault("FEEDMIND_TTS", "cloud")

import feedmind_audio  # noqa: E402

# Request fields that become `--flag value`, and the flag each one maps to.
VALUE_FLAGS = {
    "process_doc": "--process-doc",
    "category": "--category",
    "article_id": "--article-id",
    "limit": "--limit",
    "timeout": "--timeout",
    "provider": "--provider",
    "model": "--model",
    "select_ratio": "--select-ratio",
    "voice": "--voice",
    "rate": "--rate",
    "tts": "--tts",
}

# Request fields that become a bare `--flag` when truthy.
BOOL_FLAGS = {"force": "--force", "dry_run": "--dry-run"}

TRUTHY = {"1", "true", "yes", "on"}

# Defaults for anything the message does not specify, so an empty message still
# does something useful. Set by deploy/deploy.sh.
ENV_PREFIX = "FEEDMIND_"

# The full topic path this function publishes back to when a batch needs another
# pass. Set by deploy/deploy.sh; unset simply disables continuation.
TOPIC_ENV_VAR = "FEEDMIND_TOPIC"
REPUBLISH_TIMEOUT_S = 30


def log(message):
    print(message, file=sys.stderr, flush=True)


def is_true(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUTHY


def env_defaults():
    """Parameters taken from the function's own environment."""
    params = {}
    for field in list(VALUE_FLAGS) + list(BOOL_FLAGS):
        value = os.environ.get(ENV_PREFIX + field.upper())
        if value:
            params[field] = value
    return params


def build_argv(params):
    """Translate parameters into feedmind_audio's command line."""
    argv = []
    for field, flag in VALUE_FLAGS.items():
        value = params.get(field)
        if value not in (None, ""):
            argv += [flag, str(value)]
    for field, flag in BOOL_FLAGS.items():
        if field in params and is_true(params[field]):
            argv.append(flag)
    return argv


def republish(params):
    """Send the trigger message back to the topic to continue a long batch.

    An event-driven function is capped at 540s, which is not always enough for a
    whole batch, so the run stops short and asks to be called again rather than
    being killed part-way through an item. Each pass skips whatever already has
    an audio_url, so the batch drains a slice at a time.

    This only ever follows a pass that completed at least one item, so it cannot
    become a loop: no progress means no continuation.
    """
    topic = os.environ.get(TOPIC_ENV_VAR)
    if not topic:
        log(f"items remain, but ${TOPIC_ENV_VAR} is unset - not continuing")
        return False

    try:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        future = publisher.publish(topic, json.dumps(params).encode("utf-8"))
        message_id = future.result(timeout=REPUBLISH_TIMEOUT_S)
    except Exception as error:  # noqa: BLE001 - the batch itself succeeded
        log(f"could not republish to continue the batch: {error}")
        return False

    log(f"republished as {message_id} to continue the batch")
    return True


def run(params):
    """Run the pipeline. Returns (stdout, exit code)."""
    argv = build_argv(params)
    log(f"running: feedmind_audio.py {' '.join(argv)}")

    # feedmind_audio prints its results to stdout; capture them for the caller.
    captured = io.StringIO()
    with redirect_stdout(captured):
        code = feedmind_audio.main(argv)
    return captured.getvalue(), code


# ----------------------------------------------------------------------
# Pub/Sub
# ----------------------------------------------------------------------
def decode_message(cloud_event):
    """Pull the parameters out of a Pub/Sub CloudEvent.

    The payload may be JSON in the message body, key/value attributes, or
    nothing at all. Attributes are the easier half of the API to publish from,
    so both are supported and the body wins where they overlap.

    A body that is not JSON is a publisher bug rather than a transient fault:
    it is logged and treated as empty, because failing would only feed an
    identical message back through the retry.
    """
    message = (cloud_event.data or {}).get("message") or {}

    params = dict(message.get("attributes") or {})

    encoded = message.get("data")
    if encoded:
        try:
            body = base64.b64decode(encoded).decode("utf-8").strip()
        except (binascii.Error, UnicodeDecodeError, ValueError) as error:
            log(f"message data is not decodable base64/UTF-8, ignoring it: {error}")
            body = ""
        if body:
            try:
                decoded = json.loads(body)
            except json.JSONDecodeError as error:
                log(f"message data is not JSON, ignoring it: {error}")
            else:
                if isinstance(decoded, dict):
                    params.update(decoded)
                else:
                    log(f"message data is {type(decoded).__name__}, expected an object")

    return params


@functions_framework.cloud_event
def on_content_ready(cloud_event):
    """Pub/Sub entrypoint. Deployed with --trigger-topic.

    Returning normally acks the message. This never raises, which means a
    message is never redelivered because of something inside the pipeline -
    deliberately, since a batch that partly succeeded would redo the whole
    batch on redelivery, and the failures it retried would be the ones least
    likely to succeed the second time. Failures are logged and tallied instead;
    the next run picks up anything still missing audio.
    """
    message = (cloud_event.data or {}).get("message") or {}
    log(f"triggered by message {message.get('messageId', '?')} "
        f"published at {message.get('publishTime', '?')}")

    params = dict(env_defaults())
    params.update(decode_message(cloud_event))

    try:
        urls, code = run(params)
    except SystemExit as exit_error:  # argparse rejected a parameter
        log(f"BAD MESSAGE - the parameters were rejected: {exit_error}")
        return
    except Exception:  # noqa: BLE001 - log it and ack; do not spin on retries
        import traceback

        traceback.print_exc(file=sys.stderr)
        log("UNHANDLED ERROR - see the traceback above")
        return

    done = len(urls.splitlines())

    if code == feedmind_audio.EXIT_ALL_FAILED:
        log("every item failed")
    elif code == feedmind_audio.EXIT_NO_ITEMS:
        log("no items to process")
    elif code == feedmind_audio.EXIT_INCOMPLETE:
        log(f"{done} item(s) published, more to do")
        republish(params)
    else:
        log(f"done: {done} item(s) published")


# ----------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------
@functions_framework.http
def summarize_feed(request):
    """HTTP entrypoint, kept for manual runs and backfills.

    Not what `deploy.sh` deploys - a function has one trigger, and the Pub/Sub
    one is it. Deploy this separately under another name if you want a callable
    endpoint alongside the topic:

        gcloud functions deploy feedmind-audio-http --gen2 --trigger-http \
            --entry-point=summarize_feed ...

    Otherwise, publishing to the topic is the way to run it by hand.
    """
    params = dict(env_defaults())
    params.update(request.args.to_dict())
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        params.update(body)

    try:
        urls, code = run(params)
    except SystemExit as exit_error:
        return f"bad request: {exit_error}\n", 400
    except Exception as error:  # noqa: BLE001 - the traceback goes to the log
        import traceback

        traceback.print_exc(file=sys.stderr)
        return f"unhandled error: {type(error).__name__}: {error}\n", 500

    if code == feedmind_audio.EXIT_ALL_FAILED:
        return f"every item failed; see the logs\n{urls}", 500
    if code == feedmind_audio.EXIT_NO_ITEMS:
        # Nothing to collect - a normal outcome, not an error.
        return "no items to process\n", 200
    return urls or "nothing to do\n", 200
