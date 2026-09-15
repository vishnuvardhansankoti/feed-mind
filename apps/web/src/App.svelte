<script>
  import { onMount } from "svelte";
  import { LENSES } from "./lib/constants.js";
  import { getLatest, getArchive, getStatus, getNews, getVideos, getStories, getKnowledgeBytes } from "./lib/data.js";
  import LensColumn from "./components/LensColumn.svelte";
  import PaperCard from "./components/PaperCard.svelte";
  import FreshnessBadge from "./components/FreshnessBadge.svelte";
  import NewsFeed from "./components/NewsFeed.svelte";
  import VideoFeed from "./components/VideoFeed.svelte";
  import StoriesFeed from "./components/StoriesFeed.svelte";
  import KnowledgeFeed from "./components/KnowledgeFeed.svelte";
  import SearchBar from "./components/SearchBar.svelte";
  import ConsentBanner from "./components/ConsentBanner.svelte";
  import AccountMenu from "./components/AccountMenu.svelte";
  import SavedView from "./components/SavedView.svelte";
  import SettingsSheet from "./components/SettingsSheet.svelte";
  import ListenAllButton from "./components/ListenAllButton.svelte";
  import MiniPlayer from "./components/MiniPlayer.svelte";
  import { paperTracks, topSummaryTracks } from "./lib/playlists.js";
  import { queue, playQueue, stopQueue } from "./lib/audio.svelte.js";
  import { isFollowed } from "./lib/follows.svelte.js";
  import { settingsUi } from "./lib/settingsUi.svelte.js";
  import { analyticsEnabled } from "./lib/analytics.js";
  import { openConsent } from "./lib/consentUi.svelte.js";
  import { startSession, session } from "./lib/session.svelte.js";
  import { bookmarks } from "./lib/bookmarks.svelte.js";

  // Top-level section from the URL hash: "#/papers" -> papers, "#/videos" ->
  // videos, "#/stories" -> stories, "#/knowledge" -> knowledge, "#/saved" ->
  // saved, anything else (incl. the default "#/") -> news, the landing
  // section.
  const pageFromHash = () => {
    if (typeof location === "undefined") return "news";
    if (location.hash === "#/papers") return "papers";
    if (location.hash === "#/videos") return "videos";
    if (location.hash === "#/stories") return "stories";
    if (location.hash === "#/knowledge") return "knowledge";
    if (location.hash === "#/saved") return "saved";
    return "news";
  };
  let page = $state(pageFromHash());
  const HASH = {
    papers: "#/papers", videos: "#/videos", stories: "#/stories",
    knowledge: "#/knowledge", saved: "#/saved", news: "#/",
  };
  const goto = (p) => { location.hash = HASH[p] ?? "#/"; };

  // Labels only — the internal page ids ("news", "stories") and their hashes
  // (#/, #/stories) are unchanged, so existing bookmarks keep working. "news"
  // now displays as "AI Cloud Blogs"; "stories" now displays as "News". See
  // the root CLAUDE.md. Rendered twice from this one array — as the sidebar
  // list on wide screens and the bottom bar on narrow ones (see the
  // navButton snippet below) — so the two surfaces cannot drift apart.
  const SECTIONS = [
    { id: "news", label: "AI Cloud Blogs" },
    { id: "papers", label: "Papers" },
    { id: "videos", label: "Videos" },
    { id: "stories", label: "News" },
    { id: "knowledge", label: "Knowledge Bytes" },
  ];
  // Only for signed-in users: there is nothing to show otherwise, and the tab
  // would advertise a section that immediately turns them away.
  let navSections = $derived(
    session.status === "in" ? [...SECTIONS, { id: "saved", label: "Saved" }] : SECTIONS,
  );

  let tab = $state("latest");

  // Everything above the content is sticky, in two stacked layers: the content
  // pane's top bar (search / Listen Top Blogs / account) → the section's own
  // tab bar. First-level navigation lives beside the content instead (sidebar
  // on wide screens, a fixed bottom bar on narrow ones), so it no longer
  // occupies a layer here. The top bar's height is measured rather than
  // hardcoded — it wraps to an extra row on narrow screens — and published as
  // a custom property, which is how the tab bars inside NewsFeed/StoriesFeed/
  // VideoFeed get their offset without prop-drilling.
  let headH = $state(0);

  let loading = $state(true);
  let error = $state(null);
  let latest = $state({});
  let archive = $state({});
  let status = $state(null);

  // News is loaded lazily the first time the News section is opened.
  let news = $state(null);            // { articles } once loaded
  let newsLoading = $state(false);
  let newsError = $state(null);

  // The in-flight promise, not just a boolean: Listen Top Summaries awaits this
  // to build its queue, and a caller arriving mid-fetch has to wait for the
  // same load rather than being turned away with `news` still null.
  let newsInflight = null;

  async function loadNews() {
    if (news) return;
    if (newsInflight) return newsInflight;
    newsLoading = true;
    newsInflight = (async () => {
      try {
        news = await getNews();
      } catch (e) {
        newsError = e?.message ?? String(e);
      } finally {
        newsLoading = false;
        newsInflight = null;
      }
    })();
    return newsInflight;
  }

  // Videos are loaded lazily the first time the Videos section is opened.
  let videos = $state(null);          // { videos } once loaded
  let videosLoading = $state(false);
  let videosError = $state(null);

  async function loadVideos() {
    if (videos || videosLoading) return;
    videosLoading = true;
    try {
      videos = await getVideos();
    } catch (e) {
      videosError = e?.message ?? String(e);
    } finally {
      videosLoading = false;
    }
  }

  // Stories are loaded lazily the first time the Stories section is opened.
  let stories = $state(null);         // { stories } once loaded
  let storiesLoading = $state(false);
  let storiesError = $state(null);

  async function loadStories() {
    if (stories || storiesLoading) return;
    storiesLoading = true;
    try {
      stories = await getStories();
    } catch (e) {
      storiesError = e?.message ?? String(e);
    } finally {
      storiesLoading = false;
    }
  }

  // Knowledge Bytes are loaded lazily the first time that section is opened.
  let knowledge = $state(null);       // { articles } once loaded
  let knowledgeLoading = $state(false);
  let knowledgeError = $state(null);

  async function loadKnowledge() {
    if (knowledge || knowledgeLoading) return;
    knowledgeLoading = true;
    try {
      knowledge = await getKnowledgeBytes();
    } catch (e) {
      knowledgeError = e?.message ?? String(e);
    } finally {
      knowledgeLoading = false;
    }
  }

  // Papers: Listen All follows the visible tab, same rule as News.
  let paperQueue = $derived(
    tab === "latest" ? paperTracks(latest) : paperTracks(archive, { many: true }),
  );

  // Top Summaries spans sections, so it is the one control that isn't scoped to
  // the tab you are on. News is lazy, so it may have to be fetched first — a
  // user who lands on Papers and presses this has never triggered loadNews().
  let topLoading = $state(false);
  let topNote = $state("");

  // Whether the queue now playing is this button's. Without it the button never
  // showed a playing state, so pressing it again silently restarted the queue
  // from the first track — indistinguishable from the playlist looping.
  let topPlaying = $derived(queue.state !== "idle" && queue.source === "top");

  async function playTopSummaries() {
    if (topPlaying) {
      stopQueue();
      return;
    }
    topNote = "";
    topLoading = true;
    try {
      await loadNews();
      const tracks = topSummaryTracks({
        articles: news?.articles ?? [],
        isFollowed,
      });
      // playQueue no-ops on an empty list, which would leave the press with no
      // visible effect at all; say so instead.
      if (!tracks.length) topNote = "No audio summaries available yet.";
      else playQueue(tracks, "top");
    } finally {
      topLoading = false;
    }
  }

  // UTC: run_date is a calendar date stamped at midnight UTC (the doc id is
  // `runs/YYYY-MM-DD_<CAT>`), not an instant, so formatting it locally labels a
  // run one day early for every reader behind UTC.
  const dateFmt = new Intl.DateTimeFormat(undefined, {
    year: "numeric", month: "short", day: "numeric", timeZone: "UTC",
  });
  const fmt = (d) => (d ? dateFmt.format(d instanceof Date ? d : new Date(d)) : "");

  onMount(async () => {
    const onHash = () => { page = pageFromHash(); };
    window.addEventListener("hashchange", onHash);

    // Independent of the digest fetch below: sign-in is additive, so a failure
    // here must never keep the (public) content from rendering.
    const stopSession = startSession();

    try {
      [latest, status, archive] = await Promise.all([
        getLatest(), getStatus(), getArchive(),
      ]);
    } catch (e) {
      error = e?.message ?? String(e);
    } finally {
      loading = false;
    }

    return () => {
      window.removeEventListener("hashchange", onHash);
      stopSession();
    };
  });

  // Kick off the lazy fetch whenever a lazy section becomes active.
  $effect(() => { if (page === "news") loadNews(); });
  $effect(() => { if (page === "videos") loadVideos(); });
  $effect(() => { if (page === "stories") loadStories(); });
  $effect(() => { if (page === "knowledge") loadKnowledge(); });

  // The settings sheet lists sources derived from the loaded documents, so both
  // lazy sections have to be fetched before it can show a complete list —
  // otherwise a user who never opened Videos would see no channels to manage.
  $effect(() => {
    if (settingsUi.open) { loadNews(); loadVideos(); }
  });

  // The element whose text the global search scans, and a key that changes
  // whenever its contents change so the search can re-highlight.
  let contentEl;
  const getContentEl = () => contentEl;
  let searchRevision = $derived(
    `${page}|${tab}|${loading}|${newsLoading}|${videosLoading}|${storiesLoading}|${knowledgeLoading}|` +
      `${news ? news.articles?.length : 0}|${videos ? videos.videos?.length : 0}|` +
      `${stories ? Object.values(stories.stories ?? {}).flat().length : 0}|` +
      `${knowledge ? knowledge.articles?.length : 0}|` +
      `${Object.keys(latest).length}|${Object.keys(archive).length}|` +
      // Saved items are searchable content too, and starring one re-renders
      // the list without changing anything else in this key.
      `${bookmarks.items.length}`,
  );
