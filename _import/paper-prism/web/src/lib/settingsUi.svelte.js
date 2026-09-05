// Shared UI state so the account menu (AccountMenu.svelte) can open the
// settings sheet, which App.svelte renders — same pattern as consentUi.
// The sheet needs the loaded news/videos to build its source list, and App is
// what holds those, so it can't live inside the menu itself.
export const settingsUi = $state({ open: false });

export function openSettings() {
  settingsUi.open = true;
}

export function closeSettings() {
  settingsUi.open = false;
}
