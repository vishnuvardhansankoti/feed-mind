// @vitest-environment node
import { describe, it, expect } from "vitest";
import {
  LENSES,
  LENS_CODES,
  NEWS_CATEGORIES,
  NEWS_CATEGORY_CODES,
  STATIC_NEWS_LINKS,
  NEWS_WINDOW_DAYS,
  NEWS_MAX_ARTICLES,
  VIDEO_WINDOW_DAYS,
  VIDEO_MAX_ITEMS,
  VIDEO_BATCH_TOLERANCE_HOURS,
  STORY_CATEGORIES,
  STORY_CATEGORY_CODES,
  BUSINESS_STORY_CATEGORIES,
  NEWS_COUNTRIES,
  NEWS_COUNTRY_CODES,
  KNOWLEDGE_CATEGORIES,
  KNOWLEDGE_CATEGORY_CODES,
  KNOWLEDGE_WINDOW_DAYS,
  KNOWLEDGE_MAX_ARTICLES,
} from "./constants.js";

describe("lens metadata", () => {
  it("defines the three lenses in Firestore-category order", () => {
    expect(LENS_CODES).toEqual(["AIML", "NLP", "CV"]);
  });

  it("every lens carries a code, label, and sources string", () => {
    expect(LENSES).toHaveLength(3);
    for (const lens of LENSES) {
      expect(lens.code).toBeTruthy();
      expect(lens.label).toBeTruthy();
      expect(lens.sources).toBeTruthy();
    }
  });

  it("LENS_CODES is derived from LENSES", () => {
    expect(LENS_CODES).toEqual(LENSES.map((l) => l.code));
  });
});

