// Which news sources / YouTube channels the signed-in user has switched off.
//
// Held once for the whole app, like bookmarks.svelte.js, because the same
// answer is needed by NewsFeed, VideoFeed and the settings sheet at the same
// time. Stored as the UNFOLLOWED set — see prefs.js::loadUnfollowed for why
// that direction matters.
//
// Deliberately answers "followed" for everyone when signed out or unloaded, so
// the public site and a fresh account both show the complete feed.

import { loadUnfollowed, saveUnfollowed } from "./prefs.js";

export const follows = $state({
  /** { news: string[], video: string[] } — sources switched OFF. */
  unfollowed: { news: [], video: [] },
  loading: false,
  error: null,
});

let uid = null;

/** Load for a signed-in user. Called by session.svelte.js. */
export async function initFollows(userId) {
  uid = userId;
  follows.loading = true;
  follows.error = null;
  try {
    follows.unfollowed = await loadUnfollowed(userId);
  } catch (e) {
    // Failing open: show everything rather than hiding content because a
    // preference read failed.
    follows.unfollowed = { news: [], video: [] };
    follows.error = e?.message ?? String(e);
  } finally {
    follows.loading = false;
  }
}

export function resetFollows() {
  uid = null;
  follows.unfollowed = { news: [], video: [] };
  follows.loading = false;
  follows.error = null;
}

/**
 * Is this source shown? True unless it was explicitly switched off, so an
 * unknown or brand-new source is followed by default.
 *
 * @param {"news"|"video"} kind
 * @param {string} name  feed_source (news) or channel (video)
 */
export function isFollowed(kind, name) {
  return !(follows.unfollowed[kind] ?? []).includes(name);
}

/** Flip one source on/off and persist. */
export async function toggleFollow(kind, name) {
  const current = follows.unfollowed[kind] ?? [];
  const next = current.includes(name)
    ? current.filter((n) => n !== name)
    : [...current, name];

  // Optimistic: the checkbox and the feed update together, before the write
  // lands. A failed write is reported but not rolled back — the next load
  // reconciles, and silently reverting a toggle under the user is worse.
  follows.unfollowed = { ...follows.unfollowed, [kind]: next };
  if (!uid) return;
  try {
    await saveUnfollowed(uid, follows.unfollowed);
    follows.error = null;
  } catch (e) {
    follows.error = e?.message ?? String(e);
  }
}

/** Switch every listed source back on. */
export async function followAll(kind, names) {
  follows.unfollowed = { ...follows.unfollowed, [kind]: [] };
  if (!uid) return;
  try {
    await saveUnfollowed(uid, follows.unfollowed);
  } catch (e) {
    follows.error = e?.message ?? String(e);
  }
}
