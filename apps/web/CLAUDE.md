# apps/web

Guidance for working inside the web app. The system-level view — the four
deployables, the shared Firestore database and the cross-component schema
contracts — is in the **root `CLAUDE.md`**; read that first if you are changing
anything another component writes.

## What this is

A Svelte 5 + Vite SPA (PWA) that reads Firestore **directly from the browser**.
There is no backend API and no request-path compute. It is the reader for all
of FeedMind's services:

| Section | Route | Collection | Written by |
|---|---|---|---|
| News | `#/news` | `processed_articles` | `services/ingest` (news group) |
| Videos | `#/videos` | `youtube_videos` | `services/ingest` (youtube group) |
| Papers | `#/` | `runs`, `run_status` | `services/paper-prism` |
| Stories | `#/stories` | `stories` | `services/news-curator` |
| Knowledge Bytes | `#/knowledge` | `processed_articles` | `services/ingest` (knowledge_bytes group) |
| (all five) | — | `ai_summary`, `audio_url` fields | `services/summarizer` |
| Saved / prefs | `#/saved` | `users/{uid}` | this app — the only write path |

## Web architecture

`src/lib/data.js` is a data-source abstraction exposing `getLatest()`, `getArchive()`, `getStatus()`. `VITE_DATA_SOURCE` selects the backend:

- `mock` (default) — bundled JSON fixtures under `public/fixtures/`, so the UI runs with zero cloud setup.
- `firestore` — reads Firestore directly from the browser. The Firebase SDK is loaded via **dynamic import**, so `mock` builds don't ship it.

Both backends return identical shapes. Firestore read access is public and governed by `../../infra/firebase/firestore.rules` (public read, `write: if false` — the pipeline writes server-side via a service account that bypasses rules). The Latest/Archive queries need the composite index in `../../infra/firebase/firestore.indexes.json` (mirrored in `../../infra/terraform/main.tf`).

**Named database coupling:** `VITE_FIRESTORE_DATABASE` selects a non-default Firestore database and is passed to `getFirestore(app, id)` (unset → `(default)`). It **must match `services/paper-prism`'s `FIRESTORE_DATABASE`** and `services/summarizer`'s (default `feed-mind-db`) — the browser reads Firestore directly, so a mismatch silently reads an empty `(default)`. `VITE_*` values are inlined at build time, so changing the database requires a rebuild. Collections `runs`/`run_status` are never created explicitly; they appear on the pipeline's first write. On the gcloud path, `services/paper-prism/deploy/01b-setup-firestore-db.sh` provisions the named database (create + TTL + `runs` index).

**`firebase.json` must target the named database too.** The `firestore` block sets `"database": "feed-mind-db"`. Without it the Firebase CLI deploys rules/indexes to `(default)` — and will *create* an empty `(default)` database — while the app and pipeline use `feed-mind-db`, so `firestore.rules` (incl. the `processed_articles` public-read rule) silently never reaches the database the browser reads. There are **two build/deploy footguns to keep paired here:** (1) always ship a **firestore** build to production — a mock build has the fixtures inlined and never touches Firestore, so deploying that `dist/` serves placeholder data; (2) keep `firebase.json`'s `database` pinned so `firebase deploy` hits `feed-mind-db`, not `(default)`.

**Env precedence & the prod build (subtle).** `.env` holds the firestore defaults + real (public) Firebase keys, but `.env.local` (gitignored) forces `VITE_DATA_SOURCE=mock` with *empty* keys for local `npm run dev`. Vite loads `.env.local` in **every** mode, above `.env` — so a plain `vite build` bakes **mock**. Production therefore builds with `vite build --mode prod` (the `build` script does this), which loads `.env.prod` (gitignored) *after* `.env.local`, flipping the source back to `firestore` and restoring the real keys. `.env.prod` **must** carry the real `VITE_FIREBASE_*` values, because `.env.local`'s empty ones would otherwise clobber `.env`. Net rule: `npm run build` = firestore/prod; `npm run dev` = mock; to force a mock QA build, prefix `VITE_DATA_SOURCE=mock` (a shell env var beats all `.env*` files).

### News feed (second data source: the FeedMind ingest services)

The web app is a two-section SPA behind a minimal hash router in `App.svelte`: **Papers** (`#/`, the arXiv digest above) and **News** (`#/news`). The News section reads a **different collection written by a different service** — `processed_articles` in the *same* `feed-mind-db` database, produced by `services/ingest`. `services/paper-prism` does not write it.

