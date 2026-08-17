<script>
  // Videos section: Latest (newest day that has videos) + Archive (whole
  // 3-day window). All slicing is client-side over the single `videos` list
  // handed in by App (newest first).
  import VideoCard from "./VideoCard.svelte";

  let { videos = [] } = $props();

  let view = $state("latest"); // "latest" | "archive"

  const dayFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });

  // Group into calendar-day buckets, preserving newest-first order.
  let days = $derived.by(() => {
    const groups = [];
    let current = null;
    for (const v of videos) {
      const d = v.published_date;
      const key = d instanceof Date && !isNaN(d) ? d.toDateString() : "unknown";
      if (!current || current.key !== key) {
        current = { key, date: d, items: [] };
        groups.push(current);
      }
      current.items.push(v);
    }
    return groups;
  });

  // Latest = just the newest day bucket; Archive = every bucket in the window.
  let shownDays = $derived(view === "latest" ? days.slice(0, 1) : days);
</script>

<div class="videos">
  <div class="subtabs" role="tablist" aria-label="Videos window">
    <button role="tab" aria-selected={view === "latest"} class:active={view === "latest"} onclick={() => (view = "latest")}>
      Latest
    </button>
    <button role="tab" aria-selected={view === "archive"} class:active={view === "archive"} onclick={() => (view = "archive")}>
      Archive · 3 days
    </button>
  </div>

  {#if shownDays.length}
    {#each shownDays as group (group.key)}
      <section class="day-group">
        {#if view === "archive"}
          <div class="day-date">{group.date ? dayFmt.format(group.date) : "—"}</div>
        {/if}
        <div class="grid">
          {#each group.items as video (video.video_id)}
            <VideoCard {video} />
          {/each}
        </div>
      </section>
    {/each}
  {:else}
    <p class="empty">No new videos from your subscriptions.</p>
  {/if}
</div>

<style>
  .videos { display: flex; flex-direction: column; gap: 1rem; }
  .subtabs { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .subtabs button {
    font: inherit; cursor: pointer;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
    font-size: 0.85rem; padding: 0.4rem 1rem; border-radius: 999px;
  }
  .subtabs button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

  .day-group { display: flex; flex-direction: column; gap: 0.6rem; }
  .day-date {
    font-size: 0.75rem; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em; margin-top: 0.5rem;
  }
  .grid {
    display: grid; gap: 0.9rem;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    align-items: start;
  }
  .empty {
    color: var(--muted); font-size: 0.85rem; padding: 0.75rem;
    border: 1px dashed var(--border); border-radius: var(--radius); text-align: center;
  }
</style>
