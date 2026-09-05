# apps/web

Guidance for working inside the web app. The system-level view — the four
deployables, the shared Firestore database and the cross-component schema
contracts — is in the **root `CLAUDE.md`**; read that first if you are changing
anything another component writes.

## What this is

A Svelte 5 + Vite SPA (PWA) that reads Firestore **directly from the browser**.
There is no backend API and no request-path compute. It is the reader for all
three services:

| Section | Route | Collection | Written by |
|---|---|---|---|
| News | `#/news` | `processed_articles` | `services/feed-mind` |
| Videos | `#/videos` | `youtube_videos` | `services/feed-mind` |
| Papers | `#/` | `runs`, `run_status` | `services/paper-prism` |
| (all three) | — | `ai_summary`, `audio_url` fields | `services/summarizer` |
| Saved / prefs | `#/saved` | `users/{uid}` | this app — the only write path |

## Web architecture

`src/lib/data.js` is a data-source abstraction exposing `getLatest()`, `getArchive()`, `getStatus()`. `VITE_DATA_SOURCE` selects the backend:

- `mock` (default) — bundled JSON fixtures under `public/fixtures/`, so the UI runs with zero cloud setup.
- `firestore` — reads Firestore directly from the browser. The Firebase SDK is loaded via **dynamic import**, so `mock` builds don't ship it.

Both backends return identical shapes. Firestore read access is public and governed by `../../infra/firebase/firestore.rules` (public read, `write: if false` — the pipeline writes server-side via a service account that bypasses rules). The Latest/Archive queries need the composite index in `../../infra/firebase/firestore.indexes.json` (mirrored in `../../infra/terraform/main.tf`).

**Named database coupling:** `VITE_FIRESTORE_DATABASE` selects a non-default Firestore database and is passed to `getFirestore(app, id)` (unset → `(default)`). It **must match `services/paper-prism`'s `FIRESTORE_DATABASE`** and `services/summarizer`'s (default `feed-mind-db`) — the browser reads Firestore directly, so a mismatch silently reads an empty `(default)`. `VITE_*` values are inlined at build time, so changing the database requires a rebuild. Collections `runs`/`run_status` are never created explicitly; they appear on the pipeline's first write. On the gcloud path, `services/paper-prism/deploy/01b-setup-firestore-db.sh` provisions the named database (create + TTL + `runs` index).

**`firebase.json` must target the named database too.** The `firestore` block sets `"database": "feed-mind-db"`. Without it the Firebase CLI deploys rules/indexes to `(default)` — and will *create* an empty `(default)` database — while the app and pipeline use `feed-mind-db`, so `firestore.rules` (incl. the `processed_articles` public-read rule) silently never reaches the database the browser reads. There are **two build/deploy footguns to keep paired here:** (1) always ship a **firestore** build to production — a mock build has the fixtures inlined and never touches Firestore, so deploying that `dist/` serves placeholder data; (2) keep `firebase.json`'s `database` pinned so `firebase deploy` hits `feed-mind-db`, not `(default)`.

**Env precedence & the prod build (subtle).** `.env` holds the firestore defaults + real (public) Firebase keys, but `.env.local` (gitignored) forces `VITE_DATA_SOURCE=mock` with *empty* keys for local `npm run dev`. Vite loads `.env.local` in **every** mode, above `.env` — so a plain `vite build` bakes **mock**. Production therefore builds with `vite build --mode prod` (the `build` script does this), which loads `.env.prod` (gitignored) *after* `.env.local`, flipping the source back to `firestore` and restoring the real keys. `.env.prod` **must** carry the real `VITE_FIREBASE_*` values, because `.env.local`'s empty ones would otherwise clobber `.env`. Net rule: `npm run build` = firestore/prod; `npm run dev` = mock; to force a mock QA build, prefix `VITE_DATA_SOURCE=mock` (a shell env var beats all `.env*` files).

### News feed (second data source: `services/feed-mind`)

The web app is a two-section SPA behind a minimal hash router in `App.svelte`: **Papers** (`#/`, the arXiv digest above) and **News** (`#/news`). The News section reads a **different collection written by a different service** — `processed_articles` in the *same* `feed-mind-db` database, produced by `services/feed-mind`, the RSS→Telegram pipeline. `services/paper-prism` does not write it.

