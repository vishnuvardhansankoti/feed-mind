// NewsFeed renders one tab per NEWS_CATEGORIES entry and filters the article
// list by `feed_category`. These cover the tabbing contract in general and
// exact-match filtering in particular — a category code matched loosely would
// mask a real pipeline/reader drift.
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

  it("opens on Academic, not on the newly added category", () => {
    render(NewsFeed, {
      articles: [article("a", "academic"), article("t", "industry")],
    });
    expect(titles()).toContain("Article a");
    expect(titles()).not.toContain("Article t");
  });
});

describe("NewsFeed — category filtering", () => {
  const mixed = [
    article("acad", "academic"),
    article("ind", "industry"),
    article("oss1", "open-source", 2),
    article("oss2", "open-source", 5),
  ];

  it("shows only the selected category's articles", async () => {
    render(NewsFeed, { articles: mixed });
    await clickTab("Open Source");

    expect(titles()).toContain("Article oss1");
    expect(titles()).toContain("Article oss2");
    expect(titles()).not.toContain("Article acad");
    expect(titles()).not.toContain("Article ind");
  });

  it("does not leak one category's articles into another tab", async () => {
    render(NewsFeed, { articles: mixed });

    // Academic is already selected.
    expect(titles()).not.toContain("Article oss1");

    await clickTab("Industry");
    expect(titles()).toContain("Article ind");
    expect(titles()).not.toContain("Article oss1");
  });

  it("matches the hyphenated code exactly, not an underscored variant", async () => {
    // A doc written under the wrong separator must NOT appear — that would mean
    // the tab is matching loosely and would mask a real pipeline/reader drift.
    render(NewsFeed, {
      articles: [article("wrong", "open_source"), article("right", "open-source")],
    });
    await clickTab("Open Source");

    expect(titles()).toContain("Article right");
    expect(titles()).not.toContain("Article wrong");
  });

  it("shows the empty state when no articles have been ingested for a category yet", async () => {
    render(NewsFeed, { articles: [article("acad", "academic")] });
    await clickTab("Open Source");

    expect(screen.getByText(/No articles this week/)).toBeVisible();
  });

  it("keeps the Archive view scoped to the selected category", async () => {
    render(NewsFeed, {
      articles: [article("acad", "academic", 30), article("oss", "open-source", 30)],
    });
    await clickTab("Open Source");
    screen.getByRole("tab", { name: /Archive/ }).click();
    await vi.waitFor(() => {});

    expect(titles()).toContain("Article oss");
    expect(titles()).not.toContain("Article acad");
  });
});
