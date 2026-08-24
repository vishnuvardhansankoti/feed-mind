# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

paper-prism is a **$0, zero-ops personalized weekly arXiv digest**. A scheduled batch job fetches the last 7 days of preprints across three research "lenses", ranks each against a personal interest profile using local ONNX embeddings, summarizes the top papers with Gemini, and writes results to Firestore. A Svelte SPA reads Firestore **directly from the browser** — there is no backend API and no request-path compute.

Design source of truth: `docs/paper-prism-prd.md` (the code comments reference its sections, e.g. "PRD §3.2").

## Three components, one data contract

The repo is three loosely-coupled parts joined only by the Firestore document schema in `pipeline/src/paper_prism/models.py`:

- **`pipeline/`** — Python batch job (P1/P2). arXiv → ONNX embed → cosine top-k → Gemini summary → Firestore.
- **`web/`** — Svelte 5 + Vite SPA (P3). Reads `runs` / `run_status` collections directly via the Firebase client SDK.
- **`infra/`** — Terraform for the whole GCP stack (P4). `pipeline/deploy/*.sh` is a **parallel** imperative `gcloud` path that provisions the *same* resources — pick one as source of truth; running both double-creates.

If you change the document shape in `models.py`, you must update the reader in `web/src/lib/data.js` (`normalizeRun` / query field names) in lockstep — they are only coupled by convention, not types.

## Pipeline architecture

Entrypoint `pipeline/src/paper_prism/__main__.py` wires config → clients → `Pipeline`. Per-run flow in `pipeline.py`:

- **Lenses** are defined in `models.py::LENSES`: `AIML`→(`cs.LG`,`cs.AI`), `NLP`→(`cs.CL`), `CV`→(`cs.CV`). Source category sets are **disjoint**, and a paper is kept only for the lens owning its *primary* arXiv category — this is how cross-listing duplication is resolved (`arxiv_client.py`), not a dedup pass.
- **Ranking is authoritative; the LLM is not.** `embedder.py` runs `all-MiniLM-L6-v2` via **ONNX Runtime with no torch** (deliberate — keeps the image slim), producing L2-normalized vectors so cosine == dot product. `rank_top_k` picks `TOP_K` (default 3) per lens. Gemini (`summarizer.py`) only *summarizes* the survivors; it never re-ranks or filters.
- **Best-effort degradation is the core reliability model.** A lens that throws is logged, recorded as `skipped` in `run_status`, and does not abort the other lenses. A failed Gemini call writes `summary: null` rather than dropping the paper. `run()` returns non-zero exit only if any lens failed (surfaced to Cloud Logging → log-based alert).
- **Sinks are idempotent** (`sinks.py`): deterministic doc IDs (`runs/YYYY-MM-DD_<CATEGORY>`, `run_status/YYYY-MM-DD`) mean re-runs overwrite cleanly. `LocalJsonSink` (default, writes `./output/`) vs `FirestoreSink` (lazy-imports `google-cloud-firestore`).
- **Firestore TTL retention:** the pipeline stamps `expire_at = run_date + RETENTION_DAYS` (default 45) on every doc. Firestore TTL policies on the `expire_at` field (declared in `infra/main.tf` and enabled by `pipeline/deploy/01-setup.sh`) sweep expired docs. TTL only affects docs written *after* the field was added; there is no built-in "delete N days after creation", which is why the field exists.

- **The run announces itself when it finishes** (`events.py`, called from `__main__.py` after `pipeline.run()`). It publishes `{"process_doc": "RESEARCH_PAPERS", ...}` to the `CONTENT_READY_TOPIC` Pub/Sub topic, which wakes the sibling `feed-mind-summarizer` to generate the per-paper `ai_summary` / `audio_url` fields described below. Three guards, all following the same best-effort model as the rest of the pipeline: it publishes only when `SINK=firestore` (a local run has no consumer), only when at least one paper was written, and it swallows publish failures — the papers are already in Firestore, and failing there would only invite a retry of the whole run. **The topic is owned by the consumer**, not by this repo: `feed-mind-summarizer/deploy/setup.sh` creates it and grants `paper-prism-job@` `roles/pubsub.publisher`, so that must run before this job first publishes (until it does, the run still succeeds and logs a permission error).

Everything is env-driven via `config.py` (`load_config()`); there are no CLI flags.

## Web architecture

`web/src/lib/data.js` is a data-source abstraction exposing `getLatest()`, `getArchive()`, `getStatus()`. `VITE_DATA_SOURCE` selects the backend:

- `mock` (default) — bundled JSON fixtures under `web/public/fixtures/`, so the UI runs with zero cloud setup.
- `firestore` — reads Firestore directly from the browser. The Firebase SDK is loaded via **dynamic import**, so `mock` builds don't ship it.

Both backends return identical shapes. Firestore read access is public and governed by `firestore.rules` (public read, `write: if false` — the pipeline writes server-side via a service account that bypasses rules). The Latest/Archive queries need the composite index in `firestore.indexes.json` (mirrored in `infra/main.tf`).

