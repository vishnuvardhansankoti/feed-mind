// NewsFeed renders one tab per NEWS_CATEGORIES entry and filters the article
// list by `feed_category`. These cover the tabbing contract in general and the
// `top_stories` tab in particular — the category whose code uses an underscore
// where `open-source` uses a hyphen, which is the easy way to break it.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import NewsFeed from "./NewsFeed.svelte";
import { NEWS_CATEGORIES } from "../lib/constants.js";

// Pin the clock: the day-bucket headers and "Latest" both key off calendar days.
const NOW = new Date(2026, 7, 24, 10, 0, 0);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => vi.useRealTimers());

const hoursAgo = (h) => new Date(Date.now() - h * 3600 * 1000);

const article = (id, category, hours = 2, overrides = {}) => ({
  article_id: id,
  url: `https://example.com/${id}`,
  title: `Article ${id}`,
  feed_source: `${category} source`,
  feed_category: category,
  summary: `Summary ${id}`,
  ai_summary: "",
  audio_url: "",
  processed_date: hoursAgo(hours),
  published_date: hoursAgo(hours),
  ...overrides,
});

const titles = () => screen.queryAllByRole("heading").map((h) => h.textContent.trim());

const catTab = (label) => screen.getByRole("tab", { name: label });

const clickTab = async (label) => {
  catTab(label).click();
  await vi.waitFor(() => {});
};

describe("NewsFeed — category tabs", () => {
  it("renders a tab for every configured category", () => {
    render(NewsFeed, { articles: [] });
    for (const c of NEWS_CATEGORIES) {
      expect(catTab(c.label)).toBeTruthy();
    }
  });

  it("renders a Top Stories tab", () => {
    render(NewsFeed, { articles: [] });
    expect(catTab("Top Stories")).toBeTruthy();
  });

  it("opens on Academic, not on the newly added category", () => {
    render(NewsFeed, {
      articles: [article("a", "academic"), article("t", "top_stories")],
    });
    expect(titles()).toContain("Article a");
    expect(titles()).not.toContain("Article t");
  });
});

describe("NewsFeed — top_stories filtering", () => {
  const mixed = [
    article("acad", "academic"),
    article("ind", "industry"),
    article("top1", "top_stories", 2),
    article("top2", "top_stories", 5),
  ];

  it("shows only top_stories articles when that tab is selected", async () => {
    render(NewsFeed, { articles: mixed });
    await clickTab("Top Stories");

    expect(titles()).toContain("Article top1");
    expect(titles()).toContain("Article top2");
    expect(titles()).not.toContain("Article acad");
    expect(titles()).not.toContain("Article ind");
  });

  it("does not leak top_stories articles into the other tabs", async () => {
    render(NewsFeed, { articles: mixed });

    // Academic is already selected.
    expect(titles()).not.toContain("Article top1");

    await clickTab("Industry");
    expect(titles()).toContain("Article ind");
    expect(titles()).not.toContain("Article top1");
  });

  it("matches the underscore code exactly, not a hyphenated variant", async () => {
    // A doc written under the wrong separator must NOT appear — that would mean
    // the tab is matching loosely and would mask a real pipeline/reader drift.
    render(NewsFeed, {
      articles: [article("wrong", "top-stories"), article("right", "top_stories")],
    });
    await clickTab("Top Stories");

    expect(titles()).toContain("Article right");
    expect(titles()).not.toContain("Article wrong");
  });

  it("shows the empty state when no top stories have been ingested yet", async () => {
    // The state on the day the category is added but the pipeline has not run.
    render(NewsFeed, { articles: [article("acad", "academic")] });
    await clickTab("Top Stories");

    expect(screen.getByText(/No articles this week/)).toBeVisible();
  });

  it("keeps the Archive view scoped to the selected category", async () => {
    render(NewsFeed, {
      articles: [article("acad", "academic", 30), article("top", "top_stories", 30)],
    });
    await clickTab("Top Stories");
    screen.getByRole("tab", { name: /Archive/ }).click();
    await vi.waitFor(() => {});

    expect(titles()).toContain("Article top");
    expect(titles()).not.toContain("Article acad");
  });
});
