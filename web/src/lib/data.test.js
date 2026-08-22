// @vitest-environment node
// Exercises the default "mock" data source (VITE_DATA_SOURCE unset) by stubbing
// global fetch, so no fixtures on disk and no Firestore are required.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { getLatest, getArchive, getStatus, getNews, getVideos } from "./data.js";
import { STATIC_NEWS_LINKS, VIDEO_MAX_ITEMS } from "./constants.js";

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

  it("getLatest yields null for a lens the manifest does not list", async () => {
    global.fetch = vi.fn(async (url) => ({
      ok: true,
      json: async () =>
        String(url).endsWith("manifest.json")
          ? { runs: { AIML: ["2026-08-13_AIML"] }, latest_status: "2026-08-13" }
          : runDoc("AIML"),
    }));
    const latest = await getLatest();
    expect(latest.AIML).not.toBeNull();
    expect(latest.NLP).toBeNull();
    expect(latest.CV).toBeNull();
  });
});

describe("run_date coercion", () => {
  // Firestore hands back a Timestamp, the fixtures hand back an ISO string, and
  // a re-normalized doc hands back a Date. All three must land as a Date so the
  // card's date formatting has one type to deal with.
  const withRunDate = (value) => ({
    ok: true,
    json: async () => ({
      id: "2026-08-13_AIML",
      category: "AIML",
      run_date: value,
      papers: [],
    }),
  });

  const latestAIML = async (value) => {
    global.fetch = vi.fn(async (url) =>
      String(url).endsWith("manifest.json")
        ? { ok: true, json: async () => MANIFEST }
        : withRunDate(value),
    );
    return (await getLatest()).AIML;
  };

  it("converts a Firestore Timestamp via its toDate()", async () => {
    const stamp = { toDate: () => new Date("2026-08-13T00:00:00Z") };
    const run = await latestAIML(stamp);
    expect(run.run_date).toBeInstanceOf(Date);
    expect(run.run_date.toISOString()).toBe("2026-08-13T00:00:00.000Z");
  });

  it("passes an existing Date through unchanged", async () => {
    const d = new Date("2026-08-13T00:00:00Z");
    const run = await latestAIML(d);
    expect(run.run_date).toBe(d);
  });

  it("leaves a missing run_date null rather than an Invalid Date", async () => {
    const run = await latestAIML(null);
    expect(run.run_date).toBeNull();
  });

  it("tolerates a run doc with no papers array", async () => {
    global.fetch = vi.fn(async (url) =>
      String(url).endsWith("manifest.json")
        ? { ok: true, json: async () => MANIFEST }
        : { ok: true, json: async () => ({ id: "x", category: "AIML", run_date: null }) },
    );
    expect((await getLatest()).AIML.papers).toEqual([]);
  });
});

