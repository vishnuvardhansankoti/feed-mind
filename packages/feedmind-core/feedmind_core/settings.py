"""
settings.py — constants shared by every FeedMind service.

**Feed lists are NOT here.** Which URLs a service fetches, what it does with
them, and whether it wakes the Telegram notifier are per-service data and live
in that service's `feeds.yaml`, loaded by `serviceconfig.py`. This module holds
only what is genuinely global: the GCP project, collection names, API tuning,
and the topic names the services use to talk to each other.

The split matters: adding a feed should be a one-line YAML edit in one service,
not a change to a module every other service imports.
"""

# Only videos published within this many days are ingested per run. Firestore
# accumulates a rolling history under the 90-day TTL; the web app slices its own
# window (Latest = newest ingest batch, Archive = last 3 days).
MAX_VIDEO_AGE_DAYS = 1

# ---------------------------------------------------------------------------
# GCP / Secret Manager
# ---------------------------------------------------------------------------
GCP_PROJECT_ID = "feed-mind"  # TODO: replace before deploying

SECRET_NAME_TELEGRAM_TOKEN = "TELEGRAM_BOT_TOKEN"
SECRET_NAME_TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"
SECRET_NAME_GEMINI_API_KEY = "GEMINI_API_KEY"

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
ENABLE_GEMINI_SUMMARIES = False
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_TIMEOUT_SECONDS = 30
GEMINI_REQUEST_DELAY_S = 4  # sleep between Gemini calls to respect free-tier RPM (~15/min)
MAX_SNIPPET_CHARS = 2_000  # truncate article text before sending to Gemini

GEMINI_SYSTEM_PROMPT = (
    "You are a highly technical AI research assistant summarizing content "
    "for a senior ML engineer.\n"
    "Your task is to summarize the following article in exactly one concise sentence.\n"
    "Rules:\n"
    "- The summary must be ≤20 words.\n"
    "- Use technical language. Do not oversimplify.\n"
    "- Output ONLY the one sentence.\n"
    "- Do NOT include a preamble, title, or closing statement."
)

# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
FEED_FETCH_TIMEOUT_SECONDS = 10  # per-feed connection timeout
MAX_ARTICLE_AGE_DAYS = 1  # skip articles older than this

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_MESSAGE_DELAY_S = 1  # sleep between messages to respect rate limits
TELEGRAM_MAX_MESSAGE_LENGTH = 4000  # maximum characters per Telegram message chunk

# ---------------------------------------------------------------------------
# Firestore
# ---------------------------------------------------------------------------
FIRESTORE_DATABASE = "feed-mind-db"  # Use "(default)" if you didn't name your database
FIRESTORE_COLLECTION = "processed_articles"
FIRESTORE_YOUTUBE_COLLECTION = "youtube_videos"

# Written by the sibling paper-prism repo, not by this one — read-only here, and
# only by the archiver. Each doc holds a `papers` array and carries a 45-day TTL
# on `expire_at` (note: not `expires_at`, which is what this repo's own
# collections use).
FIRESTORE_RUNS_COLLECTION = "runs"

# ---------------------------------------------------------------------------
# Pub/Sub — telling downstream consumers a run has finished
# ---------------------------------------------------------------------------
# feed-mind-summarizer listens on this topic and turns the articles this run
# wrote into spoken summaries. FeedMind is the only thing that knows when new
# articles have actually landed, so it announces rather than letting the
# consumer guess with a schedule of its own. See feedmind/events.py.
ENABLE_CONTENT_READY_EVENTS = True
CONTENT_READY_TOPIC = "feedmind-content-ready"

# Which of the consumer's two pipelines to run. The papers pipeline is fed by
# paper-prism, not by this service.
CONTENT_READY_PROCESS_DOC = "RSS_FEED"

# ---------------------------------------------------------------------------
# Pub/Sub — telling the Telegram notifier there is something to send
# ---------------------------------------------------------------------------
# An ingest service writes articles to Firestore, then publishes here. The
# notifier is a separate function so that a Telegram outage cannot cost us the
# ingest: the articles are already stored, and the notifier retries.
#
# The message is deliberately almost empty — see events.publish_telegram_ready.
# It is a doorbell, not a payload. Everything the notifier needs is the set of
# documents carrying TELEGRAM_PENDING, which it queries for itself.
TELEGRAM_READY_TOPIC = "feedmind-telegram-ready"

# ---------------------------------------------------------------------------
# Telegram delivery state (the `telegram_status` field on processed_articles)
# ---------------------------------------------------------------------------
# The old single-function pipeline wrote a document ONLY after Telegram accepted
# it, so "exists in Firestore" meant "delivered". Splitting ingest from delivery
# makes that impossible — the document has to exist before the notifier can be
# told about it — so delivery state becomes an explicit field.
#
# This is what preserves the old retry property. A doc left PENDING (notifier
# crashed, Telegram down, Pub/Sub message dropped) is picked up by the next
# trigger, because the notifier queries state rather than trusting the message.
TELEGRAM_PENDING = "pending"   # written by ingest; awaiting delivery
TELEGRAM_SENT = "sent"         # notifier confirmed delivery
TELEGRAM_SKIPPED = "skipped"   # this feed never goes to Telegram

# Most articles the notifier will pull in one invocation. A cap is required:
# the query is unbounded otherwise, and a long backlog would run the function
# past its timeout mid-batch. Anything left over stays PENDING and is collected
# on the next trigger.
TELEGRAM_MAX_ARTICLES_PER_RUN = 200

# ---------------------------------------------------------------------------
# BigQuery archive
# ---------------------------------------------------------------------------
# The Firestore collections above are all on TTLs (90 days for this repo's, 45
# for paper-prism's `runs`), so anything not copied out is deleted for good.
# The `feedmind-archive` function copies every live document into BigQuery on
# the 1st and 16th of each month. See docs/bigquery-archival-plan.md.
BQ_DATASET = "feedmind_archive"
BQ_LOCATION = "US"

# --- Free-tier guardrails --------------------------------------------------
# BigQuery's always-free tier is 1 TiB of query processing and 10 GiB of
# storage per month. Batch loads are free; streaming inserts are not. The
# archive sits far inside all of that, and these two limits are what make that
# a guarantee rather than an expectation.

# Refuse any query that would scan more than this. BigQuery rejects the job
# *before* running it, so a runaway MERGE fails loudly in the Telegram report
# instead of quietly billing. Sized for ~50x the current archive: normal growth
# (roughly 200 MB/year, and the MERGE scans the whole target each run) will not
# reach it for decades, so tripping this means a bug, not success.
BQ_MAX_BYTES_BILLED = 10 * 1024**3  # 10 GiB

# Report storage against the 10 GiB free tier, and start saying so out loud at
# 80%. Storage is the only limit here that grows monotonically — queries and
# loads reset monthly, bytes kept do not.
BQ_FREE_STORAGE_BYTES = 10 * 1024**3
BQ_STORAGE_WARN_BYTES = 8 * 1024**3

# One line per run to Telegram. This is not decoration: with a 16-day cadence
# against a 45-day TTL it is the only thing standing between a silently broken
# run and permanent data loss.
ENABLE_ARCHIVE_TELEGRAM_REPORT = True

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FUNCTION_SOFT_TIMEOUT_S = 240  # warn and exit gracefully before the 300s hard limit
