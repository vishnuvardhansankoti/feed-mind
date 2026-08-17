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
  import { analyticsEnabled } from "./lib/analytics.js";
  import { openConsent } from "./lib/consentUi.svelte.js";

  // Top-level section from the URL hash: "#/papers" -> papers, "#/videos" ->
  // videos, anything else (incl. the default "#/") -> news, the landing section.
  const pageFromHash = () => {
    if (typeof location === "undefined") return "news";
    if (location.hash === "#/papers") return "papers";
    if (location.hash === "#/videos") return "videos";
    return "news";
  };
  let page = $state(pageFromHash());
  const HASH = { papers: "#/papers", videos: "#/videos", news: "#/" };
  const goto = (p) => { location.hash = HASH[p] ?? "#/"; };

  let tab = $state("latest");
  let loading = $state(true);
  let error = $state(null);
  let latest = $state({});
  let archive = $state({});
  let status = $state(null);

  // News is loaded lazily the first time the News section is opened.
  let news = $state(null);            // { articles } once loaded
  let newsLoading = $state(false);
  let newsError = $state(null);

  async function loadNews() {
    if (news || newsLoading) return;
    newsLoading = true;
    try {
      news = await getNews();
    } catch (e) {
      newsError = e?.message ?? String(e);
    } finally {
      newsLoading = false;
    }
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

  const dateFmt = new Intl.DateTimeFormat(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
  const fmt = (d) => (d ? dateFmt.format(d instanceof Date ? d : new Date(d)) : "");

  onMount(async () => {
    const onHash = () => { page = pageFromHash(); };
    window.addEventListener("hashchange", onHash);

    try {
      [latest, status, archive] = await Promise.all([
        getLatest(), getStatus(), getArchive(),
      ]);
    } catch (e) {
      error = e?.message ?? String(e);
    } finally {
      loading = false;
    }

    return () => window.removeEventListener("hashchange", onHash);
  });

  // Kick off the lazy fetch whenever a lazy section becomes active.
  $effect(() => { if (page === "news") loadNews(); });
  $effect(() => { if (page === "videos") loadVideos(); });

  // The element whose text the global search scans, and a key that changes
  // whenever its contents change so the search can re-highlight.
  let contentEl;
  const getContentEl = () => contentEl;
  let searchRevision = $derived(
    `${page}|${tab}|${loading}|${newsLoading}|${videosLoading}|` +
      `${news ? news.articles?.length : 0}|${videos ? videos.videos?.length : 0}|` +
      `${Object.keys(latest).length}|${Object.keys(archive).length}`,
  );
</script>

<div class="wrap">
  <header class="masthead">
    <div class="brand">
      <span class="prism" aria-hidden="true"></span>
      <div>
        <h1>feed-mind</h1>
        <p class="tagline">Daily Tech News and Weekly Research Papers Digest</p>
      </div>
    </div>
    <div class="masthead-tools">
      <SearchBar root={getContentEl} revision={searchRevision} />
      {#if page === "papers" && status}<FreshnessBadge {status} />{/if}
    </div>
  </header>

  <nav class="nav" aria-label="Sections">
    <button aria-current={page === "news"} class:active={page === "news"} onclick={() => goto("news")}>
      News
    </button>
    <button aria-current={page === "papers"} class:active={page === "papers"} onclick={() => goto("papers")}>
      Papers
    </button>
    <button aria-current={page === "videos"} class:active={page === "videos"} onclick={() => goto("videos")}>
      Videos
    </button>
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
  {:else if page === "videos"}
    {#if videosLoading}
      <div class="state"><span class="spinner"></span> Loading videos…</div>
    {:else if videosError}
      <div class="state err">Couldn’t load the videos feed: {videosError}</div>
    {:else}
      <VideoFeed videos={videos?.videos ?? []} />
    {/if}
  {:else}

  <div class="tabs" role="tablist">
    <button role="tab" aria-selected={tab === "latest"} class:active={tab === "latest"} onclick={() => (tab = "latest")}>
      Latest
    </button>
    <button role="tab" aria-selected={tab === "archive"} class:active={tab === "archive"} onclick={() => (tab = "archive")}>
      Archive
    </button>
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
    <span>Daily tech news across academia, industry, cloud &amp; open source · Weekly arXiv research ranked to your interests and summarized by AI</span>
    {#if analyticsEnabled}
      <span class="footsep">·</span>
      <button type="button" class="cookie-link" onclick={openConsent}>Cookie settings</button>
    {/if}
  </footer>
</div>

<ConsentBanner />

<style>
  .wrap { max-width: 1180px; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }
  .masthead {
    display: flex; flex-wrap: wrap; gap: 1rem;
    align-items: center; justify-content: space-between; margin-bottom: 1.25rem;
  }
  .brand { display: flex; align-items: center; gap: 0.9rem; }
  .masthead-tools { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
  .prism {
    width: 34px; height: 34px; border-radius: 9px;
    background: conic-gradient(from 210deg, #ff6b6b, #ffd166, #4ade80, #38bdf8, #a78bfa, #ff6b6b);
  }
  h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.02em; }
  .tagline { margin: 0; color: var(--muted); font-size: 0.85rem; }

  .nav {
    display: flex; gap: 0.4rem; margin-bottom: 1.25rem;
    border-bottom: 1px solid var(--border);
  }
  .nav button {
    font: inherit; font-size: 0.95rem; font-weight: 600; cursor: pointer;
    padding: 0.5rem 0.9rem; background: none; border: none;
    color: var(--muted); border-bottom: 2px solid transparent; margin-bottom: -1px;
  }
  .nav button.active { color: var(--text); border-bottom-color: var(--accent); }

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
</style>