- **Schema coupling:** `getNews()` in `data.js` and `ArticleCard.svelte` depend on the doc shape written by `packages/feedmind-core/feedmind_core/store.py::save_article` (`title`, `url`, `feed_source`, `feed_category`, `summary`, `ai_summary`, `audio_url`, `processed_at`, `published_at`). This is the same convention-only coupling as `models.py ↔ data.js`: still enforced by nothing, but now visible in a single diff. Notably, `summary` was **added** to feed-mind for this feature; docs written before that lack it and the card degrades to no-summary.
- **Audio + AI summary:** `ai_summary` (a longer LLM summary, shown behind an "AI summary" disclosure) and `audio_url` (a Cloud Storage object holding its spoken version, played by the card's Listen button) are written for every category **except `open-source`** — those are the client-pinned static links, which have no pipeline-generated content at all. Both fields are optional everywhere: `normalizeArticle` defaults them to `""` and the card hides the control, so pre-existing docs degrade rather than break. `publicAudioUrl` in `data.js` accepts either an `https://` URL or a `gs://` URI (rewritten to `storage.googleapis.com`) and rejects anything else, so the bucket **must be public-read** — the browser fetches the object directly with no signed URL and no backend.
- **The same pair on papers:** `runs` docs carry `ai_summary` / `audio_url` (plus `audio_generated_at`) **per-paper inside the `papers` array**, not on the run doc — written by `services/summarizer`, *not* by `services/paper-prism/src/paper_prism/models.py`, whose `Paper.to_dict()` still omits them. `normalizePaper` in `data.js` defaults them exactly as `normalizeArticle` does, and `PaperCard` renders an "AI summary" disclosure above the existing "Abstract" one. Runs written before the feature have neither field on any paper, so the Papers *Archive* view routinely mixes cards with and without the controls — that mix is the intended degraded state, not a bug. Both cards share `ListenButton.svelte`, whose module scope makes **one clip play at a time across the whole app**.
- **Categories** come from `feed_category` ∈ `{academic, industry, cloud, open-source, top_stories}`, listed data-driven in `constants.js::NEWS_CATEGORIES` (rendered as tabs). Adding a category is one entry there — the tab strip, filtering and both views are derived from it — but the `code` **must match the `category` in an ingest service's `feeds.yaml` exactly**, and those strings are not internally consistent (`open-source` hyphenates, `top_stories` underscores). The reader matches with `===`, so a "tidied" separator empties the tab silently, with no error on either side; `constants.test.js` pins both spellings. Order is tab order and `NEWS_CATEGORIES[0]` is the tab that opens by default, so append rather than prepend. `open-source` has **no RSS source** — its content is the evergreen `GitHub Trending` link, **pinned client-side** via `constants.js::STATIC_NEWS_LINKS`. `getNews()` (`withPinnedLinks`) stamps each pinned link with a fresh "now" timestamp so it always appears in today's *Latest*, and dedupes by `article_id`, so the pipeline must **not** also persist static links (the static links live in `services/telegram-notifier/notifier.yaml` and are never persisted). Pinning in the reader guarantees the link shows every day regardless of whether feed-mind ran.
- **Recency is `processed_at`, not `published_at`** (`published_at` is an inconsistent per-feed string; `processed_at` is a uniform UTC ISO string). One query — `where processed_at >= now-7d, orderBy processed_at desc, limit ~200` — backs both News views: **Latest** = newest day-group (derived client-side), **Archive** = the whole 7-day window grouped by day. Single-field inequality+orderBy needs **no composite index**.
- **Rules:** `../../infra/firebase/firestore.rules` adds `processed_articles` as public-read / `write: if false`. feed-mind writes via the Admin SDK (bypasses rules) and does **not** manage rules, so this app solely owns them on `feed-mind-db`.
- **Mock parity:** `public/fixtures/news.json` backs `VITE_DATA_SOURCE=mock`. The mock path deliberately skips the 7-day cutoff (a static fixture would otherwise age out and render empty).

### Videos (third section, from `services/ingest`)

`#/videos` reads `youtube_videos` in `feed-mind-db`, written by `packages/feedmind-core/feedmind_core/store.py::save_video` (`video_id`, `url`, `title`, `channel`, `thumbnail_url`, `published_at`, `processed_at`) — same convention-only coupling as `processed_articles`. One query backs both tabs (`VIDEO_WINDOW_DAYS` = 3, `VIDEO_MAX_ITEMS` = 200).

**Latest is an ingest batch, not a time window — this is the whole design.** `services/ingest` writes a video once, on first sight, stamping `processed_at` with that run's `now`; the doc id is the video id, so re-runs never restamp. `lib/videos.js::latestBatch` anchors to the **newest `processed_at` present in the data** and keeps everything within `VIDEO_BATCH_TOLERANCE_HOURS` (6) of it. Any clock-relative rule (the two earlier ones: newest calendar day, then rolling 24h) makes the tab **shrink through the day** as videos age past the cutoff with no new run — the failure this design exists to prevent, pinned by tests in `videos.test.js` and `VideoFeed.test.js` that advance the clock and assert the count holds. For the same reason the Firestore query windows on `processed_at`, not `published_at`: a batch then ages out of the 3-day window all at once instead of one video at a time. Display order is still `published_at` desc (`byPublishedDesc` re-sorts, since `processed_at` is uniform within a batch), and Archive buckets by publish day.

Videos with no parseable `processed_at` can't be placed in a batch, so Latest omits them and says so; Archive still lists them under a `—` header. Both `VideoFeed` and `VideoCard` must guard dates with `isDate`, never truthiness — an Invalid Date is truthy and `Intl.DateTimeFormat` throws on it, taking down the whole feed render.

### Stories (fourth section, from `services/news-curator`)

`#/stories` reads the `stories` collection in `feed-mind-db`, written by `services/news-curator`'s `pipeline.py` (`story_id`, `coarse_category`, `business_category`, `rank`, `score`, `cluster_size`, `sources`, `canonical`, `related_articles`, `run_date`) and later stamped with `ai_summary`/`audio_url` by `services/summarizer`'s `NEWS_STORIES` pipeline — same convention-only coupling as every other collection here. Full schema: `docs/feed-mind/news-curator-design.md` §5.2.

**Categories are a second, independent taxonomy.** `constants.js::STORY_CATEGORIES` (politics/global/business/sports/culture) has nothing to do with `NEWS_CATEGORIES` — different collection, different pipeline, and `constants.test.js` asserts the two code sets don't overlap so a stray `===` filter can't silently cross them. Codes must match `services/news-curator/src/news_curator/anchors.py::COARSE_ANCHORS` byte-for-byte, same contract shape as `NEWS_CATEGORIES` ↔ ingest `feeds.yaml`. `BUSINESS_STORY_CATEGORIES` is a pure label lookup for the badge on a business story that has one; eligibility is decided entirely server-side.

**One query per category, not one query for everything.** `firestoreStories` mirrors `firestoreLatest`'s per-lens shape (`Promise.all` over `STORY_CATEGORY_CODES`), each `where(coarse_category==code).where(run_date>=cutoff).orderBy(run_date desc).orderBy(rank asc).limit(STORY_MAX_PER_CATEGORY)` — needs the composite index in `../../infra/firebase/firestore.indexes.json` on exactly those three fields (country, coarse_category, run_date, rank), in that order. The `run_date >=` range filter is compatible with that same index without changes, because Firestore only requires the ranged field to be the first `orderBy` after the equality filters, which it already is.

**`rank` resets to 1 every run, so it cannot be ordered on alone.** `services/news-curator` writes a `Story` for *every* cluster in a category, not just the ones selected for summarization, so a busy category can carry 10-20+ ranked docs a day and the same rank number recurs across days. `StoriesFeed.svelte` groups the (run_date desc, rank asc)-ordered results into day buckets client-side (`days`/`shownDays`, same shape as `NewsFeed`/`VideoFeed`) — the same "the field that means latest can't be filtered on server-side" shape as `services/summarizer/feedmind_audio.py::collect_articles`' `processed_date` match, just solved client-side here because the browser owns the query.

**Latest/Archive split, same one-query-backs-both-views shape as News and Videos.** `getStories()` now returns the whole `STORY_ARCHIVE_WINDOW_DAYS` (3) window per (country, category), newest run_date first, instead of pre-slicing to the newest run — `constants.js::STORY_MAX_PER_CATEGORY` is `STORY_MAX_PER_DAY * STORY_ARCHIVE_WINDOW_DAYS`, sized per day and multiplied by the window rather than picked independently. `StoriesFeed.svelte`'s Latest tab takes just the newest day bucket; Archive shows every bucket in the window, with a day-date heading per group like `NewsFeed`'s Archive. The mock fixture is *not* cutoff-filtered against real "now", same reasoning as `mockNews`/`mockVideos` — a static fixture would age out to empty.

**`title` is flattened up from `canonical.title`.** `normalizeStory` copies it to the top level so `lib/playlists.js::tracksFrom` — which reads a flat `title` + `audio_url`, same as an article or paper — works on a story with no changes to that shared code.

**No bookmarking yet, unlike News.** `StoryCard` has no `BookmarkButton` — a natural follow-up once the section has settled, not an omission to fix reflexively. Follow/unfollow does exist, though, as of the `"story"` kind in `follows.svelte.js`/`SettingsSheet.svelte`: the catalog is every distinct name across every story's `sources` array (a cluster, so several publications per story, across both countries and all categories), and a story stays visible as long as **at least one** of its contributing sources is still followed — unfollowing one outlet doesn't blank a cluster the others also covered. `StoriesFeed.svelte` filters on that before grouping into day buckets. `App.svelte`'s settings-open effect eagerly `loadStories()`s so the catalog is complete even for a user who never opened `#/stories`.

**Rules:** `../../infra/firebase/firestore.rules` adds `stories` as public-read / `write: if false`, same shape as `processed_articles`.

**Mock parity:** `public/fixtures/stories.json` backs `VITE_DATA_SOURCE=mock` — a flat array like `news.json`/`videos.json`, not manifest-driven. `mockStories` applies the same category-split + `sortByRunThenRank` ordering as the Firestore path (both leave Latest/Archive slicing to `StoriesFeed.svelte`) so both sources produce identical shapes.

### Knowledge Bytes (fifth section, from `services/ingest`'s `knowledge_bytes.yaml`)

`#/knowledge` reads the **same** `processed_articles` collection as News, filtered to `constants.js::KNOWLEDGE_CATEGORY_CODES` (`aiml`, `dsa`, `system_design`) instead of `NEWS_CATEGORY_RSS_CODES` — same one-query-backs-both-views shape as `firestoreNews`, same composite index (`feed_category`, `processed_at`), and `KnowledgeFeed.svelte` is structurally a copy of `NewsFeed.svelte`'s Latest/Archive + category-tab pattern (this repo's established convention for these near-identical feed sections, see `NewsFeed`/`StoriesFeed`/`VideoFeed`). Follow/unfollow exists (the `"knowledge"` kind, keyed on `feed_source`) — with a third series now shipped alongside AI/ML and DSA, per-source muting stops being a second way to hide a whole tab and starts doing real work. No masthead "Listen Top" shortcut, unlike News.

