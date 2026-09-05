// @vitest-environment node
// The Videos "Latest" rule. The bug these pin down: Latest used to be a window
// measured back from Date.now(), so the same data yielded fewer videos as the
// day passed. Every test here therefore checks stability against the *clock*,
// not just correctness at one instant.
import { describe, it, expect, afterEach, vi } from "vitest";
import { latestBatch } from "./videos.js";
import { VIDEO_BATCH_TOLERANCE_HOURS } from "./constants.js";

const HOUR = 3_600_000;

// A video ingested `hoursAgo` before `now`, published whenever.
const vid = (id, processedHoursAgo, now = Date.now()) => ({
  video_id: id,
  processed_date: new Date(now - processedHoursAgo * HOUR),
  published_date: new Date(now - processedHoursAgo * HOUR - HOUR),
});

afterEach(() => vi.useRealTimers());

describe("latestBatch", () => {
  it("returns every video sharing the newest ingest stamp", () => {
    const now = Date.now();
    const batch = [vid("a", 2, now), vid("b", 2, now), vid("c", 2, now)];
    expect(latestBatch(batch).map((v) => v.video_id)).toEqual(["a", "b", "c"]);
  });

  it("holds together a batch whose stamps differ by minutes", () => {
    // feed-mind stamps each doc with its own now, so one run is not one instant.
    const now = Date.now();
    const spread = [
      { video_id: "first", processed_date: new Date(now) },
      { video_id: "mid", processed_date: new Date(now - 4 * 60_000) },
      { video_id: "last", processed_date: new Date(now - 9 * 60_000) },
    ];
    expect(latestBatch(spread)).toHaveLength(3);
  });

  it("excludes the previous day's batch", () => {
    const now = Date.now();
    const videos = [
      vid("today-1", 1, now),
      vid("today-2", 1, now),
      vid("yesterday-1", 25, now),
      vid("yesterday-2", 26, now),
    ];
    expect(latestBatch(videos).map((v) => v.video_id)).toEqual([
      "today-1",
      "today-2",
    ]);
  });

  it("keeps the same set as the day wears on — the actual bug", () => {
    // One batch ingested at a fixed instant; videos published across 3 days.
    const ingest = new Date("2026-08-22T07:00:00Z").getTime();
    const batch = [
      { video_id: "fresh", processed_date: new Date(ingest), published_date: new Date(ingest - 2 * HOUR) },
      { video_id: "day-old", processed_date: new Date(ingest + 60_000), published_date: new Date(ingest - 26 * HOUR) },
      { video_id: "two-days-old", processed_date: new Date(ingest + 120_000), published_date: new Date(ingest - 50 * HOUR) },
    ];

    // Walk the clock forward through the day and re-evaluate each time.
    const counts = [];
    for (const hoursLater of [0, 1, 6, 12, 18, 23]) {
      vi.useFakeTimers();
      vi.setSystemTime(new Date(ingest + hoursLater * HOUR));
      counts.push(latestBatch(batch).length);
      vi.useRealTimers();
    }
    // Stable all day. Under the old published_at-vs-now rule this read
    // [3, 3, 2, 2, 1, 1] — shrinking without any new run.
    expect(counts).toEqual([3, 3, 3, 3, 3, 3]);
  });

  it("is anchored to the data, so an old batch stays whole", () => {
    // Nothing has been ingested for a week: Latest still shows that last run in
    // full rather than going empty.
    const stale = new Date(Date.now() - 7 * 24 * HOUR).getTime();
    const batch = [
      { video_id: "a", processed_date: new Date(stale) },
      { video_id: "b", processed_date: new Date(stale + 30_000) },
    ];
    expect(latestBatch(batch)).toHaveLength(2);
  });

  it("splits two runs separated by more than the tolerance", () => {
    const now = Date.now();
    const gap = VIDEO_BATCH_TOLERANCE_HOURS + 1;
    const videos = [vid("new", 0, now), vid("old", gap, now)];
    expect(latestBatch(videos).map((v) => v.video_id)).toEqual(["new"]);
  });

  it("keeps two runs together when they fall inside the tolerance", () => {
    const now = Date.now();
    const gap = VIDEO_BATCH_TOLERANCE_HOURS - 1;
    const videos = [vid("new", 0, now), vid("recent", gap, now)];
    expect(latestBatch(videos)).toHaveLength(2);
  });

  it("ignores videos with a missing or unparseable processed_date", () => {
    const now = Date.now();
    const videos = [
      vid("good", 1, now),
      { video_id: "no-stamp" },
      { video_id: "null-stamp", processed_date: null },
      { video_id: "invalid-stamp", processed_date: new Date("nonsense") },
    ];
    expect(latestBatch(videos).map((v) => v.video_id)).toEqual(["good"]);
  });

  it("returns an empty list for no videos, or none with stamps", () => {
    expect(latestBatch([])).toEqual([]);
    expect(latestBatch()).toEqual([]);
    expect(latestBatch([{ video_id: "x" }])).toEqual([]);
  });

  it("preserves input order rather than re-sorting", () => {
    // The caller has already sorted by published_at desc; Latest must not
    // reshuffle into ingest order.
    const now = Date.now();
    const videos = [vid("c", 1, now), vid("a", 1, now), vid("b", 1, now)];
    expect(latestBatch(videos).map((v) => v.video_id)).toEqual(["c", "a", "b"]);
  });

  it("does not mutate its input", () => {
    const now = Date.now();
    const videos = [vid("a", 1, now), vid("b", 30, now)];
    latestBatch(videos);
    expect(videos.map((v) => v.video_id)).toEqual(["a", "b"]);
  });
});
