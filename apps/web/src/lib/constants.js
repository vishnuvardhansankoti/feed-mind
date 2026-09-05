// Lens display metadata — keyed by the `category` codes in Firestore (PRD §3.1).
export const LENSES = [
  { code: "AIML", label: "AI / ML", sources: "cs.LG · cs.AI" },
  { code: "NLP", label: "NLP", sources: "cs.CL" },
  { code: "CV", label: "Computer Vision", sources: "cs.CV" },
];

export const LENS_CODES = LENSES.map((l) => l.code);

// News-feed categories — keyed by the `feed_category` values the feed-mind
// pipeline writes to the `processed_articles` collection. `open-source` has no
// RSS source; its content is the pinned static link(s) below.
//
// Order is tab order, and the first entry is the tab that opens by default —
// so new categories go on the end unless they are meant to take over the
// landing view. Each `code` must match feed-mind's `RSS_FEEDS` category string
// byte-for-byte; note the inconsistent separators there (`open-source` hyphen,
// `top_stories` underscore) are deliberate mirrors of the pipeline, not typos.
export const NEWS_CATEGORIES = [
  { code: "academic", label: "Academic" },
  { code: "industry", label: "Industry" },
  { code: "cloud", label: "Cloud" },
  { code: "open-source", label: "Open Source" },
  { code: "top_stories", label: "Top Stories" },
];

// Evergreen links pinned into the feed by the reader itself, independent of the
// pipeline — so they show *every day* regardless of whether feed-mind ran. Each
// is shaped like a `processed_articles` doc; `getNews()` stamps a fresh
// timestamp (so they land in today's "Latest") and dedupes by `article_id`
// against Firestore, so a matching pipeline-written doc never doubles them up.
export const STATIC_NEWS_LINKS = [
  {
    article_id: "static_github_trending",
    url: "https://github.com/trending",
    title: "GitHub Trending",
    feed_source: "GitHub",
    feed_category: "open-source",
    summary: "Today's trending open-source repositories.",
  },
];

export const NEWS_CATEGORY_CODES = NEWS_CATEGORIES.map((c) => c.code);

// Rolling window (days) and hard read cap for the news feed.
export const NEWS_WINDOW_DAYS = 7;
export const NEWS_MAX_ARTICLES = 200;

// Videos page: YouTube subscriptions written to `youtube_videos` by feed-mind.
// One read backs both tabs — Latest (the most recent ingest batch) and Archive
// (last VIDEO_WINDOW_DAYS days) — with client-side slicing.
export const VIDEO_WINDOW_DAYS = 3;
export const VIDEO_MAX_ITEMS = 200;

// Latest is the newest *ingest batch*, not a window measured back from now.
// A clock-relative window (the previous "last 24h" rule) made the tab shrink
// video-by-video as the day wore on, so the same visit showed fewer items each
// time. Anchoring to the newest `processed_at` in the data instead means the
// set only changes when feed-mind actually runs again.
//
// feed-mind stamps each doc in a run with its own `now`, so one batch spans
// seconds-to-minutes rather than a single instant. This tolerance is what
// "same batch" means: comfortably wider than one run, comfortably narrower
// than the daily cadence between runs.
export const VIDEO_BATCH_TOLERANCE_HOURS = 6;

// Saved items, for signed-in users only. The cap is not a storage concern —
// it is what lets the whole list live as an array on the single `users/{uid}`
// document, which in turn is what makes the limit enforceable in
// firestore.rules at all (rules can check `size()` on a list, but cannot count
// the documents in a subcollection). Raising it is safe well into the hundreds
// — a Firestore document holds 1 MiB and a snapshot is a couple of KB — but it
// must be raised in BOTH places: here and in the rules.
export const BOOKMARK_LIMIT = 5;

// The saved item's `type`, which decides how the Saved view renders it and how
// its id is namespaced (see prefs.js::bookmarkIdFor).
export const BOOKMARK_TYPES = ["paper", "news", "video"];
