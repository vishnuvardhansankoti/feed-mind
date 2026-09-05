// The star on a card. Two things carry real weight: it is completely absent
// when signed out (the public site must be exactly what it was before sign-in
// existed), and hitting the cap explains itself instead of failing silently.
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import BookmarkButton from "./BookmarkButton.svelte";
import { session } from "../lib/session.svelte.js";
import { initBookmarks, resetBookmarks, bookmarks } from "../lib/bookmarks.svelte.js";
import { BOOKMARK_LIMIT } from "../lib/constants.js";

const paper = (id = "2501.001") => ({
  arxiv_id: id,
  title: `Paper ${id}`,
  url: `https://arxiv.org/abs/${id}`,
  summary: "s",
});

const signedIn = async () => {
  Object.assign(session, { status: "in", user: { uid: "u1" }, error: null });
  await initBookmarks("u1");
};

beforeEach(() => localStorage.clear());

afterEach(() => {
  Object.assign(session, { status: "loading", user: null, error: null });
  resetBookmarks();
});

describe("BookmarkButton", () => {
  it("renders nothing at all when signed out", () => {
    Object.assign(session, { status: "out", user: null });
    render(BookmarkButton, { type: "paper", item: paper() });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("renders nothing while auth is still resolving", () => {
    render(BookmarkButton, { type: "paper", item: paper() });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers an unsaved star when signed in", async () => {
    await signedIn();
    render(BookmarkButton, { type: "paper", item: paper() });

    const btn = screen.getByRole("button");
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(btn).toHaveAccessibleName(/^Save/);
  });

  it("saves on click and reflects it in the star", async () => {
    await signedIn();
    render(BookmarkButton, { type: "paper", item: paper() });

    screen.getByRole("button").click();

    await waitFor(() =>
      expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "true"),
    );
    expect(bookmarks.items.map((b) => b.id)).toEqual(["paper_2501.001"]);
  });

  it("unsaves on a second click", async () => {
    await signedIn();
    render(BookmarkButton, { type: "paper", item: paper() });

    screen.getByRole("button").click();
    // Not just aria-pressed: the star is disabled while the write is in
    // flight, so a click sent too early is deliberately swallowed.
    await waitFor(() => {
      const btn = screen.getByRole("button");
      expect(btn).toHaveAttribute("aria-pressed", "true");
      expect(btn).not.toBeDisabled();
    });
    screen.getByRole("button").click();

    await waitFor(() =>
      expect(screen.getByRole("button")).toHaveAttribute("aria-pressed", "false"),
    );
    expect(bookmarks.items).toEqual([]);
  });

  it("shows an already-saved item as saved on first render", async () => {
    await signedIn();
    render(BookmarkButton, { type: "paper", item: paper() });
    screen.getByRole("button").click();
    await waitFor(() => expect(bookmarks.items).toHaveLength(1));

    // A second card for the same item — e.g. the same paper in Archive.
    render(BookmarkButton, { type: "paper", item: paper() });
    await waitFor(() => {
      const stars = screen.getAllByRole("button");
      expect(stars.every((b) => b.getAttribute("aria-pressed") === "true")).toBe(true);
    });
  });

  // Fill every slot, then click the star on one more card.
  const overflow = async () => {
    for (let i = 0; i < BOOKMARK_LIMIT; i++) {
      render(BookmarkButton, { type: "paper", item: paper(`p${i}`) });
      screen.getAllByRole("button").at(-1).click();
      await waitFor(() => expect(bookmarks.items).toHaveLength(i + 1));
    }
    render(BookmarkButton, { type: "paper", item: paper("overflow") });
    const last = screen.getAllByRole("button").at(-1);
    last.click();
    return last;
  };

  it("explains the cap instead of failing silently", async () => {
    await signedIn();
    const last = await overflow();

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(`Limit reached (${BOOKMARK_LIMIT})`),
    );
    // Refused, not evicted — and still offering to save once a slot is free.
    expect(last).toHaveAttribute("aria-pressed", "false");
    expect(bookmarks.items).toHaveLength(BOOKMARK_LIMIT);
    expect(bookmarks.items.map((b) => b.id)).toContain("paper_p0");
    expect(bookmarks.items.map((b) => b.id)).not.toContain("paper_overflow");
  });

  it("points at the Saved view so the user can free a slot", async () => {
    await signedIn();
    await overflow();

    const link = await screen.findByRole("link", { name: "remove one" });
    expect(link).toHaveAttribute("href", "#/saved");
  });
});
