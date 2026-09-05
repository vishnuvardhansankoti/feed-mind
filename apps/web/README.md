# apps/web

Lightweight **Svelte SPA** that reads **directly from Firestore** (Path A — no
backend API). Three sections behind a hash router, each with Latest + Archive
sub-tabs, plus a per-lens freshness badge from `run_status` and graceful
missing-field / empty-window states throughout. See `../../docs/paper-prism/paper-prism-prd.md` §3.5 / §4.

| Section | Route | Collection | Written by |
|---|---|---|---|
| News | `#/` (landing) | `processed_articles` | `services/news-ingest`, `services/topstories-ingest` |
| Papers | `#/papers` | `runs`, `run_status` | `services/paper-prism` |
| Videos | `#/videos` | `youtube_videos` | `services/youtube-ingest` |

Every optional field degrades to "control not rendered" rather than an error —
paper `summary`/`abstract`/`ai_summary`/`audio_url`, article
`summary`/`ai_summary`/`audio_url`. This
matters because two of the three collections are written by a different
component, and `ai_summary`/`audio_url` by a third, so the reader routinely
meets documents older than the field it wants.

## Run locally (mock data, no cloud)

Uses the bundled JSON fixtures under `public/fixtures/` (generated from a real
pipeline run), so the UI runs with zero cloud setup.

```bash
npm install
cp .env.example .env      # VITE_DATA_SOURCE=mock (default)
npm run dev               # http://localhost:5173
```

## Run against live Firestore

```bash
# .env
VITE_DATA_SOURCE=firestore
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_PROJECT_ID=...
VITE_FIREBASE_APP_ID=...
VITE_FIRESTORE_DATABASE=feed-mind-db   # named (non-default) database; unset = "(default)"
```

The Firebase web config is **public, not secret** — read access is governed by
`../firestore.rules` (public read, no client write). The Firestore SDK is loaded
via dynamic import, so `mock` builds don't ship it.

`VITE_FIRESTORE_DATABASE` **must match the pipeline's `FIRESTORE_DATABASE`** —
the browser reads Firestore directly, so a mismatch means the app queries an
empty `(default)` database. These `VITE_*` values are inlined at build time, so
rebuild (`npm run build`) after changing them.

## Build & deploy (Firebase Hosting, free Spark tier)

> **Env precedence is load-bearing.** Vite loads `.env.local` in *every* mode,
> above `.env` — and `.env.local` (gitignored) pins `VITE_DATA_SOURCE=mock` with
> empty keys for local dev. So a plain `vite build` bakes **mock**, and shipping
> that `dist/` serves fixture data in production. `npm run build` therefore runs
> `vite build --mode prod`, which loads `.env.prod` *after* `.env.local` and
> flips the source back to firestore. `.env.prod` must carry the real
> `VITE_FIREBASE_*` values, since `.env.local`'s empty ones would clobber
> `.env`. To force a mock QA build, prefix `VITE_DATA_SOURCE=mock` — a shell
> variable beats every `.env*` file.

```bash
npm run build             # -> dist/  (firestore/prod; see the note above)
# from the repo root (uses ../firebase.json + firestore.rules + indexes):
firebase deploy --only hosting
firebase deploy --only firestore:rules,firestore:indexes
```

## Data source abstraction

`src/lib/data.js` exposes `getLatest()`, `getArchive()`, `getStatus()`,
`getNews()` and `getVideos()`. Both backends return the same shapes:

| view | query |
|---|---|
| Papers · Latest | per lens: `where(category==X).orderBy(run_date desc).limit(1)` |
| Papers · Archive | per lens: same, `limit(5)` |
| Freshness | latest `run_status` doc |
| News (both views) | one query: `where(processed_at >= now-7d).orderBy(processed_at desc).limit(200)` — Latest/Archive are sliced client-side |
| Videos (both views) | one query: same shape on `published_at`, 3-day window |

