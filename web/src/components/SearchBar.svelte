<script>
  import { onMount, tick } from "svelte";

  // Global "find on this page" search. Highlights every occurrence of the query
  // in the active section's content using the CSS Custom Highlight API — this
  // paints over the live DOM without inserting nodes, so it never disturbs
  // Svelte's rendering or reactivity. Navigation scrolls between matches.
  //
  // Props:
  //  - root: () => HTMLElement — the container whose text is searched.
  //  - revision: any — changes whenever the searchable content changes (section
  //    switch, lazy load, tab flip); re-runs the search when it does.
  let { root, revision } = $props();

  const SUPPORTED =
    typeof CSS !== "undefined" && "highlights" in CSS && typeof Highlight !== "undefined";

  let query = $state("");
  let inputEl;
  let ranges = $state([]);        // every match, in document order
  let current = $state(-1);       // index into `ranges`, -1 when none

  const clearHighlights = () => {
    if (!SUPPORTED) return;
    CSS.highlights.delete("pp-search");
    CSS.highlights.delete("pp-search-current");
  };

  // Walk the container's text nodes and build a Range per match.
  function findMatches() {
    ranges = [];
    current = -1;
    clearHighlights();

    const container = root?.();
    const needle = query.trim().toLowerCase();
    if (!SUPPORTED || !container || needle.length < 2) return;

    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        // Skip the search bar's own text so it can't match itself.
        const p = node.parentElement;
        if (!p || p.closest(".pp-search") || p.closest("script,style"))
          return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    const found = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const hay = node.nodeValue.toLowerCase();
      let from = 0;
      for (let i = hay.indexOf(needle); i !== -1; i = hay.indexOf(needle, from)) {
        const r = document.createRange();
        r.setStart(node, i);
        r.setEnd(node, i + needle.length);
        found.push(r);
        from = i + needle.length;
      }
    }

    ranges = found;
    if (found.length) {
      CSS.highlights.set("pp-search", new Highlight(...found));
      go(0);
    }
  }

  // Select match `i` and scroll it into view.
  function go(i) {
    if (!ranges.length) return;
    current = ((i % ranges.length) + ranges.length) % ranges.length;
    const r = ranges[current];
    CSS.highlights.set("pp-search-current", new Highlight(r));
    r.startContainer.parentElement?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  const next = () => go(current + 1);
  const prev = () => go(current - 1);

  function reset() {
    query = "";
    findMatches();
    inputEl?.blur();
  }

  function onKeydown(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (!ranges.length) findMatches();
      else e.shiftKey ? prev() : next();
    } else if (e.key === "Escape") {
      e.preventDefault();
      reset();
    }
  }

  // Debounce re-search as the user types.
  let timer;
  function onInput() {
    clearTimeout(timer);
    timer = setTimeout(findMatches, 120);
  }

  // Re-run when the searchable content changes underneath us.
  $effect(() => {
    revision; // track
    if (query.trim().length >= 2) tick().then(findMatches);
  });

  onMount(() => {
    const onDocKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputEl?.focus();
        inputEl?.select();
      }
    };
    window.addEventListener("keydown", onDocKey);
    return () => {
      window.removeEventListener("keydown", onDocKey);
      clearTimeout(timer);
      clearHighlights();
    };
  });
</script>

{#if SUPPORTED}
  <div class="pp-search" role="search">
    <span class="icon" aria-hidden="true">⌕</span>
    <input
      bind:this={inputEl}
      bind:value={query}
      oninput={onInput}
      onkeydown={onKeydown}
      type="search"
      placeholder="Find on this page…"
      aria-label="Find on this page"
      spellcheck="false"
    />
    {#if query.trim().length >= 2}
      <span class="count" aria-live="polite">
        {ranges.length ? `${current + 1}/${ranges.length}` : "0/0"}
      </span>
      <button class="nav" onclick={prev} disabled={!ranges.length} aria-label="Previous match" title="Previous (Shift+Enter)">↑</button>
      <button class="nav" onclick={next} disabled={!ranges.length} aria-label="Next match" title="Next (Enter)">↓</button>
      <button class="nav" onclick={reset} aria-label="Clear search" title="Clear (Esc)">✕</button>
    {/if}
  </div>
{/if}

<style>
  .pp-search {
    display: flex; align-items: center; gap: 0.35rem;
    padding: 0.3rem 0.6rem; border-radius: 999px;
    background: var(--surface); border: 1px solid var(--border);
    max-width: 100%;
  }
  .pp-search:focus-within { border-color: var(--accent); }
  .icon { color: var(--muted); font-size: 1rem; line-height: 1; }
  .pp-search input {
    font: inherit; font-size: 0.9rem; border: none; outline: none;
    background: none; color: var(--text); width: 11rem; max-width: 40vw;
    padding: 0.1rem 0;
  }
  .pp-search input::placeholder { color: var(--muted); }
  .count {
    font-size: 0.78rem; color: var(--muted); font-variant-numeric: tabular-nums;
    white-space: nowrap; padding: 0 0.15rem;
  }
  .pp-search .nav {
    font: inherit; font-size: 0.85rem; line-height: 1; cursor: pointer;
    background: none; border: none; color: var(--muted);
    padding: 0.15rem 0.25rem; border-radius: 6px;
  }
  .pp-search .nav:hover:not(:disabled) { color: var(--text); background: var(--surface-2); }
  .pp-search .nav:disabled { opacity: 0.4; cursor: default; }
</style>
