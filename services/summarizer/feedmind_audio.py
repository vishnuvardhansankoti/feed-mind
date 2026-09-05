#!/usr/bin/env python3
"""Turn the newest FeedMind content into spoken summaries in Cloud Storage.

Two sources, selected with --process-doc:

  RSS_FEED (default)   every article sharing the latest processed_at date in
                       `processed_articles`. The page is scraped for its text.

  RESEARCH_PAPERS      every paper in the latest run of each category in
                       `runs`. The stored abstract is the text, so nothing is
                       fetched over the network.

Both then follow the same tail:

    text -> spaCy extractive filter -> LLM rewrite -> title prepended -> speech
         -> Cloud Storage -> Firestore (ai_summary, audio_url, audio_generated_at)

The title is prepended for speech only (see speech_text); the summary stored in
ai_summary stays free of it.

Speech comes from one of two backends, chosen with --tts: pyttsx3 plus an
ffmpeg transcode locally, or the Google Text-to-Speech API when deployed.

Items are independent: one failure is logged and the batch continues. Each
Firestore write happens only after that item's upload succeeds, so a document
never points at an object that does not exist.

Usage:
    python feedmind_audio.py                            # latest RSS batch
    python feedmind_audio.py --process-doc RESEARCH_PAPERS
    python feedmind_audio.py --process-doc RESEARCH_PAPERS --category CV
    python feedmind_audio.py --limit 2 --dry-run        # no uploads, no writes
    python feedmind_audio.py --force                    # redo finished items
    python feedmind_audio.py --article-id <id>          # article_id, or arxiv_id
    python feedmind_audio.py --tts cloud                # Google Text-to-Speech
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# The speech engine forks while gRPC's poll engine is live, which makes gRPC
# log an INFO-level complaint about inherited file descriptors. Harmless, but
# it has to be set before google.cloud pulls grpc in.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feedmind_push import notify  # noqa: E402
from google.api_core import exceptions as gcp_exceptions  # noqa: E402
from google.cloud import firestore, storage  # noqa: E402
from webscraper import config as ws_config  # noqa: E402
from webscraper.cloud_speech import synthesize_mp3  # noqa: E402
from webscraper.condense import compression_note, extractive_filter  # noqa: E402
from webscraper.errors import ScraperError  # noqa: E402
from webscraper.extractor import extract_article  # noqa: E402
from webscraper.fetcher import fetch  # noqa: E402
from webscraper.llm import summarize  # noqa: E402
from webscraper.speech import speak  # noqa: E402

# -- FeedMind's own settings; see feed-mind/feedmind/config.py ---------------
GCP_PROJECT_ID = "feed-mind"
FIRESTORE_DATABASE = "feed-mind-db"
ARTICLES_COLLECTION = "processed_articles"
RUNS_COLLECTION = "runs"
BUCKET_NAME = "feed-mind-audio-summaries"

PAPERS_PREFIX = "research-papers"
PAPERS_ARRAY = "papers"

PUBLIC_URL = "https://storage.googleapis.com/{bucket}/{blob}"
AUDIO_CONTENT_TYPE = "audio/mpeg"
AUDIO_BITRATE = "64k"

RSS_FEED = "RSS_FEED"
RESEARCH_PAPERS = "RESEARCH_PAPERS"

# Which speech engine to use. `local` is pyttsx3 plus an ffmpeg transcode, and
# needs a machine with a speech engine on it. `cloud` is the Text-to-Speech API,
# which returns MP3 directly and is the only one that works on a serverless
# runtime - so the deployed function sets FEEDMIND_TTS=cloud.
TTS_LOCAL = "local"
TTS_CLOUD = "cloud"
TTS_ENV_VAR = "FEEDMIND_TTS"

# Wall-clock budget for the batch, so a serverless runtime with a hard kill can
# be given a deadline to stop short of. See --max-runtime.
MAX_RUNTIME_ENV_VAR = "FEEDMIND_MAX_RUNTIME"

# Fields this script adds. FeedMind's own fields are never touched.
AI_SUMMARY_FIELD = "ai_summary"
AUDIO_URL_FIELD = "audio_url"
AUDIO_GENERATED_AT_FIELD = "audio_generated_at"

# Written by an earlier version of this script; migrated into AI_SUMMARY_FIELD.
LEGACY_SUMMARY_FIELD = "audio_summary"

# Stand-in for a document with no usable title. It is a progress-log label, not
# something to speak: speech_text() drops it rather than opening a clip by
# announcing "untitled".
UNTITLED = "(untitled)"

EXIT_OK = 0
EXIT_NO_ITEMS = 1
EXIT_ALL_FAILED = 2
# Stopped on --max-runtime with items still to do. Distinct from EXIT_OK so a
# caller can arrange to be called again; see main.py.
EXIT_INCOMPLETE = 3


class PipelineError(RuntimeError):
    """A step failed for one item; nothing was written for it."""


def log(message=""):
    """Progress goes to stderr so stdout stays parseable."""
    print(message, file=sys.stderr, flush=True)


@dataclass
class Item:
    """One unit of work — an article to scrape, or a paper already in hand."""

    item_id: str
    title: str
    blob: str
    record: Callable[[str, str], None]
    url: str = ""          # scraped when `text` is empty
    text: str = ""         # supplied directly (papers)
    fallback: str = ""     # used when the scrape fails
    done: bool = False     # already has audio
    note: str = ""         # extra label for the progress line


# ----------------------------------------------------------------------
# Firestore
# ----------------------------------------------------------------------
def open_firestore():
    return firestore.Client(project=GCP_PROJECT_ID, database=FIRESTORE_DATABASE)


def audio_fields(summary, audio_url):
    return {
        AI_SUMMARY_FIELD: summary,
        AUDIO_URL_FIELD: audio_url,
        AUDIO_GENERATED_AT_FIELD: datetime.now(UTC).isoformat(),
    }


# -- RSS_FEED ----------------------------------------------------------
def processed_date(doc):
    """The YYYY-MM-DD portion of an ISO-8601 processed_at string."""
    return (doc.get("processed_at") or "")[:10]


def record_article(snapshot, drop_legacy):
    """Return a callback that writes the audio fields onto an article doc."""
    def write(summary, audio_url):
        payload = audio_fields(summary, audio_url)
        if drop_legacy:
            payload[LEGACY_SUMMARY_FIELD] = firestore.DELETE_FIELD
        snapshot.reference.update(payload)
    return write


def collect_articles(db, args):
    """Items for every article sharing the most recent processed_at date.

    Firestore cannot filter on "field is missing", and ordering by audio_url
    would exclude exactly the documents that need audio, so the date is found
    and the batch assembled client-side.
    """
    collection = db.collection(ARTICLES_COLLECTION)

    if args.article_id:
        snapshot = collection.document(args.article_id).get()
        if not snapshot.exists:
            raise PipelineError(f"No document {args.article_id!r} in {ARTICLES_COLLECTION}.")
        snapshots = [snapshot]
        day = processed_date(snapshot.to_dict() or {})
    else:
        snapshots = list(collection.stream())
        if not snapshots:
            raise PipelineError(f"Collection {ARTICLES_COLLECTION} is empty.")
        # ISO-8601 UTC strings, always written by datetime.now(UTC).isoformat(),
        # so lexicographic max is chronological max.
        day = max(processed_date(snap.to_dict() or {}) for snap in snapshots)
        snapshots = [s for s in snapshots if processed_date(s.to_dict() or {}) == day]
        snapshots.sort(key=lambda s: (s.to_dict() or {}).get("processed_at", ""))

    items = []
    for snapshot in snapshots:
        doc = snapshot.to_dict() or {}
        article_id = doc.get("article_id") or snapshot.id
        items.append(
            Item(
                item_id=article_id,
                title=doc.get("title") or UNTITLED,
                blob=f"{processed_date(doc) or day}/{article_id}.mp3",
                record=record_article(snapshot, LEGACY_SUMMARY_FIELD in doc),
                url=doc.get("url") or "",
                fallback=(doc.get("summary") or "").strip(),
                done=bool(doc.get(AUDIO_URL_FIELD)),
            )
        )
    return f"latest processed_at date: {day}", items


# -- RESEARCH_PAPERS ---------------------------------------------------
def record_paper(db, doc_ref, arxiv_id):
    """Return a callback that updates one paper inside the `papers` array.

    Firestore has no way to address a single array element, so the array is
    rewritten wholesale. That happens inside a transaction to avoid clobbering
    a concurrent write from the FeedMind pipeline.
    """
    def write(summary, audio_url):
        transaction = db.transaction()

        @firestore.transactional
        def apply(tx, ref):
            snapshot = ref.get(transaction=tx)
            papers = list((snapshot.to_dict() or {}).get(PAPERS_ARRAY) or [])
            for index, paper in enumerate(papers):
                if paper.get("arxiv_id") == arxiv_id:
                    papers[index] = {**paper, **audio_fields(summary, audio_url)}
                    break
            else:
                raise PipelineError(f"{arxiv_id} vanished from {ref.id} before writing")
            tx.update(ref, {PAPERS_ARRAY: papers})

        apply(transaction, doc_ref)
    return write


def latest_run_per_category(db, category=None):
    """The newest run document for each category, keyed by category name."""
    newest = {}
    for snapshot in db.collection(RUNS_COLLECTION).stream():
        doc = snapshot.to_dict() or {}
        name = doc.get("category")
        run_date = doc.get("run_date")
        if not name or run_date is None:
            continue
        if category and name.upper() != category.upper():
            continue
        current = newest.get(name)
        if current is None or run_date > current[0]:
            newest[name] = (run_date, snapshot)
    return newest


def collect_papers(db, args):
    """Items for every paper in the latest run of each category."""
    newest = latest_run_per_category(db, args.category)
    if not newest:
        target = f" for category {args.category!r}" if args.category else ""
        raise PipelineError(f"No runs found in {RUNS_COLLECTION}{target}.")

    items = []
    labels = []
    for name in sorted(newest):
        run_date, snapshot = newest[name]
        doc = snapshot.to_dict() or {}
        day = run_date.strftime("%Y-%m-%d")
        papers = doc.get(PAPERS_ARRAY) or []
        labels.append(f"{name} {day} ({len(papers)})")

        for paper in papers:
            arxiv_id = paper.get("arxiv_id")
            if not arxiv_id:
                log(f"  skipping a paper in {snapshot.id} with no arxiv_id")
                continue
            if args.article_id and arxiv_id != args.article_id:
                continue
            items.append(
                Item(
                    item_id=arxiv_id,
                    title=paper.get("title") or UNTITLED,
                    blob=f"{PAPERS_PREFIX}/{day}/{name}/{arxiv_id}.mp3",
                    record=record_paper(db, snapshot.reference, arxiv_id),
                    text=(paper.get("abstract") or "").strip(),
                    fallback=(paper.get("summary") or "").strip(),
                    done=bool(paper.get(AUDIO_URL_FIELD)),
                    note=name,
                )
            )

    if args.article_id and not items:
        raise PipelineError(f"No paper with arxiv_id {args.article_id!r} in the latest runs.")
    return "latest run per category: " + ", ".join(labels), items


COLLECTORS = {RSS_FEED: collect_articles, RESEARCH_PAPERS: collect_papers}


# ----------------------------------------------------------------------
# Text
# ----------------------------------------------------------------------
def article_text(url, timeout):
    """Scraped article text, or None when the page cannot be read."""
    try:
        article = extract_article(fetch(url, timeout=timeout))
    except ScraperError as error:
        log(f"         scrape failed: {error}")
        return None

    text = article.text(width=0)
    if not text.strip():
        log("         scrape produced no readable content")
        return None
    return text


def build_summary(text, settings, options, config):
    """Condense with spaCy, then have the LLM rewrite the extract."""
    extract = extractive_filter(
        text,
        select_ratio=float(options.get("select_ratio") or 0.25),
        model=options.get("model") or "en_core_web_sm",
    )
    log("         " + compression_note(text, extract, options.get("model")))

    return summarize(
        extract,
        settings,
        prompt=options.get("prompt") or ws_config.CONDENSE_PROMPT,
        max_input_chars=ws_config.max_input_chars_for(config),
    )


# Punctuation that already ends a sentence, so the engine pauses on its own.
SENTENCE_ENDINGS = ".!?"
# Trailing punctuation that reads as a run-on when a new sentence follows it.
DANGLING_PUNCTUATION = " \t:;,-–—"


def speech_text(title, summary):
    """What the clip actually says: the item's title, then its summary.

    The summaries are 2–3 sentences with no lead-in — CONDENSE_PROMPT forbids
    one — which is fine on a card next to its heading, but leaves a "Listen All"
    queue as a run of anonymous clips with no way to tell what any of them is
    about.

    Spoken, never stored: process() still records the bare `summary`, so the
    card's "AI summary" disclosure does not repeat the heading directly above
    it.

    Cloud TTS is given plain text rather than SSML (see cloud_speech.py), so the
    pause between the two comes from punctuation alone — hence the terminator.
    """
    title = (title or "").strip()
    summary = (summary or "").strip()

    # UNTITLED is a log label; announcing "untitled" is worse than saying nothing.
    if not title or title == UNTITLED:
        return summary
    if not summary:
        return title

    # "Scaling laws:" or "A study -" would run straight into the summary.
    title = title.rstrip(DANGLING_PUNCTUATION)
    if not title:
        return summary
    # A title already ending in "?" or "!" keeps it, rather than collecting a
    # second terminator ("...at scale?." reads as a stumble).
    if title[-1] not in SENTENCE_ENDINGS:
        title += "."
    return f"{title} {summary}"


def source_text(item, args):
    """The text to summarize: supplied, scraped, or the stored fallback."""
    if item.text:
        return item.text
    if item.url:
        scraped = article_text(item.url, args.timeout)
        if scraped:
            return scraped
    if item.fallback:
        log("         falling back to the stored summary")
        return item.fallback
    raise PipelineError("no text available and no stored summary to fall back on")


# ----------------------------------------------------------------------
# Audio
# ----------------------------------------------------------------------
def require_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise PipelineError("ffmpeg is not on PATH - install it with: brew install ffmpeg")
    return ffmpeg


def to_mp3(source, target, ffmpeg):
    """Transcode the driver's native audio into a streamable MP3."""
    result = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(source),
         "-b:a", AUDIO_BITRATE, str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not target.exists():
        detail = (result.stderr or "").strip()[:300]
        raise PipelineError(f"ffmpeg failed: {detail}")
    return target


