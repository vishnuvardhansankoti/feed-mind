// @vitest-environment jsdom
// Source follow/unfollow. The direction of storage is the thing under test:
// preferences record what is switched OFF, so anything unknown — a brand-new
// feed added in feed-mind, a user with no saved preferences, a failed read —
// is shown rather than hidden.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { follows, initFollows, resetFollows, isFollowed, toggleFollow, followAll } from "./follows.svelte.js";
import { loadUnfollowed, saveUnfollowed } from "./prefs.js";

const UID = "u1";

beforeEach(() => localStorage.clear());
afterEach(() => resetFollows());

describe("isFollowed", () => {
  it("follows everything before anything is loaded", () => {
    // Signed out, or the very first paint: the public feed must be complete.
    expect(isFollowed("news", "Anything")).toBe(true);
    expect(isFollowed("video", "Any Channel")).toBe(true);
  });

  it("follows a source that has never been switched off", async () => {
    await initFollows(UID);
    expect(isFollowed("news", "Google Developers")).toBe(true);
  });

  it("follows a source the user has never seen", async () => {
    // The catalog lives in feed-mind and grows without us. A stored "followed"
    // list would hide this one; storing exclusions shows it.
    await initFollows(UID);
    await toggleFollow("news", "Old Source");
    expect(isFollowed("news", "Brand New Feed")).toBe(true);
  });
});

describe("toggleFollow", () => {
  it("switches a source off and back on", async () => {
    await initFollows(UID);

    await toggleFollow("news", "TechCrunch");
    expect(isFollowed("news", "TechCrunch")).toBe(false);

    await toggleFollow("news", "TechCrunch");
    expect(isFollowed("news", "TechCrunch")).toBe(true);
  });

  it("keeps news and video preferences independent", async () => {
    await initFollows(UID);
    await toggleFollow("news", "Shared Name");
    expect(isFollowed("video", "Shared Name")).toBe(true);
  });

  it("persists across a reload", async () => {
    await initFollows(UID);
    await toggleFollow("video", "Some Channel");

    resetFollows();
    await initFollows(UID);
    expect(isFollowed("video", "Some Channel")).toBe(false);
  });

  it("keeps each user's preferences separate", async () => {
    await initFollows("alice");
    await toggleFollow("news", "Only Alice Hides This");

    await initFollows("bob");
    expect(isFollowed("news", "Only Alice Hides This")).toBe(true);
  });

  it("updates the UI even when the write fails", async () => {
    // Optimistic: silently reverting a toggle under the user is worse than a
    // preference that doesn't survive the session.
    await initFollows(UID);
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });

    await toggleFollow("news", "Whatever");
    expect(isFollowed("news", "Whatever")).toBe(false);
    spy.mockRestore();
  });
});

describe("followAll", () => {
  it("switches every source in a kind back on", async () => {
    await initFollows(UID);
    await toggleFollow("news", "A");
    await toggleFollow("news", "B");

    await followAll("news", ["A", "B"]);
    expect(isFollowed("news", "A")).toBe(true);
    expect(isFollowed("news", "B")).toBe(true);
  });

  it("leaves the other kind alone", async () => {
    await initFollows(UID);
    await toggleFollow("video", "Keep Hidden");
    await followAll("news", []);
    expect(isFollowed("video", "Keep Hidden")).toBe(false);
  });
});

describe("initFollows", () => {
  it("shows everything when the stored value is corrupt", async () => {
    localStorage.setItem("fm-unfollowed-u1", "{not json");
    await initFollows(UID);
    expect(isFollowed("news", "Anything")).toBe(true);
  });

  it("clears one user's preferences on sign-out", async () => {
    await initFollows(UID);
    await toggleFollow("news", "Hidden");
    resetFollows();
    expect(isFollowed("news", "Hidden")).toBe(true);
    expect(follows.unfollowed).toEqual({ news: [], video: [] });
  });
});

describe("prefs storage shape", () => {
  it("round-trips both kinds", async () => {
    await saveUnfollowed(UID, { news: ["A"], video: ["B"] });
    expect(await loadUnfollowed(UID)).toEqual({ news: ["A"], video: ["B"] });
  });

  it("defaults missing kinds to empty rather than undefined", async () => {
    await saveUnfollowed(UID, { news: ["A"] });
    expect(await loadUnfollowed(UID)).toEqual({ news: ["A"], video: [] });
  });

  it("de-duplicates before writing", async () => {
    const written = await saveUnfollowed(UID, { news: ["A", "A", "B"], video: [] });
    expect(written.news).toEqual(["A", "B"]);
  });

  it("is empty for a user with no stored preferences", async () => {
    expect(await loadUnfollowed("nobody")).toEqual({ news: [], video: [] });
  });
});