describe("news categories", () => {
  it("matches the feed_category values feed-mind writes", () => {
    expect(NEWS_CATEGORY_CODES).toEqual([
      "academic",
      "industry",
      "cloud",
      "open-source",
    ]);
  });

  it("keeps each code in the exact separator form the pipeline writes", () => {
    // feed-mind's RSS_FEEDS uses a hyphen for open-source, and the reader
    // matches on `feed_category` with ===. "Tidying" it here silently empties
    // that tab, with no error anywhere.
    expect(NEWS_CATEGORY_CODES).toContain("open-source");
    expect(NEWS_CATEGORY_CODES).not.toContain("open_source");
  });

  it("no longer carries top_stories — that pipeline moved to STORY_CATEGORIES", () => {
    expect(NEWS_CATEGORY_CODES).not.toContain("top_stories");
  });

  it("opens on Academic, so a new category cannot hijack the landing tab", () => {
    // NewsFeed seeds its selected tab from NEWS_CATEGORIES[0].
    expect(NEWS_CATEGORIES[0].code).toBe("academic");
  });

  it("gives every category a distinct code and label", () => {
    const codes = NEWS_CATEGORIES.map((c) => c.code);
    const labels = NEWS_CATEGORIES.map((c) => c.label);
    expect(new Set(codes).size).toBe(codes.length);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("NEWS_CATEGORY_CODES is derived from NEWS_CATEGORIES", () => {
    expect(NEWS_CATEGORY_CODES).toEqual(NEWS_CATEGORIES.map((c) => c.code));
  });

  it("every category carries a code and a tab label", () => {
    for (const c of NEWS_CATEGORIES) {
      expect(c.code).toBeTruthy();
      expect(c.label).toBeTruthy();
    }
  });
});

describe("story categories", () => {
  it("matches services/news-curator's coarse_category values", () => {
    // Byte-for-byte contract with news_curator/anchors.py::COARSE_ANCHORS —
    // the reader matches with ===, same as NEWS_CATEGORY_CODES.
    expect(STORY_CATEGORY_CODES).toEqual([
      "politics",
      "global",
      "business",
      "sports",
      "culture",
    ]);
  });

  it("opens on Politics, so a new category cannot hijack the landing tab", () => {
    // StoriesFeed seeds its selected tab from STORY_CATEGORIES[0].
    expect(STORY_CATEGORIES[0].code).toBe("politics");
  });

  it("gives every category a distinct code and label", () => {
    const codes = STORY_CATEGORIES.map((c) => c.code);
    const labels = STORY_CATEGORIES.map((c) => c.label);
    expect(new Set(codes).size).toBe(codes.length);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("STORY_CATEGORY_CODES is derived from STORY_CATEGORIES", () => {
    expect(STORY_CATEGORY_CODES).toEqual(STORY_CATEGORIES.map((c) => c.code));
  });

  it("has no overlap with NEWS_CATEGORY_CODES", () => {
    // Two independent taxonomies on two independent collections — a shared
    // code would not break anything today, but would be a trap for a future
    // `===` filter written against the wrong constant.
    for (const code of STORY_CATEGORY_CODES) {
      expect(NEWS_CATEGORY_CODES).not.toContain(code);
    }
  });
});

describe("knowledge categories", () => {
  it("matches services/ingest/knowledge_bytes.yaml's category values", () => {
    expect(KNOWLEDGE_CATEGORY_CODES).toEqual(["aiml", "dsa"]);
  });

  it("opens on AI/ML, so a new category cannot hijack the landing tab", () => {
    // KnowledgeFeed seeds its selected tab from KNOWLEDGE_CATEGORIES[0].
    expect(KNOWLEDGE_CATEGORIES[0].code).toBe("aiml");
  });

  it("gives every category a distinct code and label", () => {
    const codes = KNOWLEDGE_CATEGORIES.map((c) => c.code);
    const labels = KNOWLEDGE_CATEGORIES.map((c) => c.label);
    expect(new Set(codes).size).toBe(codes.length);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("KNOWLEDGE_CATEGORY_CODES is derived from KNOWLEDGE_CATEGORIES", () => {
    expect(KNOWLEDGE_CATEGORY_CODES).toEqual(KNOWLEDGE_CATEGORIES.map((c) => c.code));
  });

  it("shares processed_articles but has no overlap with NEWS_CATEGORY_CODES", () => {
    // Same collection as News (unlike Stories, which is a separate collection
    // entirely), so an overlapping code here really would cross-contaminate
    // both tabs' Firestore queries — not just a future-proofing exercise.
    for (const code of KNOWLEDGE_CATEGORY_CODES) {
      expect(NEWS_CATEGORY_CODES).not.toContain(code);
    }
  });

  it("has no overlap with STORY_CATEGORY_CODES", () => {
    for (const code of KNOWLEDGE_CATEGORY_CODES) {
      expect(STORY_CATEGORY_CODES).not.toContain(code);
    }
  });

  it("defines a window and a read cap", () => {
    expect(KNOWLEDGE_WINDOW_DAYS).toBeGreaterThan(0);
    expect(KNOWLEDGE_MAX_ARTICLES).toBeGreaterThan(0);
  });
});

describe("BUSINESS_STORY_CATEGORIES", () => {
  it("labels every business sub-category services/news-curator can assign", () => {
    // design doc §4.3's five codes.
    expect(Object.keys(BUSINESS_STORY_CATEGORIES)).toEqual([
      "markets",
      "economy",
      "companies",
      "portfolio",
      "personal_finance",
    ]);
  });
});

describe("news countries", () => {
  it("matches the country values services/news-curator writes", () => {
    expect(NEWS_COUNTRY_CODES).toEqual(["IN", "US"]);
  });

  it("opens on India, so a new country cannot hijack the landing view", () => {
    // StoriesFeed seeds its selected country from NEWS_COUNTRIES[0].
    expect(NEWS_COUNTRIES[0].code).toBe("IN");
  });

  it("gives every country a distinct code and label", () => {
    const codes = NEWS_COUNTRIES.map((c) => c.code);
    const labels = NEWS_COUNTRIES.map((c) => c.label);
    expect(new Set(codes).size).toBe(codes.length);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("NEWS_COUNTRY_CODES is derived from NEWS_COUNTRIES", () => {
    expect(NEWS_COUNTRY_CODES).toEqual(NEWS_COUNTRIES.map((c) => c.code));
  });
});

describe("pinned static news links", () => {
  it("declares at least one link, so the open-source tab is never empty", () => {
    // open-source has no RSS source; these links are its entire content.
    expect(STATIC_NEWS_LINKS.length).toBeGreaterThan(0);
  });

  it("uses a static_ id prefix, which feed-mind skips when persisting", () => {
    // The writer deliberately never stores these; a drifting prefix here would
    // let the same link be both pinned and persisted under different ids.
    for (const link of STATIC_NEWS_LINKS) {
      expect(link.article_id.startsWith("static_")).toBe(true);
    }
  });

  it("files every link under a real category tab", () => {
    for (const link of STATIC_NEWS_LINKS) {
      expect(NEWS_CATEGORY_CODES).toContain(link.feed_category);
    }
  });

  it("carries the fields ArticleCard renders", () => {
    for (const link of STATIC_NEWS_LINKS) {
      expect(link.url).toMatch(/^https:\/\//);
      expect(link.title).toBeTruthy();
      expect(link.feed_source).toBeTruthy();
    }
  });

  it("carries no audio or ai_summary — there is no pipeline behind them", () => {
    for (const link of STATIC_NEWS_LINKS) {
      expect(link.audio_url ?? "").toBe("");
      expect(link.ai_summary ?? "").toBe("");
    }
  });

  it("does not hard-code a timestamp — getNews stamps a fresh one per load", () => {
    // A baked-in processed_at would age out of the rolling window and the link
    // would silently stop appearing.
    for (const link of STATIC_NEWS_LINKS) {
      expect(link.processed_at).toBeUndefined();
      expect(link.published_at).toBeUndefined();
    }
  });
});

describe("window and cap constants", () => {
  it("keeps the news window inside the read cap's intent", () => {
    expect(NEWS_WINDOW_DAYS).toBeGreaterThan(0);
    expect(NEWS_MAX_ARTICLES).toBeGreaterThan(0);
  });

  it("keeps the batch tolerance inside the Archive window", () => {
    // The tolerance defines "one ingest batch". Wider than the Archive window
    // and Latest could span every batch the reader holds, making the two tabs
    // identical.
    expect(VIDEO_BATCH_TOLERANCE_HOURS).toBeGreaterThan(0);
    expect(VIDEO_BATCH_TOLERANCE_HOURS).toBeLessThan(VIDEO_WINDOW_DAYS * 24);
    expect(VIDEO_MAX_ITEMS).toBeGreaterThan(0);
  });
});