def synthesize(text, workdir, args, ffmpeg):
    """Speak `text` into an MP3 inside `workdir`."""
    if args.tts == TTS_CLOUD:
        # The API encodes MP3 itself, so there is nothing to transcode.
        return synthesize_mp3(
            text, workdir / "speech.mp3", voice=args.voice, rate=args.rate
        )

    # pyttsx3's macOS driver writes AIFF whatever extension it is handed.
    raw = speak(text, voice=args.voice, rate=args.rate, output=workdir / "speech.aiff")
    return to_mp3(raw, workdir / "speech.mp3", ffmpeg)


# ----------------------------------------------------------------------
# Cloud Storage
# ----------------------------------------------------------------------
def upload(client, path, destination):
    """Upload the MP3 and return its public URL."""
    try:
        blob = client.bucket(BUCKET_NAME).blob(destination)
        blob.upload_from_filename(str(path), content_type=AUDIO_CONTENT_TYPE)
    except gcp_exceptions.GoogleAPIError as error:
        raise PipelineError(f"upload failed: {error}")
    return PUBLIC_URL.format(bucket=BUCKET_NAME, blob=destination)


# ----------------------------------------------------------------------
# One item
# ----------------------------------------------------------------------
def process(item, context):
    """Run the pipeline for one item. Raises PipelineError on failure.

    Returns the audio URL, or None on a dry run.
    """
    args = context["args"]
    text = source_text(item, args)
    summary = build_summary(text, context["settings"], context["condense"],
                            context["config"])
    if not summary.strip():
        raise PipelineError("the model returned an empty summary")

    with tempfile.TemporaryDirectory(prefix="feedmind-audio-") as tmp:
        # Spoken text carries the title; the stored summary below does not.
        mp3 = synthesize(speech_text(item.title, summary), Path(tmp), args,
                         context["ffmpeg"])
        size_kb = mp3.stat().st_size / 1024

        if args.dry_run:
            log(f"         dry run - would upload gs://{BUCKET_NAME}/{item.blob} "
                f"({size_kb:.0f} KB)")
            return None

        audio_url = upload(context["storage"], mp3, item.blob)

    item.record(summary, audio_url)
    log(f"         {size_kb:.0f} KB -> gs://{BUCKET_NAME}/{item.blob}")
    return audio_url


