// The badge went from "one chip per lens, always" to "the build date, plus a
// chip only when a lens actually failed". The point of these tests is that the
// healthy case stays quiet and the unhealthy case cannot be missed.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import FreshnessBadge from "./FreshnessBadge.svelte";

const healthy = {
  run_date: new Date("2026-08-13T00:00:00Z"),
  categories: {
    AIML: { status: "ok", paper_count: 3 },
    NLP: { status: "ok", paper_count: 3 },
    CV: { status: "ok", paper_count: 3 },
  },
};

describe("FreshnessBadge", () => {
  it("dates the run in UTC, not the reader's timezone", () => {
    // run_date is a calendar date at midnight UTC; formatting it locally labels
    // the 13th as "Aug 12" for every reader behind UTC.
    render(FreshnessBadge, { status: healthy });
    expect(screen.getByText(/Aug 13/)).toBeInTheDocument();
  });

  it("shows only the build date when every lens succeeded", () => {
    render(FreshnessBadge, { status: healthy });

    expect(screen.getByText("Digest")).toBeInTheDocument();
    // The old always-green chips are gone.
    expect(screen.queryByText("fresh")).not.toBeInTheDocument();
    expect(screen.queryByText("AI / ML")).not.toBeInTheDocument();
    expect(screen.queryByText("NLP")).not.toBeInTheDocument();
  });

  it("names a lens the pipeline marked skipped", () => {
    render(FreshnessBadge, {
      status: {
        ...healthy,
        categories: { ...healthy.categories, NLP: { status: "skipped", reason: "arxiv 503" } },
      },
    });

    expect(screen.getByText("NLP")).toBeInTheDocument();
    expect(screen.getByText("incomplete")).toBeInTheDocument();
    // The healthy lenses stay silent.
    expect(screen.queryByText("AI / ML")).not.toBeInTheDocument();
  });

  it("flags a lens missing from the doc entirely", () => {
    // A run that died before reaching a lens never records it at all, which is
    // a different failure from one it recorded as skipped.
    render(FreshnessBadge, {
      status: { ...healthy, categories: { AIML: { status: "ok" } } },
    });

    expect(screen.getByText("NLP")).toBeInTheDocument();
    expect(screen.getByText("Computer Vision")).toBeInTheDocument();
    expect(screen.getAllByText("no data")).toHaveLength(2);
  });

  it("renders nothing when there is no status at all", () => {
    const { container } = render(FreshnessBadge, { status: null });
    expect(container.querySelector(".badges")).toBeNull();
  });

  it("survives an unparseable run_date without taking the masthead down", () => {
    // Intl.DateTimeFormat throws on an Invalid Date, and this sits in the
    // masthead — a throw here blanks the whole page.
    render(FreshnessBadge, {
      status: { run_date: new Date("nonsense"), categories: healthy.categories },
    });

    expect(screen.queryByText("Digest")).not.toBeInTheDocument();
  });

  it("still reports failures when the date is unusable", () => {
    render(FreshnessBadge, {
      status: {
        run_date: null,
        categories: { ...healthy.categories, CV: { status: "skipped" } },
      },
    });

    expect(screen.getByText("Computer Vision")).toBeInTheDocument();
  });
});
