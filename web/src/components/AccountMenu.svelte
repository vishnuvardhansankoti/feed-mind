<script>
  // Sign-in control for the masthead. Renders one of the four session states
  // (see lib/session.svelte.js); the signed-out site is unchanged, so this is
  // purely additive — nothing here gates content.
  import { session, requestSignIn, requestSignOut, clearRejection } from "../lib/session.svelte.js";
  import { openSettings } from "../lib/settingsUi.svelte.js";

  let open = $state(false);

  // First letter of the display name, or of the email, as a photo fallback —
  // a Google account with no picture is common.
  let initial = $derived(
    (session.user?.displayName || session.user?.email || "?").trim().charAt(0).toUpperCase(),
  );

  const close = () => (open = false);

  async function onSignOut() {
    close();
    await requestSignOut();
  }

  function onSettings() {
    close();
    openSettings();
  }

  // Close on outside click / Escape. Bound on window so it also catches clicks
  // in the rest of the masthead.
  function onWindowClick(e) {
    if (open && !e.target.closest?.(".account")) close();
  }
  function onKeydown(e) {
    if (e.key === "Escape") close();
  }
</script>

<svelte:window onclick={onWindowClick} onkeydown={onKeydown} />

<div class="account">
  {#if session.status === "loading"}
    <!-- Nothing: a "Sign in" button that flips to an avatar a tick later is
         worse than a brief gap, and auth state resolves fast. -->
  {:else if session.status === "rejected"}
    <div class="rejected" role="status">
      <span>This account doesn’t have access.</span>
      <button type="button" onclick={clearRejection}>Dismiss</button>
    </div>
  {:else if session.status === "in"}
    <button
      type="button"
      class="avatar-btn"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-label="Account menu"
      onclick={() => (open = !open)}
    >
      {#if session.user?.photoURL}
        <img class="avatar" src={session.user.photoURL} alt="" referrerpolicy="no-referrer" />
      {:else}
        <span class="avatar fallback" aria-hidden="true">{initial}</span>
      {/if}
    </button>

    {#if open}
      <div class="menu" role="menu">
        <div class="who">
          {#if session.user?.displayName}<strong>{session.user.displayName}</strong>{/if}
          <span class="email">{session.user?.email}</span>
        </div>
        <button type="button" role="menuitem" onclick={onSettings}>Sources…</button>
        <button type="button" role="menuitem" onclick={onSignOut}>Sign out</button>
      </div>
    {/if}
  {:else}
    <button type="button" class="signin" onclick={requestSignIn}>Sign in</button>
    {#if session.error}
      <span class="err" role="alert">{session.error}</span>
    {/if}
  {/if}
</div>

<style>
  .account { position: relative; display: flex; align-items: center; gap: 0.5rem; }

  .signin {
    font: inherit; font-size: 0.85rem; cursor: pointer;
    padding: 0.4rem 0.9rem; border-radius: 999px;
    background: var(--surface); color: var(--text);
    border: 1px solid var(--border);
  }
  .signin:hover { border-color: var(--accent); color: var(--accent); }

  .avatar-btn {
    padding: 0; cursor: pointer; background: none; border: none;
    border-radius: 50%; line-height: 0;
  }
  .avatar {
    width: 30px; height: 30px; border-radius: 50%;
    border: 1px solid var(--border); object-fit: cover;
  }
  .fallback {
    display: grid; place-items: center;
    background: var(--accent); color: #fff;
    font-size: 0.8rem; font-weight: 600; line-height: 1;
  }

  .menu {
    position: absolute; top: calc(100% + 0.4rem); right: 0; z-index: 20;
    min-width: 190px; padding: 0.4rem;
    display: flex; flex-direction: column; gap: 0.2rem;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: 0 8px 24px rgb(0 0 0 / 0.18);
  }
  .who {
    display: flex; flex-direction: column; gap: 0.1rem;
    padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border);
    margin-bottom: 0.2rem;
  }
  .who strong { font-size: 0.85rem; }
  .email { font-size: 0.75rem; color: var(--muted); word-break: break-all; }
  .menu button {
    font: inherit; font-size: 0.85rem; cursor: pointer; text-align: left;
    padding: 0.45rem 0.6rem; border-radius: calc(var(--radius) - 2px);
    background: none; border: none; color: var(--text);
  }
  .menu button:hover { background: var(--bg); color: var(--accent); }

  .rejected {
    display: flex; align-items: center; gap: 0.5rem;
    font-size: 0.78rem; color: var(--muted);
  }
  .rejected button {
    font: inherit; font-size: inherit; cursor: pointer; padding: 0;
    background: none; border: none; color: var(--accent);
  }
  .rejected button:hover { text-decoration: underline; }

  .err { font-size: 0.75rem; color: var(--warn); max-width: 220px; }
</style>
