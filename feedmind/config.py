"""
FeedMind — Feed configuration and constants.

Update RSS_FEEDS with validated URLs before deploying.
The URLs below are best-effort canonical paths; validate them
against each source's actual RSS endpoint before first run.
"""

# ---------------------------------------------------------------------------
# RSS Feed Definitions
# ---------------------------------------------------------------------------
# Each entry: (human_readable_name, rss_url, category)
# category: one of "academic" | "industry" | "cloud"

RSS_FEEDS = [
    # --- Academic / Research ---
    # ("arXiv ML",           "https://rss.arxiv.org/rss/cs.LG",                                      "academic"),
    # ("arXiv AI",           "https://rss.arxiv.org/rss/cs.AI",                                      "academic"),
    # ("arXiv NLP", "https://rss.arxiv.org/rss/cs.CL",                                      "academic"),
    ("Hugging Face Papers", "https://huggingface.co/blog/feed.xml", "academic"),
    ("Google Research Blog", "https://research.google/blog/rss/", "academic"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", "academic"),
    (
        "Google Developers Blog",
        "https://developers.googleblog.com/feeds/posts/default/",
        "academic",
    ),
    ("NVIDIA Developer Blog", "https://developer.nvidia.com/blog/feed/", "industry"),
    # --- Industry News ---
    ("OpenAI News", "https://openai.com/news/rss.xml", "industry"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", "industry"),
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/", "industry"),
    ("ByteByteGo", "https://blog.bytebytego.com/feed", "industry"),
    ("Daily AI", "https://dailyai.com/feed/", "industry"),
    ("Meta Engineering", "https://engineering.fb.com/feed/", "industry"),
    ("Netflix Tech Blog", "https://netflixtechblog.com/feed", "industry"),
    # --- Cloud Computing ---
    ("CNCF Blog", "https://www.cncf.io/blog/feed/", "cloud"),
    ("AWS News Blog", "https://aws.amazon.com/blogs/aws/feed/", "cloud"),
    ("Google Cloud Blog", "https://cloudblog.withgoogle.com/rss", "cloud"),
    ("Azure Updates", "https://azure.microsoft.com/en-us/blog/feed/", "cloud"),
    ("Amazon ML Research", "https://aws.amazon.com/blogs/machine-learning/feed/", "cloud"),
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

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FUNCTION_SOFT_TIMEOUT_S = 240  # warn and exit gracefully before the 300s hard limit
