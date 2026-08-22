<script>
  // One news article from the `processed_articles` collection. `summary`,
  // `ai_summary` and `audio_url` may all be empty — on docs written before
  // feed-mind persisted them, and on the pinned `open-source` links, which have
  // no pipeline-generated content. Every one of them degrades to "not shown".
  import ListenButton from "./ListenButton.svelte";

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
      <ListenButton url={article.audio_url} label={article.title} />
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