describe("paper audio + ai_summary normalization", () => {
  // Papers carry the pair per-paper inside the run doc. Newer runs have it on
  // every paper; runs written before the feature have it on none.
  const mixedRun = {
    id: "2026-08-13_AIML",
    category: "AIML",
    run_date: "2026-08-13T00:00:00Z",
    papers: [
      {
        rank: 1, title: "with audio", arxiv_id: "1", url: "u", score: 0.5,
        ai_summary: "Long form paper summary.",
        audio_url: "https://storage.googleapis.com/bucket/2026-08-13/AIML/1.mp3",
      },
      {
        rank: 2, title: "gs uri", arxiv_id: "2", url: "u", score: 0.4,
        audio_url: "gs://feed-mind-audio-summaries/research-papers/2 a.mp3",
      },
      { rank: 3, title: "legacy", arxiv_id: "3", url: "u", score: 0.3 },
      {
        rank: 4, title: "junk audio", arxiv_id: "4", url: "u", score: 0.2,
        audio_url: "not-a-url",
      },
    ],
  };

  beforeEach(() => {
    global.fetch = vi.fn(async (url) => {
      const u = String(url);
      const body = u.endsWith("manifest.json") ? MANIFEST : mixedRun;
      return { ok: true, json: async () => body };
    });
  });

  const rank = (papers, n) => papers.find((p) => p.rank === n);

  it("normalizes papers on the Latest path, not just Archive", async () => {
    const latest = await getLatest();
    const papers = latest.AIML.papers;
    expect(rank(papers, 1).ai_summary).toBe("Long form paper summary.");
    expect(rank(papers, 1).audio_url).toBe(
      "https://storage.googleapis.com/bucket/2026-08-13/AIML/1.mp3",
    );
  });

  it("rewrites a gs:// paper audio uri to its public https form", async () => {
    const { AIML } = await getArchive();
    expect(rank(AIML[0].papers, 2).audio_url).toBe(
      "https://storage.googleapis.com/feed-mind-audio-summaries/research-papers/2%20a.mp3",
    );
  });

  it("degrades to empty strings on runs written before the fields existed", async () => {
    const { AIML } = await getArchive();
    const legacy = rank(AIML[0].papers, 3);
    expect(legacy.audio_url).toBe("");
    expect(legacy.ai_summary).toBe("");
  });

  it("drops an unrecognized paper audio_url rather than rendering a dead player", async () => {
    const { AIML } = await getArchive();
    expect(rank(AIML[0].papers, 4).audio_url).toBe("");
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

  it("defaults a missing summary to an empty string", async () => {
    const { articles } = await getNews();
    expect(byId(articles, "c-legacy").summary).toBe("");
  });

  it("exposes processed_at / published_at as Dates for display", async () => {
    const { articles } = await getNews();
    const a = byId(articles, "a-https");
    expect(a.processed_date).toBeInstanceOf(Date);
    expect(a.processed_date.toISOString()).toBe("2026-08-15T07:00:00.000Z");
    // published_at is absent on these docs — must be null, not Invalid Date.
    expect(a.published_date).toBeNull();
  });
});

describe("audio url forms that must not produce a player", () => {
  const newsWith = (audio_url) => [
    { article_id: "x", feed_category: "cloud", processed_at: "2026-08-15T07:00:00+00:00", audio_url },
  ];
  const urlFor = async (audio_url) => {
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => newsWith(audio_url) }));
    const { articles } = await getNews();
    return articles.find((a) => a.article_id === "x").audio_url;
  };

  it("rejects a gs:// uri naming a bucket but no object", async () => {
    expect(await urlFor("gs://bucket-only")).toBe("");
    expect(await urlFor("gs://bucket-only/")).toBe("");
  });

  it("rejects a gs:// uri with no bucket", async () => {
    expect(await urlFor("gs:///object.mp3")).toBe("");
  });

  it("rejects non-string values written by a buggy producer", async () => {
    expect(await urlFor(null)).toBe("");
    expect(await urlFor(42)).toBe("");
    expect(await urlFor({ bucket: "b", object: "o" })).toBe("");
  });

  it("rejects a scheme that is neither http(s) nor gs", async () => {
    // javascript: and data: would both be live URLs if handed to new Audio().
    expect(await urlFor("javascript:alert(1)")).toBe("");
    expect(await urlFor("data:audio/wav;base64,AAAA")).toBe("");
    expect(await urlFor("//storage.googleapis.com/b/o.mp3")).toBe("");
  });

  it("encodes each object path segment but keeps the separators", async () => {
    expect(await urlFor("gs://b/a dir/sub dir/file name.mp3")).toBe(
      "https://storage.googleapis.com/b/a%20dir/sub%20dir/file%20name.mp3",
    );
  });
});

