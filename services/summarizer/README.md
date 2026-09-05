# services/summarizer

Two command-line tools built on one library:

| | |
|---|---|
| **`web-page-scraper.py`** | Scrape a page, strip the ads and chrome, print the article. Optionally summarize it with an LLM and read it aloud. |
| **`feedmind_audio.py`** | Take the newest [FeedMind](../news-ingest/) article out of Firestore, summarize it, and publish the audio to Cloud Storage. |
| **`webscraper/`** | The package both scripts import. |

The core extraction path is standard library only. spaCy, pyttsx3 and the Google Cloud clients are optional and imported lazily — the scraper still runs without any of them.

## Setup

```bash
uv venv                                   # if .venv does not exist yet
uv pip install --python .venv/bin/python spacy pyttsx3 \
    google-cloud-firestore google-cloud-storage google-cloud-texttospeech
.venv/bin/python -m spacy download en_core_web_sm
brew install ffmpeg                       # only for MP3 output
```

| Feature | Needs |
|---|---|
| Scraping, extraction | nothing (stdlib) |
| Summarization | a reachable LLM — Ollama running locally by default |
| `--condense` (two-step) | `spacy` + `en_core_web_sm` |
| `--speak` / `--audio` | `pyttsx3` |
| MP3 output | `ffmpeg` on `PATH` |
| `--tts cloud` | `google-cloud-texttospeech` — no `pyttsx3`, no `ffmpeg` |
| `feedmind_audio.py` | all of the above, plus GCP credentials (`gcloud auth application-default login`) |

---

## `web-page-scraper.py`

```bash
.venv/bin/python web-page-scraper.py <URL>                  # just the article text
.venv/bin/python web-page-scraper.py <URL> --summary-only   # just a 2-3 sentence summary
.venv/bin/python web-page-scraper.py <URL> -c --summary-only # two-step summary
.venv/bin/python web-page-scraper.py <URL> --speak          # read the summary aloud
```

### How extraction works

Four passes, in `webscraper/`:

1. **`fetcher.py`** — download with a browser user-agent, transparent gzip/deflate, charset from headers or the meta tag.
2. **`dom.py`** — parse into a forgiving tree on `html.parser`, applying the auto-closing rules real HTML needs (unclosed `<p>`, `<li>`, `<td>`, `<tr>`).
3. **`cleaner.py`** — drop `script/style/nav/header/footer/aside/form/iframe` outright, plus anything whose `class`/`id`/`role`/`aria-label` looks like chrome: ads, banners, cookie bars, paywalls, share widgets, related rails, comments, pagination. Two safeguards stop it eating the article — names matching `article|post|content|main|story|entry` are exempt, and a soft-noise match (`widget`, `meta`, `tags`) is overridden when the subtree holds >400 chars of paragraph text at low link density.
4. **`scorer.py` → `renderer.py`** — readability-style scoring: paragraphs earn points for length and comma count, propagated to ancestors with halving weight, discounted by link density. Output keeps headings, bullets and blockquotes.

**Limits.** HTTP only, so JS-rendered SPAs return whatever is in the initial HTML. On index pages you get the post list, not one article — the heuristic targets article pages by design.

### Summarization

One step by default: the whole cleaned article goes to the model.

`-c` / `--condense` makes it two steps — spaCy ranks sentences by content-word frequency and keeps the top `--select-ratio` (default 0.25), then the LLM rewrites only that extract. Useful on long pages, and cheaper.

```bash
.venv/bin/python web-page-scraper.py <URL> -c --show-extract --summary-only
```

```
spaCy (en_core_web_sm) condensed 28,485 -> 10,121 chars (36% kept)
Web scraping is the process of automatically extracting data from websites...
```

Sentence scores are `sum(word scores) / sqrt(token count)`, and sentences under 8 tokens are skipped. Plain summing rewards length for its own sake; dividing by the full token count inverts the bias and floats keyword-dense fragments (`THE HISTORY OF THE WEB .`) to the top. The square root damps without reversing. See `webscraper/condense.py`.

### Configuration

Resolution order: `--config PATH` → `$WEB_SCRAPER_CONFIG` → `./scraper-config.json` → `~/.config/web-page-scraper/config.json` → `~/.web-page-scraper.json`. With no config at all it uses `llama3.2:latest` at `http://localhost:11434/v1`.

```bash
.venv/bin/python web-page-scraper.py --init-config    # writes a documented sample
```