**The source is a sibling repo, not another FeedMind service.** `services/ingest/knowledge_bytes.yaml` fetches `https://florilex.web.app/<series>/rss.xml` — a fully static Astro site (`../florilex`) with no relationship to this repo's GCP project. Each florilex series feed exposes only its **2 most-recently-published lessons ever**, not a rolling time window, so most 08:00 runs find nothing new — that is the source's normal cadence, not a misconfiguration to chase.

**`summarize: none` here means "use the feed's own description," not "no summary."** Every RSS `<description>` in florilex is already the lesson's own hand-written summary (`apps/aiml/src/content/config.ts`'s `summary` field), so re-summarizing it would be redundant work for a worse result. `packages/feedmind-core/feedmind_core/runner.py::_summarize`'s `SUMMARIZE_NONE` branch returns `article.snippet` (the fetched RSS text) rather than `""`, which is what `store.py::save_article` writes to the `summary` field the web app actually renders — the previously-existing behavior of returning `""` left the description stranded in `snippet`, a field `ArticleCard.svelte` never reads. This is a shared `feedmind-core` behavior change, not a Knowledge-Bytes-only branch: safe for `youtube.yaml` (never calls `_summarize`) and for `services/india-news-ingest` (its `summary` field is never read downstream — its articles are excluded from this web app's News tab via `curation_status` and rendered instead through `services/news-curator`'s own `ai_summary`).

