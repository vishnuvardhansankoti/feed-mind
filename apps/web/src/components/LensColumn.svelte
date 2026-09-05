<script>
  import PaperCard from "./PaperCard.svelte";
  // A lens heading + its ranked papers (handles the empty-window case, PRD §3.3).
  let { lens, run } = $props();
  let papers = $derived(run?.papers ?? []);
</script>

<section class="lens">
  <header>
    <h2>{lens.label}</h2>
    <span class="sources">{lens.sources}</span>
  </header>

  {#if papers.length}
    <div class="cards">
      {#each papers as paper (paper.arxiv_id)}
        <PaperCard {paper} />
      {/each}
    </div>
  {:else}
    <p class="empty">No papers in the window for this lens.</p>
  {/if}
</section>

<style>
  .lens { display: flex; flex-direction: column; gap: 0.75rem; }
  header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
    padding-bottom: 0.5rem;
    border-bottom: 2px solid var(--border);
  }
  h2 { margin: 0; font-size: 1.05rem; }
  .sources { font-size: 0.72rem; color: var(--muted); font-family: ui-monospace, monospace; }
  .cards { display: flex; flex-direction: column; gap: 0.75rem; }
  .empty {
    color: var(--muted);
    font-size: 0.88rem;
    padding: 1rem;
    border: 1px dashed var(--border);
    border-radius: var(--radius);
    text-align: center;
  }
</style>
