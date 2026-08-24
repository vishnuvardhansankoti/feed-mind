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
