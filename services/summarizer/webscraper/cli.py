"""Argument parsing and the console output format."""

from __future__ import annotations

import argparse
import sys
import textwrap

from . import config as config_module
from .errors import (
    CondenseError,
    ConfigError,
    FetchError,
    LLMError,
    ScraperError,
    SpeechError,
)
from .extractor import extract_article
from .fetcher import fetch, normalize_url
from .llm import summarize

EXIT_OK = 0
EXIT_FETCH_ERROR = 1
EXIT_NO_CONTENT = 2
EXIT_SUMMARY_FAILED = 3
EXIT_SPEECH_FAILED = 4

MIN_RULE_WIDTH = 40
NO_WRAP = 10 ** 6


def build_parser():
    parser = argparse.ArgumentParser(
        prog="web-page-scraper.py",
        description="Scrape a page, print its readable content, "
                    "and optionally summarize it with an LLM.",
    )
    parser.add_argument("url", nargs="?", help="URL of the page to scrape")
    parser.add_argument(
        "--width", type=int, default=100,
        help="wrap width in columns; 0 disables wrapping (default: 100)",
    )
    parser.add_argument(
        "--max-chars", type=int, default=0,
        help="truncate the output to this many characters (default: no limit)",
    )
    parser.add_argument(
        "--timeout", type=float, default=20, help="HTTP timeout in seconds"
    )

    llm = parser.add_argument_group("summarization")
    llm.add_argument(
        "-s", "--summarize", action="store_true",
        help="summarize the extracted content in 2-3 sentences",
    )
    llm.add_argument(
        "--summary-only", action="store_true",
        help="print only the summary (implies --summarize)",
    )
    llm.add_argument("--config", help="path to the JSON config file")
    llm.add_argument("--provider", help="provider name defined in the config")
    llm.add_argument("--model", help="override the configured model")
    llm.add_argument("--base-url", help="override the configured base URL")
    llm.add_argument(
        "--api", choices=list(config_module.SUPPORTED_APIS),
        help="override the wire format",
    )
    llm.add_argument(
        "--api-key-env", help="env var holding the API key (e.g. OPENAI_API_KEY)"
    )
    llm.add_argument("--prompt", help="override the summarization instruction")
    llm.add_argument(
        "--init-config", nargs="?", const="", metavar="PATH",
        help="write a sample config file and exit",
    )

    two_step = parser.add_argument_group("two-step summarization (requires spaCy)")
    two_step.add_argument(
        "-c", "--condense", action="store_true",
        help="rank sentences with spaCy first, then send only the best to the "
             "LLM (implies --summarize)",
    )
    two_step.add_argument(
        "--select-ratio", type=float, metavar="R",
        help="fraction of sentences to keep when condensing (default: 0.25)",
    )
    two_step.add_argument(
        "--spacy-model", metavar="NAME",
        help="spaCy pipeline to load (default: en_core_web_sm)",
    )
    two_step.add_argument(
        "--show-extract", action="store_true",
        help="print the condensed extract that is sent to the LLM",
    )

    audio = parser.add_argument_group("audio (requires pyttsx3)")
    audio.add_argument(
        "--speak", action="store_true",
        help="read the summary aloud (implies --summarize)",
    )
    audio.add_argument(
        "--audio", metavar="PATH",
        help="save the spoken summary to a file instead of playing it",
    )
    audio.add_argument("--voice", help="voice name or id (see --list-voices)")
    audio.add_argument("--rate", type=int, help="speech rate in words per minute")
    audio.add_argument("--volume", type=float, help="volume from 0.0 to 1.0")
    audio.add_argument(
        "--list-voices", action="store_true",
        help="list the installed voices and exit",
    )
    return parser


def overrides_from(args):
    """The CLI flags that override provider settings."""
    return {
        "provider": args.provider,
        "api": args.api,
        "base_url": args.base_url,
        "model": args.model,
        "api_key_env": args.api_key_env,
    }


def tts_overrides_from(args):
    """The CLI flags that override text-to-speech settings."""
    return {
        "voice": args.voice,
        "rate": args.rate,
        "volume": args.volume,
        "output": args.audio,
    }


def run_list_voices():
    from .speech import list_voices

    try:
        voices = list_voices()
    except ScraperError as error:
        print(error, file=sys.stderr)
        return EXIT_SPEECH_FAILED
    for voice_id, name, languages in voices:
        tags = ", ".join(languages) if languages else "-"
        print(f"{name or '?':<24} {tags:<12} {voice_id}")
    print(f"\n{len(voices)} voices. Pass one with --voice NAME.", file=sys.stderr)
    return EXIT_OK


