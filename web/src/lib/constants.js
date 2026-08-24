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
export const NEWS_CATEGORIES = [
  { code: "academic", label: "Academic" },
  { code: "industry", label: "Industry" },
  { code: "cloud", label: "Cloud" },
  { code: "open-source", label: "Open Source" },
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