The News and Videos queries use a single-field inequality + matching `orderBy`,
so they need **no composite index** (only the Papers queries do — see
`../firestore.indexes.json`).

### Audio summaries

Both news articles and papers carry an optional `ai_summary` (a longer LLM
summary, behind an "AI summary" disclosure) and `audio_url` (its spoken version).
On articles the pair sits on the doc; on papers it sits **per-paper inside the
run doc**, alongside `audio_generated_at`.

`normalizeArticle` and `normalizePaper` both run `audio_url` through
`publicAudioUrl()`, which accepts an `https://` URL as-is, rewrites
`gs://bucket/object` to its `storage.googleapis.com` public form, and returns
`""` for anything it does not recognize — so a malformed value hides the player
instead of producing a dead one. `ListenButton.svelte` (shared by `ArticleCard`
and `PaperCard`) creates the `<audio>` element on first click — a feed page
holds up to 200 cards, and eager elements would mean 200 media requests — and
its module-scoped state ensures **only one clip plays at a time app-wide**,
across sections as well as within one.

The bucket must be public-read and serve a real audio `Content-Type`; the
browser fetches the object with a plain `GET` and no credentials.

## Regenerating fixtures

`runs/` + `run_status/` + `manifest.json` come from a pipeline run under
`../pipeline/output/`. `news.json` and `videos.json` are curated by hand, since
the feed-mind pipeline writes those collections from a different repo — keep
them shaped like real documents, including a couple of entries that *omit* the
optional fields so the degrade paths stay exercised. The mock source
deliberately skips the rolling-window cutoff for news and videos, so a static
fixture doesn't age out and render empty.

## Layout

```
src/
  App.svelte                 # hash router (News/Papers/Videos), loading/error, layouts
  lib/data.js                # firestore | mock source abstraction
  lib/constants.js           # lens + news-category metadata, pinned static links, windows
  lib/analytics.js           # consent-gated Google Analytics loader
  components/
    LensColumn.svelte        # lens heading + papers (empty-window state)
    PaperCard.svelte         # one paper (null-summary state, ai_summary + abstract disclosures)
    FreshnessBadge.svelte    # per-lens fresh/stale chips from run_status
    NewsFeed.svelte          # category tabs + day grouping for News
    ArticleCard.svelte       # one article (ai_summary disclosure)
    ListenButton.svelte      # shared audio player (one clip at a time, app-wide)
    VideoFeed.svelte         # Latest (24h rolling) + Archive for Videos
    VideoCard.svelte         # one video
    SearchBar.svelte         # find-on-page over the rendered feed
    ConsentBanner.svelte     # analytics opt-in
  test/setup.js              # jsdom setup: fake Audio, jest-dom matchers
public/fixtures/             # bundled mock data (manifest, runs, run_status, news, videos)
```

## Tests

```bash
npm test                     # vitest: lib + component suites
npm run test:watch
```

Two kinds of suite, split by environment:

- **`src/lib/*.test.js`** — data-source normalization and constants. They stub
  `fetch` and exercise the default mock source, so they need neither fixtures on
  disk nor a Firestore project. They opt into Node with a
  `// @vitest-environment node` docblock.
- **`src/components/*.test.js`** — real components mounted in jsdom via
  `@testing-library/svelte`. jsdom is the project-wide default environment, and
  `resolve.conditions: ["browser"]` (set only under `VITEST`) is what makes
  Svelte resolve its client build; without it `mount()` renders nothing.

`src/test/setup.js` replaces `Audio` with a controllable fake — jsdom has no
media stack, so `play()` would throw and no `playing`/`pause`/`ended` event
would ever fire, which is the whole state machine behind `ListenButton`. The
setup file is global, so it no-ops when there is no `window` (the Node suites).

Time-dependent tests (`VideoFeed`) pin the clock with
`vi.useFakeTimers({ toFake: ["Date"] })`. The Videos "Latest" window is defined
against *local midnight*, so a floating `now` would make those tests pass or
fail depending on the hour they ran.
