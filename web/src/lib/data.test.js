// Exercises the default "mock" data source (VITE_DATA_SOURCE unset) by stubbing
// global fetch, so no fixtures on disk and no Firestore are required.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { getLatest, getArchive, getStatus } from "./data.js";

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
