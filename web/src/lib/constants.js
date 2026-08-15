// Lens display metadata — keyed by the `category` codes in Firestore (PRD §3.1).
export const LENSES = [
  { code: "AIML", label: "AI / ML", sources: "cs.LG · cs.AI" },
  { code: "NLP", label: "NLP", sources: "cs.CL" },
  { code: "CV", label: "Computer Vision", sources: "cs.CV" },
];

export const LENS_CODES = LENSES.map((l) => l.code);

// News-feed categories — keyed by the `feed_category` values the feed-mind
// pipeline writes to the `processed_articles` collection. `open-source` is the
// daily static "GitHub Trending" link (feed-mind now persists static links, so
// it appears here as a single, daily-refreshed entry).
export const NEWS_CATEGORIES = [
  { code: "academic", label: "Academic" },
  { code: "industry", label: "Industry" },
  { code: "cloud", label: "Cloud" },
  { code: "open-source", label: "Open Source" },
];

export const NEWS_CATEGORY_CODES = NEWS_CATEGORIES.map((c) => c.code);

// Rolling window (days) and hard read cap for the news feed.
export const NEWS_WINDOW_DAYS = 7;
export const NEWS_MAX_ARTICLES = 200;
