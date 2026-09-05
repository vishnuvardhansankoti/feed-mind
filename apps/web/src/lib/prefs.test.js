// @vitest-environment jsdom
// Bookmark storage against the mock backend. The rules that matter here are the
// ones the UI can't be trusted to enforce: the cap refuses rather than evicts,
// ids are deterministic so re-saving can't duplicate, and a snapshot carries
// enough to render without its source document (which is on a TTL and, for
// papers, was never a document at all).
import { describe, it, expect, beforeEach } from "vitest";
import {
  loadBookmarks,
  saveBookmark,
  removeBookmark,
  bookmarkIdFor,
  snapshotOf,
  BookmarkLimitError,
} from "./prefs.js";
import { BOOKMARK_LIMIT } from "./constants.js";

const UID = "u1";

const paper = (id = "2501.001") => ({
  arxiv_id: id,
  title: `Paper ${id}`,
  url: `https://arxiv.org/abs/${id}`,
  summary: "One-line summary.",
  abstract: "A very long abstract that has no business being stored.",
  score: 0.71,
});

const article = () => ({
  article_id: "a1",
  title: "Some article",
  url: "https://example.com/a1",
  feed_source: "Google Developers",
  summary: "Article summary.",
  processed_at: "2026-08-20T10:00:00+00:00",
});

const video = () => ({
  video_id: "v1",
  title: "Some video",
  url: "https://youtube.com/watch?v=v1",
  channel: "Sam Witteveen AI",
  thumbnail_url: "https://i.ytimg.com/vi/v1/hqdefault.jpg",
  published_at: "2026-08-20T09:00:00+00:00",
});

beforeEach(() => localStorage.clear());

describe("bookmarkIdFor", () => {
  it("namespaces by type so ids can't collide across sections", () => {
    expect(bookmarkIdFor("paper", { arxiv_id: "x" })).toBe("paper_x");
    expect(bookmarkIdFor("news", { article_id: "x" })).toBe("news_x");
    expect(bookmarkIdFor("video", { video_id: "x" })).toBe("video_x");
  });

  it("is deterministic for the same item", () => {
    expect(bookmarkIdFor("paper", paper())).toBe(bookmarkIdFor("paper", paper()));
  });
});

describe("snapshotOf", () => {
  it("keeps what the Saved view renders and drops the rest", () => {
    const snap = snapshotOf("paper", paper());
    expect(snap).toMatchObject({
      id: "paper_2501.001",
      type: "paper",
      title: "Paper 2501.001",
      arxiv_id: "2501.001",
      summary: "One-line summary.",
    });
    // Whitelisted, not spread: an abstract would bloat every saved doc.
    expect(snap.abstract).toBeUndefined();
    expect(snap.score).toBeUndefined();
  });

  it("carries the per-type display fields", () => {
    expect(snapshotOf("news", article())).toMatchObject({
      feed_source: "Google Developers",
    });
    expect(snapshotOf("video", video())).toMatchObject({
      channel: "Sam Witteveen AI",
      thumbnail_url: "https://i.ytimg.com/vi/v1/hqdefault.jpg",
    });
  });

  it("never produces undefined, which Firestore rejects outright", () => {
    const snap = snapshotOf("video", { video_id: "v" });
    for (const v of Object.values(snap)) expect(v).not.toBeUndefined();
    expect(snap.title).toBe("");
  });

  it("stamps saved_at as an ISO string", () => {
    expect(snapshotOf("paper", paper()).saved_at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });
});

describe("saveBookmark", () => {
  it("stores an item and reads it back", async () => {
    await saveBookmark(UID, "paper", paper());
    const items = await loadBookmarks(UID);
    expect(items).toHaveLength(1);
    expect(items[0].title).toBe("Paper 2501.001");
  });

  it("keeps items of different types apart", async () => {
    await saveBookmark(UID, "paper", paper());
    await saveBookmark(UID, "news", article());
    await saveBookmark(UID, "video", video());
    const types = (await loadBookmarks(UID)).map((b) => b.type);
    expect(types.sort()).toEqual(["news", "paper", "video"]);
  });

  it("is idempotent — saving the same item twice doesn't duplicate", async () => {
    await saveBookmark(UID, "paper", paper());
    await saveBookmark(UID, "paper", paper());
    expect(await loadBookmarks(UID)).toHaveLength(1);
  });

  it("refuses the item past the cap instead of evicting the oldest", async () => {
    for (let i = 0; i < BOOKMARK_LIMIT; i++) {
      await saveBookmark(UID, "paper", paper(`p${i}`));
    }
    await expect(saveBookmark(UID, "paper", paper("overflow"))).rejects.toThrow(
      BookmarkLimitError,
    );

    // The whole point of refusing: nothing the user saved was deleted.
    const items = await loadBookmarks(UID);
    expect(items).toHaveLength(BOOKMARK_LIMIT);
    expect(items.map((b) => b.id)).not.toContain("paper_overflow");
    expect(items.map((b) => b.id)).toContain("paper_p0");
  });

  it("accepts a new item again once one is removed", async () => {
    for (let i = 0; i < BOOKMARK_LIMIT; i++) {
      await saveBookmark(UID, "paper", paper(`p${i}`));
    }
    await removeBookmark(UID, "paper_p0");
    await saveBookmark(UID, "paper", paper("fresh"));

    const ids = (await loadBookmarks(UID)).map((b) => b.id);
    expect(ids).toContain("paper_fresh");
    expect(ids).not.toContain("paper_p0");
    expect(ids).toHaveLength(BOOKMARK_LIMIT);
  });

  it("keeps each user's list separate", async () => {
    await saveBookmark("alice", "paper", paper());
    expect(await loadBookmarks("bob")).toEqual([]);
  });
});

describe("loadBookmarks", () => {
  it("returns newest save first", async () => {
    await saveBookmark(UID, "paper", paper("old"));
    await new Promise((r) => setTimeout(r, 2)); // distinct saved_at
    await saveBookmark(UID, "paper", paper("new"));
    expect((await loadBookmarks(UID))[0].id).toBe("paper_new");
  });

  it("is empty for a user who has never saved anything", async () => {
    expect(await loadBookmarks("nobody")).toEqual([]);
  });

  it("recovers from corrupt storage rather than throwing", async () => {
    localStorage.setItem("fm-bookmarks-u1", "{not json");
    expect(await loadBookmarks(UID)).toEqual([]);
  });
});

describe("removeBookmark", () => {
  it("removes by id", async () => {
    await saveBookmark(UID, "paper", paper());
    await removeBookmark(UID, "paper_2501.001");
    expect(await loadBookmarks(UID)).toEqual([]);
  });

  it("ignores an id that isn't saved", async () => {
    await saveBookmark(UID, "paper", paper());
    await removeBookmark(UID, "paper_nope");
    expect(await loadBookmarks(UID)).toHaveLength(1);
  });
});
