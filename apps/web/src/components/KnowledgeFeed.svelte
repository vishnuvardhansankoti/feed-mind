<script>
  // Knowledge Bytes section: Latest (newest day that has articles) + Archive
  // (whole window), each split by series tab (AI/ML, DSA). Structurally a copy
  // of NewsFeed.svelte's Latest/Archive + category-tab pattern — this repo's
  // established convention is duplicating this shape per section rather than
  // generalizing it (see NewsFeed/StoriesFeed/VideoFeed). All slicing is
  // client-side over the single `articles` list handed in by App (newest
  // first). Source follow/unfollow lives in SettingsSheet, same "kind" scheme
  // as News/Videos/Stories — muting a series' feed_source here just hides that
  // tab's items, which today means the whole tab, since each series has one.
  import { KNOWLEDGE_CATEGORIES } from "../lib/constants.js";
  import { isFollowed } from "../lib/follows.svelte.js";
  import ArticleCard from "./ArticleCard.svelte";
  import ListenAllButton from "./ListenAllButton.svelte";
  import { tracksFrom } from "../lib/playlists.js";

  let { articles = [] } = $props();

  let view = $state("latest"); // "latest" | "archive"
  let cat = $state(KNOWLEDGE_CATEGORIES[0].code);

  const dayFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });

  let inCat = $derived(
    articles.filter((a) => a.feed_category === cat && isFollowed("knowledge", a.feed_source)),
  );

  // Group into calendar-day buckets, preserving newest-first order.
  let days = $derived.by(() => {
    const groups = [];
    let current = null;
    for (const a of inCat) {
      const d = a.processed_date;
      const key = d instanceof Date && !isNaN(d) ? d.toDateString() : "unknown";
      if (!current || current.key !== key) {
        current = { key, date: d, items: [] };
        groups.push(current);
      }
      current.items.push(a);
    }
    return groups;
  });

  // Latest = just the newest day bucket; Archive = every bucket in the window.
  let shownDays = $derived(view === "latest" ? days.slice(0, 1) : days);

  let catLabel = $derived(KNOWLEDGE_CATEGORIES.find((c) => c.code === cat)?.label ?? "");
  let visible = $derived(shownDays.flatMap((g) => g.items));
  let tracks = $derived(tracksFrom(visible, catLabel));
</script>

<div class="knowledge">
  <div class="controls">
    <div class="subtabs" role="tablist" aria-label="Knowledge Bytes window">
      <button role="tab" aria-selected={view === "latest"} class:active={view === "latest"} onclick={() => (view = "latest")}>
        Latest
      </button>
      <button role="tab" aria-selected={view === "archive"} class:active={view === "archive"} onclick={() => (view = "archive")}>
        Archive · 7 days
      </button>
    </div>

    <div class="cats" role="tablist" aria-label="Knowledge Bytes series">
      {#each KNOWLEDGE_CATEGORIES as c (c.code)}
        <button role="tab" aria-selected={cat === c.code} class:active={cat === c.code} onclick={() => (cat = c.code)}>
          {c.label}
        </button>
      {/each}
    </div>

    <div class="listen">
      <ListenAllButton {tracks} id={`knowledge:${cat}:${view}`} label="Listen All" />
    </div>
  </div>

  {#if shownDays.length}
    {#each shownDays as group (group.key)}
      <section class="day-group">
        {#if view === "archive"}
          <div class="day-date">{group.date ? dayFmt.format(group.date) : "—"}</div>
        {/if}
        {#each group.items as article (article.article_id)}
          <ArticleCard {article} />
        {/each}
      </section>
    {/each}
  {:else}
    <p class="empty">No new {catLabel} lessons this week.</p>
  {/if}
</div>

<style>
  .knowledge { display: flex; flex-direction: column; gap: 1rem; }

  /* Pins directly below App's sticky content-pane top bar, same convention as
     NewsFeed's .controls. */
  .controls {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: 0.7rem 0.75rem;
    position: sticky; top: var(--stick-top, 0px); z-index: 11;
    background: var(--bg);
    box-shadow: 0 -1.25rem 0 var(--bg), 0 0.6rem 0 var(--bg);
  }
  .subtabs { grid-column: 1 / -1; }
  .cats { grid-column: 1; min-width: 0; }
  .listen { grid-column: 2; justify-self: end; }

  .subtabs, .cats { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .subtabs button, .cats button {
    font: inherit; cursor: pointer;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
  }
  .subtabs button {
    font-size: 0.85rem; padding: 0.4rem 1rem; border-radius: 999px;
  }
  .cats button {
    font-size: 0.8rem; padding: 0.35rem 0.85rem; border-radius: 8px;
  }
  .subtabs button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .cats button.active { background: var(--surface-2); color: var(--text); border-color: var(--accent); }

  @media (max-width: 700px) {
    .subtabs { grid-column: 1; }
    .listen { grid-row: 1; grid-column: 2; }
    .cats {
      grid-column: 1 / -1;
      flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
    }
    .cats::-webkit-scrollbar { display: none; }
    .cats button { flex: 0 0 auto; }
  }

  .day-group { display: flex; flex-direction: column; gap: 0.6rem; }
  .day-date {
    font-size: 0.75rem; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em; margin-top: 0.5rem;
  }
  .empty {
    color: var(--muted); font-size: 0.85rem; padding: 0.75rem;
    border: 1px dashed var(--border); border-radius: var(--radius); text-align: center;
  }
</style>
