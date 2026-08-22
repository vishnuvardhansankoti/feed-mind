"""Cloud Function entrypoint - runs feedmind_audio.py on an HTTP request.

The function is a thin wrapper: it turns a request into the argv that
`feedmind_audio.main` already understands, runs it, and reports the exit code.
All of the pipeline logic stays in feedmind_audio.py, so the CLI and the
deployed function can never drift apart.

Arguments arrive either as a JSON body or as query parameters, so the same
deployment can be driven by Cloud Scheduler (which posts a body) and by curl:

    {"process_doc": "RESEARCH_PAPERS", "category": "CV", "limit": 5}
    ?process_doc=RESEARCH_PAPERS&category=CV&limit=5

Progress goes to stderr and lands in Cloud Logging. The response body is the
list of audio URLs the run produced - the same thing the CLI prints to stdout.

A run that finds nothing to do is a success, not an error: the pipeline is
scheduled, so most invocations legitimately have no new items. Only a run where
every item failed returns 500, which is what makes Cloud Scheduler retry.
"""

from __future__ import annotations

import io
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

# Defaults for anything the request does not specify, so the function has a
# useful behaviour with an empty body. Overridden by environment variables of
# the same name, upper-cased and prefixed - see deploy/deploy.sh.
ENV_PREFIX = "FEEDMIND_"


def is_true(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in TRUTHY


def request_params(request):
    """Merge the JSON body, the query string and the environment defaults.

    Precedence, highest first: JSON body > query string > environment.
    """
    params = {}

    for field in list(VALUE_FLAGS) + list(BOOL_FLAGS):
        value = os.environ.get(ENV_PREFIX + field.upper())
        if value:
            params[field] = value

    params.update(request.args.to_dict())

    body = request.get_json(silent=True)
    if isinstance(body, dict):
        params.update(body)

    return params


def build_argv(params):
    """Translate request parameters into feedmind_audio's command line."""
    argv = []
    for field, flag in VALUE_FLAGS.items():
        value = params.get(field)
        if value not in (None, ""):
            argv += [flag, str(value)]
    for field, flag in BOOL_FLAGS.items():
        if field in params and is_true(params[field]):
            argv.append(flag)
    return argv


@functions_framework.http
def summarize_feed(request):
    """HTTP entrypoint. Returns (body, status) for the functions framework."""
    argv = build_argv(request_params(request))
    print(f"running: feedmind_audio.py {' '.join(argv)}", file=sys.stderr, flush=True)

    # feedmind_audio prints its results to stdout; capture them for the body.
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            code = feedmind_audio.main(argv)
    except SystemExit as exit_error:  # argparse rejects a bad parameter
        return f"bad request: {exit_error}\n", 400
    except Exception as error:  # noqa: BLE001 - the traceback goes to the log
        import traceback

        traceback.print_exc(file=sys.stderr)
        return f"unhandled error: {type(error).__name__}: {error}\n", 500

    urls = captured.getvalue()

    if code == feedmind_audio.EXIT_ALL_FAILED:
        return f"every item failed; see the logs\n{urls}", 500
    if code == feedmind_audio.EXIT_NO_ITEMS:
        # Nothing to collect - a normal outcome for a scheduled run.
        return "no items to process\n", 200
    return urls or "nothing to do\n", 200
