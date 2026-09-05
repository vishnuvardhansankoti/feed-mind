"""
FeedMind — Feed configuration and constants.

Update RSS_FEEDS with validated URLs before deploying.
The URLs below are best-effort canonical paths; validate them
against each source's actual RSS endpoint before first run.
"""

# ---------------------------------------------------------------------------
# RSS Feed Definitions
# ---------------------------------------------------------------------------
# Each entry: (human_readable_name, rss_url, category, post_to_telegram)
# category: one of "academic" | "industry" | "cloud" | "top_stories"
# post_to_telegram: when False the feed is still fetched, summarized and written
#   to Firestore (so the paper-prism web reader keeps showing it), but its
#   articles are left out of the batched Telegram messages.

RSS_FEEDS = [
    # --- Academic / Research ---
    # ("arXiv ML",           "https://rss.arxiv.org/rss/cs.LG",                                      "academic", True),
    # ("arXiv AI",           "https://rss.arxiv.org/rss/cs.AI",                                      "academic", True),
    # ("arXiv NLP", "https://rss.arxiv.org/rss/cs.CL",                                      "academic", True),
    ("Hugging Face Papers", "https://huggingface.co/blog/feed.xml", "academic", True),
    ("Google Research Blog", "https://research.google/blog/rss/", "academic", True),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "academic", True),
    (
        "Google Developers Blog",
        "https://developers.googleblog.com/feeds/posts/default/",
        "academic",
        True,
    ),
    ("NVIDIA Developer Blog", "https://developer.nvidia.com/blog/feed/", "industry", True),
    # --- Industry News ---
    ("OpenAI News", "https://openai.com/news/rss.xml", "industry", True),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "industry", True),
    (
        "TechCrunch AI",
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "industry",
        True,
    ),
    ("ByteByteGo", "https://blog.bytebytego.com/feed", "industry", True),
    ("Daily AI", "https://dailyai.com/feed/", "industry", True),
    ("Meta Engineering", "https://engineering.fb.com/feed/", "industry", True),
    ("Netflix Tech Blog", "https://netflixtechblog.com/feed", "industry", True),
    # --- Cloud Computing ---
    ("CNCF Blog", "https://www.cncf.io/blog/feed/", "cloud", True),
    ("AWS News Blog", "https://aws.amazon.com/blogs/aws/feed/", "cloud", True),
    ("Google Cloud Blog", "https://cloudblog.withgoogle.com/rss", "cloud", True),
    ("Azure Updates", "https://azure.microsoft.com/en-us/blog/feed/", "cloud", True),
    ("Amazon ML Research", "https://aws.amazon.com/blogs/machine-learning/feed/", "cloud", True),
    # ---- News ---
    (
        "TOI Top Stories",
        "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
        "top_stories",
        False,
    ),
]

# ---------------------------------------------------------------------------
# YouTube Feeds
# ---------------------------------------------------------------------------
# YouTube channel RSS feeds. These are NOT delivered via Telegram — new videos
# from the last MAX_VIDEO_AGE_DAYS are written to the `youtube_videos` Firestore
# collection and surfaced by the paper-prism web app's "Videos" page.
# Each entry: (channel_name, feed_url)
YOUTUBE_FEEDS = [
    (
        "Aishwarya Srinivasan",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCzd4ZN716evEjtbJERBMTfg",
    ),
    ("Vaibhav", "https://www.youtube.com/feeds/videos.xml?channel_id=UClXAalunTPaX1YV185DWUeg"),
    (
        "HyperAutomation Labs",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCiax-xbEI0P6Y8C8VwZGMgQ",
    ),
    (
        "Think School",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UCKZozRVHRYsYHGEyNKuhhdA",
    ),
    (
        "AI Revolution",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC5l7RouTQ60oUjLjt1Nh-UQ",
    ),
    (
        "Sam Witteveen AI",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC55ODQSvARtgSyc8ThfiepQ",
    ),
    ("Fahd Mirza", "https://www.youtube.com/feeds/videos.xml?channel_id=UCPix8N6PMRI4KzgyjuZeF0g"),
]

# Only videos published within this many days are ingested per run. Firestore
# accumulates a rolling history under the 90-day TTL; the web app slices its own
# window (Latest = newest day, Archive = last 3 days).
MAX_VIDEO_AGE_DAYS = 1

# ---------------------------------------------------------------------------
# Static Links
# ---------------------------------------------------------------------------
# Direct links appended daily without RSS fetching.
# Each entry: (title, url, category, message)
STATIC_LINKS = [
    (
        "GitHub Trending",
        "https://github.com/trending",
        "open-source",
        "Check out today's trending open-source repositories!",
    ),
]

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
