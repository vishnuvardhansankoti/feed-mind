<script>
  // Play button for a spoken summary hosted in Cloud Storage. Render it only
  // when `url` is non-empty — the caller decides, since an absent audio_url is
  // a normal state on docs written before the pipeline generated audio.
  //
  // Only one thing plays at a time across the whole app. That guard used to
  // live in this file's `<script module>` block, back when a card was the only
  // possible player; it now lives in lib/audio.svelte.js, which also arbitrates
  // the queues behind "Listen All". Starting a card stops a running queue and
  // vice versa — same slot, one owner.
  import { onDestroy } from "svelte";
  import { claimPlayback, releasePlayback } from "../lib/audio.svelte.js";

  // `label` names the thing being read aloud; it only reaches screen readers.
  let { url, label = "" } = $props();

  // The <audio> element is created on first play, not on render: a feed page
  // holds ~200 cards and we do not want 200 pending media requests.
  let audio = null;
  let playState = $state("idle"); // idle | loading | playing | error

  const LABELS = {
    idle: "Listen",
    loading: "Loading…",
    playing: "Pause",
    error: "Audio unavailable",
  };

  function stop() {
    audio?.pause();
    if (playState !== "error") playState = "idle";
    releasePlayback(stop);
  }

  async function toggle() {
    if (playState === "playing" || playState === "loading") {
      stop();
      return;
    }
    if (!audio) {
      audio = new Audio(url);
      audio.preload = "none";
      audio.addEventListener("playing", () => (playState = "playing"));
      audio.addEventListener("pause", () => {
        if (playState === "playing") playState = "idle";
      });
      audio.addEventListener("ended", () => {
        playState = "idle";
        releasePlayback(stop);
      });
      audio.addEventListener("error", () => (playState = "error"));
    }
    claimPlayback(stop);
    playState = "loading";
    try {
      await audio.play();
    } catch {
      // Autoplay rejection or an unreachable object — same dead end either way.
      playState = "error";
    }
  }

  onDestroy(stop);
</script>

<button
  class="listen"
  class:playing={playState === "playing"}
  class:failed={playState === "error"}
  onclick={toggle}
  disabled={playState === "error"}
  aria-label="{LABELS[playState]} audio summary of {label}"
>
  <span class="icon" aria-hidden="true">
    {playState === "playing" ? "❚❚" : playState === "error" ? "⚠" : "▶"}
  </span>
  {LABELS[playState]}
</button>

<style>
  .listen {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font: inherit;
    font-size: 0.72rem;
    cursor: pointer;
    color: var(--accent);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.1rem 0.55rem;
  }
  .listen:hover:not(:disabled) { border-color: var(--accent); }
  .listen.playing { border-color: var(--accent); }
  .listen.failed { color: var(--muted); cursor: default; }
  .listen .icon { font-size: 0.62rem; line-height: 1; }
</style>