# ----------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="feedmind_audio.py",
        description="Summarize the newest FeedMind content and publish one "
                    "audio file per item.",
    )
    parser.add_argument(
        "--process-doc", choices=[RSS_FEED, RESEARCH_PAPERS], default=RSS_FEED,
        help=f"which source to process (default: {RSS_FEED})",
    )
    parser.add_argument(
        "--category",
        help=f"only this category, e.g. AIML/CV/NLP ({RESEARCH_PAPERS} only)",
    )
    parser.add_argument(
        "--article-id",
        help="process only this item - an article_id, or an arxiv_id in "
             f"{RESEARCH_PAPERS} mode",
    )
    parser.add_argument(
        "--limit", type=int, help="process at most this many items"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="regenerate items that already have an audio_url",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="do everything except uploading and writing to Firestore",
    )
    parser.add_argument(
        "--timeout", type=float, default=30, help="HTTP timeout when scraping"
    )
    parser.add_argument(
        "--max-runtime", type=float,
        default=float(os.environ.get(MAX_RUNTIME_ENV_VAR) or 0),
        help="stop starting new items after this many seconds, exiting "
             f"{EXIT_INCOMPLETE} if any are left. 0 disables it. Defaults to "
             f"${MAX_RUNTIME_ENV_VAR}",
    )
    parser.add_argument("--config", help="path to the webscraper JSON config")
    parser.add_argument("--provider", help="LLM provider name from the config")
    parser.add_argument("--model", help="override the LLM model")
    parser.add_argument(
        "--select-ratio", type=float,
        help="fraction of sentences spaCy keeps (default: 0.25)",
    )
    parser.add_argument(
        "--tts", choices=[TTS_LOCAL, TTS_CLOUD],
        default=os.environ.get(TTS_ENV_VAR, TTS_LOCAL),
        help=f"speech engine: {TTS_LOCAL} (pyttsx3 + ffmpeg) or {TTS_CLOUD} "
             f"(Google Text-to-Speech). Defaults to ${TTS_ENV_VAR}, else "
             f"{TTS_LOCAL}",
    )
    parser.add_argument(
        "--voice",
        help=f"a pyttsx3 voice name or id, or a Cloud TTS voice name such as "
             f"en-US-Neural2-F with --tts {TTS_CLOUD}",
    )
    parser.add_argument("--rate", type=int, help="speech rate in words per minute")
    return parser


