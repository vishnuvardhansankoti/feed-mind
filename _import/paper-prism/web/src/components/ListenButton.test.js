// The audio button is a four-state machine (idle | loading | playing | error)
// driven by media events, plus a module-scoped "only one clip at a time" guard
// shared by every instance. Both are exercised here against the fake Audio from
// test/setup.js — jsdom has no media stack of its own.
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/svelte";
import ListenButton from "./ListenButton.svelte";
import { audioInstances, setPlayImplementation } from "../test/setup.js";

const URL_A = "https://storage.googleapis.com/bucket/a.mp3";
const URL_B = "https://storage.googleapis.com/bucket/b.mp3";

// Let queued microtasks (the fake's `playing` event) and Svelte's reactivity
// both settle before asserting on the rendered label.
const settle = async () => {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
};

describe("ListenButton", () => {
  it("renders the idle label and an accessible name naming the item", () => {
    render(ListenButton, { url: URL_A, label: "Attention Is All You Need" });
    const btn = screen.getByRole("button");
    expect(btn).toHaveTextContent("Listen");
    expect(btn.getAttribute("aria-label")).toBe(
      "Listen audio summary of Attention Is All You Need",
    );
  });

  it("does not construct an Audio element until first click", async () => {
    render(ListenButton, { url: URL_A, label: "x" });
    // A feed page holds ~200 cards; eager elements would mean 200 media requests.
    expect(audioInstances).toHaveLength(0);

    screen.getByRole("button").click();
    await settle();

    expect(audioInstances).toHaveLength(1);
    expect(audioInstances[0].src).toBe(URL_A);
    expect(audioInstances[0].preload).toBe("none");
  });

  it("moves to the playing state and offers Pause", async () => {
    render(ListenButton, { url: URL_A, label: "x" });
    screen.getByRole("button").click();
    await settle();

    expect(screen.getByRole("button")).toHaveTextContent("Pause");
    expect(audioInstances[0].play).toHaveBeenCalledOnce();
  });

  it("pauses and returns to idle on a second click", async () => {
    render(ListenButton, { url: URL_A, label: "x" });
    const btn = screen.getByRole("button");

    btn.click();
    await settle();
    expect(btn).toHaveTextContent("Pause");

    btn.click();
    await settle();
    expect(btn).toHaveTextContent("Listen");
    expect(audioInstances[0].pause).toHaveBeenCalled();
  });

  it("reuses the same Audio element across replays", async () => {
    render(ListenButton, { url: URL_A, label: "x" });
    const btn = screen.getByRole("button");

    btn.click();
    await settle();
    btn.click();
    await settle();
    btn.click();
    await settle();

    expect(audioInstances).toHaveLength(1);
    expect(audioInstances[0].play).toHaveBeenCalledTimes(2);
  });

  it("returns to idle when the clip ends on its own", async () => {
    render(ListenButton, { url: URL_A, label: "x" });
    screen.getByRole("button").click();
    await settle();

    audioInstances[0].fireEnded();
    await settle();

    expect(screen.getByRole("button")).toHaveTextContent("Listen");
  });

  it("shows an unavailable, disabled button when play() rejects", async () => {
    // Autoplay rejection or an unreachable object — same dead end either way.
    setPlayImplementation(() => Promise.reject(new Error("NotAllowedError")));
    render(ListenButton, { url: URL_A, label: "x" });

    screen.getByRole("button").click();
    await settle();

    const btn = screen.getByRole("button");
    expect(btn).toHaveTextContent("Audio unavailable");
    expect(btn.disabled).toBe(true);
  });

  it("shows an unavailable button when the element emits an error event", async () => {
    // A 404 on the storage object surfaces as an `error` event, not a rejection.
    setPlayImplementation(function () {
      queueMicrotask(() => this.dispatchEvent(new Event("error")));
      return Promise.resolve();
    });
    render(ListenButton, { url: URL_A, label: "x" });

    screen.getByRole("button").click();
    await settle();

    expect(screen.getByRole("button")).toHaveTextContent("Audio unavailable");
  });

  it("stops the previous clip when another button starts — app-wide", async () => {
    // This is the guard that keeps a paper card and a news card from overlapping.
    render(ListenButton, { url: URL_A, label: "first" });
    render(ListenButton, { url: URL_B, label: "second" });

    const [first, second] = screen.getAllByRole("button");

    first.click();
    await settle();
    expect(first).toHaveTextContent("Pause");

    second.click();
    await settle();

    expect(audioInstances[0].pause).toHaveBeenCalled();
    expect(first).toHaveTextContent("Listen");
    expect(second).toHaveTextContent("Pause");
  });

  it("stops playback when the card unmounts", async () => {
    const { unmount } = render(ListenButton, { url: URL_A, label: "x" });
    screen.getByRole("button").click();
    await settle();

    unmount();

    // Switching tabs destroys the card; the clip must not keep playing.
    expect(audioInstances[0].pause).toHaveBeenCalled();
  });

  it("lets a new button play after the previous one already unmounted", async () => {
    // Releasing the module-scoped slot on unmount must not strand it: a stale
    // holder would make every later click stop a dead element.
    const first = render(ListenButton, { url: URL_A, label: "first" });
    screen.getByRole("button").click();
    await settle();
    first.unmount();

    render(ListenButton, { url: URL_B, label: "second" });
    const btn = screen.getByRole("button");
    btn.click();
    await settle();

    expect(btn).toHaveTextContent("Pause");
  });
});
