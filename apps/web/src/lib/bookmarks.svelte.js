// The signed-in user's saved items, held once for the whole app.
//
// Shared state rather than per-component fetching, because the same item can be
// on screen in two places at once (a card in News and its entry in Saved), and
// starring in one must update the other immediately. Loaded once per sign-in;
// every mutation writes through to prefs.js and keeps the local list in step.
//
// Does NOT import session.svelte.js — session drives this module (on sign-in /
// sign-out), so depending back on it would be circular. The uid is handed in.

import {
  loadBookmarks,
  saveBookmark,
  removeBookmark,
  bookmarkIdFor,
  BookmarkLimitError,
} from "./prefs.js";
import { BOOKMARK_LIMIT } from "./constants.js";

export const bookmarks = $state({
  items: [],
  loading: false,
  /** Set when the list could not be loaded; saving still works. */
  error: null,
});

let uid = null;

/** Load the list for a signed-in user. Called by session.svelte.js. */
export async function initBookmarks(userId) {
  uid = userId;
  bookmarks.loading = true;
  bookmarks.error = null;
  try {
    bookmarks.items = await loadBookmarks(userId);
  } catch (e) {
    // A failed load must not break the page: the site is public and readable
    // without any of this.
    bookmarks.items = [];
    bookmarks.error = e?.message ?? String(e);
  } finally {
    bookmarks.loading = false;
  }
}

/** Drop everything on sign-out, so the next user never sees the last one's list. */
export function resetBookmarks() {
  uid = null;
  bookmarks.items = [];
  bookmarks.loading = false;
  bookmarks.error = null;
}

export function isSaved(type, item) {
  const id = bookmarkIdFor(type, item);
  return bookmarks.items.some((b) => b.id === id);
}

export function atLimit() {
  return bookmarks.items.length >= BOOKMARK_LIMIT;
}

/**
 * Star / unstar one item. Throws BookmarkLimitError when saving would exceed
 * the cap, so the calling button can show the message next to itself rather
 * than as global state.
 */
export async function toggleBookmark(type, item) {
  if (!uid) return;
  if (isSaved(type, item)) {
    bookmarks.items = await removeBookmark(uid, bookmarkIdFor(type, item));
    return;
  }
  // Let BookmarkLimitError propagate; anything else is a real failure and
  // should surface the same way.
  bookmarks.items = await saveBookmark(uid, type, item);
}

/** Remove by id — what the Saved view's remove control calls. */
export async function removeSaved(id) {
  if (!uid) return;
  bookmarks.items = await removeBookmark(uid, id);
}

export { BookmarkLimitError };