- **Schema coupling:** `getNews()` in `data.js` and `ArticleCard.svelte` depend on the doc shape written by `services/feed-mind/feedmind/deduplication.py::mark_as_delivered` (`title`, `url`, `feed_source`, `feed_category`, `summary`, `ai_summary`, `audio_url`, `processed_at`, `published_at`). This is the same convention-only coupling as `models.py ↔ data.js`: still enforced by nothing, but now visible in a single diff. Notably, `summary` was **added** to feed-mind for this feature; docs written before that lack it and the card degrades to no-summary.
- **Audio + AI summary:** `ai_summary` (a longer LLM summary, shown behind an "AI summary" disclosure) and `audio_url` (a Cloud Storage object holding its spoken version, played by the card's Listen button) are written for every category **except `open-source`** — those are the client-pinned static links, which have no pipeline-generated content at all. Both fields are optional everywhere: `normalizeArticle` defaults them to `""` and the card hides the control, so pre-existing docs degrade rather than break. `publicAudioUrl` in `data.js` accepts either an `https://` URL or a `gs://` URI (rewritten to `storage.googleapis.com`) and rejects anything else, so the bucket **must be public-read** — the browser fetches the object directly with no signed URL and no backend.
- **The same pair on papers:** `runs` docs carry `ai_summary` / `audio_url` (plus `audio_generated_at`) **per-paper inside the `papers` array**, not on the run doc — written by `services/summarizer`, *not* by `services/paper-prism/src/paper_prism/models.py`, whose `Paper.to_dict()` still omits them. `normalizePaper` in `data.js` defaults them exactly as `normalizeArticle` does, and `PaperCard` renders an "AI summary" disclosure above the existing "Abstract" one. Runs written before the feature have neither field on any paper, so the Papers *Archive* view routinely mixes cards with and without the controls — that mix is the intended degraded state, not a bug. Both cards share `ListenButton.svelte`, whose module scope makes **one clip play at a time across the whole app**.
- **Categories** come from `feed_category` ∈ `{academic, industry, cloud, open-source, top_stories}`, listed data-driven in `constants.js::NEWS_CATEGORIES` (rendered as tabs). Adding a category is one entry there — the tab strip, filtering and both views are derived from it — but the `code` **must match `services/feed-mind`'s `RSS_FEEDS` category string exactly**, and those strings are not internally consistent (`open-source` hyphenates, `top_stories` underscores). The reader matches with `===`, so a "tidied" separator empties the tab silently, with no error on either side; `constants.test.js` pins both spellings. Order is tab order and `NEWS_CATEGORIES[0]` is the tab that opens by default, so append rather than prepend. `open-source` has **no RSS source** — its content is the evergreen `GitHub Trending` link, **pinned client-side** via `constants.js::STATIC_NEWS_LINKS`. `getNews()` (`withPinnedLinks`) stamps each pinned link with a fresh "now" timestamp so it always appears in today's *Latest*, and dedupes by `article_id`, so the pipeline must **not** also persist static links (feed-mind's `mark_as_delivered` loop deliberately skips `static_*` ids). Pinning in the reader guarantees the link shows every day regardless of whether feed-mind ran.
- **Recency is `processed_at`, not `published_at`** (`published_at` is an inconsistent per-feed string; `processed_at` is a uniform UTC ISO string). One query — `where processed_at >= now-7d, orderBy processed_at desc, limit ~200` — backs both News views: **Latest** = newest day-group (derived client-side), **Archive** = the whole 7-day window grouped by day. Single-field inequality+orderBy needs **no composite index**.
- **Rules:** `../../infra/firebase/firestore.rules` adds `processed_articles` as public-read / `write: if false`. feed-mind writes via the Admin SDK (bypasses rules) and does **not** manage rules, so this app solely owns them on `feed-mind-db`.
- **Mock parity:** `public/fixtures/news.json` backs `VITE_DATA_SOURCE=mock`. The mock path deliberately skips the 7-day cutoff (a static fixture would otherwise age out and render empty).

### Videos (third section, also from `services/feed-mind`)

`#/videos` reads `youtube_videos` in `feed-mind-db`, written by `services/feed-mind/feedmind/deduplication.py::save_video` (`video_id`, `url`, `title`, `channel`, `thumbnail_url`, `published_at`, `processed_at`) — same convention-only coupling as `processed_articles`. One query backs both tabs (`VIDEO_WINDOW_DAYS` = 3, `VIDEO_MAX_ITEMS` = 200).

**Latest is an ingest batch, not a time window — this is the whole design.** feed-mind writes a video once, on first sight, stamping `processed_at` with that run's `now`; the doc id is the video id, so re-runs never restamp. `lib/videos.js::latestBatch` anchors to the **newest `processed_at` present in the data** and keeps everything within `VIDEO_BATCH_TOLERANCE_HOURS` (6) of it. Any clock-relative rule (the two earlier ones: newest calendar day, then rolling 24h) makes the tab **shrink through the day** as videos age past the cutoff with no new run — the failure this design exists to prevent, pinned by tests in `videos.test.js` and `VideoFeed.test.js` that advance the clock and assert the count holds. For the same reason the Firestore query windows on `processed_at`, not `published_at`: a batch then ages out of the 3-day window all at once instead of one video at a time. Display order is still `published_at` desc (`byPublishedDesc` re-sorts, since `processed_at` is uniform within a batch), and Archive buckets by publish day.

Videos with no parseable `processed_at` can't be placed in a batch, so Latest omits them and says so; Archive still lists them under a `—` header. Both `VideoFeed` and `VideoCard` must guard dates with `isDate`, never truthiness — an Invalid Date is truthy and `Intl.DateTimeFormat` throws on it, taking down the whole feed render.

### Sign-in and per-user data (the one write path)

Optional Google sign-in adds a personal layer on top of the public site. **It is purely additive: signed out, the app is exactly what it was** — same content, same queries, no gating. There is **no backend, no API and no cloud function**: Firebase Auth is hosted, and `../../infra/firebase/firestore.rules` does the authorization server-side, so the "no request-path compute" contract is intact. Deploying it needs only a web build + `firebase deploy --only firestore:rules`.

- **`users/{uid}` is the only collection the browser may write**, and the only one that isn't public. Everything for one user is on that single document: `bookmarks` (array) and `unfollowed` (map). `lib/prefs.js` owns it; both writes use `merge: true` so the two fields never clobber each other.
- **The allowlist lives in `../../infra/firebase/firestore.rules` and nowhere else.** Anyone with a Google account can *authenticate* — only listed, `email_verified` addresses can read or write anything. The client never carries a copy (that would ship real emails in a public bundle and create two lists that drift); it **probes** instead, reading its own doc and treating `permission-denied` as "not allowed" (`prefs.js::probeAccess`). Only `permission-denied` rejects — offline/transient errors fail *open*, because signing someone out over a network blip is worse, and the rules still reject the writes anyway. **Adding a person = edit the rules and redeploy them.**
- **Four session states, not two** (`lib/session.svelte.js`): `loading` / `out` / `in` / `rejected`. `rejected` exists because "signed in" and "allowed" are different questions — a non-allowlisted visitor is signed straight back out with an explanation rather than left in a logged-in UI whose every write fails.
- **`lib/auth.js` mirrors `data.js`'s two-backend split** on the same `VITE_DATA_SOURCE`. This is not a convenience: `npm run dev` forces mock with *empty* Firebase keys, so without the fake user the entire signed-in half of the UI would be unreachable outside production, and component tests would need a real project. `firebase/auth` stays behind a dynamic import — **mock builds must never contain the auth SDK** (grep a mock `dist/` for `signInWithPopup` to check). `lib/firebase.js` owns the shared `initializeApp` *and* `firestoreDb()`, because `initializeApp` throws on a second call and a duplicated named-database choice silently reads an empty `(default)`.
- **Bookmarks store a snapshot, not a reference** (`prefs.js::snapshotOf`). Every source collection is on a TTL (runs 45 days, articles/videos 90) and **papers aren't documents at all** — they live inside a run doc's `papers` array, so there is nothing to point at. A saved item therefore carries its own render payload, whitelisted per type (an abstract would bloat every doc) with every value coerced to a string (Firestore rejects `undefined`). The tradeoff: a snapshot never updates.
- **`BOOKMARK_LIMIT` (5) and the single-document shape imply each other.** Rules can check `size()` on a list but cannot count documents in a subcollection, so the cap is only enforceable because the bookmarks are an array on `users/{uid}`. **Raising it means changing `src/lib/constants.js` *and* `../../infra/firebase/firestore.rules`.** At the cap a save is **refused, never evicted** — silently deleting something the user chose to keep is worse than refusing, so the star points at `#/saved` to free a slot.
- **Follow/unfollow stores what's switched OFF** (`unfollowed`), not what's on. The source catalog isn't ours — it's `services/feed-mind/feedmind/config.py`, and it grows. A stored "followed" list would silently hide every newly added feed from existing users, with no migration step available in a client-only app. Storing exclusions means absence = followed, so new sources appear automatically and an unloaded/failed/signed-out state shows everything. The settings sheet derives its catalog from the loaded documents for the same reason — a hardcoded copy would drift.
- **The channel filter runs *before* `latestBatch()`** in `VideoFeed`. Filtering afterwards could empty Latest entirely while an older batch sat visible in Archive; upstream, unfollowing the channel that owns the newest batch correctly falls through to the next one.
- **One-time console setup:** enable the Google provider, and add every serving domain under Authentication → Settings → Authorized domains, or the popup fails silently. `VITE_FIREBASE_AUTH_DOMAIN` is only needed for a *custom* auth domain — it defaults to `<projectId>.firebaseapp.com`.
- **Not covered by tests:** the Firestore backends of `auth.js`/`prefs.js` and the rules themselves. The suite exercises the mock path only; there is no Firestore emulator configured, so "the rules accept five bookmarks and reject six" is verified by reading, not by running.

## Common commands

Run from `apps/web/`.

```bash
npm install
npm run dev            # http://localhost:5173, mock data
npm run build          # -> dist/, firestore/prod mode
npm test               # vitest; jsdom + @testing-library/svelte for components
```

Deploying is `firebase deploy --only hosting` **from the repo root** —
`firebase.json` lives there and points `hosting.public` at `apps/web/dist`.

## Not covered by tests

The Firestore backends of `auth.js`/`prefs.js`, and the rules themselves. The
suite exercises the mock path only; there is no Firestore emulator configured,
so "the rules accept five bookmarks and reject six" is verified by reading, not
by running.
