// Shared sign-in state, so any component can read who is signed in without
// each one subscribing to auth itself. Same module-scope-$state pattern as
// consentUi.svelte.js.
//
// There are FOUR states, not two. Firebase Auth will happily create an account
// for anyone with a Google account, but firestore.rules only lets an
// allowlisted email touch its own document — so "signed in" and "allowed" are
// different questions, and a visitor can be the first without being the second.
// Leaving that person in a logged-in-looking UI whose every write fails is the
// worst outcome, so they are signed straight back out with an explanation.
//
//   loading  — auth state not yet known (first paint; don't flash "Sign in")
//   out      — nobody signed in
//   in       — signed in AND allowlisted
//   rejected — signed in but not allowlisted; already signed back out

import { onUser, signIn, signOut } from "./auth.js";
import { probeAccess } from "./prefs.js";
import { initBookmarks, resetBookmarks } from "./bookmarks.svelte.js";
import { initFollows, resetFollows } from "./follows.svelte.js";

export const session = $state({
  status: "loading",
  user: null,
  /** Set when sign-in itself failed, for display. Not used for `rejected`. */
  error: null,
});

let started = false;

/** Begin tracking auth state. Idempotent; call once from App.onMount. */
export function startSession() {
  if (started) return () => {};
  started = true;

  return onUser(async (user) => {
    if (!user) {
      session.user = null;
      resetBookmarks();
      resetFollows();
      // Preserve `rejected` across the sign-out it triggers itself, otherwise
      // the explanation vanishes in the same tick it was set.
      if (session.status !== "rejected") session.status = "out";
      return;
    }

    if (await probeAccess(user.uid)) {
      session.user = user;
      session.status = "in";
      session.error = null;
      // Not awaited: the signed-in UI should paint immediately, and the stars
      // and source filters fill in when they arrive.
      initBookmarks(user.uid);
      initFollows(user.uid);
    } else {
      // Not on the allowlist. Sign out first, then mark rejected — the
      // resulting null-user callback runs before this assignment.
      session.user = null;
      await signOut();
      session.status = "rejected";
    }
  });
}

export async function requestSignIn() {
  session.error = null;
  try {
    await signIn();
    // Deliberately no state change here: the onUser subscription above owns
    // every transition, so the popup path and a restored session behave alike.
  } catch (e) {
    // Closing the popup is a normal thing to do, not an error worth showing.
    if (e?.code === "auth/popup-closed-by-user" || e?.code === "auth/cancelled-popup-request") return;
    session.error = e?.message ?? String(e);
  }
}

export async function requestSignOut() {
  await signOut();
  session.status = "out";
  session.user = null;
  session.error = null;
  resetBookmarks();
  resetFollows();
}

/** Dismiss the "no access" notice and return to a plain signed-out state. */
export function clearRejection() {
  if (session.status === "rejected") session.status = "out";
}