def run_init_config(path):
    try:
        target = config_module.write_sample_config(path or None)
    except (ScraperError, OSError) as error:
        print(error, file=sys.stderr)
        return EXIT_FETCH_ERROR
    print(f"Wrote sample config to {target}")
    return EXIT_OK


def condense_overrides_from(args):
    """The CLI flags that override extractive-filter settings."""
    return {
        "enabled": args.condense or None,
        "select_ratio": args.select_ratio,
        "model": args.spacy_model,
    }


def run_condense(text, args, config):
    """Step one: shrink `text` with spaCy. Returns (extract, prompt_override)."""
    from .condense import compression_note, extractive_filter

    options = config_module.condense_settings(config, condense_overrides_from(args))
    if not options.get("enabled"):
        return text, None

    extract = extractive_filter(
        text,
        select_ratio=float(options.get("select_ratio", 0.25)),
        model=options.get("model") or "en_core_web_sm",
    )
    print(compression_note(text, extract, options.get("model")), file=sys.stderr)
    if args.show_extract:
        print(f"\n--- extract sent to the LLM ---\n{extract}\n", file=sys.stderr)
    return extract, options.get("prompt") or config_module.CONDENSE_PROMPT


def make_summary(text, args, config):
    """Return (summary, settings). Raises ConfigError / LLMError / CondenseError."""
    settings = config_module.resolve_provider(config, overrides_from(args))
    text, condense_prompt = run_condense(text, args, config)
    summary = summarize(
        text,
        settings,
        prompt=args.prompt or condense_prompt or config_module.prompt_for(config),
        max_input_chars=config_module.max_input_chars_for(config),
    )
    return summary, settings


def play_summary(summary, args, config):
    """Speak or save the summary. Returns an exit code."""
    from .speech import speak

    sys.stdout.flush()  # keep the printed summary ahead of the audio notices
    tts = config_module.tts_settings(config, tts_overrides_from(args))
    try:
        path = speak(
            summary,
            rate=tts.get("rate"),
            volume=tts.get("volume"),
            voice=tts.get("voice"),
            output=tts.get("output"),
        )
    except SpeechError as error:
        print(f"Audio failed: {error}", file=sys.stderr)
        return EXIT_SPEECH_FAILED
    if path:
        print(f"Saved audio to {path}", file=sys.stderr)
    return EXIT_OK


def print_summary(summary, settings, width, with_header):
    if with_header:
        label = f"Summary - {settings['model']} via {settings['name']}"
        rule = "-" * max(len(label) + 2, MIN_RULE_WIDTH)
        print(f"\n{rule}\n{label}\n{rule}")
    for paragraph in summary.split("\n\n"):
        print("\n".join(textwrap.wrap(paragraph, width or NO_WRAP)) or paragraph)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.init_config is not None:
        return run_init_config(args.init_config)
    if args.list_voices:
        return run_list_voices()
    if not args.url:
        parser.error("the following arguments are required: url")
    if args.summary_only or args.speak or args.audio or args.condense:
        args.summarize = True
    wants_audio = args.speak or args.audio

    try:
        html = fetch(normalize_url(args.url), timeout=args.timeout)
    except FetchError as error:
        print(error, file=sys.stderr)
        return EXIT_FETCH_ERROR

    text = extract_article(html).text(width=args.width)
    if not text:
        print("No readable content found on that page.", file=sys.stderr)
        return EXIT_NO_CONTENT

    config = {}
    summary = settings = None
    if args.summarize:
        # Summarize the full extraction, before any --max-chars truncation.
        try:
            config = config_module.load_config(args.config)
            summary, settings = make_summary(text, args, config)
        except (CondenseError, ConfigError, LLMError) as error:
            print(f"Summarization failed: {error}", file=sys.stderr)
            if args.summary_only or wants_audio:
                return EXIT_SUMMARY_FAILED

    if args.max_chars and len(text) > args.max_chars:
        text = text[: args.max_chars].rstrip() + "\n\n[... truncated ...]"

    if not args.summary_only:
        print(text)
    if summary:
        width = args.width if args.width and args.width > 0 else 0
        print_summary(summary, settings, width, with_header=not args.summary_only)
        if wants_audio:
            return play_summary(summary, args, config)

    return EXIT_OK
