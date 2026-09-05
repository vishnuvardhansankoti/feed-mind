<script>
  import { onMount } from "svelte";
  import { LENSES } from "./lib/constants.js";
  import { getLatest, getArchive, getStatus, getNews, getVideos } from "./lib/data.js";
  import LensColumn from "./components/LensColumn.svelte";
  import PaperCard from "./components/PaperCard.svelte";
  import FreshnessBadge from "./components/FreshnessBadge.svelte";
  import NewsFeed from "./components/NewsFeed.svelte";
  import VideoFeed from "./components/VideoFeed.svelte";
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
  // videos, "#/saved" -> saved, anything else (incl. the default "#/") -> news,
  // the landing section.
  const pageFromHash = () => {
    if (typeof location === "undefined") return "news";
    if (location.hash === "#/papers") return "papers";
    if (location.hash === "#/videos") return "videos";
    if (location.hash === "#/saved") return "saved";
    return "news";
  };
  let page = $state(pageFromHash());
  const HASH = { papers: "#/papers", videos: "#/videos", saved: "#/saved", news: "#/" };
  const goto = (p) => { location.hash = HASH[p] ?? "#/"; };

  let tab = $state("latest");

  // Everything above the content is sticky, in three stacked layers: masthead
  // (search / Listen Top News / account) → section nav → the section's own tab
  // bar. Each layer pins below the ones above it, so their heights are measured
  // rather than hardcoded — both wrap to extra rows on narrow screens. `.wrap`
  // publishes them as custom properties, which is how the bars inside
  // NewsFeed/VideoFeed get their offset without prop-drilling.
  let headH = $state(0);
  let navH = $state(0);

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

  // Pinned = the masthead has left its natural place at the top of the page.
  // Watching a zero-height sentinel above it, rather than listening to scroll,
  // keeps this off the scroll path entirely; the class it drives condenses the
  // header (see .masthead.pinned) so three stacked sticky layers don't swallow
  // the viewport on a phone.
  let pinned = $state(false);
  let sentinel;

  onMount(async () => {
    const onHash = () => { page = pageFromHash(); };
    window.addEventListener("hashchange", onHash);

    // IntersectionObserver is absent in jsdom, so component tests must not
    // depend on it existing.
    const io =
      typeof IntersectionObserver !== "undefined" && sentinel
        ? new IntersectionObserver(([e]) => { pinned = !e.isIntersecting; })
        : null;
    io?.observe(sentinel);

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
      io?.disconnect();
      stopSession();
    };
  });

  // Kick off the lazy fetch whenever a lazy section becomes active.
  $effect(() => { if (page === "news") loadNews(); });
  $effect(() => { if (page === "videos") loadVideos(); });

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
    `${page}|${tab}|${loading}|${newsLoading}|${videosLoading}|` +
      `${news ? news.articles?.length : 0}|${videos ? videos.videos?.length : 0}|` +
      `${Object.keys(latest).length}|${Object.keys(archive).length}|` +
      // Saved items are searchable content too, and starring one re-renders
      // the list without changing anything else in this key.
      `${bookmarks.items.length}`,
  );
</script>