**Named database coupling:** `VITE_FIRESTORE_DATABASE` selects a non-default Firestore database and is passed to `getFirestore(app, id)` (unset → `(default)`). It **must match the pipeline's `FIRESTORE_DATABASE`** (default `feed-mind-db`) — the browser reads Firestore directly, so a mismatch silently reads an empty `(default)`. `VITE_*` values are inlined at build time, so changing the database requires a rebuild. Collections `runs`/`run_status` are never created explicitly; they appear on the pipeline's first write. On the gcloud path, `pipeline/deploy/01b-setup-firestore-db.sh` provisions the named database (create + TTL + `runs` index).

**`firebase.json` must target the named database too.** The `firestore` block sets `"database": "feed-mind-db"`. Without it the Firebase CLI deploys rules/indexes to `(default)` — and will *create* an empty `(default)` database — while the app and pipeline use `feed-mind-db`, so `firestore.rules` (incl. the `processed_articles` public-read rule) silently never reaches the database the browser reads. There are **two build/deploy footguns to keep paired here:** (1) always ship a **firestore** build to production — a mock build has the fixtures inlined and never touches Firestore, so deploying that `dist/` serves placeholder data; (2) keep `firebase.json`'s `database` pinned so `firebase deploy` hits `feed-mind-db`, not `(default)`.

**Env precedence & the prod build (subtle).** `.env` holds the firestore defaults + real (public) Firebase keys, but `.env.local` (gitignored) forces `VITE_DATA_SOURCE=mock` with *empty* keys for local `npm run dev`. Vite loads `.env.local` in **every** mode, above `.env` — so a plain `vite build` bakes **mock**. Production therefore builds with `vite build --mode prod` (the `build` script does this), which loads `.env.prod` (gitignored) *after* `.env.local`, flipping the source back to `firestore` and restoring the real keys. `.env.prod` **must** carry the real `VITE_FIREBASE_*` values, because `.env.local`'s empty ones would otherwise clobber `.env`. Net rule: `npm run build` = firestore/prod; `npm run dev` = mock; to force a mock QA build, prefix `VITE_DATA_SOURCE=mock` (a shell env var beats all `.env*` files).

### News feed (second data source: the `feed-mind` repo)

The web app is a two-section SPA behind a minimal hash router in `App.svelte`: **Papers** (`#/`, the arXiv digest above) and **News** (`#/news`). The News section reads a **different collection written by a different repo** — `processed_articles` in the *same* `feed-mind-db` database, produced by the sibling `feed-mind` RSS→Telegram pipeline (`../feed-mind`). paper-prism's pipeline does not write it.

- **Schema coupling (cross-repo):** `getNews()` in `data.js` and `ArticleCard.svelte` depend on the doc shape written by `feed-mind/feedmind/deduplication.py::mark_as_delivered` (`title`, `url`, `feed_source`, `feed_category`, `summary`, `ai_summary`, `audio_url`, `processed_at`, `published_at`). This is the same convention-only coupling as `models.py ↔ data.js`, but it spans repos — change one side and the other silently breaks. Notably, `summary` was **added** to feed-mind for this feature; docs written before that lack it and the card degrades to no-summary.
- **Audio + AI summary:** `ai_summary` (a longer LLM summary, shown behind an "AI summary" disclosure) and `audio_url` (a Cloud Storage object holding its spoken version, played by the card's Listen button) are written for every category **except `open-source`** — those are the client-pinned static links, which have no pipeline-generated content at all. Both fields are optional everywhere: `normalizeArticle` defaults them to `""` and the card hides the control, so pre-existing docs degrade rather than break. `publicAudioUrl` in `data.js` accepts either an `https://` URL or a `gs://` URI (rewritten to `storage.googleapis.com`) and rejects anything else, so the bucket **must be public-read** — the browser fetches the object directly with no signed URL and no backend.
- **The same pair on papers:** `runs` docs carry `ai_summary` / `audio_url` (plus `audio_generated_at`) **per-paper inside the `papers` array**, not on the run doc — written by whatever generates the audio, *not* by `pipeline/src/paper_prism/models.py`, whose `Paper.to_dict()` still omits them. `normalizePaper` in `data.js` defaults them exactly as `normalizeArticle` does, and `PaperCard` renders an "AI summary" disclosure above the existing "Abstract" one. Runs written before the feature have neither field on any paper, so the Papers *Archive* view routinely mixes cards with and without the controls — that mix is the intended degraded state, not a bug. Both cards share `ListenButton.svelte`, whose module scope makes **one clip play at a time across the whole app**.
- **Categories** come from `feed_category` ∈ `{academic, industry, cloud, open-source}`, listed data-driven in `constants.js::NEWS_CATEGORIES` (rendered as tabs). `open-source` has **no RSS source** — its content is the evergreen `GitHub Trending` link, **pinned client-side** via `constants.js::STATIC_NEWS_LINKS`. `getNews()` (`withPinnedLinks`) stamps each pinned link with a fresh "now" timestamp so it always appears in today's *Latest*, and dedupes by `article_id`, so the pipeline must **not** also persist static links (feed-mind's `mark_as_delivered` loop deliberately skips `static_*` ids). Pinning in the reader guarantees the link shows every day regardless of whether feed-mind ran.
- **Recency is `processed_at`, not `published_at`** (`published_at` is an inconsistent per-feed string; `processed_at` is a uniform UTC ISO string). One query — `where processed_at >= now-7d, orderBy processed_at desc, limit ~200` — backs both News views: **Latest** = newest day-group (derived client-side), **Archive** = the whole 7-day window grouped by day. Single-field inequality+orderBy needs **no composite index**.
- **Rules:** `firestore.rules` adds `processed_articles` as public-read / `write: if false`. feed-mind writes via the Admin SDK (bypasses rules) and does **not** manage rules, so paper-prism solely owns them on `feed-mind-db`.
- **Mock parity:** `web/public/fixtures/news.json` backs `VITE_DATA_SOURCE=mock`. The mock path deliberately skips the 7-day cutoff (a static fixture would otherwise age out and render empty).

