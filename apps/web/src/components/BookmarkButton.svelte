<script>
  // Star toggle on a paper / article / video card.
  //
  // Renders nothing at all when signed out — the signed-out site is exactly
  // what it was before sign-in existed, and an inert star that does nothing on
  // click is worse than no star.
  import { session } from "../lib/session.svelte.js";
  import { isSaved, toggleBookmark, BookmarkLimitError } from "../lib/bookmarks.svelte.js";
  import { BOOKMARK_LIMIT } from "../lib/constants.js";

  let { type, item } = $props();

  let busy = $state(false);
  // Local, not global: the message belongs next to the star that was clicked.
  let limit = $state(false);
  let error = $state(null);

  let saved = $derived(session.status === "in" && isSaved(type, item));

  async function onClick(e) {
    // VideoCard wraps its whole card in an <a>, so without this the click
    // navigates to YouTube instead of saving.
    e.preventDefault();
    e.stopPropagation();
    if (busy) return;

    busy = true;
    limit = false;
    error = null;
    try {
      await toggleBookmark(type, item);
    } catch (err) {
      if (err instanceof BookmarkLimitError) limit = true;
      else error = err?.message ?? String(err);
    } finally {
      busy = false;
    }
  }
</script>

{#if session.status === "in"}
  <span class="bookmark">
    <button
      type="button"
      class="star"
      class:saved
      disabled={busy}
      aria-pressed={saved}
      aria-label={saved ? `Remove “${item.title}” from saved` : `Save “${item.title}”`}
      title={saved ? "Saved — click to remove" : "Save"}
      onclick={onClick}
    >
      {saved ? "★" : "☆"}
    </button>
    {#if limit}
      <!-- Refuse rather than evict: the cap never silently deletes something
           the user chose to keep, so it has to say where to free a slot. -->
      <span class="note" role="alert">
        Limit reached ({BOOKMARK_LIMIT}) — <a href="#/saved">remove one</a> to save this
      </span>
    {:else if error}
      <span class="note err" role="alert">{error}</span>
    {/if}
  </span>
{/if}

<style>
  .bookmark { display: inline-flex; align-items: center; gap: 0.4rem; }
  .star {
    font: inherit; font-size: 1rem; line-height: 1; cursor: pointer;
    padding: 0.1rem 0.2rem; background: none; border: none;
    color: var(--muted);
  }
  .star:hover:not(:disabled) { color: var(--accent); }
  .star.saved { color: var(--accent); }
  .star:disabled { opacity: 0.5; cursor: default; }
  .note { font-size: 0.7rem; color: var(--muted); }
  .note.err { color: var(--warn); }
  .note a { color: var(--accent); }
</style>
