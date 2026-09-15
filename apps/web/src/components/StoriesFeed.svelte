<script>
  // Stories section: the newest curation run's ranked stories, split by
  // country toggle and category tab. Unlike NewsFeed there is no
  // Latest/Archive toggle — data.js already resolves `stories` down to one
  // {country: {category: cards}} map of the newest run per country,
  // rank-ordered (see getStories/latestRunOnly). Both countries are fetched
  // eagerly, so switching the toggle is a client-side re-slice, not a fetch.
  import { STORY_CATEGORIES, NEWS_COUNTRIES } from "../lib/constants.js";
  import StoryCard from "./StoryCard.svelte";
  import ListenAllButton from "./ListenAllButton.svelte";
  import { tracksFrom } from "../lib/playlists.js";

  let { stories = {} } = $props();

  let country = $state(NEWS_COUNTRIES[0].code);
  let cat = $state(STORY_CATEGORIES[0].code);

  let inCountry = $derived(stories[country] ?? {});
  let inCat = $derived(inCountry[cat] ?? []);
  let catLabel = $derived(STORY_CATEGORIES.find((c) => c.code === cat)?.label ?? "");
  let countryLabel = $derived(NEWS_COUNTRIES.find((c) => c.code === country)?.label ?? "");
  let tracks = $derived(tracksFrom(inCat, catLabel));

  // The run_date every visible card shares — there is exactly one per
  // (country, category) pair, since inCat is already sliced to the newest run.
  let runDate = $derived(inCat[0]?.run_date ?? "");
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

    <div class="cats" role="tablist" aria-label="Story category">
      {#each STORY_CATEGORIES as c (c.code)}
        <button role="tab" aria-selected={cat === c.code} class:active={cat === c.code} onclick={() => (cat = c.code)}>
          {c.label}
        </button>
      {/each}
    </div>

    <div class="listen">
      <ListenAllButton {tracks} id={`stories:${country}:${cat}`} label="Listen All" />
    </div>
  </div>

  {#if runDate}
    <div class="run-date">{runDate}</div>
  {/if}

  {#if inCat.length}
    <section class="story-list">
      {#each inCat as story (story.story_id)}
        <StoryCard {story} />
      {/each}
    </section>
  {:else}
    <p class="empty">No {countryLabel} {catLabel.toLowerCase()} stories yet.</p>
  {/if}
</div>

<style>
  .stories { display: flex; flex-direction: column; gap: 1rem; }

  /* Pins directly below App's sticky content-pane top bar, same convention
     as NewsFeed's .controls. Two tab rows stacked (country, then category) —
     same grid shape as NewsFeed's subtabs+cats, just one more axis. */
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
  .cats { grid-column: 1; min-width: 0; display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .listen { grid-column: 2; justify-self: end; }

  .countries button {
    font: inherit; font-size: 0.85rem; cursor: pointer;
    padding: 0.4rem 1rem; border-radius: 999px;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
  }
  .countries button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

  .cats button {
    font: inherit; font-size: 0.8rem; cursor: pointer;
    padding: 0.35rem 0.85rem; border-radius: 8px;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
  }
  .cats button.active { background: var(--surface-2); color: var(--text); border-color: var(--accent); }

  .run-date {
    font-size: 0.75rem; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .story-list { display: flex; flex-direction: column; gap: 0.6rem; }

  .empty {
    color: var(--muted); font-size: 0.85rem; padding: 0.75rem;
    border: 1px dashed var(--border); border-radius: var(--radius); text-align: center;
  }

  @media (max-width: 700px) {
    .cats {
      grid-column: 1 / -1;
      flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
    }
    .cats::-webkit-scrollbar { display: none; }
    .listen { grid-row: 1; grid-column: 2; }
  }
</style>
