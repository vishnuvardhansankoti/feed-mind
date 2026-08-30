<script>
  // Follow / unfollow the sources behind the News and Videos sections.
  //
  // The catalog is DERIVED from the documents already loaded, not hardcoded:
  // the real list lives in feed-mind's config.py, in another repo, and a copy
  // here would drift the moment a feed is added there. Deriving means a new
  // source appears in this list the first time it publishes anything.
  import { follows, isFollowed, toggleFollow, followAll } from "../lib/follows.svelte.js";
  import { closeSettings } from "../lib/settingsUi.svelte.js";
  import { session } from "../lib/session.svelte.js";
  import { enablePush, disablePush, isSubscribed, pushUnavailableReason } from "../lib/push.js";

  let { articles = [], videos = [] } = $props();

  const distinct = (items, field) =>
    [...new Set(items.map((i) => i[field]).filter(Boolean))].sort((a, b) =>
      a.localeCompare(b),
    );

  let newsSources = $derived(distinct(articles, "feed_source"));
  let videoChannels = $derived(distinct(videos, "channel"));

  let hiddenNews = $derived(newsSources.filter((s) => !isFollowed("news", s)).length);
  let hiddenVideos = $derived(videoChannels.filter((c) => !isFollowed("video", c)).length);

  // --- notifications -------------------------------------------------------
  // The toggle must run from the click itself: every browser rejects a
  // permission prompt that is not tied to a user gesture, and Safari does so
  // silently.
  let notifyOn = $state(false);
  let notifyBusy = $state(false);
  let notifyError = $state("");

  let blockedReason = $derived(pushUnavailableReason());

  const REASONS = {
    unsupported: "This browser can’t show notifications.",
    "ios-needs-install": "On iPhone, add feed-mind to your Home Screen first — iOS only delivers notifications to installed apps.",
    denied: "Notifications are blocked for this site. Re-allow them in your browser settings.",
    unconfigured: "Notifications aren’t configured for this deployment yet.",
    dismissed: "Permission wasn’t granted.",
    "signed-out": "Sign in to turn notifications on.",
  };

  $effect(() => {
    const uid = session.user?.uid;
    if (!uid) return;
    isSubscribed(uid).then((v) => (notifyOn = v));
  });

  async function toggleNotifications() {
    const uid = session.user?.uid;
    notifyError = "";
    notifyBusy = true;
    try {
      if (notifyOn) {
        await disablePush(uid);
        notifyOn = false;
      } else {
        const reason = await enablePush(uid);
        if (reason) notifyError = REASONS[reason] ?? "Couldn’t turn notifications on.";
        else notifyOn = true;
      }
    } catch (e) {
      notifyError = e?.message ?? String(e);
    } finally {
      notifyBusy = false;
    }
  }

  function onKeydown(e) {
    if (e.key === "Escape") closeSettings();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="backdrop" onclick={closeSettings}></div>

<div class="sheet" role="dialog" aria-modal="true" aria-label="Source settings">
  <header>
    <h2>Sources</h2>
    <button type="button" class="close" aria-label="Close settings" onclick={closeSettings}>✕</button>
  </header>

  <p class="hint">
    Switch a source off to hide it from your feed. New sources are shown by default.
  </p>

  {#if follows.error}
    <p class="err" role="alert">Couldn’t save that: {follows.error}</p>
  {/if}

  <section class="notify">
    <div class="head"><h3>Notifications</h3></div>
    <p class="hint">
      A single alert when each run finishes — news each morning, papers on Monday.
    </p>
    <label class="row">
      <input
        type="checkbox"
        checked={notifyOn}
        disabled={notifyBusy || (!notifyOn && !!blockedReason)}
        onchange={toggleNotifications}
      />
      <span>{notifyBusy ? "Working…" : "Notify me when new content is ready"}</span>
    </label>
    {#if notifyError}
      <p class="err" role="alert">{notifyError}</p>
    {:else if blockedReason && !notifyOn}
      <p class="hint sub">{REASONS[blockedReason]}</p>
    {/if}
  </section>

  <section>
    <div class="head">
      <h3>News <span class="n">({newsSources.length})</span></h3>
      {#if hiddenNews}
        <button type="button" class="all" onclick={() => followAll("news", newsSources)}>
          Show all
        </button>
      {/if}
    </div>
    {#if newsSources.length}
      {#each newsSources as source (source)}
        <label class="row">
          <input
            type="checkbox"
            checked={isFollowed("news", source)}
            onchange={() => toggleFollow("news", source)}
          />
          <span>{source}</span>
        </label>
      {/each}
    {:else}
      <p class="empty">No news sources loaded yet.</p>
    {/if}
  </section>

  <section>
    <div class="head">
      <h3>Videos <span class="n">({videoChannels.length})</span></h3>
      {#if hiddenVideos}
        <button type="button" class="all" onclick={() => followAll("video", videoChannels)}>
          Show all
        </button>
      {/if}
    </div>
    {#if videoChannels.length}
      {#each videoChannels as channel (channel)}
        <label class="row">
          <input
            type="checkbox"
            checked={isFollowed("video", channel)}
            onchange={() => toggleFollow("video", channel)}
          />
          <span>{channel}</span>
        </label>
      {/each}
    {:else}
      <p class="empty">No channels loaded yet.</p>
    {/if}
  </section>
</div>

<style>
  .backdrop {
    position: fixed; inset: 0; z-index: 40;
    background: rgb(0 0 0 / 0.45);
  }
  .sheet {
    position: fixed; z-index: 41;
    top: 50%; left: 50%; transform: translate(-50%, -50%);
    width: min(440px, calc(100vw - 2rem));
    max-height: min(80vh, 640px); overflow-y: auto;
    padding: 1.1rem 1.25rem 1.4rem;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 12px 40px rgb(0 0 0 / 0.3);
  }
  header { display: flex; align-items: center; justify-content: space-between; }
  h2 { margin: 0; font-size: 1.1rem; }
  .close {
    font: inherit; cursor: pointer; padding: 0.2rem 0.4rem;
    background: none; border: none; color: var(--muted);
  }
  .close:hover { color: var(--text); }

  .hint { margin: 0.35rem 0 1rem; font-size: 0.78rem; color: var(--muted); }
  .hint.sub { margin: 0.4rem 0 0; }
  .notify { margin-bottom: 1.25rem; }
  .err { margin: 0 0 0.8rem; font-size: 0.78rem; color: var(--warn); }

  section { margin-bottom: 1.1rem; }
  .head {
    display: flex; align-items: baseline; justify-content: space-between;
    border-bottom: 1px solid var(--border); padding-bottom: 0.35rem;
    margin-bottom: 0.5rem;
  }
  h3 { margin: 0; font-size: 0.9rem; }
  .n { color: var(--muted); font-weight: 400; font-size: 0.8rem; }
  .all {
    font: inherit; font-size: 0.75rem; cursor: pointer; padding: 0;
    background: none; border: none; color: var(--accent);
  }
  .all:hover { text-decoration: underline; }

  .row {
    display: flex; align-items: center; gap: 0.6rem;
    padding: 0.35rem 0.1rem; font-size: 0.87rem; cursor: pointer;
  }
  .row input { cursor: pointer; }

  .empty { margin: 0; font-size: 0.8rem; color: var(--muted); }
</style>