**No `curation_status`, so no summarizer changes.** Knowledge Bytes articles flow through `services/summarizer`'s default `RSS_FEED` pipeline exactly like News's tech-blog articles, getting a real LLM-generated `ai_summary` and audio in the same 08:00 batch — see the root `CLAUDE.md`'s ingest section.

**Bookmarking reuses `ArticleCard`'s hardcoded `type="news"`.** A saved Knowledge Bytes lesson works (saves, restores, counts against `BOOKMARK_LIMIT`) but is grouped under the "AI Cloud Blogs" heading in `SavedView`, not its own — introducing a real `"knowledge"` bookmark type would touch `BOOKMARK_TYPES`, `SavedView.svelte`'s label map, and `prefs.js`, which wasn't asked for and isn't done here.

**Mock parity:** `public/fixtures/knowledge.json` backs `VITE_DATA_SOURCE=mock`, same flat-array shape as `news.json`. `mockKnowledgeBytes` does **not** apply the window cutoff to the static fixture, same reasoning as `mockNews`/`mockStories` — a cutoff against real "now" would age it out to empty.

### Sign-in and per-user data (the one write path)

Optional Google sign-in adds a personal layer on top of the public site. **It is purely additive: signed out, the app is exactly what it was** — same content, same queries, no gating. There is **no backend, no API and no cloud function**: Firebase Auth is hosted, and `../../infra/firebase/firestore.rules` does the authorization server-side, so the "no request-path compute" contract is intact. Deploying it needs only a web build + `firebase deploy --only firestore:rules`.

