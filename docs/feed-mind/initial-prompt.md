You are an expert Senior Technical Product Manager. I want you to write a comprehensive, production-ready Product Requirement Document (PRD) for a self-hosted, serverless RSS summarization and notification system. 

The system will ingest academic papers and industry news related to AI, ML, and Cloud Computing, summarize them using an LLM hosted on Ollama Cloud, and push notifications to a private Telegram bot.

Please structure the PRD using the following specific sections:

1. PRODUCT OVERVIEW & GOALS
- High-level project definition.
- Key objectives (cost-efficiency, automated delivery, low operational maintenance).
- Target audience (internal/developer use only).

2. SYSTEM ARCHITECTURE & GOAL CONSTRAINTS
- Platform: Google Cloud Platform (GCP).
- Stack Components: 
  * Cloud Scheduler (Trigger)
  * Cloud Functions Gen 2 (Python compute)
  * Firestore Native Mode (Deduplication database)
  * Ollama Cloud Free Tier API (AI Inference engine)
  * Telegram Bot API (Presentation layer)
- Guardrails: Address Ollama Cloud's specific free-tier constraints (concurrency limits of 1 model at a time, 5-hour rolling session GPU-time limits, use of Level 1/2 models like Llama 3.1 8B).

3. CURATED DATA SOURCES (FEEDS TO INGEST)
Incorporate the following exact RSS feed URLs into the product scope:
- Academic/Research:
  * http://arxiv.org (arXiv Machine Learning)
  * http://arxiv.org (arXiv AI)
  * https://githubusercontent.com (Hugging Face Daily Papers)
- Industry News:
  * https://openai.com (OpenAI News)
  * https://deepmind.google (Google DeepMind)
  * https://microsoft.com (Microsoft Research)
  * https://techcrunch.com (TechCrunch AI)
- Cloud Computing:
  * https://cncf.io (CNCF Blog)
  * https://aws.amazon.com/blogs/aws/feed/ (AWS News Blog)
  * https://google.com (Google Cloud Blog)
  * https://azureedge.net (Microsoft Azure Updates Feed)

4. FUNCTIONAL REQUIREMENTS
- Ingestion Engine: How it parses feeds (e.g., using feedparser), handles connection timeouts gracefully, and extracts clean text (titles, snippets, urls).
- Deduplication Logic: Strict step-by-step logic checking if an article's unique identifier exists in Firestore *before* sending anything to the LLM.
- Summarization Engine: Input payload optimization strategy (truncating long academic papers to 2,000 characters to conserve Ollama GPU time). Include a detailed "System Prompt" block for Ollama optimized for an 8B model to generate 3 punchy, technical, markdown-formatted bullet points under 60 words total.
- Notification Delivery: Formatting payload for Telegram Bot API using Markdown (bolding titles, hyperlinking source code/URLs). Sequential processing of message delivery to avoid Telegram rate limits.

5. NON-FUNCTIONAL REQUIREMENTS
- Security: Secure handling of environmental variables (GCP Secret Manager or runtime vars for Telegram Token, Chat ID, and Ollama API key). Access control to prevent unauthenticated execution of the Cloud Function.
- Cost Boundary: Strict alignment with GCP Free Tier limits (Firestore reads/writes, Cloud Function invocations) to guarantee $0 or near-$0 monthly operational costs.
- Performance & Timeouts: Cloud Function execution timeout handling (e.g., setting a 5-minute timeout window to handle sequential processing without crashing).

6. DATA SCHEMA (FIRESTORE)
- Define a precise document structure for the `processed_articles` collection to log document IDs, feed source, title, publication timestamp, and processing status.

7. SUCCESS METRICS & LOGGING
- Basic logging requirements within GCP Cloud Logging to track: number of feeds successfully checked, number of new articles identified, and a count of successful vs. failed Ollama inference requests.

Generate this PRD using professional technical product management language, ensuring it is comprehensive enough for a software engineer to immediately use for scaffolding and writing the application code.
