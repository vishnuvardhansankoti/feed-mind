// ArticleCard's inline audio player was extracted into the shared
// ListenButton so PaperCard could reuse it. These are regression tests for that
// refactor: the news card's rendered behaviour must be unchanged.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import ArticleCard from "./ArticleCard.svelte";

const article = (overrides = {}) => ({
  article_id: "a1",
  title: "A fused attention kernel",
  url: "https://example.com/post",
  feed_source: "Hugging Face",
  feed_category: "academic",
  summary: "One-line summary.",
  ai_summary: "",
  audio_url: "",
  processed_date: new Date(Date.now() - 2 * 3600 * 1000),
  published_date: new Date(Date.now() - 3 * 3600 * 1000),
  ...overrides,
});

const AUDIO = "https://storage.googleapis.com/bucket/2026-08-22/a1.mp3";

const disclosure = (name) =>
  screen.queryAllByText(name, { selector: "summary" })[0] ?? null;

describe("ArticleCard after the ListenButton extraction", () => {
  it("still renders the Listen button when the article has audio", () => {
    render(ArticleCard, { article: article({ audio_url: AUDIO }) });
    const btn = screen.getByRole("button", { name: /audio summary of/i });
    expect(btn).toHaveTextContent("Listen");
    expect(btn.getAttribute("aria-label")).toContain("A fused attention kernel");
  });

  it("still renders no audio control when audio_url is empty", () => {
    render(ArticleCard, { article: article() });
    expect(screen.queryByRole("button", { name: /audio summary of/i })).toBeNull();
  });

  it("still renders the AI summary disclosure, collapsed", () => {
    render(ArticleCard, { article: article({ ai_summary: "Longer summary." }) });
    const details = disclosure("AI summary").closest("details");
    expect(details.open).toBe(false);
    expect(details).toHaveTextContent("Longer summary.");
  });

  it("renders a pinned link (no summary, no audio, no ai_summary) cleanly", () => {
    // The open-source category is pinned client-side and has no pipeline content.
    render(ArticleCard, {
      article: article({ summary: "", ai_summary: "", audio_url: "", feed_source: "GitHub" }),
    });
    expect(screen.queryByRole("button", { name: /audio summary of/i })).toBeNull();
    expect(disclosure("AI summary")).toBeNull();
    expect(screen.getByText("GitHub")).toBeVisible();
  });

  it("still renders source and a relative age", () => {
    render(ArticleCard, { article: article() });
    expect(screen.getByText("Hugging Face")).toBeVisible();
    expect(screen.getByText(/2h ago/)).toBeVisible();
  });

  it("omits the age when the article has no processed date", () => {
    render(ArticleCard, { article: article({ processed_date: null }) });
    expect(screen.queryByText(/ago/)).toBeNull();
  });
});