- **`users/{uid}` is the only collection the browser may write**, and the only one that isn't public. Everything for one user is on that single document: `bookmarks` (array) and `unfollowed` (map). `lib/prefs.js` owns it; both writes use `merge: true` so the two fields never clobber each other.
- **The allowlist lives in `../../infra/firebase/firestore.rules` and nowhere else.** Anyone with a Google account can *authenticate* — only listed, `email_verified` addresses can read or write anything. The client never carries a copy (that would ship real emails in a public bundle and create two lists that drift); it **probes** instead, reading its own doc and treating `permission-denied` as "not allowed" (`prefs.js::probeAccess`). Only `permission-denied` rejects — offline/transient errors fail *open*, because signing someone out over a network blip is worse, and the rules still reject the writes anyway. **Adding a person = edit the rules and redeploy them.**
- **Four session states, not two** (`lib/session.svelte.js`): `loading` / `out` / `in` / `rejected`. `rejected` exists because "signed in" and "allowed" are different questions — a non-allowlisted visitor is signed straight back out with an explanation rather than left in a logged-in UI whose every write fails.
- **`lib/auth.js` mirrors `data.js`'s two-backend split** on the same `VITE_DATA_SOURCE`. This is not a convenience: `npm run dev` forces mock with *empty* Firebase keys, so without the fake user the entire signed-in half of the UI would be unreachable outside production, and component tests would need a real project. `firebase/auth` stays behind a dynamic import — **mock builds must never contain the auth SDK** (grep a mock `dist/` for `signInWithPopup` to check). `lib/firebase.js` owns the shared `initializeApp` *and* `firestoreDb()`, because `initializeApp` throws on a second call and a duplicated named-database choice silently reads an empty `(default)`.
- **Bookmarks store a snapshot, not a reference** (`prefs.js::snapshotOf`). Every source collection is on a TTL (runs 45 days, articles/videos 90) and **papers aren't documents at all** — they live inside a run doc's `papers` array, so there is nothing to point at. A saved item therefore carries its own render payload, whitelisted per type (an abstract would bloat every doc) with every value coerced to a string (Firestore rejects `undefined`). The tradeoff: a snapshot never updates.
- **`BOOKMARK_LIMIT` (5) and the single-document shape imply each other.** Rules can check `size()` on a list but cannot count documents in a subcollection, so the cap is only enforceable because the bookmarks are an array on `users/{uid}`. **Raising it means changing `src/lib/constants.js` *and* `../../infra/firebase/firestore.rules`.** At the cap a save is **refused, never evicted** — silently deleting something the user chose to keep is worse than refusing, so the star points at `#/saved` to free a slot.
- **Follow/unfollow stores what's switched OFF** (`unfollowed`), not what's on, across all four kinds — `news`, `video`, `story`, `knowledge`. The source catalog isn't ours — it's the `feeds.yaml` of each ingest service (or, for `story`, the `sources` array `services/news-curator` writes onto each cluster), and it grows. A stored "followed" list would silently hide every newly added feed from existing users, with no migration step available in a client-only app. Storing exclusions means absence = followed, so new sources appear automatically and an unloaded/failed/signed-out state shows everything. The settings sheet derives its catalog from the loaded documents for the same reason — a hardcoded copy would drift, which is also why `App.svelte` eagerly loads all four lazy sections (`loadNews`/`loadVideos`/`loadStories`/`loadKnowledge`) the moment settings opens, not just the two a visitor happened to browse first.
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
