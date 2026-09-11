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
// byte-for-byte — including the hyphen in `open-source`, a deliberate mirror
// of the pipeline, not a typo.
//
// `top_stories` (the one Times of India feed) was removed from here when the
// Indian-news pipeline moved to services/india-news-ingest +
// services/news-curator — see STORY_CATEGORIES below and the root CLAUDE.md.
// Existing `feed_category=top_stories` documents live on under their 90-day
// TTL; they simply have no tab to appear in anymore.
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

// The subset of NEWS_CATEGORY_CODES that actually have RSS-backed Firestore
// docs — `open-source` is pinned client-side only (see STATIC_NEWS_LINKS) and
// never written to `processed_articles`. getNews()'s Firestore query filters
// on this list so the "most recent N" window can't be flooded out by
// services/india-news-ingest and services/us-news-ingest, which write into
// this same collection with `feed_category` values ("general"/"business")
// outside this taxonomy entirely — see the root CLAUDE.md's category-codes
// warning.
export const NEWS_CATEGORY_RSS_CODES = NEWS_CATEGORY_CODES.filter(
  (code) => code !== "open-source",
);

// Rolling window (days) and hard read cap for the news feed.
export const NEWS_WINDOW_DAYS = 7;
export const NEWS_MAX_ARTICLES = 200;

// Stories tab: curated Indian news, keyed by the `coarse_category` values
// services/news-curator writes to the `stories` collection
// (docs/feed-mind/news-curator-design.md §4.2). Deliberately no `tech` or
// `top_stories` code — the curator's taxonomy is its own, not NEWS_CATEGORIES'.
//
// Each `code` must match `services/news-curator/src/news_curator/anchors.py`'s
// COARSE_ANCHORS keys byte-for-byte — same `===`-matching contract as
// NEWS_CATEGORIES, see the root CLAUDE.md.
export const STORY_CATEGORIES = [
  { code: "politics", label: "Politics" },
  { code: "global", label: "Global" },
  { code: "business", label: "Business" },
  { code: "sports", label: "Sports" },
  { code: "culture", label: "Culture" },
];

export const STORY_CATEGORY_CODES = STORY_CATEGORIES.map((c) => c.code);

// Countries the Stories/News tab covers, keyed by the `country` field
// services/india-news-ingest and services/us-news-ingest stamp on
// processed_articles, which services/news-curator carries onto `stories`.
// Same 5 STORY_CATEGORIES apply to both — this is a second, independent axis
// (which country), not a second taxonomy.
//
// Order is toggle order; the first entry is selected by default. India is
// first because it predates the US pipeline — see the root CLAUDE.md.
export const NEWS_COUNTRIES = [
  { code: "IN", label: "India" },
  { code: "US", label: "US" },
];

export const NEWS_COUNTRY_CODES = NEWS_COUNTRIES.map((c) => c.code);

// Detailed business sub-categories (design doc §4.3), for the badge on a
// business story that has one. Purely a label lookup — eligibility is decided
// entirely server-side, by services/news-curator.
export const BUSINESS_STORY_CATEGORIES = {
  markets: "Markets",
  economy: "Economy",
  companies: "Companies",
  portfolio: "Portfolio",
  personal_finance: "Personal Finance",
};

// Rows fetched per category before slicing to the newest run_date client-side
// (data.js::latestRunOnly) — generous enough to cover a busy day's full
// cluster count for one category, not just its top-ranked canonical picks.
// See data.js for why "the newest run" can't be a server-side equality filter.
export const STORY_MAX_PER_CATEGORY = 50;

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