</script>

{#snippet navButton(s)}
  <button
    aria-current={page === s.id}
    class:active={page === s.id}
    onclick={() => goto(s.id)}
  >
    {s.label}
  </button>
{/snippet}

<div class="shell">
  <aside class="sidebar">
    <div class="brand">
      <span class="prism" aria-hidden="true"></span>
      <div>
        <h1>feed-mind</h1>
        <p class="tagline">Daily Tech News and Weekly Research Papers Digest</p>
      </div>
    </div>

    <nav class="sidebar-nav" aria-label="Sections">
      {#each navSections as s (s.id)}{@render navButton(s)}{/each}
    </nav>
  </aside>

  <div class="content" style="--head-h: {headH}px; --stick-top: {headH}px">
    <header class="topbar" bind:clientHeight={headH}>
      <div class="brand-compact">
        <span class="prism" aria-hidden="true"></span>
        <h1>feed-mind</h1>
      </div>
      <div class="masthead-tools">
        <SearchBar root={getContentEl} revision={searchRevision} />
        <!-- AI Cloud Blogs only, in both senses: the queue is that section's
             articles, and the control appears only there. Elsewhere it would
             offer to play one section's content from another's — and on Papers
             it would sit beside that tab's own Listen All playing something
             different. A queue already running keeps playing as you navigate
             away; the mini-player still holds Stop and Skip.
             Internal id is still "news" (see pageFromHash) — only the visible
             label changed when this section was renamed to "AI Cloud Blogs". -->
        {#if page === "news"}
          <button
            type="button"
            class="top-listen"
            class:playing={topPlaying}
            onclick={playTopSummaries}
            disabled={topLoading}
            aria-label={topPlaying
              ? "Stop playing the top blogs"
              : "Listen to the top blogs from every category"}
          >
            <span class="icon" aria-hidden="true">{topPlaying ? "■" : "▶"}</span>
            {topPlaying ? "Stop" : topLoading ? "Preparing…" : "Listen Top Blogs"}
          </button>
          {#if topNote}<span class="top-note" role="status">{topNote}</span>{/if}
        {/if}
        {#if page === "papers" && status}<FreshnessBadge {status} />{/if}
        <AccountMenu />
      </div>
    </header>

    <main bind:this={contentEl}>
    {#if page === "news"}
      {#if newsLoading}
        <div class="state"><span class="spinner"></span> Loading news…</div>
      {:else if newsError}
        <div class="state err">Couldn’t load the news feed: {newsError}</div>
      {:else}
        <NewsFeed articles={news?.articles ?? []} />
      {/if}
    {:else if page === "saved"}
      <!-- Reachable by URL while signed out (a bookmarked link, or a sign-out
           while the section is open), so it has to say why it's empty rather
           than silently redirecting somewhere else. -->
      {#if session.status === "in"}
        <SavedView />
      {:else}
        <div class="state">Sign in to see the items you’ve saved.</div>
      {/if}
    {:else if page === "videos"}
      {#if videosLoading}
        <div class="state"><span class="spinner"></span> Loading videos…</div>
      {:else if videosError}
        <div class="state err">Couldn’t load the videos feed: {videosError}</div>
      {:else}
        <VideoFeed videos={videos?.videos ?? []} />
      {/if}
    {:else if page === "stories"}
      {#if storiesLoading}
        <div class="state"><span class="spinner"></span> Loading stories…</div>
      {:else if storiesError}
        <div class="state err">Couldn’t load the stories feed: {storiesError}</div>
      {:else}
        <StoriesFeed stories={stories?.stories ?? {}} />
      {/if}
    {:else if page === "knowledge"}
      {#if knowledgeLoading}
        <div class="state"><span class="spinner"></span> Loading Knowledge Bytes…</div>
      {:else if knowledgeError}
        <div class="state err">Couldn’t load Knowledge Bytes: {knowledgeError}</div>
      {:else}
        <KnowledgeFeed articles={knowledge?.articles ?? []} />
      {/if}
    {:else}

    <div class="tabrow">
      <div class="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "latest"} class:active={tab === "latest"} onclick={() => (tab = "latest")}>
          Latest
        </button>
        <button role="tab" aria-selected={tab === "archive"} class:active={tab === "archive"} onclick={() => (tab = "archive")}>
          Archive
        </button>
      </div>
      <ListenAllButton tracks={paperQueue} id={`papers:${tab}`} label="Listen All" />
    </div>

    {#if loading}
      <div class="state"><span class="spinner"></span> Loading digest…</div>
    {:else if error}
      <div class="state err">Couldn’t load the digest: {error}</div>
    {:else if tab === "latest"}
      <div class="grid">
        {#each LENSES as lens (lens.code)}
          <LensColumn {lens} run={latest[lens.code]} />
        {/each}
      </div>
    {:else}
      <div class="grid">
        {#each LENSES as lens (lens.code)}
          <section class="archive-lens">
            <header class="arch-head">
              <h2>{lens.label}</h2><span class="sources">{lens.sources}</span>
            </header>
            {#if (archive[lens.code] ?? []).length}
              {#each archive[lens.code] as run (run.run_date)}
                <div class="run-group">
                  <div class="run-date">{fmt(run.run_date)}</div>
                  {#each run.papers as paper (paper.arxiv_id)}
                    <PaperCard {paper} />
                  {/each}
                  {#if !run.papers.length}
                    <p class="empty">No papers this run.</p>
                  {/if}
                </div>
              {/each}
            {:else}
              <p class="empty">No history yet.</p>
            {/if}
          </section>
        {/each}
      </div>
    {/if}
    {/if}
    </main>

    <footer>
      <span>Daily AI &amp; cloud blogs across academia, industry and open source · Curated Indian news · Weekly arXiv research ranked to your interests and summarized by AI</span>
      {#if analyticsEnabled}
        <span class="footsep">·</span>
        <button type="button" class="cookie-link" onclick={openConsent}>Cookie settings</button>
      {/if}
    </footer>
  </div>
</div>

<!-- Mobile counterpart to .sidebar-nav above — same navSections, same
     navButton snippet, so the two surfaces can't drift apart. Fixed instead of
     sticky: it belongs to the viewport, not the content column, and stays put
     under MiniPlayer/ConsentBanner (see --bottom-nav-h in app.css). -->
<nav class="bottom-nav" aria-label="Sections">
  {#each navSections as s (s.id)}{@render navButton(s)}{/each}
</nav>

<MiniPlayer />

<ConsentBanner />

{#if settingsUi.open && session.status === "in"}
  <SettingsSheet articles={news?.articles ?? []} videos={videos?.videos ?? []} />
{/if}

<style>
  /* Sidebar (wide screens) + content column, side by side. On narrow screens
     the sidebar is hidden (see the media query at the bottom) and first-level
     navigation moves to .bottom-nav instead — .shell just carries .content
     full width in that case. */
  .shell { display: flex; }

  /* First-level nav on wide screens: brand at the top, full height, pinned
     via `position: sticky` + `height: 100vh` rather than `fixed`, so it scrolls
     back into flow if the shell's own height were ever shorter than the
     viewport. Hidden below 700px — .bottom-nav takes over there instead. */
  .sidebar {
    display: none;
    flex: 0 0 220px;
    flex-direction: column;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
    padding: 1.5rem 1.25rem;
    border-right: 1px solid var(--border);
  }
  .sidebar .brand { margin-bottom: 2rem; }
  /* Stacked, not side-by-side: at the sidebar's 220px width a row layout left
     so little room for the text that the icon's flex-shrink kicked in and
     squashed it out of square. Stacking removes that competition entirely. */
  .brand { display: flex; flex-direction: column; align-items: flex-start; gap: 0.7rem; }
  .sidebar-nav { display: flex; flex-direction: column; gap: 0.15rem; }
  .sidebar-nav button {
    font: inherit; font-size: 0.95rem; font-weight: 600; cursor: pointer;
    text-align: left; padding: 0.6rem 0.8rem; border-radius: var(--radius);
    background: none; border: none; color: var(--muted);
  }
  .sidebar-nav button:hover { background: var(--surface); color: var(--text); }
  .sidebar-nav button.active { background: var(--surface-2); color: var(--text); }

  .prism {
    width: 42px; height: 42px; border-radius: 11px;
    flex-shrink: 0;
    background: conic-gradient(from 210deg, #ff6b6b, #ffd166, #4ade80, #38bdf8, #a78bfa, #ff6b6b);
  }
  h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.02em; }
  .tagline { margin: 0; color: var(--muted); font-size: 0.85rem; }

  .content {
    flex: 1; min-width: 0; max-width: 1180px; margin: 0 auto;
    /* Bottom padding leaves room for .bottom-nav on a phone, where it would
       otherwise sit on top of the footer. --bottom-nav-h is 0 above 700px. */
    padding: 1.5rem 1.25rem calc(3rem + var(--bottom-nav-h, 0px));
  }

  /* Compact brand shown in .topbar on narrow screens only, where .sidebar
     (which otherwise carries the brand) is hidden. No scroll-triggered
     condensing needed — unlike the old masthead, this is already the small
     form, and it never leaves the top of a two-layer sticky stack. */
  .brand-compact { display: flex; align-items: center; gap: 0.6rem; }
  .brand-compact .prism { width: 26px; height: 26px; border-radius: 7px; }
  .brand-compact h1 { font-size: 1.15rem; }

  /* Top of the sticky stack inside the content column: search / Listen Top
     Blogs / account. Deliberately not transitioned: --head-h is measured from
     this element and the section tab bar below it pins against that height,
     so an animated height would drag the tab bar along for the ride. */
  .topbar {
    display: flex; flex-wrap: wrap; gap: 1rem;
    align-items: center; justify-content: space-between; margin-bottom: 1.25rem;
    position: sticky; top: 0; z-index: 13;
    background: var(--bg);
    /* Covers the .content padding above it, which the page scrolls through. */
    box-shadow: 0 -1.5rem 0 var(--bg);
  }
  .masthead-tools { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }

  /* First-level nav on narrow screens: fixed to the viewport (not the content
     column) so it stays put regardless of scroll. Sits under MiniPlayer/
     ConsentBanner (z-index 40/50), which clear it via --bottom-nav-h instead
     of overlapping it. Hidden at 701px+ — .sidebar takes over there instead. */
  .bottom-nav {
    display: flex;
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 30;
    background: var(--bg); border-top: 1px solid var(--border);
    padding: 0 0.25rem env(safe-area-inset-bottom, 0);
  }
  .bottom-nav button {
    flex: 1 1 0; min-width: 0;
    font: inherit; font-size: 0.72rem; font-weight: 600; cursor: pointer;
    background: none; border: none; color: var(--muted);
    padding: 0.6rem 0.2rem;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .bottom-nav button.active { color: var(--accent); }

  .top-listen {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font: inherit;
    font-size: 0.78rem;
    cursor: pointer;
    color: var(--accent);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 0.2rem 0.7rem;
    white-space: nowrap;
  }
  .top-listen:hover:not(:disabled) { border-color: var(--accent); }
  .top-listen:disabled { color: var(--muted); cursor: default; }
  .top-listen.playing {
    border-color: var(--accent);
    background: var(--accent);
    color: #fff;
  }
  .top-listen .icon { font-size: 0.62rem; line-height: 1; }
  .top-note { font-size: 0.72rem; color: var(--muted); }

  .tabrow {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-bottom: 1.5rem;
    position: sticky; top: var(--stick-top, 0px); z-index: 11;
    /* Zero-blur shadows extend the bar's own background over the gap above
       (the nav's margin) and a little below it, so cards scrolling underneath
       never show through. Padding would have shifted the layout instead. */
    background: var(--bg);
    box-shadow: 0 -1.25rem 0 var(--bg), 0 0.6rem 0 var(--bg);
  }
  .tabrow .tabs { margin-bottom: 0; }
  .tabs { display: flex; gap: 0.4rem; margin-bottom: 1.5rem; }
  .tabs button {
    font: inherit; font-size: 0.9rem; cursor: pointer;
    padding: 0.45rem 1.1rem; border-radius: 999px;
    background: var(--surface); color: var(--muted);
    border: 1px solid var(--border);
  }
  .tabs button.active { background: var(--accent); color: #fff; border-color: var(--accent); }

  .grid {
    display: grid; gap: 1.5rem;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
    align-items: start;
  }

  .archive-lens { display: flex; flex-direction: column; gap: 1rem; }
  .arch-head {
    display: flex; align-items: baseline; justify-content: space-between;
    border-bottom: 2px solid var(--border); padding-bottom: 0.5rem;
  }
  .arch-head h2 { margin: 0; font-size: 1.05rem; }
  .sources { font-size: 0.72rem; color: var(--muted); font-family: ui-monospace, monospace; }
  .run-group { display: flex; flex-direction: column; gap: 0.6rem; }
  .run-date {
    font-size: 0.75rem; color: var(--muted); text-transform: uppercase;
    letter-spacing: 0.05em; margin-top: 0.5rem;
  }

  .state {
    display: flex; align-items: center; gap: 0.6rem;
    color: var(--muted); padding: 3rem 1rem; justify-content: center;
  }
  .state.err { color: var(--warn); }
  .spinner {
    width: 18px; height: 18px; border-radius: 50%;
    border: 2px solid var(--border); border-top-color: var(--accent);
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  .empty {
    color: var(--muted); font-size: 0.85rem; padding: 0.75rem;
    border: 1px dashed var(--border); border-radius: var(--radius); text-align: center;
  }

  footer {
    margin-top: 2.5rem; padding-top: 1.25rem; border-top: 1px solid var(--border);
    color: var(--muted); font-size: 0.78rem; text-align: center;
  }
  .footsep { margin: 0 0.4rem; }
  .cookie-link {
    font: inherit; font-size: inherit; cursor: pointer; padding: 0;
    background: none; border: none; color: var(--accent); text-decoration: none;
  }
  .cookie-link:hover { text-decoration: underline; }

  /* Keep the topbar to two rows on a phone: brand, then the tools on one line
     of their own (they otherwise wrap the account button onto a third row).
     Must stay after the base rules — a media query adds no specificity, so a
     later plain rule would win. */
  @media (max-width: 700px) {
    .topbar { gap: 0.6rem; }
    .masthead-tools { flex: 1 1 100%; gap: 0.5rem; flex-wrap: nowrap; }
    .top-listen { padding: 0.2rem 0.55rem; }
  }

  /* Desktop layout switch: sidebar replaces the bottom nav bar, and the
     compact mobile brand in .topbar gives way to the sidebar's full one. */
  @media (min-width: 701px) {
    .sidebar { display: flex; }
    .brand-compact { display: none; }
    .bottom-nav { display: none; }
    .topbar { justify-content: flex-end; }
  }
</style>
