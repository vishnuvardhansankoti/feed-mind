// KnowledgeFeed renders one tab per KNOWLEDGE_CATEGORIES entry and filters the
// article list by `feed_category` — same tabbing/filtering contract as
// NewsFeed.test.js, since KnowledgeFeed is structurally a copy of NewsFeed.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import KnowledgeFeed from "./KnowledgeFeed.svelte";
import { KNOWLEDGE_CATEGORIES } from "../lib/constants.js";
import { initFollows, resetFollows, toggleFollow } from "../lib/follows.svelte.js";

// Pin the clock: the day-bucket headers and "Latest" both key off calendar days.
const NOW = new Date(2026, 8, 14, 10, 0, 0);

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => vi.useRealTimers());

const hoursAgo = (h) => new Date(Date.now() - h * 3600 * 1000);

const lesson = (id, category, hours = 2, overrides = {}) => ({
  article_id: id,
  url: `https://florilex.web.app/${category}/${id}`,
  title: `Lesson ${id}`,
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

describe("KnowledgeFeed — series tabs", () => {
  it("renders a tab for every configured series", () => {
    render(KnowledgeFeed, { articles: [] });
    for (const c of KNOWLEDGE_CATEGORIES) {
      expect(catTab(c.label)).toBeTruthy();
    }
  });

  it("opens on AI/ML, not on DSA", () => {
    render(KnowledgeFeed, {
      articles: [lesson("a", "aiml"), lesson("d", "dsa")],
    });
    expect(titles()).toContain("Lesson a");
    expect(titles()).not.toContain("Lesson d");
  });

  it("shows System Design lessons under their own tab", async () => {
    render(KnowledgeFeed, {
      articles: [lesson("a", "aiml"), lesson("sd", "system_design")],
    });
    expect(titles()).not.toContain("Lesson sd");

    await clickTab("System Design");
    expect(titles()).toContain("Lesson sd");
    expect(titles()).not.toContain("Lesson a");
  });
});

describe("KnowledgeFeed — series filtering", () => {
  const mixed = [
    lesson("aiml1", "aiml"),
    lesson("dsa1", "dsa", 2),
    lesson("dsa2", "dsa", 5),
  ];

  it("shows only the selected series' lessons", async () => {
    render(KnowledgeFeed, { articles: mixed });
    await clickTab("DSA");

    expect(titles()).toContain("Lesson dsa1");
    expect(titles()).toContain("Lesson dsa2");
    expect(titles()).not.toContain("Lesson aiml1");
  });

  it("does not leak one series' lessons into the other tab", async () => {
    render(KnowledgeFeed, { articles: mixed });

    // AI/ML is already selected.
    expect(titles()).not.toContain("Lesson dsa1");

    await clickTab("DSA");
    expect(titles()).toContain("Lesson dsa1");
    expect(titles()).not.toContain("Lesson aiml1");
  });

  it("shows the empty state when no lessons have been ingested for a series yet", async () => {
    render(KnowledgeFeed, { articles: [lesson("aiml1", "aiml")] });
    await clickTab("DSA");

    expect(screen.getByText(/No new DSA lessons this week/)).toBeVisible();
  });

  it("keeps the Archive view scoped to the selected series", async () => {
    render(KnowledgeFeed, {
      articles: [lesson("aiml1", "aiml", 30), lesson("dsa1", "dsa", 30)],
    });
    await clickTab("DSA");
    screen.getByRole("tab", { name: /Archive/ }).click();
    await vi.waitFor(() => {});

    expect(titles()).toContain("Lesson dsa1");
    expect(titles()).not.toContain("Lesson aiml1");
  });

  it("shows the RSS description as the visible summary (summarize: none)", () => {
    render(KnowledgeFeed, {
      articles: [lesson("aiml1", "aiml", 1, { summary: "Real florilex description text." })],
    });
    expect(screen.getByText("Real florilex description text.")).toBeVisible();
  });
});

describe("KnowledgeFeed — source follow/unfollow", () => {
  beforeEach(async () => {
    localStorage.clear();
    resetFollows();
    await initFollows("u1");
  });
  afterEach(() => resetFollows());

  it("hides a series' lessons once its source is unfollowed", async () => {
    await toggleFollow("knowledge", "aiml source");
    render(KnowledgeFeed, { articles: [lesson("aiml1", "aiml")] });
    expect(titles()).not.toContain("Lesson aiml1");
  });

  it("leaves the other series' lessons alone", async () => {
    await toggleFollow("knowledge", "aiml source");
    render(KnowledgeFeed, { articles: [lesson("dsa1", "dsa")] });
    await clickTab("DSA");
    expect(titles()).toContain("Lesson dsa1");
  });
});
