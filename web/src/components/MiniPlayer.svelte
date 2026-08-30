<script>
  // Controls for a running queue, pinned so they stay reachable after the
  // button that started the queue has scrolled away — or after the user has
  // moved to another section entirely, since playback deliberately survives
  // navigation.
  import { queue, skipTrack, stopQueue, clearProblem } from "../lib/audio.svelte.js";

  let track = $derived(queue.tracks[queue.index] ?? null);
  let position = $derived(`${queue.index + 1} of ${queue.tracks.length}`);
  let last = $derived(queue.index >= queue.tracks.length - 1);
</script>

{#if queue.problem}
  <div class="mini problem" role="alert">
    <span class="warn" aria-hidden="true">⚠</span>
    <div class="now"><span class="title">{queue.problem}</span></div>
    <div class="controls">
      <button type="button" onclick={clearProblem} aria-label="Dismiss">Dismiss</button>
    </div>
  </div>
{/if}

{#if queue.state !== "idle" && track}
  <div class="mini" role="region" aria-label="Audio queue">
    <span class="pulse" class:loading={queue.state === "loading"} aria-hidden="true"></span>

    <div class="now" aria-live="polite">
      <span class="title">{track.title || "Untitled"}</span>
      <span class="meta">
        {#if track.context}<span class="ctx">{track.context}</span>{/if}
        <span class="pos">{position}</span>
        {#if queue.state === "loading"}<span class="pos">loading…</span>{/if}
      </span>
    </div>

    <div class="controls">
      <button type="button" onclick={skipTrack} disabled={last} aria-label="Skip to next summary">
        Skip
      </button>
      <button type="button" class="stop" onclick={stopQueue} aria-label="Stop playing">
        Stop
      </button>
    </div>
  </div>
{/if}

<style>
  .mini {
    position: fixed;
    left: 50%;
    transform: translateX(-50%);
    bottom: 1rem;
    z-index: 40;
    width: min(560px, calc(100vw - 2rem));
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 0.55rem 0.8rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 999px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
  }

  .pulse {
    flex: none;
    width: 0.5rem;
    height: 0.5rem;
    border-radius: 50%;
    background: var(--accent);
  }
  .pulse.loading { opacity: 0.4; }

  .warn { flex: none; font-size: 0.8rem; }
  .problem .title { color: var(--muted); }

  .now { display: flex; flex-direction: column; min-width: 0; flex: 1; }
  .title {
    font-size: 0.82rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .meta {
    display: flex;
    gap: 0.5rem;
    font-size: 0.68rem;
    color: var(--muted);
    font-family: ui-monospace, monospace;
  }
  .ctx { color: var(--accent); }

  .controls { display: flex; gap: 0.35rem; flex: none; }
  .controls button {
    font: inherit;
    font-size: 0.72rem;
    cursor: pointer;
    color: var(--accent);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.15rem 0.6rem;
  }
  .controls button:hover:not(:disabled) { border-color: var(--accent); }
  .controls button:disabled { color: var(--muted); cursor: default; opacity: 0.6; }
  .controls .stop { color: var(--muted); }

  @media (max-width: 520px) {
    .mini { border-radius: var(--radius); }
    .title { font-size: 0.78rem; }
  }
</style>
