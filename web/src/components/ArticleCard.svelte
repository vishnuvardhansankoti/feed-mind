<script module>
  // Only one audio summary plays at a time across the whole feed: a card about
  // to play asks the previous one to stop. Module scope is shared by every
  // ArticleCard instance, so no store is needed.
  let stopCurrent = null;

  function claimPlayback(stop) {
    if (stopCurrent && stopCurrent !== stop) stopCurrent();
    stopCurrent = stop;
  }

  function releasePlayback(stop) {
    if (stopCurrent === stop) stopCurrent = null;
  }
</script>

<script>
  // One news article from the `processed_articles` collection. `summary`,
  // `ai_summary` and `audio_url` may all be empty — on docs written before
  // feed-mind persisted them, and on the pinned `open-source` links, which have
  // no pipeline-generated content. Every one of them degrades to "not shown".
  import { onDestroy } from "svelte";

  let { article } = $props();

  const dateFmt = new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric",
  });

  // Compact relative age ("2h", "3d") from the processed timestamp.
  function relAge(d) {
    if (!(d instanceof Date) || isNaN(d)) return "";
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86_400) return `${Math.floor(s / 3600)}h`;
    return `${Math.floor(s / 86_400)}d`;
  }

  // --- audio summary -------------------------------------------------------

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
      audio = new Audio(article.audio_url);
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

<article class="card">
  <h3 class="title">
    <a href={article.url} target="_blank" rel="noopener noreferrer">{article.title}</a>
  </h3>
  <div class="meta">
    <span class="source">{article.feed_source}</span>
    {#if article.processed_date}
      <span class="age" title={article.processed_date.toString()}>
        {dateFmt.format(article.processed_date)} · {relAge(article.processed_date)} ago
      </span>
    {/if}
    {#if article.audio_url}
      <button
        class="listen"
        class:playing={playState === "playing"}
        class:failed={playState === "error"}
        onclick={toggle}
        disabled={playState === "error"}
        aria-label="{LABELS[playState]} audio summary of {article.title}"
      >
        <span class="icon" aria-hidden="true">
          {playState === "playing" ? "❚❚" : playState === "error" ? "⚠" : "▶"}
        </span>
        {LABELS[playState]}
      </button>
    {/if}
  </div>
  {#if article.summary}
    <p class="summary">{article.summary}</p>
  {/if}
  {#if article.ai_summary}
    <details class="ai-summary">
      <summary>AI summary</summary>
      <p>{article.ai_summary}</p>
    </details>
  {/if}
</article>

<style>
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.9rem 1rem;
  }
  .title { margin: 0 0 0.35rem; font-size: 0.98rem; font-weight: 600; }
  .meta {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    font-size: 0.75rem;
    color: var(--muted);
  }
  .source { color: var(--accent); }
  .summary { margin: 0.4rem 0 0; font-size: 0.88rem; color: var(--text); }

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

  .ai-summary { margin-top: 0.5rem; font-size: 0.82rem; }
  .ai-summary summary {
    cursor: pointer;
    color: var(--muted);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .ai-summary summary:hover { color: var(--accent); }
  .ai-summary p { margin: 0.4rem 0 0; color: var(--muted); line-height: 1.5; }
</style>
