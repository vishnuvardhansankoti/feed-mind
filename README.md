# FeedMind

A self-hosted, serverless RSS ingestion and AI-summarization pipeline running on GCP.

Ingests 11 RSS feeds (AI/ML research, industry news, cloud computing), summarizes new articles using **Gemini 3.5 Flash Lite** (or the offline **Sumy NLP** library), and pushes batched notifications to a private **Telegram bot** — once daily, at $0/month.

---

## Project Structure

```
feed-mind/
├── main.py             # Cloud Function entry point (HTTP trigger)
├── feedmind/           # Core application package
│   ├── __init__.py
│   ├── config.py       # Feed URLs, constants, system prompt
│   ├── secrets.py      # GCP Secret Manager loader
│   ├── ingestion.py    # RSS feed fetching & parsing (feedparser)
│   ├── deduplication.py # Firestore dedup check & write
│   ├── summarization.py # Gemini AI & Sumy offline NLP summarization
│   ├── notification.py # Telegram batched message delivery
│   └── events.py       # Pub/Sub announcement when a run finishes
├── tests/              # Unit tests
│   ├── __init__.py
│   └── test_config.py
├── pyproject.toml      # Python dependencies & config
└── deploy.sh           # One-shot GCP deployment script
```

---

## Prerequisites

