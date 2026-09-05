<script>
  // Starts a queue of spoken summaries. Renders nothing when there is no audio
  // to play — the same rule ListenButton follows on a card, so a section with
  // no generated audio (Videos, and Saved until snapshots carry audio_url)
  // simply has no control rather than a dead one.
  import { queue, playQueue, stopQueue } from "../lib/audio.svelte.js";

  // `id` identifies this button's queue, so only the button that started the
  // running queue flips to Stop.
  let { tracks = [], id, label = "Listen All", compact = false } = $props();

  let mine = $derived(queue.state !== "idle" && queue.source === id);

  function toggle() {
    if (mine) stopQueue();
    else playQueue(tracks, id);
  }
</script>

{#if tracks.length}
  <button
    class="listen-all"
    class:playing={mine}
    class:compact
    type="button"
    onclick={toggle}
    aria-label={mine
      ? `Stop playing ${label}`
      : `${label}, ${tracks.length} audio ${tracks.length === 1 ? "summary" : "summaries"}`}
  >
    <span class="icon" aria-hidden="true">{mine ? "■" : "▶"}</span>
    {mine ? "Stop" : label}
    {#if !mine}<span class="count">{tracks.length}</span>{/if}
  </button>
{/if}

<style>
  .listen-all {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font: inherit;
    font-size: 0.78rem;
    cursor: pointer;
    color: var(--accent);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.2rem 0.7rem;
    white-space: nowrap;
  }
  .listen-all:hover { border-color: var(--accent); }
  .listen-all.playing {
    border-color: var(--accent);
    background: var(--accent);
    color: #fff;
  }
  .listen-all.compact { font-size: 0.72rem; padding: 0.15rem 0.6rem; }
  .icon { font-size: 0.62rem; line-height: 1; }
  .count {
    font-size: 0.68rem;
    font-family: ui-monospace, monospace;
    opacity: 0.75;
    border-left: 1px solid currentColor;
    padding-left: 0.35rem;
    margin-left: 0.1rem;
  }
</style>
