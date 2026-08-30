// The app's single audio channel.
//
// Two kinds of playback compete for it: one card's ListenButton, and a queue
// started by "Listen All" / "Listen Top Summaries". They must never overlap, so
// both claim the same slot here — starting a queue stops a card mid-clip, and
// starting a card stops the queue. One owner, no races.
//
// This used to be a `<script module>` block inside ListenButton.svelte, which
// was enough while a card was the only thing that could play. A queue is a
// second kind of owner and needs state the whole app can read (the mini-player
// renders it), so the arbiter moved here.
//
// Cards still own their own <audio> element, built lazily on first click — a
// feed page holds ~200 of them and eager elements would mean 200 media
// requests. This module only arbitrates *who* holds the channel. The queue has
// a single element of its own, reused across tracks.

/**
 * The running queue.
 *
 * `source` is an opaque id naming the button that started it, so that button
 * can render as Stop while its own queue plays without every other Listen All
 * button on the page doing the same.
 */
export const queue = $state({
  /** [{ url, title, context }] */
  tracks: [],
  index: -1,
  /** idle | loading | playing */
  state: "idle",
  source: null,
  /**
   * Set when a queue ended without a single track having played — every URL
   * was unreachable. Without it the whole queue skips past in a fraction of a
   * second and the only feedback is a flicker, which reads as a dead button.
   * Cleared when the next queue starts.
   */
  problem: "",
});

let releaseCurrent = null;

/** Take the channel, stopping whoever held it. */
export function claimPlayback(stop) {
  if (releaseCurrent && releaseCurrent !== stop) releaseCurrent();
  releaseCurrent = stop;
}

/** Give the channel back — but only if this holder still owns it. */
export function releasePlayback(stop) {
  if (releaseCurrent === stop) releaseCurrent = null;
}

let el = null;

/** Whether the running queue has managed to play anything at all. */
let playedAny = false;

function element() {
  if (el) return el;
  el = new Audio();
  el.preload = "none";
  el.addEventListener("playing", () => {
    if (queue.state === "idle") return;
    playedAny = true;
    queue.state = "playing";
  });
  el.addEventListener("ended", () => advance());
  // A dead storage object surfaces as an `error` event rather than a rejected
  // play(). One bad track must not end the queue — skip it exactly as if it had
  // finished. The idle guard keeps a late event from reviving a stopped queue.
  el.addEventListener("error", () => {
    if (queue.state !== "idle") advance();
  });
  return el;
}

/**
 * Move to the next track, or stop when the queue runs out. Each call advances
 * the index, so even a queue where every track fails terminates.
 */
async function advance() {
  const next = queue.index + 1;
  if (next >= queue.tracks.length) {
    // Read the length before stopQueue() clears it.
    const total = queue.tracks.length;
    const nothingPlayed = !playedAny && total > 0;
    stopQueue();
    if (nothingPlayed) {
      queue.problem =
        total === 1
          ? "That summary couldn’t be played."
          : "None of those summaries could be played.";
    }
    return;
  }
  queue.index = next;
  queue.state = "loading";

  const a = element();
  a.pause();
  a.src = queue.tracks[next].url;
  try {
    await a.play();
  } catch {
    // Autoplay refusal or an unreachable object — same dead end either way, and
    // the same handling as a track that finished.
    if (queue.state !== "idle") advance();
  }
}

/** Stop and clear the queue. Also the token this module claims the channel with. */
export function stopQueue() {
  el?.pause();
  queue.tracks = [];
  queue.index = -1;
  queue.state = "idle";
  queue.source = null;
  releasePlayback(stopQueue);
}

/**
 * Start playing `tracks` in order. An empty list is a no-op — callers decide
 * whether to render a control at all, the same way ListenButton is only
 * rendered when there is a URL to play.
 */
export function playQueue(tracks, source = null) {
  if (!tracks?.length) return;
  claimPlayback(stopQueue);
  queue.problem = "";
  playedAny = false;
  queue.tracks = tracks;
  queue.index = -1;
  queue.source = source;
  advance();
}

/** Dismiss the "couldn't play" notice. */
export function clearProblem() {
  queue.problem = "";
}

/** Jump to the next track. No-op when nothing is queued. */
export function skipTrack() {
  if (queue.state !== "idle") advance();
}

/** The track now playing, or null. */
export function currentTrack() {
  return queue.tracks[queue.index] ?? null;
}