1. **GCP Project** with billing enabled (free tier is sufficient)
2. **gcloud CLI** installed: https://cloud.google.com/sdk/docs/install
3. **Telegram Bot** created via [@BotFather](https://t.me/botfather) — get your bot token and chat ID
4. **Gemini API Key** from [Google AI Studio](https://aistudio.google.com/app/apikey)
5. **Firestore** database created in Native Mode (GCP Console → Firestore → Create Database)

---

## Setup

### 1. Clone & configure

```bash
git clone <repo>
cd feed-mind
```

Edit `config.py`:
- Set `GCP_PROJECT_ID` to your GCP project ID
- Validate and update the RSS feed URLs in `RSS_FEEDS` (some may need real RSS paths)

### 2. Set up Firestore Database

This project uses Firestore to keep track of articles it has already seen (deduplication).

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your project.
3. In the navigation menu, go to **Firestore**.
4. Click **Create Database**.
5. Select **Native mode** (required for this project).
6. Choose a location (e.g., `nam5` for multi-region US or a specific region) and click **Create Database**.

### 3. Create secrets in Secret Manager

```bash
PROJECT_ID="your-gcp-project-id"

# Telegram Bot Token (from BotFather)
echo -n "YOUR_TELEGRAM_BOT_TOKEN" | \
  gcloud secrets create TELEGRAM_BOT_TOKEN --data-file=- --project=$PROJECT_ID

# Telegram Chat ID (your personal chat ID or group ID)
echo -n "YOUR_TELEGRAM_CHAT_ID" | \
  gcloud secrets create TELEGRAM_CHAT_ID --data-file=- --project=$PROJECT_ID

# Gemini API Key (from Google AI Studio)
echo -n "YOUR_GEMINI_API_KEY" | \
  gcloud secrets create GEMINI_API_KEY --data-file=- --project=$PROJECT_ID
```

> **Tip:** To find your Telegram Chat ID, send a message to your bot and call:
> `https://api.telegram.org/bot<TOKEN>/getUpdates`

### 4. Deploy

```bash
# Update PROJECT_ID and SCHEDULER_TIMEZONE in deploy.sh first
chmod +x deploy.sh
./deploy.sh
```

The script will:
- Enable all required GCP APIs
- Create a `feedmind-sa` service account with minimum IAM roles
- Deploy the Cloud Function (Gen 2, authenticated only)
- Set up a Cloud Scheduler job (daily at 8 AM)

### 5. Test manually

```bash
gcloud scheduler jobs run feedmind-daily-trigger \
  --location=us-central1 \
  --project=your-gcp-project-id
```

Then check Cloud Logging:
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND jsonPayload.message="FeedMind run complete"' \
  --limit=5 \
  --project=your-gcp-project-id \
  --format=json
```

---

## Downstream: announcing a finished run

As its last step, FeedMind publishes to a Pub/Sub topic so downstream consumers
know new articles have landed. Today there is one consumer —
[`feed-mind-summarizer`](../feed-mind-summarizer), which turns those articles
into spoken summaries.

```
FeedMind run ends ──publish──► feedmind-content-ready ──► feedmind-audio
```

FeedMind is the only thing that knows when its run actually finished, so it
announces rather than leaving the consumer to guess with a schedule of its own.
The message is small — `process_doc` selects which consumer pipeline to run, the
rest is provenance:

```json
{"process_doc": "RSS_FEED", "source": "feed-mind", "articles_delivered": 7,
 "run_completed_at": "2026-08-23T13:15:04+00:00"}
```

Two deliberate behaviours in `feedmind/events.py`:

- **Nothing is published when no articles were delivered.** Waking the consumer
  to find an empty batch costs a cold start and buys nothing.
- **Publishing is best-effort.** A run that summarized and delivered has done
  its job; failing it because Pub/Sub was unreachable would turn a good run into
  a retried one, and the retry would re-deliver every article to Telegram.
  Errors are logged and swallowed.

Publishing happens after every article is written to Firestore — the consumer
reads that collection, so announcing any earlier would race it.

| Setting | In `feedmind/config.py` |
|---|---|
| `ENABLE_CONTENT_READY_EVENTS` | `True` — set `False` to stop announcing |
| `CONTENT_READY_TOPIC` | `feedmind-content-ready` |
| `CONTENT_READY_PROCESS_DOC` | `RSS_FEED` |

The topic itself, and `feedmind-sa`'s `roles/pubsub.publisher` grant on it, are
created by the consumer's `deploy/setup.sh` — the topic belongs to whoever reads
it. Run that before deploying this side, or the first publish will log a
permission error (and only that: the run still succeeds).

---

## Local Development

We use [uv](https://docs.astral.sh/uv/) for lightning-fast Python dependency management.

```bash
# Install dependencies and create a virtual environment automatically
uv sync

# Run locally using Functions Framework
# (requires Application Default Credentials: gcloud auth application-default login)
uv run functions-framework --target=feedmind --debug
```

Then trigger it:
```bash
curl -X POST http://localhost:8080
```

> For local runs, Application Default Credentials (ADC) are used automatically.
> Ensure your local ADC has access to Secret Manager and Firestore in your GCP project.

### Linting

```bash
# Check for lint errors
uv run ruff check .

# Auto-fix fixable lint errors
uv run ruff check --fix .
```

---

## Cost Analysis

| Service | Monthly Usage | Free Limit | Cost |
|---------|--------------|------------|------|
| Cloud Functions | 30 invocations | 2M/month | $0.00 |
| Cloud Scheduler | 1 job | 3 jobs | $0.00 |
| Firestore reads | ~6,600 | 1.5M/month | $0.00 |
| Firestore writes | ~450 | 600K/month | $0.00 |
| Secret Manager | 90 accesses | 10K/month | $0.00 |
| Gemini 3.5 Lite (Optional) | ~450 req | 45K/month | $0.00 |
| **Total** | | | **$0.00** |

---

## Telegram Message Format

Articles are now **batched by category** to reduce notification spam. Each daily run yields up to 3 messages (Academic, Industry, Cloud). 
Example:

```text
*🎓 Academic News*

• *Attention Is All You Need* — Introduces multi-head self-attention replacing recurrence in seq2seq models.
  🔗 Read More | 📰 arXiv ML

• *LoRA: Low-Rank Adaptation* — A new technique that freezes pre-trained model weights.
  🔗 Read More | 📰 Hugging Face Papers
```

---

## Open Items Before Production

- [ ] Validate all 11 RSS feed URLs return valid feeds
- [ ] Set correct timezone in `deploy.sh` (`SCHEDULER_TIMEZONE`)
- [ ] Replace `your-gcp-project-id` in `config.py` and `deploy.sh`
- [ ] Create Firestore database in Native Mode
- [ ] Create all 3 secrets in Secret Manager
