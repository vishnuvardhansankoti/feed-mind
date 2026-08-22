<script>
  // One ranked paper. Handles the null-summary state (PRD §3.3 / §3.5).
  let { paper } = $props();
</script>

<article class="card">
  <div class="rank">#{paper.rank}</div>
  <div class="body">
    <h3 class="title">
      <a href={paper.url} target="_blank" rel="noopener noreferrer">{paper.title}</a>
    </h3>
    <div class="meta">
      <span class="arxiv">{paper.arxiv_id}</span>
      <span class="score" title="cosine similarity to the interest profile">
        match {(paper.score * 100).toFixed(0)}%
      </span>
    </div>
    {#if paper.summary}
      <p class="summary">{paper.summary}</p>
    {:else}
      <p class="summary muted">Summary unavailable for this paper.</p>
    {/if}
    <!-- The author's abstract, verbatim from arXiv. Absent on docs written
         before the pipeline persisted it, so it's collapsed and optional. -->
    {#if paper.abstract}
      <details class="abstract">
        <summary>Abstract</summary>
        <p>{paper.abstract}</p>
      </details>
    {/if}
  </div>
</article>

<style>
  .card {
    display: flex;
    gap: 0.85rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0.9rem 1rem;
  }
  .rank {
    flex: 0 0 auto;
    font-weight: 700;
    font-size: 0.8rem;
    color: var(--accent);
    background: var(--surface-2);
    border-radius: 999px;
    height: 1.9rem;
    min-width: 1.9rem;
    display: grid;
    place-items: center;
    padding: 0 0.4rem;
  }
  .body { min-width: 0; }
  .title { margin: 0 0 0.35rem; font-size: 0.98rem; font-weight: 600; }
  .meta {
    display: flex;
    gap: 0.75rem;
    font-size: 0.75rem;
    color: var(--muted);
    margin-bottom: 0.4rem;
  }
  .score { color: var(--accent); }
  .summary { margin: 0; font-size: 0.88rem; color: var(--text); }
  .summary.muted { color: var(--muted); font-style: italic; }
  .abstract { margin-top: 0.5rem; font-size: 0.82rem; }
  .abstract summary {
    cursor: pointer;
    color: var(--muted);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .abstract summary:hover { color: var(--accent); }
  .abstract p { margin: 0.4rem 0 0; color: var(--muted); line-height: 1.5; }
</style>
