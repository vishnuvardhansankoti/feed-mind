<script>
  // Stories section: curated stories split by country toggle and category
  // tab, each with a Latest/Archive window like NewsFeed and VideoFeed.
  // data.js now hands over the whole STORY_ARCHIVE_WINDOW_DAYS window per
  // (country, category), sorted newest run_date first (see getStories) —
  // this component groups it into day buckets client-side, same shape as
  // NewsFeed's `days`/`shownDays`. Both countries are fetched eagerly, so
  // switching any of the three tabs is a client-side re-slice, not a fetch.
  import { STORY_CATEGORIES, NEWS_COUNTRIES } from "../lib/constants.js";
  import StoryCard from "./StoryCard.svelte";
  import ListenAllButton from "./ListenAllButton.svelte";
  import { tracksFrom } from "../lib/playlists.js";

  let { stories = {} } = $props();

  let country = $state(NEWS_COUNTRIES[0].code);
  let cat = $state(STORY_CATEGORIES[0].code);
  let view = $state("latest"); // "latest" | "archive"

  const dayFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric", timeZone: "UTC",
  });

  let inCountry = $derived(stories[country] ?? {});
  let inCat = $derived(inCountry[cat] ?? []);
  let catLabel = $derived(STORY_CATEGORIES.find((c) => c.code === cat)?.label ?? "");
  let countryLabel = $derived(NEWS_COUNTRIES.find((c) => c.code === country)?.label ?? "");

  // Group into calendar-day buckets, preserving the newest-first order
  // data.js already sorted them into — run_date is a plain "YYYY-MM-DD"
  // string (see the root CLAUDE.md), so equality is enough to bucket by day,
  // no Date parsing needed until display.
  let days = $derived.by(() => {
    const groups = [];
    let current = null;
    for (const s of inCat) {
      const key = s.run_date || "unknown";
      if (!current || current.key !== key) {
        current = { key, items: [] };
        groups.push(current);
      }
      current.items.push(s);
    }
    return groups;
  });

  // Latest = just the newest day bucket; Archive = every bucket in the window.
  let shownDays = $derived(view === "latest" ? days.slice(0, 1) : days);

  // Listen All plays exactly what is on screen: this country, this category,
  // this window, in display order — keyed by all three tabs so switching any
  // one gives the button a fresh queue identity.
  let visible = $derived(shownDays.flatMap((g) => g.items));
  let tracks = $derived(tracksFrom(visible, catLabel));
</script>

<div class="stories">
  <div class="controls">
    <div class="countries" role="tablist" aria-label="News country">
      {#each NEWS_COUNTRIES as c (c.code)}
        <button role="tab" aria-selected={country === c.code} class:active={country === c.code} onclick={() => (country = c.code)}>
          {c.label}
        </button>
      {/each}
    </div>

    <div class="subtabs" role="tablist" aria-label="Stories window">
      <button role="tab" aria-selected={view === "latest"} class:active={view === "latest"} onclick={() => (view = "latest")}>
        Latest
      </button>
      <button role="tab" aria-selected={view === "archive"} class:active={view === "archive"} onclick={() => (view = "archive")}>
        Archive · 3 days
      </button>
    </div>

    <div class="cats" role="tablist" aria-label="Story category">
      {#each STORY_CATEGORIES as c (c.code)}
        <button role="tab" aria-selected={cat === c.code} class:active={cat === c.code} onclick={() => (cat = c.code)}>
          {c.label}
        </button>
      {/each}
    </div>

    <div class="listen">
      <ListenAllButton {tracks} id={`stories:${country}:${cat}:${view}`} label="Listen All" />
    </div>
  </div>

  {#if shownDays.length}
    {#each shownDays as group (group.key)}
      <section class="day-group">
        {#if view === "archive"}
          <div class="day-date">
            {group.key === "unknown" ? "—" : dayFmt.format(new Date(group.key))}
          </div>
        {/if}
        {#each group.items as story (story.story_id)}
          <StoryCard {story} />
        {/each}
      </section>
    {/each}
  {:else}
    <p class="empty">No {countryLabel} {catLabel.toLowerCase()} stories yet.</p>
  {/if}
</div>

<style>
  .stories { display: flex; flex-direction: column; gap: 1rem; }

  /* Pins directly below App's sticky content-pane top bar, same convention
     as NewsFeed's .controls. Three tab rows stacked (country, then window,
     then category) — same grid shape as NewsFeed's subtabs+cats, just one
     more axis. */
  .controls {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    gap: 0.7rem 0.75rem;
    position: sticky; top: var(--stick-top, 0px); z-index: 11;
    background: var(--bg);
    box-shadow: 0 -1.25rem 0 var(--bg), 0 0.6rem 0 var(--bg);
  }
  .countries { grid-column: 1 / -1; display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .subtabs { grid-column: 1 / -1; display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .cats { grid-column: 1; min-width: 0; display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .listen { grid-column: 2; justify-self: end; }

  .countries button {
    font: inherit; font-size: 0.85rem; cursor: pointer;
    padding: 0.4rem 1rem; border-radius: 999px;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
  }
  .countries button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

  .subtabs button {
    font: inherit; font-size: 0.85rem; cursor: pointer;
    padding: 0.4rem 1rem; border-radius: 999px;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
  }
  .subtabs button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

  .cats button {
    font: inherit; font-size: 0.8rem; cursor: pointer;
    padding: 0.35rem 0.85rem; border-radius: 8px;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
  }
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

  /* Same trick as NewsFeed's mobile override, shifted one row down: countries
     stays its own full-width row (just 2 short pills, never wraps), .subtabs
     shrinks to column 1 so Listen All can share its row at column 2 instead
     of claiming a row of its own, and .cats — the widest tab group — gets a
     full-width scrolling row to itself below both. */
  @media (max-width: 700px) {
    .subtabs { grid-column: 1; }
    .listen { grid-row: 2; grid-column: 2; }
    .cats {
      grid-column: 1 / -1;
      flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
    }
    .cats::-webkit-scrollbar { display: none; }
    .cats button { flex: 0 0 auto; }
  }
</style>
