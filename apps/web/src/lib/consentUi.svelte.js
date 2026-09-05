// Shared UI state so the footer "Cookie settings" link (App.svelte) can reopen
// the consent banner (ConsentBanner.svelte) after a choice has already been made.
// The actual consent value lives in localStorage via analytics.js; this only
// controls whether the banner is forced visible.
export const consentUi = $state({ open: false });

export function openConsent() {
  consentUi.open = true;
}
