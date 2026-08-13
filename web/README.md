# paper-prism — web (P3)

Lightweight **Svelte SPA** that reads the digest **directly from Firestore**
(Path A — no backend API). Two tabs (Latest, Archive), a per-lens freshness
badge from `run_status`, and graceful null-summary / empty-window states. See
PRD §3.5 / §4.

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
```

The Firebase web config is **public, not secret** — read access is governed by
`../firestore.rules` (public read, no client write). The Firestore SDK is loaded
via dynamic import, so `mock` builds don't ship it.

## Build & deploy (Firebase Hosting, free Spark tier)

```bash
npm run build             # -> dist/
# from the repo root (uses ../firebase.json + firestore.rules + indexes):
firebase deploy --only hosting
firebase deploy --only firestore:rules,firestore:indexes
```

## Data source abstraction

`src/lib/data.js` exposes `getLatest()`, `getArchive()`, `getStatus()`.
Both backends return the same shapes:

| view | query |
|---|---|
| Latest | per lens: `where(category==X).orderBy(run_date desc).limit(1)` |
| Archive | per lens: same, `limit(5)` |
| Freshness | latest `run_status` doc |

## Regenerating fixtures

After a pipeline run writes `../pipeline/output/`, rebuild the mock fixtures with
the snippet in the repo (see commit history) or point `VITE_DATA_SOURCE=firestore`
at a real project.

## Layout

```
src/
  App.svelte                 # tabs, loading/error, Latest + Archive layouts
  lib/data.js                # firestore | mock source abstraction
  lib/constants.js           # lens display metadata
  components/
    LensColumn.svelte        # lens heading + papers (empty-window state)
    PaperCard.svelte         # one paper (null-summary state)
    FreshnessBadge.svelte    # per-lens fresh/stale chips from run_status
public/fixtures/             # bundled mock data (manifest + runs + run_status)
```
