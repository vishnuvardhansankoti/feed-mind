// Videos "Latest" used to be the newest *calendar-day* bucket, which meant a
// video published yesterday evening was never in Latest no matter how recently
// it was ingested — feed-mind runs once a day, so most of a day's uploads are
// already "yesterday" by the time they land. Latest is now a rolling
// VIDEO_LATEST_HOURS window; Archive still buckets by day.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import VideoFeed from "./VideoFeed.svelte";
import { VIDEO_LATEST_HOURS } from "../lib/constants.js";

// Pin the clock to 10:00 *local* time. The whole point of the change is how
// the window interacts with local midnight, so a floating "now" would make
// these tests pass or fail depending on the hour they happen to run: at 10:00 a
// 20h-old video is yesterday, at 21:00 it is today. `toFake: ["Date"]` freezes
// Date without touching setTimeout, so Svelte's flushing still works normally.
const NOW = new Date(2026, 7, 22, 10, 0, 0);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => vi.useRealTimers());

const hoursAgo = (h) => new Date(Date.now() - h * 3600 * 1000);

const video = (id, hours, overrides = {}) => ({
  video_id: id,
  url: `https://youtube.com/watch?v=${id}`,
  title: `Video ${id}`,
  channel: "Test Channel",
  thumbnail_url: `https://i.ytimg.com/vi/${id}/hqdefault.jpg`,
  published_date: hoursAgo(hours),
  processed_date: hoursAgo(hours),
  ...overrides,
});

// Newest first, the order App hands in.
const feed = (...videos) => [...videos].sort((a, b) => b.published_date - a.published_date);

const titles = () =>
  screen.queryAllByRole("heading").map((h) => h.textContent.trim());

const clickArchive = async () => {
  await screen.getByRole("tab", { name: /Archive/ }).click();
};

describe("VideoFeed — Latest is a rolling window", () => {
  it("keeps a video from earlier today and one from last night together", () => {
    // The exact case that used to break. At the pinned 10:00, 2h ago is today
    // and 20h ago is yesterday afternoon, so the calendar-day version showed
    // only the 2h one while the 20h one fell straight into Archive.
    render(VideoFeed, { videos: feed(video("a", 2), video("b", 20)) });

    expect(titles()).toContain("Video a");
    expect(titles()).toContain("Video b");
  });

  it("excludes a video older than the window from Latest", () => {
    render(VideoFeed, {
      videos: feed(video("recent", 3), video("stale", VIDEO_LATEST_HOURS + 6)),
    });

    expect(titles()).toContain("Video recent");
    expect(titles()).not.toContain("Video stale");
  });

  it("includes a video right at the edge of the window", () => {
    render(VideoFeed, { videos: feed(video("edge", VIDEO_LATEST_HOURS - 0.1)) });
    expect(titles()).toContain("Video edge");
  });

  it("shows no day header in Latest", () => {
    render(VideoFeed, { videos: feed(video("a", 2), video("b", 20)) });
    // Latest is one unlabelled group — a date heading would imply day bucketing.
    expect(screen.queryByText(/^\w{3}, \w{3} \d+$/)).toBeNull();
  });
});

describe("VideoFeed — Archive still buckets by day", () => {
  it("shows videos the Latest window excludes", async () => {
    render(VideoFeed, {
      videos: feed(video("recent", 3), video("stale", VIDEO_LATEST_HOURS + 6)),
    });
    await clickArchive();

    expect(titles()).toContain("Video recent");
    expect(titles()).toContain("Video stale");
  });

  it("labels each day group with a date", async () => {
    render(VideoFeed, { videos: feed(video("a", 2), video("old", 50)) });
    await clickArchive();

    // Two distinct calendar days -> two date headers.
    const headers = document.querySelectorAll(".day-date");
    expect(headers.length).toBeGreaterThanOrEqual(2);
  });

  it("keeps a video with an unparseable date reachable in Archive", async () => {
    // Excluded from the rolling window (it has no usable timestamp), but the
    // Archive's "unknown" bucket must still surface it rather than dropping it.
    const broken = video("broken", 1, { published_date: null });
    render(VideoFeed, { videos: [video("ok", 2), broken] });

    expect(titles()).not.toContain("Video broken");
    await clickArchive();
    expect(titles()).toContain("Video broken");
  });
});

describe("VideoFeed — empty states", () => {
  it("tells the user to check Archive when only the window is empty", () => {
    render(VideoFeed, { videos: feed(video("stale", VIDEO_LATEST_HOURS + 6)) });
    expect(screen.getByText(/Nothing in the last 24 hours/)).toBeVisible();
  });

  it("reports no videos at all when the feed is empty", () => {
    render(VideoFeed, { videos: [] });
    expect(screen.getByText(/No new videos from your subscriptions/)).toBeVisible();
  });

  it("does not claim 'check Archive' when Archive is empty too", () => {
    render(VideoFeed, { videos: [] });
    expect(screen.queryByText(/Nothing in the last 24 hours/)).toBeNull();
  });
});
