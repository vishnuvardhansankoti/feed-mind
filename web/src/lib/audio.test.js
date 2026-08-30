// The queue engine behind "Listen All". It drives one <audio> element through a
// list of tracks, and the behaviour that matters is what happens at the edges:
// a track that fails must not strand the queue, and a card claiming the channel
// must stop it.
//
// Runs against the fake Audio from test/setup.js — jsdom has no media stack.
import { describe, it, expect, vi, beforeEach, beforeAll } from "vitest";
import { audioInstances, setPlayImplementation } from "../test/setup.js";
import {
  queue,
  playQueue,
  stopQueue,
  skipTrack,
  currentTrack,
  claimPlayback,
  clearProblem,
} from "./audio.svelte.js";

const track = (n) => ({ url: `https://storage.googleapis.com/b/${n}.mp3`, title: n, context: "Academic" });

const settle = async () => {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
};

// The queue builds its <audio> element once and keeps it for the life of the
// module, so it is created during the first queue and never appears in
// `audioInstances` again (setup.js clears that array after every test). Warm it
// up once and hold the reference, which is also the cleanest way to assert the
// element really is reused.
let el;

beforeAll(async () => {
  playQueue([track("warmup")], "warmup");
  await settle();
  el = audioInstances.at(-1);
  stopQueue();
});

beforeEach(() => {
  stopQueue();
  clearProblem();
});

describe("playQueue", () => {
  it("starts on the first track and reports position", async () => {
    playQueue([track("a"), track("b")], "news");
    await settle();

    expect(queue.state).toBe("playing");
    expect(queue.index).toBe(0);
    expect(queue.source).toBe("news");
    expect(currentTrack().title).toBe("a");
  });

  it("ignores an empty queue", () => {
    playQueue([], "news");
    expect(queue.state).toBe("idle");
    expect(queue.source).toBe(null);
  });

  it("advances when a track ends and stops after the last one", async () => {
    playQueue([track("a"), track("b")], "news");
    await settle();

    el.fireEnded();
    await settle();
    expect(queue.index).toBe(1);
    expect(currentTrack().title).toBe("b");

    el.fireEnded();
    await settle();
    expect(queue.state).toBe("idle");
    expect(queue.tracks).toEqual([]);
  });

  it("reuses one element across the whole queue, swapping its src", async () => {
    // 200 cards already each own an element on a feed page; a queue must not
    // add one per track on top of that.
    const before = audioInstances.length;

    playQueue([track("a"), track("b")], "news");
    await settle();
    expect(el.src).toContain("a.mp3");

    el.fireEnded();
    await settle();
    expect(el.src).toContain("b.mp3");

    expect(audioInstances.length).toBe(before);
  });
});

describe("reaching the end", () => {
  it("plays a long queue exactly once and stops", async () => {
    const tracks = Array.from({ length: 12 }, (_, i) => track(`t${i}`));
    playQueue(tracks, "top");
    await settle();

    const order = [];
    for (let i = 0; i < 12; i++) {
      order.push(currentTrack()?.title ?? null);
      el.fireEnded();
      await settle();
    }

    // Every track once, in order, and then silence.
    expect(order).toEqual(tracks.map((t) => t.title));
    expect(queue.state).toBe("idle");
    expect(queue.tracks).toEqual([]);
    expect(queue.index).toBe(-1);
    expect(currentTrack()).toBe(null);
  });

  it("does not restart when a stray ended arrives after the queue finished", async () => {
    playQueue([track("a")], "top");
    await settle();
    el.fireEnded();
    await settle();
    expect(queue.state).toBe("idle");

    // A late event from the element that just stopped must not revive it.
    el.fireEnded();
    await settle();

    expect(queue.state).toBe("idle");
    expect(queue.tracks).toEqual([]);
    expect(queue.problem).toBe("");
  });

  it("restarts cleanly when the same source is played again", async () => {
    playQueue([track("a"), track("b")], "top");
    await settle();
    el.fireEnded();
    await settle();
    el.fireEnded();
    await settle();
    expect(queue.state).toBe("idle");

    playQueue([track("a"), track("b")], "top");
    await settle();

    expect(queue.index).toBe(0);
    expect(currentTrack().title).toBe("a");
  });
});

describe("failure handling", () => {
  it("skips a track whose play() rejects and keeps going", async () => {
    let calls = 0;
    setPlayImplementation(function () {
      calls += 1;
      // Only the first track is unplayable.
      if (calls === 1) return Promise.reject(new Error("NotAllowedError"));
      queueMicrotask(() => this.dispatchEvent(new Event("playing")));
      return Promise.resolve();
    });

    playQueue([track("bad"), track("good")], "news");
    await settle();

    expect(queue.index).toBe(1);
    expect(currentTrack().title).toBe("good");
    expect(queue.state).toBe("playing");
  });

  it("ends the queue rather than looping when every track fails", async () => {
    setPlayImplementation(() => Promise.reject(new Error("nope")));

    playQueue([track("a"), track("b"), track("c")], "news");
    await settle();

    expect(queue.state).toBe("idle");
    expect(queue.tracks).toEqual([]);
  });

  it("reports a problem when a queue plays nothing at all", async () => {
    // 17 dead URLs skip past in a fraction of a second; without this the only
    // feedback is a flicker, which reads as a dead button.
    setPlayImplementation(() => Promise.reject(new Error("nope")));

    playQueue([track("a"), track("b")], "news");
    await settle();

    expect(queue.problem).toMatch(/None of those summaries/);
  });

  it("says so in the singular for a one-track queue", async () => {
    setPlayImplementation(() => Promise.reject(new Error("nope")));

    playQueue([track("a")], "news");
    await settle();

    expect(queue.problem).toMatch(/That summary/);
  });

  it("stays quiet when at least one track played", async () => {
    let calls = 0;
    setPlayImplementation(function () {
      calls += 1;
      if (calls === 1) {
        queueMicrotask(() => this.dispatchEvent(new Event("playing")));
        return Promise.resolve();
      }
      return Promise.reject(new Error("nope"));
    });

    playQueue([track("a"), track("b")], "news");
    await settle();
    // Finish the one track that worked; the rest fail.
    el.fireEnded();
    await settle();

    expect(queue.problem).toBe("");
  });

  it("clears the problem when the next queue starts", async () => {
    setPlayImplementation(() => Promise.reject(new Error("nope")));
    playQueue([track("a")], "news");
    await settle();
    expect(queue.problem).not.toBe("");

    setPlayImplementation(function () {
      queueMicrotask(() => this.dispatchEvent(new Event("playing")));
      return Promise.resolve();
    });
    playQueue([track("b")], "news");
    await settle();

    expect(queue.problem).toBe("");
  });
});

describe("channel ownership", () => {
  it("stops the queue when a card claims playback", async () => {
    playQueue([track("a"), track("b")], "news");
    await settle();
    expect(queue.state).toBe("playing");

    // What ListenButton does on click.
    const cardStop = vi.fn();
    claimPlayback(cardStop);

    expect(queue.state).toBe("idle");
    expect(queue.tracks).toEqual([]);
    // The card's own stop must not have been called — it is the new owner.
    expect(cardStop).not.toHaveBeenCalled();
  });

  it("skips to the next track on demand", async () => {
    playQueue([track("a"), track("b")], "news");
    await settle();

    skipTrack();
    await settle();

    expect(currentTrack().title).toBe("b");
  });

  it("does nothing when skipping an idle queue", () => {
    skipTrack();
    expect(queue.state).toBe("idle");
    expect(queue.index).toBe(-1);
  });
});
