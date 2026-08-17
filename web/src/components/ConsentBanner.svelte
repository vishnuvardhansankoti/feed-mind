<script>
  // Cookie consent banner for Consent Mode v2 (analytics.js). Shown only when
  // analytics is actually configured (a build-time measurement id) AND the
  // visitor hasn't chosen yet. Accept/Decline flip the GA consent signal and
  // persist the choice, so the banner never reappears once answered.
  import {
    analyticsEnabled,
    getConsent,
    grantConsent,
    denyConsent,
  } from "../lib/analytics.js";
  import { consentUi } from "../lib/consentUi.svelte.js";

  // Show on first visit (no stored choice) or when reopened from the footer.
  let decided = $state(getConsent() !== null);
  let visible = $derived(analyticsEnabled && (!decided || consentUi.open));

  function accept() {
    grantConsent();
    decided = true;
    consentUi.open = false;
  }
  function decline() {
    denyConsent();
    decided = true;
    consentUi.open = false;
  }
</script>

{#if visible}
  <div class="consent" role="dialog" aria-label="Cookie consent" aria-live="polite">
    <p class="msg">
      We use privacy-friendly analytics (Google Analytics) to understand which
      sections are useful. No data is collected until you accept.
    </p>
    <div class="actions">
      <button class="decline" onclick={decline}>Decline</button>
      <button class="accept" onclick={accept}>Accept</button>
    </div>
  </div>
{/if}

<style>
  .consent {
    position: fixed; left: 1rem; right: 1rem; bottom: 1rem; z-index: 50;
    max-width: 640px; margin: 0 auto;
    display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem 1rem;
    padding: 0.9rem 1.1rem; border-radius: var(--radius);
    background: var(--surface); border: 1px solid var(--border);
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
  }
  .msg { margin: 0; flex: 1 1 260px; font-size: 0.85rem; color: var(--muted); }
  .actions { display: flex; gap: 0.5rem; margin-left: auto; }
  .consent button {
    font: inherit; font-size: 0.85rem; font-weight: 600; cursor: pointer;
    padding: 0.45rem 1rem; border-radius: 999px; border: 1px solid var(--border);
  }
  .decline { background: none; color: var(--muted); }
  .decline:hover { color: var(--text); background: var(--surface-2); }
  .accept { background: var(--accent); color: #fff; border-color: var(--accent); }
  .accept:hover { filter: brightness(1.05); }
</style>
