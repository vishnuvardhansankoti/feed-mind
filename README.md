# misc-scripts

Two command-line tools built on one library:

| | |
|---|---|
| **`web-page-scraper.py`** | Scrape a page, strip the ads and chrome, print the article. Optionally summarize it with an LLM and read it aloud. |
| **`feedmind_audio.py`** | Take the newest [FeedMind](../feed-mind/) article out of Firestore, summarize it, and publish the audio to Cloud Storage. |
| **`webscraper/`** | The package both scripts import. |

The core extraction path is standard library only. spaCy, pyttsx3 and the Google Cloud clients are optional and imported lazily — the scraper still runs without any of them.

## Setup

```bash
uv venv                                   # if .venv does not exist yet
uv pip install --python .venv/bin/python spacy pyttsx3 \
    google-cloud-firestore google-cloud-storage
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
    "ollama":    { "api": "openai", "base_url": "http://localhost:11434/v1", "model": "llama3.2:latest" },
    "openai":    { "api": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY" },
    "anthropic": { "api": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5", "api_key_env": "ANTHROPIC_API_KEY" }
  }
}
```

Per-field precedence is **CLI flag > env var (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API`, `LLM_API_KEY`, `LLM_PROVIDER`) > config file > built-in**. API keys are read from the env var named by `api_key_env` and never stored in the file.

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
                                       pyttsx3 -> ffmpeg -> MP3
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
```

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
- Ollama and pyttsx3 are local, so this script cannot move into a Cloud Function without swapping both for hosted services.

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
| `config.py` | Layering config file, env and CLI overrides |
| `cli.py` | Argument parsing and console output |

All errors derive from `ScraperError`: `FetchError`, `ConfigError`, `LLMError`, `CondenseError`, `SpeechError`.
