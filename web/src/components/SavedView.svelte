<script>
  // The Saved section (#/saved). Renders the stored snapshots directly — no
  // fetch, no joins, no source documents involved. That's the payoff of storing
  // copies: a saved paper still renders long after its run doc has expired.
  import { bookmarks, removeSaved } from "../lib/bookmarks.svelte.js";
  import { BOOKMARK_LIMIT } from "../lib/constants.js";

  const dateFmt = new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric",
  });

  const GROUPS = [
    { type: "paper", label: "Papers" },
    { type: "news", label: "News" },
    { type: "video", label: "Videos" },
  ];

  // Only non-empty groups get a heading, so a list of three videos doesn't
  // render two empty sections above it.
  let groups = $derived(
    GROUPS.map((g) => ({ ...g, items: bookmarks.items.filter((b) => b.type === g.type) }))
      .filter((g) => g.items.length),
  );

  function savedOn(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : dateFmt.format(d);
  }

  let removing = $state(null);

  async function remove(id) {
    removing = id;
    try {
      await removeSaved(id);
    } finally {
      removing = null;
    }
  }
</script>

<div class="saved">
  <div class="count">
    {bookmarks.items.length} of {BOOKMARK_LIMIT} saved
  </div>

  {#if bookmarks.loading}
    <p class="empty">Loading your saved items…</p>
  {:else if bookmarks.error}
    <p class="empty err">Couldn’t load your saved items: {bookmarks.error}</p>
  {:else if !bookmarks.items.length}
    <p class="empty">
      Nothing saved yet. Use the ☆ on any paper, article, or video to keep it here.
    </p>
  {:else}
    {#each groups as group (group.type)}
      <section class="group">
        <h2>{group.label} <span class="n">({group.items.length})</span></h2>
        {#each group.items as item (item.id)}
          <article class="card">
            {#if item.thumbnail_url}
              <img class="thumb" src={item.thumbnail_url} alt="" loading="lazy" />
            {/if}
            <div class="body">
              <h3 class="title">
                <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a>
              </h3>
              <div class="meta">
                {#if item.arxiv_id}<span>{item.arxiv_id}</span>{/if}
                {#if item.feed_source}<span>{item.feed_source}</span>{/if}
                {#if item.channel}<span>{item.channel}</span>{/if}
                {#if savedOn(item.saved_at)}<span>saved {savedOn(item.saved_at)}</span>{/if}
              </div>
              {#if item.summary}<p class="summary">{item.summary}</p>{/if}
            </div>
            <button
              type="button"
              class="remove"
              disabled={removing === item.id}
              aria-label={`Remove “${item.title}” from saved`}
              onclick={() => remove(item.id)}
            >
              ✕
            </button>
          </article>
        {/each}
      </section>
    {/each}
  {/if}
</div>

<style>
  .saved { display: flex; flex-direction: column; gap: 1rem; }
  .count { font-size: 0.78rem; color: var(--muted); }

  .group { display: flex; flex-direction: column; gap: 0.6rem; }
  .group h2 {
    margin: 0.5rem 0 0; font-size: 1rem;
    border-bottom: 1px solid var(--border); padding-bottom: 0.4rem;
  }
  .n { color: var(--muted); font-weight: 400; font-size: 0.85rem; }

  .card {
    display: flex; gap: 0.85rem; align-items: flex-start;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 0.9rem 1rem;
  }
  .thumb {
    flex: 0 0 auto; width: 110px; aspect-ratio: 16 / 9;
    object-fit: cover; border-radius: calc(var(--radius) - 3px);
  }
  .body { flex: 1 1 auto; min-width: 0; }
  .title { margin: 0 0 0.35rem; font-size: 0.98rem; font-weight: 600; }
  .title a { color: inherit; text-decoration: none; }
  .title a:hover { text-decoration: underline; }
  .meta {
    display: flex; gap: 0.75rem; flex-wrap: wrap;
    font-size: 0.75rem; color: var(--muted);
  }
  .summary { margin: 0.45rem 0 0; font-size: 0.85rem; line-height: 1.5; }

  .remove {
    flex: 0 0 auto; font: inherit; font-size: 0.85rem; cursor: pointer;
    padding: 0.2rem 0.4rem; background: none; border: none; color: var(--muted);
  }
  .remove:hover:not(:disabled) { color: var(--warn); }
  .remove:disabled { opacity: 0.5; cursor: default; }

  .empty {
    color: var(--muted); font-size: 0.85rem; padding: 0.75rem;
    border: 1px dashed var(--border); border-radius: var(--radius); text-align: center;
  }
  .empty.err { color: var(--warn); }
</style>
