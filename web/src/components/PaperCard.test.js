// PaperCard gained the `ai_summary` / `audio_url` pair that news cards already
// had. The pair arrives per-paper inside the run doc, and runs written before
// the pipeline generated it have neither field — so the degraded card is a
// normal state the Papers *Archive* view shows every day, not an edge case.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import PaperCard from "./PaperCard.svelte";

const paper = (overrides = {}) => ({
  rank: 1,
  title: "Attention Is All You Need",
  arxiv_id: "1706.03762",
  url: "https://arxiv.org/abs/1706.03762",
  score: 0.6234,
  summary: "Introduces the transformer.",
  abstract: "The dominant sequence transduction models…",
  ai_summary: "",
  audio_url: "",
  ...overrides,
});

const AUDIO = "https://storage.googleapis.com/bucket/research-papers/1706.03762.mp3";

const disclosure = (name) =>
  screen.queryAllByText(name, { selector: "summary" })[0] ?? null;

describe("PaperCard — audio + ai_summary", () => {
  it("renders the Listen button when the paper has audio", () => {
    render(PaperCard, { paper: paper({ audio_url: AUDIO }) });
    const btn = screen.getByRole("button", { name: /audio summary of/i });
    expect(btn).toHaveTextContent("Listen");
    // The accessible name must name the paper, not the card generically.
    expect(btn.getAttribute("aria-label")).toContain("Attention Is All You Need");
  });

  it("renders no audio control when audio_url is empty", () => {
    render(PaperCard, { paper: paper() });
    expect(screen.queryByRole("button", { name: /audio summary of/i })).toBeNull();
  });

  it("renders the AI summary behind a disclosure, collapsed by default", () => {
    render(PaperCard, { paper: paper({ ai_summary: "A longer machine summary." }) });
    const details = disclosure("AI summary").closest("details");
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);
    expect(details).toHaveTextContent("A longer machine summary.");
  });

  it("renders no AI summary disclosure when the field is empty", () => {
    render(PaperCard, { paper: paper() });
    expect(disclosure("AI summary")).toBeNull();
  });

  it("keeps ai_summary distinct from the one-line summary", () => {
    render(PaperCard, {
      paper: paper({ summary: "Short one.", ai_summary: "Much longer one." }),
    });
    // The short summary stays visible; only the long one is collapsed.
    expect(screen.getByText("Short one.")).toBeVisible();
    expect(disclosure("AI summary").closest("details").open).toBe(false);
  });

  it("keeps the Abstract disclosure alongside the new one", () => {
    render(PaperCard, {
      paper: paper({ ai_summary: "Machine summary.", audio_url: AUDIO }),
    });
    expect(disclosure("AI summary")).not.toBeNull();
    expect(disclosure("Abstract")).not.toBeNull();
  });

  it("renders a legacy paper — no audio, no ai_summary — without either control", () => {
    // Exactly the shape of a run written before the feature shipped.
    render(PaperCard, {
      paper: { rank: 3, title: "Old paper", arxiv_id: "1", url: "u", score: 0.4 },
    });
    expect(screen.queryByRole("button", { name: /audio summary of/i })).toBeNull();
    expect(disclosure("AI summary")).toBeNull();
    // …but the card itself still renders its core fields.
    expect(screen.getByText("Old paper")).toBeVisible();
    expect(screen.getByText("#3")).toBeVisible();
  });
});

describe("PaperCard — pre-existing behaviour still intact", () => {
  it("falls back to a muted notice when the summary is null", () => {
    render(PaperCard, { paper: paper({ summary: null }) });
    expect(screen.getByText("Summary unavailable for this paper.")).toBeVisible();
  });

  it("renders rank, arxiv id and match score", () => {
    render(PaperCard, { paper: paper() });
    expect(screen.getByText("#1")).toBeVisible();
    expect(screen.getByText("1706.03762")).toBeVisible();
    expect(screen.getByText(/match 62%/)).toBeVisible();
  });

  it("links the title out to arXiv in a new tab", () => {
    render(PaperCard, { paper: paper() });
    const link = screen.getByRole("link", { name: "Attention Is All You Need" });
    expect(link).toHaveAttribute("href", "https://arxiv.org/abs/1706.03762");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });
});
