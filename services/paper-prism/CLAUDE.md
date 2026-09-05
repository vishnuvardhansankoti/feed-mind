# services/paper-prism

Guidance for working inside this service. The system-level view — the four
deployables, the shared Firestore database, the Pub/Sub handoff and the
cross-component schema contracts — is in the **root `CLAUDE.md`**; read that
first if you are changing anything another component reads.

## What this service is

The Python batch job behind the **Papers** section: a $0, zero-ops personalized
weekly arXiv digest. It fetches the last 7 days of preprints across three
research "lenses", ranks each against a personal interest profile using local
ONNX embeddings, summarizes the top papers with Gemini, and writes results to
Firestore. It has no request path — it is a Cloud Run Job that runs to
completion on a schedule.

Design source of truth: `../../docs/paper-prism/paper-prism-prd.md` (code
comments reference its sections, e.g. "PRD §3.2").

The reader for what this writes is `apps/web`; the document schema in
`src/paper_prism/models.py` is the only thing joining them. Change the doc shape
here and you must update `apps/web/src/lib/data.js` (`normalizeRun`, query field
names) in the same commit — they are coupled by convention, not by types.

## Pipeline architecture

Entrypoint `pipeline/src/paper_prism/__main__.py` wires config → clients → `Pipeline`. Per-run flow in `pipeline.py`:

- **Lenses** are defined in `models.py::LENSES`: `AIML`→(`cs.LG`,`cs.AI`), `NLP`→(`cs.CL`), `CV`→(`cs.CV`). Source category sets are **disjoint**, and a paper is kept only for the lens owning its *primary* arXiv category — this is how cross-listing duplication is resolved (`arxiv_client.py`), not a dedup pass.
- **Ranking is authoritative; the LLM is not.** `embedder.py` runs `all-MiniLM-L6-v2` via **ONNX Runtime with no torch** (deliberate — keeps the image slim), producing L2-normalized vectors so cosine == dot product. `rank_top_k` picks `TOP_K` (default 3) per lens. Gemini (`summarizer.py`) only *summarizes* the survivors; it never re-ranks or filters.
- **Best-effort degradation is the core reliability model.** A lens that throws is logged, recorded as `skipped` in `run_status`, and does not abort the other lenses. A failed Gemini call writes `summary: null` rather than dropping the paper. `run()` returns non-zero exit only if any lens failed (surfaced to Cloud Logging → log-based alert).
- **Sinks are idempotent** (`sinks.py`): deterministic doc IDs (`runs/YYYY-MM-DD_<CATEGORY>`, `run_status/YYYY-MM-DD`) mean re-runs overwrite cleanly. `LocalJsonSink` (default, writes `./output/`) vs `FirestoreSink` (lazy-imports `google-cloud-firestore`).
- **Firestore TTL retention:** the pipeline stamps `expire_at = run_date + RETENTION_DAYS` (default 45) on every doc. Firestore TTL policies on the `expire_at` field (declared in `infra/main.tf` and enabled by `pipeline/deploy/01-setup.sh`) sweep expired docs. TTL only affects docs written *after* the field was added; there is no built-in "delete N days after creation", which is why the field exists.

- **The run announces itself when it finishes** (`events.py`, called from `__main__.py` after `pipeline.run()`). It publishes `{"process_doc": "RESEARCH_PAPERS", ...}` to the `CONTENT_READY_TOPIC` Pub/Sub topic, which wakes the sibling `feed-mind-summarizer` to generate the per-paper `ai_summary` / `audio_url` fields described below. Three guards, all following the same best-effort model as the rest of the pipeline: it publishes only when `SINK=firestore` (a local run has no consumer), only when at least one paper was written, and it swallows publish failures — the papers are already in Firestore, and failing there would only invite a retry of the whole run. **The topic is owned by the consumer**, not by this repo: `feed-mind-summarizer/deploy/setup.sh` creates it and grants `paper-prism-job@` `roles/pubsub.publisher`, so that must run before this job first publishes (until it does, the run still succeeds and logs a permission error).

Everything is env-driven via `config.py` (`load_config()`); there are no CLI flags.

## Deployment: two parallel paths

`../../infra/terraform/` and `deploy/*.sh` provision the **same** resources by
different means — pick one as source of truth; running both double-creates.
This was true before the monorepo and is still unresolved.

## Common commands

Run from `services/paper-prism/`.

**Local run** (against live arXiv):
```bash
uv sync --extra dev
cp .env.example .env            # edit the three PROFILE_* paragraphs — these ARE the product
PYTHONPATH=src uv run python -m paper_prism
```
No `GEMINI_API_KEY` → summaries written as `null` (the run still completes).
`SINK=local` (default) → JSON under `./output/`. First run downloads ~90 MB of
ONNX weights (cached by `huggingface_hub`).

**Tests:**
```bash
uv run --extra dev pytest        # pythonpath=src comes from pyproject.toml
```

**Lint** (config is the repo-root `ruff.toml`):
```bash
uvx ruff check .
```

**Deploy via gcloud scripts:** `deploy/00-config.sh` (sourced by the rest) →
`01-setup.sh` (APIs, Firestore, TTL, SAs, secret) → `01b-setup-firestore-db.sh`
→ `02-build-push.sh` → `03-deploy-job.sh` (needs `deploy/env.yaml`, copied from
`env.yaml.example`) → `04-scheduler.sh`. All idempotent; all require
`PROJECT_ID` exported. Each one `cd`s to its own directory, so they can be run
from anywhere.

**Deploy via Terraform:** see `../../infra/terraform/README.md`.

## Dependencies

`requirements.txt` is **generated** from `pyproject.toml` (`../../scripts/lock-all.sh`)
and `uv.lock` is committed. The Dockerfile installs from `requirements.txt`.
This is an independent uv project, not a workspace member — see the root
`CLAUDE.md` for why the three services do not share a resolution.

## Conventions worth matching

- The interest **profile paragraphs** (`PROFILE_AIML` / `PROFILE_NLP` /
  `PROFILE_CV`) drive all ranking quality. `config.py` warns loudly if the
  placeholder examples are used verbatim — real profiles must be authored
  deliberately.
- Env config is the only knob surface: `WINDOW_DAYS`, `TOP_K`, `RETENTION_DAYS`,
  `ARXIV_*`, `SINK`, `GEMINI_*`, `FIRESTORE_DATABASE`, `CONTENT_READY_TOPIC`.
  Add new tunables in `config.py`, then wire them into
  `../../infra/terraform/run.tf` (`job_env`) **and** `deploy/env.yaml.example`
  so both deploy paths stay in sync. A tunable that also affects the web reader
  (like `FIRESTORE_DATABASE` ↔ `VITE_FIRESTORE_DATABASE`) must be mirrored in
  `apps/web/.env*` too.
