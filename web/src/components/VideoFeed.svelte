<script>
  // Videos section: Latest (the most recent ingest batch) + Archive (whole
  // 3-day window, bucketed by calendar day). All slicing is client-side over
  // the single `videos` list handed in by App (newest first).
  import VideoCard from "./VideoCard.svelte";
  import { latestBatch } from "../lib/videos.js";
  import { isFollowed } from "../lib/follows.svelte.js";

  let { videos: allVideos = [] } = $props();

  // Channel filter runs BEFORE the batch is picked, so unfollowing a channel
  // shrinks the latest batch rather than changing which batch counts as latest
  // — filtering afterwards could empty Latest entirely while an older batch
  // sat right below it in Archive.
  let videos = $derived(allVideos.filter((v) => isFollowed("video", v.channel)));

  let view = $state("latest"); // "latest" | "archive"

  const dayFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });

  // Latest = the newest ingest batch (see lib/videos.js): stable until
  // feed-mind runs again, rather than shrinking as the day wears on.
  let latestItems = $derived(latestBatch(videos));

  const isDate = (d) => d instanceof Date && !isNaN(d);

  // Archive groups into calendar-day buckets, preserving newest-first order.
  let days = $derived.by(() => {
    const groups = [];
    let current = null;
    for (const v of videos) {
      const d = v.published_date;
      const key = isDate(d) ? d.toDateString() : "unknown";
      if (!current || current.key !== key) {
        current = { key, date: d, items: [] };
        groups.push(current);
      }
      current.items.push(v);
    }
    return groups;
  });

  // Both views render as day groups; Latest is one unlabelled group.
  let shownDays = $derived(
    view === "latest"
      ? (latestItems.length ? [{ key: "latest", date: null, items: latestItems }] : [])
      : days
  );
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
          <!-- isDate, not truthiness: an Invalid Date is truthy and makes
               Intl.DateTimeFormat throw, taking the whole render down. -->
          <div class="day-date">{isDate(group.date) ? dayFmt.format(group.date) : "—"}</div>
        {/if}
        <div class="grid">
          {#each group.items as video (video.video_id)}
            <VideoCard {video} />
          {/each}
        </div>
      </section>
    {/each}
  {:else}
    <p class="empty">
      {#if view === "latest" && days.length}
        No videos carry an ingest timestamp — check Archive.
      {:else}
        No new videos from your subscriptions.
      {/if}
    </p>
  {/if}
</div>

<style>
  .videos { display: flex; flex-direction: column; gap: 1rem; }

  /* Same sticky bar as the other sections: pins under App's masthead + section
     nav (--stick-top), with zero-blur shadows extending its background over the
     gaps above and below so cards passing underneath don't show through. */
  .subtabs {
    display: flex; gap: 0.4rem; flex-wrap: wrap;
    position: sticky; top: var(--stick-top, 0px); z-index: 11;
    background: var(--bg);
    box-shadow: 0 -1.25rem 0 var(--bg), 0 0.6rem 0 var(--bg);
  }
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
