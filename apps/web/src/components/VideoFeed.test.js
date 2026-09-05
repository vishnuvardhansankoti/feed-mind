// Videos "Latest" is the newest *ingest batch*, not a window measured back from
// now. Both earlier rules were clock-relative — newest calendar day, then a
// rolling 24h — and both made the tab shrink as the day passed: videos aged out
// one by one between refreshes with no new feed-mind run. Latest now keys off
// the newest `processed_at` in the data, so it only changes when feed-mind does.
// Archive still buckets by publish day.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import VideoFeed from "./VideoFeed.svelte";
import { VIDEO_BATCH_TOLERANCE_HOURS } from "../lib/constants.js";

// Pin the clock to 10:00 *local* time. Publish ages are expressed relative to
// it, and day bucketing is local, so a floating "now" would let the same
// fixture land on one or two calendar days depending on the hour of the run.
// `toFake: ["Date"]` freezes Date without touching setTimeout, so Svelte's
// flushing still works normally.
const NOW = new Date(2026, 7, 22, 10, 0, 0);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => vi.useRealTimers());

const hoursAgo = (h) => new Date(Date.now() - h * 3600 * 1000);

// `ingestedHoursAgo` defaults to `publishedHoursAgo` only where the two are
// irrelevant to the assertion; tests about batching always pass both, since
// separating ingest time from publish time is the whole point.
const video = (id, publishedHoursAgo, ingestedHoursAgo = publishedHoursAgo, overrides = {}) => ({
  video_id: id,
  url: `https://youtube.com/watch?v=${id}`,
  title: `Video ${id}`,
  channel: "Test Channel",
  thumbnail_url: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
  published_date: hoursAgo(publishedHoursAgo),
  processed_date: hoursAgo(ingestedHoursAgo),
  ...overrides,
});

// Newest published first, the order App hands in.
const feed = (...videos) =>
  [...videos].sort((a, b) => (b.published_date ?? 0) - (a.published_date ?? 0));

const titles = () =>
  screen.queryAllByRole("heading").map((h) => h.textContent.trim());

const clickArchive = async () => {
  await screen.getByRole("tab", { name: /Archive/ }).click();
};

describe("VideoFeed — Latest is the newest ingest batch", () => {
  it("keeps a whole batch together however old its videos are", () => {
    // One run at 1h ago picked up uploads spanning three days. Under either
    // clock-relative rule the older two fell out of Latest immediately; they
    // are the same batch and belong together.
    render(VideoFeed, {
      videos: feed(video("fresh", 2, 1), video("day-old", 26, 1), video("two-days-old", 50, 1)),
    });

    expect(titles()).toContain("Video fresh");
    expect(titles()).toContain("Video day-old");
    expect(titles()).toContain("Video two-days-old");
  });

  it("holds together a batch whose stamps differ by minutes", () => {
    // feed-mind stamps each doc with its own now, so a run is not one instant.
    render(VideoFeed, {
      videos: feed(video("a", 3, 1), video("b", 4, 1 + 5 / 60), video("c", 5, 1 + 9 / 60)),
    });
    expect(titles()).toHaveLength(3);
  });

  it("excludes the previous run from Latest", () => {
    render(VideoFeed, {
      videos: feed(
        video("today", 3, 1),
        video("yesterday", 28, 1 + VIDEO_BATCH_TOLERANCE_HOURS + 1),
      ),
    });

    expect(titles()).toContain("Video today");
    expect(titles()).not.toContain("Video yesterday");
  });

  it("shows the same videos as the day wears on — the actual bug", () => {
    // Same props, re-rendered at four points across the day. The count must not
    // move: nothing was ingested in between.
    const videos = feed(video("fresh", 2, 1), video("day-old", 26, 1), video("two-days-old", 50, 1));
    const counts = [];

    for (const hoursLater of [0, 6, 12, 23]) {
      vi.setSystemTime(new Date(NOW.getTime() + hoursLater * 3600 * 1000));
      const { unmount } = render(VideoFeed, { videos });
      counts.push(titles().length);
      unmount();
    }

    // Under the old rolling-24h rule this read [3, 2, 2, 1].
    expect(counts).toEqual([3, 3, 3, 3]);
  });

  it("still shows the last run in full when nothing has been ingested for days", () => {
    // Anchored to the data, so a stale batch stays whole instead of emptying.
    render(VideoFeed, { videos: feed(video("a", 74, 72), video("b", 80, 72)) });
    expect(titles()).toHaveLength(2);
  });

  it("shows no day header in Latest", () => {
    render(VideoFeed, { videos: feed(video("a", 2, 1), video("b", 20, 1)) });
    // Latest is one unlabelled group — a date heading would imply day bucketing.
    expect(document.querySelectorAll(".day-date")).toHaveLength(0);
  });
});

describe("VideoFeed — Archive still buckets by day", () => {
  it("shows videos the newest batch excludes", async () => {
    render(VideoFeed, {
      videos: feed(
        video("recent", 3, 1),
        video("stale", 28, 1 + VIDEO_BATCH_TOLERANCE_HOURS + 1),
      ),
    });
    await clickArchive();

    expect(titles()).toContain("Video recent");
    expect(titles()).toContain("Video stale");
  });

  it("labels each day group with a date", async () => {
    render(VideoFeed, { videos: feed(video("a", 2, 1), video("old", 50, 1)) });
    await clickArchive();

    // Two distinct publish days -> two date headers.
    const headers = document.querySelectorAll(".day-date");
    expect(headers.length).toBeGreaterThanOrEqual(2);
  });

  it("labels an unparseable publish date rather than throwing", async () => {
    // Invalid Date is truthy, so a truthiness guard would hand it to
    // Intl.DateTimeFormat and take the whole render down.
    const broken = video("broken", 1, 1, { published_date: new Date("nonsense") });
    render(VideoFeed, { videos: [video("ok", 2, 1), broken] });
    await clickArchive();

    expect(titles()).toContain("Video broken");
    expect(screen.getByText("—")).toBeVisible();
  });
});

describe("VideoFeed — empty states", () => {
  it("points at Archive when no video carries an ingest stamp", () => {
    // Pre-`processed_at` docs can be grouped by publish day but not by batch.
    render(VideoFeed, {
      videos: [video("legacy", 2, 2, { processed_date: null })],
    });

    expect(screen.getByText(/No videos carry an ingest timestamp/)).toBeVisible();
  });

  it("keeps those videos reachable in Archive", async () => {
    render(VideoFeed, {
      videos: [video("legacy", 2, 2, { processed_date: null })],
    });
    await clickArchive();

    expect(titles()).toContain("Video legacy");
  });

  it("reports no videos at all when the feed is empty", () => {
    render(VideoFeed, { videos: [] });
    expect(screen.getByText(/No new videos from your subscriptions/)).toBeVisible();
  });

  it("does not claim 'check Archive' when Archive is empty too", () => {
    render(VideoFeed, { videos: [] });
    expect(screen.queryByText(/No videos carry an ingest timestamp/)).toBeNull();
  });
});
