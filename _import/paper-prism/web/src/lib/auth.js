// Sign-in, as a data-source abstraction mirroring data.js.
//
// The same VITE_DATA_SOURCE switch picks the backend: "firestore" uses real
// Firebase Auth (Google provider, popup flow); anything else uses a local fake.
// That fake is not a convenience — `npm run dev` forces mock with *empty*
// Firebase keys, so without it there is no project to authenticate against and
// the signed-in half of the UI would be unreachable outside production. The
// component tests rely on the same path.
//
// firebase/auth is behind a dynamic import(), so mock builds never ship the SDK
// (see firebase.js, which owns the shared app instance).
//
// Sign-in is Google-only for now. Microsoft was considered and deferred: it
// needs an Entra ID app registration whose client secret expires on a 6-24 month
// timer, which breaks sign-in silently and has no place in a zero-ops project.
// Adding it later means adding a provider here and a button in AccountMenu —
// the rest of the app only ever sees the normalized user below.

import { firebaseApp } from "./firebase.js";

const SOURCE = import.meta.env.VITE_DATA_SOURCE || "mock";

/** True when auth is faked locally (no Firebase project involved). */
export const isMockAuth = SOURCE !== "firestore";

// --- public API ------------------------------------------------------------

/**
 * Open the provider's sign-in flow. Resolves with the signed-in user, or
 * throws — including when the visitor simply closes the popup, which Firebase
 * reports as `auth/popup-closed-by-user`.
 */
export function signIn() {
  return isMockAuth ? mockSignIn() : firebaseSignIn();
}

/** Sign out. Safe to call when already signed out. */
export function signOut() {
  return isMockAuth ? mockSignOut() : firebaseSignOut();
}

/**
 * Subscribe to the signed-in user. The callback fires once with the current
 * value (null when signed out) and again on every change. Returns an
 * unsubscribe function.
 *
 * @param {(user: {uid: string, email: string, displayName: string, photoURL: string}|null) => void} cb
 */
export function onUser(cb) {
  return isMockAuth ? mockOnUser(cb) : firebaseOnUser(cb);
}

// --- Firebase source -------------------------------------------------------

async function auth() {
  const { getAuth } = await import("firebase/auth");
  return getAuth(await firebaseApp());
}

async function firebaseSignIn() {
  const { GoogleAuthProvider, signInWithPopup } = await import("firebase/auth");
  // Popup rather than redirect: the redirect flow needs extra configuration on
  // custom domains and is degraded by Safari's storage partitioning, which
  // fails in a way that looks like "nothing happened".
  const cred = await signInWithPopup(await auth(), new GoogleAuthProvider());
  return normalizeUser(cred.user);
}

async function firebaseSignOut() {
  const { signOut: fbSignOut } = await import("firebase/auth");
  await fbSignOut(await auth());
}

function firebaseOnUser(cb) {
  // getAuth() is async (it awaits the SDK import), so the subscription can't be
  // established synchronously. Guard against unsubscribing before it exists.
  let cancelled = false;
  let unsub = null;

  (async () => {
    const a = await auth();
    const { onAuthStateChanged } = await import("firebase/auth");
    if (cancelled) return;
    unsub = onAuthStateChanged(a, (u) => cb(normalizeUser(u)));
  })();

  return () => {
    cancelled = true;
    unsub?.();
  };
}

// --- Mock source -----------------------------------------------------------

const MOCK_USER = Object.freeze({
  uid: "mock-user",
  email: "dev@localhost",
  displayName: "Local Dev",
  photoURL: "",
});

// Mirrors Firebase's default local persistence: a reload keeps you signed in,
// so the dev experience matches production.
const MOCK_KEY = "fm-mock-signed-in";

const listeners = new Set();

function mockRead() {
  try {
    return localStorage.getItem(MOCK_KEY) ? { ...MOCK_USER } : null;
  } catch {
    return null; // private mode / no storage: signed out, never a crash
  }
}

function mockWrite(signedIn) {
  try {
    if (signedIn) localStorage.setItem(MOCK_KEY, "1");
    else localStorage.removeItem(MOCK_KEY);
  } catch {
    /* storage unavailable — the session just won't survive a reload */
  }
}

function emit() {
  const user = mockRead();
  for (const cb of listeners) cb(user);
}

async function mockSignIn() {
  mockWrite(true);
  emit();
  return { ...MOCK_USER };
}

async function mockSignOut() {
  mockWrite(false);
  emit();
}

function mockOnUser(cb) {
  listeners.add(cb);
  // Async first call, matching onAuthStateChanged — a synchronous callback
  // would run before the caller has finished wiring up its own state.
  Promise.resolve().then(() => {
    if (listeners.has(cb)) cb(mockRead());
  });
  return () => listeners.delete(cb);
}

// --- helpers ---------------------------------------------------------------

// A plain object, not the Firebase User class: nothing downstream should have
// to know which backend produced it, and tests shouldn't need the SDK. Absent
// fields become "" rather than null/undefined so templates can render directly
// (a Google account with no photo is normal).
function normalizeUser(u) {
  if (!u) return null;
  return {
    uid: u.uid,
    email: u.email ?? "",
    displayName: u.displayName ?? "",
    photoURL: u.photoURL ?? "",
  };
}