```json
{
  "provider": "ollama",
  "max_input_chars": 12000,
  "condense": { "enabled": false, "select_ratio": 0.25, "model": "en_core_web_sm" },
  "tts": { "voice": "Samantha", "rate": 175, "volume": 1.0 },
  "providers": {
    "ollama":       { "api": "openai", "base_url": "http://localhost:11434/v1", "model": "llama3.2:latest" },
    "ollama-cloud": { "api": "openai", "base_url": "https://ollama.com/v1", "model": "gpt-oss:120b", "api_key_env": "OLLAMA_API_KEY" },
    "openai":       { "api": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY" },
    "anthropic":    { "api": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5", "api_key_env": "ANTHROPIC_API_KEY" }
  }
}
```

`ollama-cloud` is hosted Ollama — the provider the deployed function uses. Despite the name it is an **`openai`** provider: `ollama.com` speaks the OpenAI wire format, while the `ollama` adapter is for the native `/api/chat` a *local* Ollama serves.

Per-field precedence is **CLI flag > env var (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API`, `LLM_API_KEY`, `LLM_MAX_TOKENS`, `LLM_PROVIDER`) > config file > built-in**. API keys are read from the env var named by `api_key_env` and never stored in the file.

`LLM_MAX_TOKENS` exists for reasoning models: they spend part of the budget thinking before writing, so the built-in 300 — sized for a model that starts answering immediately — can leave nothing for the answer. Somewhere with no config file on disk, such as the deployed function, would otherwise have no way to raise it.

Three wire formats cover most providers:

- **`openai`** — OpenAI, Ollama's `/v1`, Groq, vLLM, LM Studio, OpenRouter, Together
- **`ollama`** — native `/api/chat`
- **`anthropic`** — `/v1/messages`

Adding a fourth means one `Adapter` subclass and one registry entry in `webscraper/llm.py`.

### Audio

```bash
.venv/bin/python web-page-scraper.py <URL> --speak
.venv/bin/python web-page-scraper.py <URL> --audio out.aiff --voice Samantha --rate 185
.venv/bin/python web-page-scraper.py --list-voices
```

Both audio flags imply `--summarize`. **macOS writes AIFF regardless of the extension you ask for** — `.wav` and `.aiff` produce byte-identical files. Worse, the driver *hangs forever at 100% CPU* on an extension it doesn't recognise, so `speech.py` rewrites any non-native suffix to `.aiff` and says so. For real MP3, transcode with ffmpeg (which is what `feedmind_audio.py` does).

### Exit codes

`0` ok · `1` fetch failed · `2` no readable content · `3` summarization failed · `4` audio failed

A failed summary is only fatal when it was the point of the run — with `--summary-only`, `--speak` or `--audio`. Otherwise the article still prints and the exit code stays `0`.

---

## `feedmind_audio.py`

Publishes **one audio file per item** from the newest FeedMind content. Two sources, chosen with `--process-doc`:

| Mode | Reads | Text comes from |
|---|---|---|
| **`RSS_FEED`** *(default)* | every doc sharing the latest `processed_at` **date** in `processed_articles` | scraping the article URL |
| **`RESEARCH_PAPERS`** | every paper in the latest run of **each category** in `runs` | the stored `abstract` — no HTTP at all |

```
                        RSS_FEED                RESEARCH_PAPERS
  select        latest processed_at date    latest run_date per category
  text          fetch + extract_article     paper['abstract']
                        |                            |
                        +------------ spaCy condense +
                                       LLM rewrite
                                       speech -> MP3     (--tts local|cloud)
                                       Cloud Storage
                                       Firestore write
```

```bash
.venv/bin/python feedmind_audio.py                          # latest RSS batch
.venv/bin/python feedmind_audio.py --process-doc RESEARCH_PAPERS
.venv/bin/python feedmind_audio.py --process-doc RESEARCH_PAPERS --category CV
.venv/bin/python feedmind_audio.py --limit 2 --dry-run      # no uploads, no writes
.venv/bin/python feedmind_audio.py --force                  # redo finished items
.venv/bin/python feedmind_audio.py --article-id <id>        # article_id, or arxiv_id
.venv/bin/python feedmind_audio.py --tts cloud              # Google Text-to-Speech
```

### Speech backends

`--tts` picks the engine, defaulting to `$FEEDMIND_TTS` and then to `local`.

| | `local` *(default)* | `cloud` |
|---|---|---|
| Engine | pyttsx3 → the OS voice | Google Text-to-Speech API |
| Output | driver-native audio, transcoded by **ffmpeg** to 64 kbps MP3 | MP3 straight from the API — no ffmpeg |
| `--voice` | a pyttsx3 voice name or id (`Samantha`) | a Cloud TTS voice name (`en-US-Neural2-F`) |
| `--rate` | words per minute, passed to the driver | words per minute, converted to the API's rate multiplier against a 175 wpm baseline |
| Cost | free | billed per character |
| Runs on | a machine with a speech engine | anything with credentials |

`cloud` is what makes the script deployable, and long text is split on sentence boundaries to stay under the API's 5000-byte request cap.

```
RESEARCH_PAPERS - latest run per category: AIML 2026-08-22 (3), CV 2026-08-22 (3), NLP 2026-08-22 (3)
  9 item(s), 1 already have audio, 8 to process
  model: llama3.2:latest via ollama (built-in default)

[ 1/8] AIML 2608.18884  Training-Free Inference-Time Self-Reflection and Cost-Boun
         spaCy (en_core_web_sm) condensed 1,435 -> 240 chars (17% kept)
         101 KB -> gs://feed-mind-audio-summaries/research-papers/2026-08-22/AIML/2608.18884.mp3
...
8 succeeded, 0 failed
```

Only the newest batch is ever touched — older articles and older runs are not backfilled. RSS articles take roughly a minute each (scraping dominates); papers are faster since there's no fetch.

### What it touches

| | |
|---|---|
| Project | `feed-mind` |
| Firestore database | **`feed-mind-db`** — *not* `(default)` |
| Collections | `processed_articles` (RSS), `runs` (papers) |
| Bucket | `gs://feed-mind-audio-summaries` (public-read, 90-day delete lifecycle) |
| RSS object | `<processed_at date>/<article_id>.mp3`, `audio/mpeg` |
| Paper object | `research-papers/<run_date>/<category>/<arxiv_id>.mp3`, `audio/mpeg` |

Firestore writes are **additive** in both modes — `ai_summary` (the text), `audio_url` (the public MP3 URL), `audio_generated_at`.

- **RSS:** three fields added to the article document. FeedMind's `summary`, `title`, `status`, `expires_at` untouched. An earlier version wrote the text to `audio_summary`; docs carrying that field are migrated to `ai_summary` on reprocessing.
- **Papers:** the three fields are added to the matching entry **inside the `papers` array**. Firestore cannot address a single array element, so the array is rewritten whole — **inside a transaction**, matched by `arxiv_id`, to avoid clobbering a concurrent pipeline write. Sibling papers and every original field (`abstract`, `rank`, `score`, `summary`, `title`, `url`) are preserved.

### Papers mode notes

- **Categories are discovered, not hardcoded.** The distinct `category` values in `runs` drive the batch, so a new category is picked up with no code change. `--category AIML` narrows it.
- **Latest run is per category.** If CV didn't run today, you still get CV's most recent papers rather than silently skipping the category.
- **The condense step is near-vacuous on abstracts.** ~200 words condensed to 25% leaves 1–2 sentences before the LLM sees them. If summaries come out thin, raise `--select-ratio` toward `1.0` for this mode.
- **`--category` is rejected in RSS mode** rather than silently ignored.

### Guarantees

- **Idempotent.** Docs that already have `audio_url` are skipped before any scraping. `--force` overrides.
- **No partial state.** Per article, one Firestore write, only after that article's upload succeeds. A doc never points at an object that doesn't exist.
- **Failures are isolated.** One article failing is logged and listed in the final tally; the batch continues. The run exits non-zero only if *every* article failed.
- **Degrades.** If a page can't be scraped, it falls back to the Gemini one-liner stored on the doc — available for only 138 of 650 docs collection-wide, so this is not a universal safety net.

Exit codes: `0` ok (even with some failures) · `1` no articles found · `2` every article failed

### Gotchas

- The Firestore database is **named**. `firestore.Client(project='feed-mind')` fails with a 404 pointing at the Datastore setup page; you must pass `database='feed-mind-db'`.
- `processed_at` is stored as an **ISO-8601 string**, not a Firestore timestamp. Ordering works only because every writer uses `datetime.now(UTC).isoformat()`.
- The bucket is **public-read**, and `roles/storage.objectViewer` on `allUsers` also grants listing — anyone who knows the bucket name can enumerate every summary.
- Ollama and pyttsx3 are local. Deploying means swapping **both** for hosted services — `--tts cloud` handles the speech half, and the LLM half is a matter of pointing `LLM_*` at a hosted provider. See below.

---

## Deploying as a Cloud Function

`main.py` wraps `feedmind_audio.main()` in a gen2 CloudEvent function, so the CLI and the deployment can't drift — the function just turns a message into argv.

Two things from the local setup cannot come along: **pyttsx3** (the runtime has no speech engine, and buildpacks can't `apt-get` one) and **ffmpeg** (same reason). The deployment therefore sets `FEEDMIND_TTS=cloud`, which takes both out of the path. Local **Ollama** can't come either — the deployment points `LLM_*` at **Ollama Cloud** instead, which keeps the model catalogue familiar.

```bash
./deploy/setup.sh      # once per project: APIs, service accounts, IAM, topic
./deploy/deploy.sh     # after every code change
./deploy/publish.sh    # trigger a run by hand, any time
```

Everything configurable lives in `deploy/config.sh` and can be overridden from the environment (`REGION=europe-west1 ./deploy/deploy.sh`).

📖 **[`deploy/README.md`](deploy/README.md)** is the full runbook — prerequisites, what each step does, smoke tests, delivery semantics, troubleshooting and teardown. Start there for an actual deploy; what follows here is the summary.

| File | Job |
|---|---|
| `main.py` | `on_content_ready` (Pub/Sub, deployed) and `summarize_feed` (HTTP, kept) |
| `requirements.txt` | Runtime deps, including the spaCy model from its release URL |
| `.gcloudignore` | Keeps the venv, `.git` and `deploy/` out of the upload |
| `deploy/config.sh` | Every setting, sourced by the others |
| `deploy/setup.sh` | APIs, service accounts, IAM, the topic — idempotent |
| `deploy/deploy.sh` | `gcloud functions deploy`, the invoker binding, the ack deadline |
| `deploy/publish.sh` | Publishes a trigger message by hand |

### What triggers it

A **Pub/Sub message**, not a clock. Only the producing pipeline knows when its run actually finished; a schedule can only guess — too early and there's nothing to summarize, too late and the audio is stale.

```
FeedMind run ends ──publish──► feedmind-content-ready ──Eventarc──► feedmind-audio
```

One topic carries both pipelines; the message says which.

| Publisher | Message | Runs | Status |
|---|---|---|---|
| `feed-mind` | `{"process_doc": "RSS_FEED"}` | the latest RSS batch | **wired up** |
| `paper-prism-job` | `{"process_doc": "RESEARCH_PAPERS"}` | the latest run per category | **wired up** |

An empty message means the default: the latest RSS batch. Each producer publishes only after its own writes have landed — this function reads those collections, so announcing earlier would race it — and only when there is something new: FeedMind skips when no articles were delivered, paper-prism when no papers were written or the run wasn't writing to Firestore. Both swallow publish failures rather than failing a run that already did its work.

The topic and both `pubsub.publisher` grants live in this service's `deploy/setup.sh` — the topic belongs to whoever reads it — so run that before either producer's first publish.

**Before the first deploy**, create the LLM API key secret — it is the one thing the scripts won't invent for you. Get a key from <https://ollama.com/settings/keys>, then:

```bash
printf '%s' "$YOUR_KEY" | gcloud secrets create feedmind-llm-api-key \
    --project=feed-mind --data-file=-
```

`deploy.sh` mounts it as `LLM_API_KEY`, which `webscraper/config.py` reads like any other override — so the key never appears in a deploy command or in the function's environment configuration. The secret name is provider-neutral on purpose: switching providers later is a new secret *version*, not a new secret.

| `deploy/config.sh` | Default |
|---|---|
| `LLM_API` | `openai` — Ollama Cloud speaks the OpenAI wire format |
| `LLM_BASE_URL` | `https://ollama.com/v1` → `POST /v1/chat/completions` |
| `LLM_MODEL` | `gpt-oss:120b` |
| `LLM_MAX_TOKENS` | `1200` — headroom for `gpt-oss`'s reasoning, not longer output |
| `LLM_API_KEY_SECRET` | `feedmind-llm-api-key` |

Ollama Cloud hosts a fixed catalogue rather than whatever you've pulled locally, so `LLM_MODEL` can't mirror the CLI's `llama3.2:latest`. The catalogue is public and needs no key:

```bash
curl -s https://ollama.com/v1/models | jq -r '.data[].id' | sort
```

`gpt-oss:20b` is the same family at roughly a fifth the size — worth trying, since a batch is a serial loop and most of its wall time is spent waiting on this call.

To run exactly what the function will run, before spending a deploy on it:

```bash
LLM_API=openai LLM_BASE_URL=https://ollama.com/v1 \
LLM_MODEL=gpt-oss:120b LLM_MAX_TOKENS=1200 LLM_API_KEY=... FEEDMIND_TTS=cloud \
    .venv/bin/python feedmind_audio.py --limit 1 --force --dry-run
```

The env vars are the same four the function gets, so this needs no config file. If you'd rather have it as a named provider, `--init-config` writes an `ollama-cloud` block that reads the key from `$OLLAMA_API_KEY`; then `--provider ollama-cloud` selects it.

### Invoking it

`./deploy/publish.sh` builds the message for you — any `feedmind_audio.py` flag passes through:

```bash
./deploy/publish.sh                                  # latest RSS batch
./deploy/publish.sh RESEARCH_PAPERS --category CV
./deploy/publish.sh RSS_FEED --limit 1 --dry-run     # no uploads, no writes
```

Or publish directly. The fields are the CLI flags — `process_doc`, `category`, `article_id`, `limit`, `force`, `dry_run`, `timeout`, `provider`, `model`, `select_ratio`, `voice`, `rate`, `tts` — as a JSON body or as attributes. Body beats attributes beats the `FEEDMIND_*` environment defaults.

```bash
gcloud pubsub topics publish feedmind-content-ready \
    --message='{"process_doc": "RESEARCH_PAPERS", "category": "CV", "limit": 1}'
```

Progress goes to stderr and lands in Cloud Logging. A malformed message body is logged and treated as empty rather than failing — failing would only feed the identical message back through the retry.

### Shape of the deployment

- **One instance, one request** (`--max-instances=1 --concurrency=1`). Papers mode rewrites the whole `papers` array, so overlapping runs would clobber each other.
- **1 GiB, 540s.** spaCy's pipeline is the memory floor. 540s is a hard ceiling for an event-driven function — the 3600s an HTTP function may ask for is not available — and covers about eight articles at a minute each.
- **A large batch drains across invocations.** Rather than truncate, the run stops at `MAX_RUNTIME` (450s) *between items*, exits `3`, and republishes its own trigger message; the next pass skips whatever now has an `audio_url`. Continuation only follows a pass that completed at least one item, so it cannot loop.
- **At-least-once delivery is safe.** The pipeline skips items that already have an `audio_url`, so a duplicate no-ops. `MAX_RUNTIME` < `TIMEOUT` < `ACK_DEADLINE` (450 < 540 < 600), so a slow run always ends on its own deadline before Pub/Sub decides the delivery failed.
- **The function never nacks.** A partly-succeeded batch would otherwise redo the whole thing on redelivery, retrying exactly the items least likely to succeed. Failures are logged and tallied; the next run picks up whatever still lacks audio.

---

## Library use

```python
from webscraper import fetch, extract, summarize, load_config, resolve_provider

html = fetch("https://example.com/article")
text = extract(html, width=100)
print(summarize(text, resolve_provider(load_config())))
```

`python -m webscraper <URL>` works too.

| Module | Job |
|---|---|
| `dom.py` | HTML → forgiving tree, plus node metrics |
| `cleaner.py` | Prune ads, nav, sidebars, comments |
| `scorer.py` | Pick the subtree holding the article |
| `renderer.py` | Flatten it into tidy text blocks |
| `extractor.py` | The pipeline tying those together |
| `fetcher.py` | Downloading pages |
| `condense.py` | spaCy extractive pre-filter *(optional dep)* |
| `llm.py` | Provider adapters and `summarize()` |
| `speech.py` | pyttsx3 text-to-speech *(optional dep)* |
| `cloud_speech.py` | Google Text-to-Speech, the deployable backend *(optional dep)* |
| `config.py` | Layering config file, env and CLI overrides |
| `cli.py` | Argument parsing and console output |

All errors derive from `ScraperError`: `FetchError`, `ConfigError`, `LLMError`, `CondenseError`, `SpeechError`.
