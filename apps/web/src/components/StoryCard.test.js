import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import StoryCard from "./StoryCard.svelte";

const story = (overrides = {}) => ({
  story_id: "business_2026-09-10_01",
  coarse_category: "business",
  business_category: "",
  rank: 1,
  score: 0.72,
  cluster_size: 1,
  sources: ["Economic Times"],
  canonical_article_id: "a1",
  canonical: {
    title: "RBI holds repo rate at 6.5%",
    url: "https://example.com/rbi",
    source: "Economic Times",
  },
  related_articles: [],
  ai_summary: "",
  audio_url: "",
  ...overrides,
});

const disclosure = (name) =>
  screen.queryAllByText(name, { selector: "summary" })[0] ?? null;

describe("StoryCard", () => {
  it("renders the canonical title linking to the canonical url", () => {
    render(StoryCard, { story: story() });
    const link = screen.getByRole("link", { name: "RBI holds repo rate at 6.5%" });
    expect(link).toHaveAttribute("href", "https://example.com/rbi");
  });

  it("renders the canonical source", () => {
    render(StoryCard, { story: story() });
    expect(screen.getByText("Economic Times")).toBeVisible();
  });

  it("shows a corroboration count only when more than one source covered it", () => {
    render(StoryCard, { story: story({ sources: ["Economic Times"] }) });
    expect(screen.queryByText(/more$/)).toBeNull();

    render(StoryCard, {
      story: story({ sources: ["Economic Times", "Business Standard", "Hindu BusinessLine"] }),
    });
    expect(screen.getByText("+2 more")).toBeVisible();
  });

  it("shows the business sub-category badge when one is assigned", () => {
    render(StoryCard, { story: story({ business_category: "markets" }) });
    expect(screen.getByText("Markets")).toBeVisible();
  });

  it("renders no badge when there is no business_category", () => {
    render(StoryCard, { story: story({ business_category: "" }) });
    expect(screen.queryByText("Markets")).toBeNull();
  });

  it("renders the Listen button only when audio_url is set", () => {
    render(StoryCard, {
      story: story({ audio_url: "https://storage.googleapis.com/bucket/x.mp3" }),
    });
    expect(screen.getByRole("button", { name: /audio summary of/i })).toBeInTheDocument();
  });

  it("renders no audio control when audio_url is empty", () => {
    render(StoryCard, { story: story() });
    expect(screen.queryByRole("button", { name: /audio summary of/i })).toBeNull();
  });

  it("renders the AI summary disclosure, collapsed, only when present", () => {
    render(StoryCard, { story: story() });
    expect(disclosure("AI summary")).toBeNull();

    render(StoryCard, { story: story({ ai_summary: "A generated summary." }) });
    const details = disclosure("AI summary").closest("details");
    expect(details.open).toBe(false);
    expect(details).toHaveTextContent("A generated summary.");
  });

  it("lists related articles from other outlets, collapsed", () => {
    render(StoryCard, {
      story: story({
        cluster_size: 2,
        related_articles: [
          { source: "Business Standard", url: "https://example.com/bs", title: "RBI keeps rates unchanged" },
        ],
      }),
    });
    const details = disclosure(/Also covered by 1 other outlet/).closest("details");
    expect(details.open).toBe(false);
    const link = screen.getByRole("link", { name: /Business Standard: RBI keeps rates unchanged/ });
    expect(link).toHaveAttribute("href", "https://example.com/bs");
  });

  it("renders nothing for related articles when the cluster has only the canonical one", () => {
    render(StoryCard, { story: story({ related_articles: [] }) });
    expect(screen.queryByText(/Also covered by/)).toBeNull();
  });
});
