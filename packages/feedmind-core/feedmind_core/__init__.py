"""
feedmind_core — the pipeline every FeedMind service shares.

    feed URLs (feeds.yaml) -> fetch -> dedupe -> summarize -> Firestore -> announce

A service is a `feeds.yaml`, a Cloud Scheduler cron, and a `main.py` that calls
`runner.run_rss_ingest` or `runner.run_youtube_ingest`. Nothing about Telegram
formatting or delivery is in that path — the notifier is a separate function
reading `telegram_status` out of Firestore, so an outage there cannot cost an
ingest.

Modules:

    serviceconfig  feeds.yaml -> ServiceConfig
    runner         the ingest pipeline itself
    ingestion      feedparser wrappers; Article and Video
    store          Firestore reads and writes, incl. the notifier's queue
    summarization  Gemini and offline Sumy
    telegram       message formatting and the Bot API call
    events         Pub/Sub announcements to the notifier and the summarizer
    secrets        Secret Manager
    settings       constants shared by all of the above (never feed lists)
    archival       Firestore doc -> BigQuery row, pure transforms
    bigquery       archive dataset/table creation, load and MERGE
"""