### Videos (third section, also from `feed-mind`)

`#/videos` reads `youtube_videos` in `feed-mind-db`, written by `feed-mind/feedmind/deduplication.py::save_video` (`video_id`, `url`, `title`, `channel`, `thumbnail_url`, `published_at`, `processed_at`) — same convention-only, cross-repo coupling as `processed_articles`. One query backs both tabs (`VIDEO_WINDOW_DAYS` = 3, `VIDEO_MAX_ITEMS` = 200).

**Latest is an ingest batch, not a time window — this is the whole design.** feed-mind writes a video once, on first sight, stamping `processed_at` with that run's `now`; the doc id is the video id, so re-runs never restamp. `lib/videos.js::latestBatch` anchors to the **newest `processed_at` present in the data** and keeps everything within `VIDEO_BATCH_TOLERANCE_HOURS` (6) of it. Any clock-relative rule (the two earlier ones: newest calendar day, then rolling 24h) makes the tab **shrink through the day** as videos age past the cutoff with no new run — the failure this design exists to prevent, pinned by tests in `videos.test.js` and `VideoFeed.test.js` that advance the clock and assert the count holds. For the same reason the Firestore query windows on `processed_at`, not `published_at`: a batch then ages out of the 3-day window all at once instead of one video at a time. Display order is still `published_at` desc (`byPublishedDesc` re-sorts, since `processed_at` is uniform within a batch), and Archive buckets by publish day.

Videos with no parseable `processed_at` can't be placed in a batch, so Latest omits them and says so; Archive still lists them under a `—` header. Both `VideoFeed` and `VideoCard` must guard dates with `isDate`, never truthiness — an Invalid Date is truthy and `Intl.DateTimeFormat` throws on it, taking down the whole feed render.

## Common commands

**Pipeline (local, runs against live arXiv):**
```bash
cd pipeline
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt
cp .env.example .env            # edit the three PROFILE_* paragraphs — these ARE the product
PYTHONPATH=src .venv/bin/python -m paper_prism
```
No `GEMINI_API_KEY` → summaries written as `null` (pipeline still runs). `SINK=local` (default) → JSON under `./output/`. First run downloads ~90 MB of ONNX weights (cached by `huggingface_hub`).

**Web (local, mock data):**
```bash
cd web
npm install
npm run dev            # http://localhost:5173
npm run build          # -> dist/
```

**Infra (Terraform):**
```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in
export TF_VAR_gemini_api_key=...
terraform init && terraform validate && terraform apply
```

**Deploy via gcloud scripts** (alternative to Terraform): `pipeline/deploy/00-config.sh` (sourced by the rest) → `01-setup.sh` (APIs, Firestore, TTL, SAs, secret) → `02-build-push.sh` → `03-deploy-job.sh` (needs `env.yaml`, copied from `env.yaml.example`) → `04-scheduler.sh`. All idempotent; require `PROJECT_ID` exported.

**Web tests:** `cd web && npm test` (vitest; jsdom + `@testing-library/svelte` for components). The **pipeline has no test suite, and no linter is configured anywhere** — validate the pipeline by running it locally and inspecting `./output/`.

## Conventions worth matching

- The interest **profile paragraphs** (`PROFILE_AIML` / `PROFILE_NLP` / `PROFILE_CV`) drive all ranking quality. `config.py` warns loudly if the placeholder examples are used verbatim — real profiles must be authored deliberately.
- Env config is the only knob surface: `WINDOW_DAYS`, `TOP_K`, `RETENTION_DAYS`, `ARXIV_*` tuning, `SINK`, `GEMINI_*`, `FIRESTORE_DATABASE`, `CONTENT_READY_TOPIC`. Add new tunables in `config.py`, wire them into `infra/run.tf` (`job_env`) and `pipeline/deploy/env.yaml.example` so all three deploy paths stay in sync. A tunable that also affects the web reader (like `FIRESTORE_DATABASE` ↔ `VITE_FIRESTORE_DATABASE`) must be mirrored in `web/.env*` too.
- Markdown files are gitignored except `docs/paper-prism-prd.md` and this `CLAUDE.md` (see `.gitignore`) — other `.md` docs are kept local-only.
