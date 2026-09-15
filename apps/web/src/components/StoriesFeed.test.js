// StoriesFeed renders a country toggle (India/US) above the category tabs and
// slices the already-nested {country: {category: cards}} prop client-side —
// no re-fetch on toggle. These pin the toggling contract and the country
// isolation it exists for.
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import StoriesFeed from "./StoriesFeed.svelte";

const story = (id, overrides = {}) => ({
  story_id: id,
  country: "IN",
  coarse_category: "business",
  business_category: "",
  rank: 1,
  score: 0.7,
  cluster_size: 1,
  sources: ["Economic Times"],
  canonical_article_id: `${id}-canonical`,
  canonical: { title: `Title ${id}`, url: `https://example.com/${id}`, source: "Economic Times" },
  related_articles: [],
  ai_summary: "",
  audio_url: "",
  run_date: "2026-09-10",
  ...overrides,
});

const stories = {
  IN: { politics: [], global: [], business: [story("in-b1")], sports: [], culture: [] },
  US: { politics: [], global: [], business: [story("us-b1", { country: "US" })], sports: [], culture: [] },
};

const tab = (label) => screen.getByRole("tab", { name: label });

const clickTab = async (label) => {
  tab(label).click();
  await vi.waitFor(() => {});
};

describe("StoriesFeed — country toggle", () => {
  it("renders a tab for India and US", () => {
    render(StoriesFeed, { stories });
    expect(tab("India")).toBeTruthy();
    expect(tab("US")).toBeTruthy();
  });

  it("opens on India, not US", async () => {
    render(StoriesFeed, { stories });
    await clickTab("Business");
    expect(screen.getByRole("link", { name: "Title in-b1" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Title us-b1" })).toBeNull();
  });

  it("switches to US stories when the US tab is clicked", async () => {
    render(StoriesFeed, { stories });
    await clickTab("Business");
    await clickTab("US");
    expect(screen.getByRole("link", { name: "Title us-b1" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Title in-b1" })).toBeNull();
  });

  it("shows the empty state scoped to the selected country and category", async () => {
    render(StoriesFeed, { stories });
    await clickTab("Sports");
    expect(screen.getByText(/No India sports stories yet\./)).toBeVisible();

    await clickTab("US");
    expect(screen.getByText(/No US sports stories yet\./)).toBeVisible();
  });
});

describe("StoriesFeed — Latest/Archive window", () => {
  // data.js now hands over the whole STORY_ARCHIVE_WINDOW_DAYS window,
  // newest run_date first — same shape NewsFeed/VideoFeed group client-side.
  const multiDay = {
    IN: {
      politics: [], global: [], sports: [], culture: [],
      business: [
        story("in-b-new", { run_date: "2026-09-10" }),
        story("in-b-old", { run_date: "2026-09-09" }),
      ],
    },
    US: { politics: [], global: [], business: [], sports: [], culture: [] },
  };

  it("Latest shows only the newest run_date's stories", async () => {
    render(StoriesFeed, { stories: multiDay });
    await clickTab("Business");
    expect(screen.getByRole("link", { name: "Title in-b-new" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Title in-b-old" })).toBeNull();
  });

  it("Archive shows every run_date in the window", async () => {
    render(StoriesFeed, { stories: multiDay });
    await clickTab("Business");
    await clickTab("Archive · 3 days");
    expect(screen.getByRole("link", { name: "Title in-b-new" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Title in-b-old" })).toBeInTheDocument();
  });

  it("switching back to Latest drops the older day again", async () => {
    render(StoriesFeed, { stories: multiDay });
    await clickTab("Business");
    await clickTab("Archive · 3 days");
    await clickTab("Latest");
    expect(screen.queryByRole("link", { name: "Title in-b-old" })).toBeNull();
  });
});
