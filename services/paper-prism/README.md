# paper-prism — pipeline (P1)

The weekly batch that fetches arXiv preprints, ranks them against personal
interest profiles with local ONNX embeddings, summarizes the top papers with
Gemini, and writes results to Firestore. See `../docs/paper-prism-prd.md`.

## What it does (per run)

For each lens — **AIML** (`cs.LG`,`cs.AI`), **NLP** (`cs.CL`), **CV** (`cs.CV`):

1. Fetch arXiv preprints `submittedDate` within the last 7 days (Atom XML,
   throttled, paginated, retried). Cross-listed papers are kept only for the lens
   that owns their *primary* category.
2. Embed `title + abstract` with `all-MiniLM-L6-v2` via **ONNX Runtime** (no torch).
3. Rank by cosine similarity to the lens's interest profile; take the **top 3**.
4. Summarize each top paper in 2 sentences with **gemini-2.5-flash** (grounded).
5. Write one `runs/YYYY-MM-DD_<CATEGORY>` document + a `run_status` document.

Best-effort per lens: one lens failing doesn't abort the run; a failed Gemini
call writes `summary: null` rather than dropping the paper.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cp .env.example .env          # then edit the three PROFILE_* paragraphs
PYTHONPATH=src .venv/bin/python -m paper_prism
```

- **No `GEMINI_API_KEY`** → summaries are written as `null` (pipeline still runs).
- **`SINK=local`** (default) → JSON written under `./output/`.
- **`SINK=firestore`** → uncomment `google-cloud-firestore` in `requirements.txt`,
  set `GOOGLE_CLOUD_PROJECT` + `GOOGLE_APPLICATION_CREDENTIALS`. Set
  `FIRESTORE_DATABASE` to write to a named (non-default) database, e.g.
  `feed-mind-db`; unset writes to `(default)`.

## Configuration (`.env`)

| Var | Purpose |
|---|---|
| `PROFILE_AIML` / `PROFILE_NLP` / `PROFILE_CV` | The interest paragraphs that drive ranking. **These are the product.** |
| `GEMINI_API_KEY` | AI Studio key; unset = null summaries |
| `GEMINI_MODEL` | default `gemini-2.5-flash` |
| `SINK` | `local` or `firestore` |
| `GOOGLE_CLOUD_PROJECT` | GCP project (for `SINK=firestore`) |
| `FIRESTORE_DATABASE` | Firestore database id; unset = `(default)`, e.g. `feed-mind-db` |
| `WINDOW_DAYS` / `TOP_K` | window size / papers per lens |
| `ARXIV_PAGE_SIZE` / `ARXIV_THROTTLE_SECONDS` / `ARXIV_MAX_PAGES` | fetch tuning |

## Layout

```
src/paper_prism/
  arxiv_client.py   # Atom XML fetch: throttle, paginate, retry, primary-cat dedup
  embedder.py       # ONNX MiniLM encode + cosine top-k
  summarizer.py     # Gemini REST, summarize-only, null on failure
  sinks.py          # LocalJsonSink / FirestoreSink (idempotent)
  models.py         # Paper / RunDocument / RunStatus (Firestore schema)
  pipeline.py       # best-effort per-lens orchestration
  config.py         # env-driven Config
  __main__.py       # entrypoint (also the Cloud Run Job command)
```
