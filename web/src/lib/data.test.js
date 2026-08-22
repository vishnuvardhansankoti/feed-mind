// Exercises the default "mock" data source (VITE_DATA_SOURCE unset) by stubbing
// global fetch, so no fixtures on disk and no Firestore are required.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { getLatest, getArchive, getStatus, getNews } from "./data.js";

const MANIFEST = {
  runs: {
    AIML: ["2026-08-13_AIML"],
    NLP: ["2026-08-13_NLP"],
    CV: ["2026-08-13_CV"],
  },
  latest_status: "2026-08-13",
};

const runDoc = (code) => ({
  id: `2026-08-13_${code}`,
  category: code,
  run_date: "2026-08-13T00:00:00Z",
  papers: [
    { rank: 1, title: `${code} paper`, arxiv_id: "1", url: "u", score: 0.5, summary: null },
  ],
});

const STATUS = {
  id: "2026-08-13",
  run_date: "2026-08-13T00:00:00Z",
  categories: { AIML: { status: "ok", paper_count: 1 } },
};

beforeEach(() => {
  global.fetch = vi.fn(async (url) => {
    const u = String(url);
    let body;
    if (u.endsWith("manifest.json")) body = MANIFEST;
    else if (u.includes("/run_status/")) body = STATUS;
    else if (u.includes("/runs/")) body = runDoc(u.match(/_([A-Z]+)\.json$/)[1]);
    else throw new Error(`unexpected fetch: ${u}`);
    return { ok: true, json: async () => body };
  });
});

afterEach(() => vi.restoreAllMocks());

describe("mock data source", () => {
  it("getLatest returns one run per lens", async () => {
    const latest = await getLatest();
    expect(Object.keys(latest).sort()).toEqual(["AIML", "CV", "NLP"]);
    expect(latest.AIML.category).toBe("AIML");
    expect(latest.NLP.papers[0].title).toBe("NLP paper");
  });

  it("getArchive returns arrays and normalizes run_date to a Date", async () => {
    const archive = await getArchive();
    expect(Array.isArray(archive.CV)).toBe(true);
    expect(archive.CV[0].run_date).toBeInstanceOf(Date);
    expect(archive.CV[0].run_date.getUTCFullYear()).toBe(2026);
  });

  it("getStatus returns the latest run_status doc", async () => {
    const status = await getStatus();
    expect(status.categories.AIML.status).toBe("ok");
  });

  it("getStatus returns null when the manifest fetch fails", async () => {
    global.fetch = vi.fn(async () => ({ ok: false }));
    expect(await getStatus()).toBeNull();
  });
});

describe("news audio + ai_summary normalization", () => {
  const news = [
    {
      article_id: "a-https",
      feed_category: "cloud",
      processed_at: "2026-08-15T07:00:00+00:00",
      ai_summary: "Long form summary.",
      audio_url: "https://storage.googleapis.com/bucket/2026-08-15/a-https.mp3",
    },
    {
      article_id: "b-gs",
      feed_category: "cloud",
      processed_at: "2026-08-14T07:00:00+00:00",
      audio_url: "gs://feed-mind-audio/2026-08-14/b gs.mp3",
    },
    {
      article_id: "c-legacy",
      feed_category: "cloud",
      processed_at: "2026-08-13T07:00:00+00:00",
    },
    {
      article_id: "d-junk",
      feed_category: "cloud",
      processed_at: "2026-08-12T07:00:00+00:00",
      audio_url: "not-a-url",
    },
  ];

  beforeEach(() => {
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => news }));
  });

  const byId = (articles, id) => articles.find((a) => a.article_id === id);

  it("passes an already-public https audio url through untouched", async () => {
    const { articles } = await getNews();
    expect(byId(articles, "a-https").audio_url).toBe(
      "https://storage.googleapis.com/bucket/2026-08-15/a-https.mp3",
    );
    expect(byId(articles, "a-https").ai_summary).toBe("Long form summary.");
  });

  it("rewrites a gs:// uri to its public https form, encoding the object path", async () => {
    const { articles } = await getNews();
    expect(byId(articles, "b-gs").audio_url).toBe(
      "https://storage.googleapis.com/feed-mind-audio/2026-08-14/b%20gs.mp3",
    );
  });

  it("degrades to empty strings on docs written before the fields existed", async () => {
    const { articles } = await getNews();
    expect(byId(articles, "c-legacy").audio_url).toBe("");
    expect(byId(articles, "c-legacy").ai_summary).toBe("");
  });

  it("drops an unrecognized audio_url rather than rendering a dead player", async () => {
    const { articles } = await getNews();
    expect(byId(articles, "d-junk").audio_url).toBe("");
  });

  it("leaves the pinned open-source link without audio", async () => {
    const { articles } = await getNews();
    const pinned = byId(articles, "static_github_trending");
    expect(pinned).toBeDefined();
    expect(pinned.audio_url).toBe("");
    expect(pinned.ai_summary).toBe("");
  });
});
