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
    ("arXiv ML",           "https://rss.arxiv.org/rss/cs.LG",                                      "academic"),
    ("arXiv AI",           "https://rss.arxiv.org/rss/cs.AI",                                      "academic"),
    ("Hugging Face Papers","https://huggingface.co/blog/feed.xml",                                  "academic"),
    ("MIT Tech Review",    "https://www.technologyreview.com/feed/",                               "academic"),

    # --- Industry News ---
    ("OpenAI News",        "https://openai.com/news/rss.xml",                                       "industry"),
    ("Google DeepMind",    "https://deepmind.google/blog/rss.xml",                                  "industry"),
    ("Google Research Blog", "https://research.google/blog/rss/",                        "industry"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/",                        "industry"),
    ("TechCrunch AI",      "https://techcrunch.com/category/artificial-intelligence/feed/",         "industry"),

    # --- Cloud Computing ---
    ("CNCF Blog",          "https://www.cncf.io/blog/feed/",                                        "cloud"),
    ("AWS News Blog",      "https://aws.amazon.com/blogs/aws/feed/",                                "cloud"),
    ("Google Cloud Blog",  "https://cloudblog.withgoogle.com/rss",                                     "cloud"),
    ("Azure Updates",      "https://azure.microsoft.com/en-us/blog/feed/",                      "cloud"),
]

# ---------------------------------------------------------------------------
# GCP / Secret Manager
# ---------------------------------------------------------------------------
GCP_PROJECT_ID = "feed-mind"   # TODO: replace before deploying

SECRET_NAME_TELEGRAM_TOKEN   = "TELEGRAM_BOT_TOKEN"
SECRET_NAME_TELEGRAM_CHAT_ID = "TELEGRAM_CHAT_ID"
SECRET_NAME_GEMINI_API_KEY   = "GEMINI_API_KEY"

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
ENABLE_GEMINI_SUMMARIES = False
GEMINI_MODEL            = "gemini-3.5-flash-lite"
GEMINI_TIMEOUT_SECONDS  = 30
GEMINI_REQUEST_DELAY_S  = 4       # sleep between Gemini calls to respect free-tier RPM (~15/min)
MAX_SNIPPET_CHARS       = 2_000   # truncate article text before sending to Gemini

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
FEED_FETCH_TIMEOUT_SECONDS = 10   # per-feed connection timeout
MAX_ARTICLE_AGE_DAYS       = 1    # skip articles older than this

# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------
TELEGRAM_API_BASE           = "https://api.telegram.org"
TELEGRAM_MESSAGE_DELAY_S    = 1      # sleep between messages to respect rate limits
TELEGRAM_MAX_MESSAGE_LENGTH = 4000   # maximum characters per Telegram message chunk

# ---------------------------------------------------------------------------
# Firestore
# ---------------------------------------------------------------------------
FIRESTORE_DATABASE   = "feed-mind-db"   # Use "(default)" if you didn't name your database
FIRESTORE_COLLECTION = "processed_articles"

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FUNCTION_SOFT_TIMEOUT_S = 240   # warn and exit gracefully before the 300s hard limit
