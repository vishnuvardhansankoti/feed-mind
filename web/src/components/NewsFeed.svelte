<script>
  // News section: Latest (newest day that has articles) + Archive (whole
  // window), each split by category tab. All slicing is client-side over the
  // single `articles` list handed in by App (newest first).
  import { NEWS_CATEGORIES } from "../lib/constants.js";
  import ArticleCard from "./ArticleCard.svelte";
  import { isFollowed } from "../lib/follows.svelte.js";

  let { articles = [] } = $props();

  let view = $state("latest"); // "latest" | "archive"
  let cat = $state(NEWS_CATEGORIES[0].code);

  const dayFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });

  // Articles in the selected category, minus any source the user switched off
  // (see lib/follows.svelte.js — everything is followed unless signed in and
  // explicitly unfollowed, so the public feed is unchanged).
  let inCat = $derived(
    articles.filter((a) => a.feed_category === cat && isFollowed("news", a.feed_source)),
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
</script>

<div class="news">
  <div class="subtabs" role="tablist" aria-label="News window">
    <button role="tab" aria-selected={view === "latest"} class:active={view === "latest"} onclick={() => (view = "latest")}>
      Latest
    </button>
    <button role="tab" aria-selected={view === "archive"} class:active={view === "archive"} onclick={() => (view = "archive")}>
      Archive · 7 days
    </button>
  </div>

  <div class="cats" role="tablist" aria-label="News category">
    {#each NEWS_CATEGORIES as c (c.code)}
      <button role="tab" aria-selected={cat === c.code} class:active={cat === c.code} onclick={() => (cat = c.code)}>
        {c.label}
      </button>
    {/each}
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
    <p class="empty">No articles this week.</p>
  {/if}
</div>

<style>
  .news { display: flex; flex-direction: column; gap: 1rem; }
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