def select(items, args):
    """Drop finished items and apply --limit."""
    if args.force:
        chosen, skipped = list(items), 0
    else:
        chosen = [item for item in items if not item.done]
        skipped = len(items) - len(chosen)

    if args.limit is not None and args.limit >= 0:
        chosen = chosen[: args.limit]
    return chosen, skipped


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.category and args.process_doc != RESEARCH_PAPERS:
        build_parser().error(f"--category only applies to --process-doc {RESEARCH_PAPERS}")

    try:
        db = open_firestore()
        label, items = COLLECTORS[args.process_doc](db, args)
    except (PipelineError, gcp_exceptions.GoogleAPIError) as error:
        log(str(error))
        return EXIT_NO_ITEMS

    chosen, skipped = select(items, args)
    log(f"{args.process_doc} - {label}")
    log(f"  {len(items)} item(s), {skipped} already have audio, "
        f"{len(chosen)} to process")
    if not chosen:
        log("  nothing to do (use --force to regenerate)")
        return EXIT_OK

    try:
        config = ws_config.load_config(args.config)
        settings = ws_config.resolve_provider(
            config, {"provider": args.provider, "model": args.model}
        )
        context = {
            "args": args,
            "config": config,
            "settings": settings,
            "condense": ws_config.condense_settings(
                config, {"select_ratio": args.select_ratio}
            ),
            "storage": storage.Client(project=GCP_PROJECT_ID),
            # Only the local backend transcodes, so only it needs ffmpeg.
            "ffmpeg": require_ffmpeg() if args.tts == TTS_LOCAL else None,
        }
    except (ScraperError, PipelineError) as error:
        log(str(error))
        return EXIT_ALL_FAILED

    log(f"  model: {settings['model']} via {settings['name']}")
    log(f"  speech: {args.tts}" + (f" ({args.voice})" if args.voice else ""))
    if args.dry_run:
        log("  DRY RUN - no uploads, no Firestore writes")
    log()

    failures = []
    started = time.monotonic()
    remaining = 0

    for index, item in enumerate(chosen, start=1):
        # Checked between items, never inside one: stopping here means every
        # object uploaded has its matching Firestore write.
        if args.max_runtime and time.monotonic() - started >= args.max_runtime:
            remaining = len(chosen) - index + 1
            log(f"\nstopping after {args.max_runtime}s with {remaining} item(s) "
                f"still to do")
            break

        tag = f"{item.note} " if item.note else ""
        log(f"[{index:2}/{len(chosen)}] {tag}{item.item_id[:14]}  {item.title[:58]}")
        try:
            audio_url = process(item, context)
        except (PipelineError, ScraperError, gcp_exceptions.GoogleAPIError) as error:
            log(f"         FAILED: {error}")
            failures.append((item.item_id, str(error)))
            continue
        print(audio_url or f"(dry run) {item.item_id}", flush=True)

    attempted = len(chosen) - remaining
    succeeded = attempted - len(failures)
    log()
    log(f"{succeeded} succeeded, {len(failures)} failed, {remaining} not started")
    for item_id, reason in failures:
        log(f"  {item_id[:14]}  {reason}")

    if succeeded == 0:
        # Nothing worked, so being called again would only repeat it.
        return EXIT_ALL_FAILED

    # Announce the batch only once it is complete: a run stopped by
    # --max-runtime will be called again, and notifying per slice would send one
    # notification per invocation for a single day's content.
    if not remaining:
        notify(db, args.process_doc, succeeded, log, dry_run=args.dry_run)

    return EXIT_INCOMPLETE if remaining else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
