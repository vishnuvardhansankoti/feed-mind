<script>
  // One news article from the `processed_articles` collection. `summary` may be
  // empty on docs written before feed-mind persisted it — degrade quietly.
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
  </div>
  {#if article.summary}
    <p class="summary">{article.summary}</p>
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
    gap: 0.75rem;
    font-size: 0.75rem;
    color: var(--muted);
  }
  .source { color: var(--accent); }
  .summary { margin: 0.4rem 0 0; font-size: 0.88rem; color: var(--text); }
</style>
