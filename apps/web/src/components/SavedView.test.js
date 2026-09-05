// The Saved section. The load-bearing property: it renders from the stored
// snapshot alone, with no source document anywhere — which is what lets a saved
// paper outlive the 45-day TTL on the run doc it came from.
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import SavedView from "./SavedView.svelte";
import { bookmarks, resetBookmarks, initBookmarks } from "../lib/bookmarks.svelte.js";
import { BOOKMARK_LIMIT } from "../lib/constants.js";

const saved = (over = {}) => ({
  id: "paper_1",
  type: "paper",
  title: "A saved paper",
  url: "https://arxiv.org/abs/1",
  arxiv_id: "2501.001",
  summary: "Its summary.",
  saved_at: "2026-08-20T10:00:00.000Z",
  ...over,
});

const setItems = (items) => (bookmarks.items = items);

beforeEach(() => resetBookmarks());
afterEach(() => resetBookmarks());

describe("SavedView", () => {
  it("invites the user to save something when the list is empty", () => {
    render(SavedView);
    expect(screen.getByText(/Nothing saved yet/)).toBeVisible();
  });

  it("shows how much of the cap is used", () => {
    setItems([saved()]);
    render(SavedView);
    expect(screen.getByText(`1 of ${BOOKMARK_LIMIT} saved`)).toBeVisible();
  });

  it("renders an item entirely from its snapshot", () => {
    // No fetch, no source doc — everything on screen came from the stored copy.
    setItems([saved()]);
    render(SavedView);

    expect(screen.getByRole("link", { name: "A saved paper" })).toHaveAttribute(
      "href",
      "https://arxiv.org/abs/1",
    );
    expect(screen.getByText("2501.001")).toBeVisible();
    expect(screen.getByText("Its summary.")).toBeVisible();
  });

  it("groups by type and counts each group", () => {
    setItems([
      saved(),
      saved({ id: "news_1", type: "news", title: "An article", feed_source: "TechCrunch" }),
      saved({ id: "video_1", type: "video", title: "A video", channel: "Some Channel" }),
    ]);
    render(SavedView);

    for (const label of ["Papers", "News", "Videos"]) {
      expect(screen.getByRole("heading", { name: `${label} (1)` })).toBeVisible();
    }
  });

  it("omits headings for types with nothing saved", () => {
    setItems([saved({ id: "video_1", type: "video", title: "A video" })]);
    render(SavedView);

    expect(screen.getByRole("heading", { name: "Videos (1)" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: /^Papers/ })).toBeNull();
    expect(screen.queryByRole("heading", { name: /^News/ })).toBeNull();
  });

  it("removes an item on click", async () => {
    // removeSaved() is a no-op without a uid, so the store has to be live.
    await initBookmarks("u1");
    bookmarks.items = [saved()];
    render(SavedView);

    screen.getByRole("button", { name: /Remove/ }).click();
    await waitFor(() => expect(bookmarks.items).toEqual([]));
  });

  it("survives a snapshot with an unparseable saved_at", () => {
    // Invalid Date would throw inside Intl.DateTimeFormat and take the view down.
    setItems([saved({ saved_at: "nonsense" })]);
    render(SavedView);
    expect(screen.getByRole("link", { name: "A saved paper" })).toBeVisible();
  });

  it("reports a load failure without hiding the section", () => {
    bookmarks.error = "offline";
    render(SavedView);
    expect(screen.getByText(/Couldn’t load your saved items/)).toBeVisible();
  });
});
