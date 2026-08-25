// The source settings sheet. Its list is derived from the loaded documents
// rather than a hardcoded catalog — the real list lives in feed-mind's
// config.py, in another repo, so a copy here would drift.
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import SettingsSheet from "./SettingsSheet.svelte";
import { initFollows, resetFollows, isFollowed, toggleFollow } from "../lib/follows.svelte.js";
import { settingsUi, openSettings, closeSettings } from "../lib/settingsUi.svelte.js";

const articles = [
  { article_id: "1", feed_source: "TechCrunch" },
  { article_id: "2", feed_source: "Google Developers" },
  { article_id: "3", feed_source: "TechCrunch" }, // duplicate source
];

const videos = [
  { video_id: "a", channel: "Sam Witteveen AI" },
  { video_id: "b", channel: "Fahd Mirza" },
];

beforeEach(async () => {
  localStorage.clear();
  resetFollows();
  await initFollows("u1");
});

afterEach(() => {
  resetFollows();
  closeSettings();
});

describe("SettingsSheet", () => {
  it("lists each distinct source once", () => {
    render(SettingsSheet, { articles, videos });

    expect(screen.getByRole("heading", { name: "News (2)" })).toBeVisible();
    expect(screen.getAllByLabelText("TechCrunch")).toHaveLength(1);
    expect(screen.getByLabelText("Google Developers")).toBeVisible();
  });

  it("lists video channels separately", () => {
    render(SettingsSheet, { articles, videos });
    expect(screen.getByRole("heading", { name: "Videos (2)" })).toBeVisible();
    expect(screen.getByLabelText("Sam Witteveen AI")).toBeVisible();
  });

  it("shows every source as followed by default", () => {
    render(SettingsSheet, { articles, videos });
    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeChecked();
  });

  it("unfollows a source when its box is unchecked", async () => {
    render(SettingsSheet, { articles, videos });

    screen.getByLabelText("TechCrunch").click();
    await waitFor(() => expect(isFollowed("news", "TechCrunch")).toBe(false));
    expect(screen.getByLabelText("TechCrunch")).not.toBeChecked();
  });

  it("reflects a source that was already unfollowed", async () => {
    await toggleFollow("video", "Fahd Mirza");
    render(SettingsSheet, { articles, videos });

    expect(screen.getByLabelText("Fahd Mirza")).not.toBeChecked();
    expect(screen.getByLabelText("Sam Witteveen AI")).toBeChecked();
  });

  it("offers 'Show all' only once something is hidden", async () => {
    render(SettingsSheet, { articles, videos });
    expect(screen.queryByRole("button", { name: "Show all" })).toBeNull();

    screen.getByLabelText("TechCrunch").click();
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: "Show all" }).length).toBe(1),
    );
  });

  it("restores everything in one click", async () => {
    await toggleFollow("news", "TechCrunch");
    await toggleFollow("news", "Google Developers");
    render(SettingsSheet, { articles, videos });

    screen.getByRole("button", { name: "Show all" }).click();
    await waitFor(() => {
      expect(isFollowed("news", "TechCrunch")).toBe(true);
      expect(isFollowed("news", "Google Developers")).toBe(true);
    });
  });

  it("says so when a section has nothing loaded yet", () => {
    render(SettingsSheet, { articles: [], videos });
    expect(screen.getByText("No news sources loaded yet.")).toBeVisible();
  });

  it("closes on the close button", async () => {
    openSettings();
    render(SettingsSheet, { articles, videos });

    screen.getByRole("button", { name: "Close settings" }).click();
    await waitFor(() => expect(settingsUi.open).toBe(false));
  });

  it("ignores sources with a missing name", () => {
    render(SettingsSheet, { articles: [{ article_id: "x" }, ...articles], videos });
    // The undefined feed_source must not become a blank, unclickable row.
    expect(screen.getByRole("heading", { name: "News (2)" })).toBeVisible();
  });
});
