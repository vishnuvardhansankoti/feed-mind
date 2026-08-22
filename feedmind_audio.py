#!/usr/bin/env python3
"""Turn the newest FeedMind content into spoken summaries in Cloud Storage.

Two sources, selected with --process-doc:

  RSS_FEED (default)   every article sharing the latest processed_at date in
                       `processed_articles`. The page is scraped for its text.

  RESEARCH_PAPERS      every paper in the latest run of each category in
                       `runs`. The stored abstract is the text, so nothing is
                       fetched over the network.

Both then follow the same tail:

    text -> spaCy extractive filter -> LLM rewrite -> pyttsx3 -> ffmpeg
         -> Cloud Storage -> Firestore (ai_summary, audio_url, audio_generated_at)

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
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

# The speech engine forks while gRPC's poll engine is live, which makes gRPC
# log an INFO-level complaint about inherited file descriptors. Harmless, but
# it has to be set before google.cloud pulls grpc in.
os.environ.setdefault("GRPC_VERBOSITY", "ERROR")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google.api_core import exceptions as gcp_exceptions  # noqa: E402
from google.cloud import firestore, storage  # noqa: E402

from webscraper import config as ws_config  # noqa: E402
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

# Fields this script adds. FeedMind's own fields are never touched.
AI_SUMMARY_FIELD = "ai_summary"
AUDIO_URL_FIELD = "audio_url"
AUDIO_GENERATED_AT_FIELD = "audio_generated_at"

# Written by an earlier version of this script; migrated into AI_SUMMARY_FIELD.
LEGACY_SUMMARY_FIELD = "audio_summary"

EXIT_OK = 0
EXIT_NO_ITEMS = 1
EXIT_ALL_FAILED = 2


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
                title=doc.get("title") or "(untitled)",
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
                    title=paper.get("title") or "(untitled)",
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
        mp3 = synthesize(summary, Path(tmp), args, context["ffmpeg"])
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
    parser.add_argument("--config", help="path to the webscraper JSON config")
    parser.add_argument("--provider", help="LLM provider name from the config")
    parser.add_argument("--model", help="override the LLM model")
    parser.add_argument(
        "--select-ratio", type=float,
        help="fraction of sentences spaCy keeps (default: 0.25)",
    )
    parser.add_argument("--voice", help="pyttsx3 voice name or id")
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
            "ffmpeg": require_ffmpeg(),
        }
    except (ScraperError, PipelineError) as error:
        log(str(error))
        return EXIT_ALL_FAILED

    log(f"  model: {settings['model']} via {settings['name']}")
    if args.dry_run:
        log("  DRY RUN - no uploads, no Firestore writes")
    log()

    failures = []
    for index, item in enumerate(chosen, start=1):
        tag = f"{item.note} " if item.note else ""
        log(f"[{index:2}/{len(chosen)}] {tag}{item.item_id[:14]}  {item.title[:58]}")
        try:
            audio_url = process(item, context)
        except (PipelineError, ScraperError, gcp_exceptions.GoogleAPIError) as error:
            log(f"         FAILED: {error}")
            failures.append((item.item_id, str(error)))
            continue
        print(audio_url or f"(dry run) {item.item_id}", flush=True)

    succeeded = len(chosen) - len(failures)
    log()
    log(f"{succeeded} succeeded, {len(failures)} failed")
    for item_id, reason in failures:
        log(f"  {item_id[:14]}  {reason}")

    return EXIT_ALL_FAILED if succeeded == 0 else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