describe("pinned static news links", () => {
  const pinnedId = STATIC_NEWS_LINKS[0].article_id;

  it("returns an empty list when the news fixture is missing", async () => {
    global.fetch = vi.fn(async () => ({ ok: false }));
    expect(await getNews()).toEqual({ articles: [] });
  });

  it("dedupes a pipeline-written doc that collides with a pinned id", async () => {
    const collide = [
      {
        article_id: pinnedId,
        title: "Stale copy written by the pipeline",
        feed_category: "open-source",
        processed_at: "2020-01-01T00:00:00+00:00",
      },
    ];
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => collide }));
    const { articles } = await getNews();
    const hits = articles.filter((a) => a.article_id === pinnedId);
    expect(hits).toHaveLength(1);
    // The reader's copy wins, not the persisted one.
    expect(hits[0].title).toBe(STATIC_NEWS_LINKS[0].title);
  });

  it("stamps pinned links with a fresh now so they sort into today's Latest", async () => {
    const older = [
      {
        article_id: "yesterday",
        feed_category: "cloud",
        processed_at: new Date(Date.now() - 86_400_000).toISOString(),
      },
    ];
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => older }));
    const { articles } = await getNews();
    expect(articles[0].article_id).toBe(pinnedId);
    expect(Date.now() - articles[0].processed_date.getTime()).toBeLessThan(60_000);
  });

  it("sorts the merged list newest-first by processed_at", async () => {
    const scrambled = [
      { article_id: "mid", feed_category: "cloud", processed_at: "2026-08-14T00:00:00+00:00" },
      { article_id: "old", feed_category: "cloud", processed_at: "2026-08-10T00:00:00+00:00" },
      { article_id: "new", feed_category: "cloud", processed_at: "2026-08-16T00:00:00+00:00" },
    ];
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => scrambled }));
    const { articles } = await getNews();
    // The pinned link carries "now", which is newer than every fixture date.
    expect(articles.map((a) => a.article_id)).toEqual([pinnedId, "new", "mid", "old"]);
  });
});

describe("videos", () => {
  const video = (id, published_at) => ({
    video_id: id,
    url: `https://www.youtube.com/watch?v=${id}`,
    title: `video ${id}`,
    channel: "some channel",
    published_at,
    processed_at: "2026-08-16T15:00:00+00:00",
  });

  it("returns an empty list when the videos fixture is missing", async () => {
    global.fetch = vi.fn(async () => ({ ok: false }));
    expect(await getVideos()).toEqual({ videos: [] });
  });

  it("sorts newest-first by published_at regardless of fixture order", async () => {
    const docs = [
      video("mid", "2026-08-15T00:00:00+00:00"),
      video("old", "2026-08-14T00:00:00+00:00"),
      video("new", "2026-08-16T00:00:00+00:00"),
    ];
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => docs }));
    const { videos } = await getVideos();
    expect(videos.map((v) => v.video_id)).toEqual(["new", "mid", "old"]);
  });

  it("exposes published_at / processed_at as Dates", async () => {
    global.fetch = vi.fn(async () => ({
      ok: true,
      json: async () => [video("a", "2026-08-16T14:05:00+00:00")],
    }));
    const { videos } = await getVideos();
    expect(videos[0].published_date).toBeInstanceOf(Date);
    expect(videos[0].published_date.toISOString()).toBe("2026-08-16T14:05:00.000Z");
    expect(videos[0].processed_date).toBeInstanceOf(Date);
  });

  it("caps the list at VIDEO_MAX_ITEMS", async () => {
    const many = Array.from({ length: VIDEO_MAX_ITEMS + 10 }, (_, i) =>
      video(`v${i}`, new Date(Date.UTC(2026, 7, 16, 0, 0, i)).toISOString()),
    );
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => many }));
    const { videos } = await getVideos();
    expect(videos).toHaveLength(VIDEO_MAX_ITEMS);
  });

  it("does not mutate the fetched array while sorting", async () => {
    const docs = [
      video("a", "2026-08-14T00:00:00+00:00"),
      video("b", "2026-08-16T00:00:00+00:00"),
    ];
    global.fetch = vi.fn(async () => ({ ok: true, json: async () => docs }));
    await getVideos();
    expect(docs.map((v) => v.video_id)).toEqual(["a", "b"]);
  });
});