<div class="wrap" style="--head-h: {headH}px; --stick-top: {headH + navH}px">
  <div class="sentinel" bind:this={sentinel} aria-hidden="true"></div>
  <header class="masthead" class:pinned bind:clientHeight={headH}>
    <div class="brand">
      <span class="prism" aria-hidden="true"></span>
      <div>
        <h1>feed-mind</h1>
        <p class="tagline">Daily Tech News and Weekly Research Papers Digest</p>
      </div>
    </div>
    <div class="masthead-tools">
      <SearchBar root={getContentEl} revision={searchRevision} />
      <!-- News only, in both senses: the queue is news, and the control appears
           only on the News section. Elsewhere it would offer to play one
           section's content from another's — and on Papers it would sit beside
           that tab's own Listen All playing something different. A queue
           already running keeps playing as you navigate away; the mini-player
           still holds Stop and Skip. -->
      {#if page === "news"}
        <button
          type="button"
          class="top-listen"
          class:playing={topPlaying}
          onclick={playTopSummaries}
          disabled={topLoading}
          aria-label={topPlaying
            ? "Stop playing the top news"
            : "Listen to the top news from every category"}
        >
          <span class="icon" aria-hidden="true">{topPlaying ? "■" : "▶"}</span>
          {topPlaying ? "Stop" : topLoading ? "Preparing…" : "Listen Top News"}
        </button>
        {#if topNote}<span class="top-note" role="status">{topNote}</span>{/if}
      {/if}
      {#if page === "papers" && status}<FreshnessBadge {status} />{/if}
      <AccountMenu />
    </div>
  </header>

  <nav class="nav" aria-label="Sections" bind:clientHeight={navH}>
    <button aria-current={page === "news"} class:active={page === "news"} onclick={() => goto("news")}>
      News
    </button>
    <button aria-current={page === "papers"} class:active={page === "papers"} onclick={() => goto("papers")}>
      Papers
    </button>
    <button aria-current={page === "videos"} class:active={page === "videos"} onclick={() => goto("videos")}>
      Videos
    </button>
    <!-- Only for signed-in users: there is nothing to show otherwise, and the
         tab would advertise a section that immediately turns them away. -->
    {#if session.status === "in"}
      <button aria-current={page === "saved"} class:active={page === "saved"} onclick={() => goto("saved")}>
        Saved
      </button>
    {/if}
  </nav>

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
    <span>Daily tech news across academia, industry, cloud, open source &amp; top stories · Weekly arXiv research ranked to your interests and summarized by AI</span>
    {#if analyticsEnabled}
      <span class="footsep">·</span>
      <button type="button" class="cookie-link" onclick={openConsent}>Cookie settings</button>
    {/if}
  </footer>
</div>

<MiniPlayer />

<ConsentBanner />

{#if settingsUi.open && session.status === "in"}
  <SettingsSheet articles={news?.articles ?? []} videos={videos?.videos ?? []} />
{/if}

<style>
  .wrap { max-width: 1180px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }

  /* Watched by the IntersectionObserver above; it must sit at the very top of
     the page, outside the masthead, or it would scroll away with it. */
  .sentinel { height: 0; }

  .masthead {
    display: flex; flex-wrap: wrap; gap: 1rem;
    align-items: center; justify-content: space-between; margin-bottom: 1.25rem;
    position: sticky; top: 0; z-index: 13;
    background: var(--bg);
    /* Covers the .wrap padding above it, which the page scrolls through. */
    box-shadow: 0 -1.5rem 0 var(--bg);
    /* Deliberately not transitioned: --head-h is measured from this element and
       every layer below pins against it, so an animated height would drag the
       whole stack along for the ride. */
  }
  /* Condensed once stuck: the tagline is orientation, not a control, and three
     pinned layers is a lot of vertical space to give up on a small screen. */
  .masthead.pinned { padding-bottom: 0.35rem; }
  .masthead.pinned .tagline { display: none; }
  .masthead.pinned h1 { font-size: 1.15rem; }
  .masthead.pinned .prism { width: 26px; height: 26px; border-radius: 7px; }
  .brand { display: flex; align-items: center; gap: 0.9rem; }
  .masthead-tools { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
  .prism {
    width: 34px; height: 34px; border-radius: 9px;
    background: conic-gradient(from 210deg, #ff6b6b, #ffd166, #4ade80, #38bdf8, #a78bfa, #ff6b6b);
  }
  h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.02em; }
  .tagline { margin: 0; color: var(--muted); font-size: 0.85rem; }

  /* Middle layer of the sticky stack: pins directly under the masthead, and
     every section's tab bar pins under it in turn (top: var(--stick-top)).
     The upward zero-blur shadow paints over the masthead's margin, which is
     briefly exposed while the masthead is stuck and the nav is still catching
     up. z-index sits under the account dropdown (20), settings sheet (40) and
     mini player (40) so those still cover the bar when open — and under the
     masthead's 13, so its shadow tucks behind the header once flush. */
  .nav {
    display: flex; gap: 0.4rem; margin-bottom: 1.25rem;
    border-bottom: 1px solid var(--border);
    position: sticky; top: var(--head-h, 0px); z-index: 12;
    background: var(--bg);
    box-shadow: 0 -1.25rem 0 var(--bg);
  }
  .nav button {
    font: inherit; font-size: 0.95rem; font-weight: 600; cursor: pointer;
    padding: 0.5rem 0.9rem; background: none; border: none;
    color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -1px;
  }
  .nav button.active { color: var(--text); border-bottom-color: var(--accent); }

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

  /* Keep the pinned header to two rows on a phone: brand, then the tools on one
     line of their own (they otherwise wrap the account button onto a third
     pinned row). Must stay after the base rules — a media query adds no
     specificity, so a later plain rule would win. */
  @media (max-width: 700px) {
    .masthead { gap: 0.6rem; }
    .masthead-tools { flex: 1 1 100%; gap: 0.5rem; flex-wrap: nowrap; }
    .top-listen { padding: 0.2rem 0.55rem; }
  }
</style>
