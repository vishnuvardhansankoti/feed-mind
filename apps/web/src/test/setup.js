// Test setup shared by the component suites.
//
// jsdom ships no media stack at all: HTMLMediaElement.play() throws
// "Not implemented", and no `playing`/`pause`/`ended` events ever fire. The
// audio button is a state machine driven entirely by those events, so we give
// it a controllable fake instead of the real element.
import { afterEach, vi } from "vitest";

// This file is a global setup, so it also loads for the lib suites that opt into
// `@vitest-environment node`. Those have no DOM and no components to unmount —
// bail out before touching `window` or importing the DOM-only test library.
const HAS_DOM = typeof window !== "undefined";

// Every Audio built during a test, so a test can drive the events itself.
export const audioInstances = [];

// A play() that resolves and then fires `playing`, the way a real element does
// once the media is decodable. Tests that need failure override this.
let playImpl = function () {
  queueMicrotask(() => this.dispatchEvent(new Event("playing")));
  return Promise.resolve();
};

export function setPlayImplementation(fn) {
  playImpl = fn;
}

export function resetAudio() {
  audioInstances.length = 0;
  playImpl = function () {
    queueMicrotask(() => this.dispatchEvent(new Event("playing")));
    return Promise.resolve();
  };
}

// EventTarget gives us real addEventListener/dispatchEvent semantics, which is
// exactly what the component relies on — no need to fake the listener registry.
class FakeAudio extends EventTarget {
  constructor(src) {
    super();
    this.src = src;
    this.preload = "";
    this.paused = true;
    this.play = vi.fn(() => {
      this.paused = false;
      return playImpl.call(this);
    });
    this.pause = vi.fn(() => {
      // A real element fires `pause` when paused while playing; mirror that so
      // the component's own pause listener runs.
      const wasPlaying = !this.paused;
      this.paused = true;
      if (wasPlaying) this.dispatchEvent(new Event("pause"));
    });
    audioInstances.push(this);
  }

  // Convenience helpers for tests to simulate what the browser would do.
  fireEnded() {
    this.paused = true;
    this.dispatchEvent(new Event("ended"));
  }

  fireError() {
    this.dispatchEvent(new Event("error"));
  }
}

if (HAS_DOM) {
  globalThis.Audio = FakeAudio;
  window.Audio = FakeAudio;

  // jest-dom's matchers (toHaveTextContent, toBeDisabled, …) are DOM-only.
  await import("@testing-library/jest-dom/vitest");
  const { cleanup } = await import("@testing-library/svelte");
  afterEach(() => {
    cleanup();
    resetAudio();
  });
}
