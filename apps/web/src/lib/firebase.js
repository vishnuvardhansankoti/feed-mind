// The one Firebase app instance, shared by every SDK surface.
//
// `initializeApp()` is not idempotent — a second call throws "Firebase App
// named '[DEFAULT]' already exists". data.js owned the call privately while
// Firestore was the only consumer; auth.js is the second one, so the instance
// moved here rather than being created twice.
//
// Still behind a dynamic `import()`, so `VITE_DATA_SOURCE=mock` builds never
// pull the Firebase SDK into the bundle. This module itself is plain JS, so a
// static import of it costs a mock build nothing.

/**
 * The public (non-secret) Firebase web config, assembled from the build-time
 * VITE_* values. Pure and parameterized so it can be tested without a build.
 *
 * `authDomain` is the origin the sign-in popup posts its result back to.
 * Firestore alone never needed it, which is why it was absent from this config
 * until sign-in was added — reads worked fine and auth would have failed with
 * an unhelpful error. It defaults to the project's `firebaseapp.com` domain
 * (what the console provisions), so only a custom auth domain needs the env
 * var set explicitly.
 *
 * @param {Record<string, string|undefined>} [env]
 */
export function firebaseConfig(env = import.meta.env) {
  const projectId = env.VITE_FIREBASE_PROJECT_ID;
  return {
    apiKey: env.VITE_FIREBASE_API_KEY,
    authDomain:
      env.VITE_FIREBASE_AUTH_DOMAIN || (projectId ? `${projectId}.firebaseapp.com` : ""),
    projectId,
    appId: env.VITE_FIREBASE_APP_ID,
  };
}

let _app = null;

/** The memoized Firebase app. Callers must be in a `firestore` build. */
export async function firebaseApp() {
  if (_app) return _app;
  const { initializeApp } = await import("firebase/app");
  _app = initializeApp(firebaseConfig());
  return _app;
}

let _db = null;

/**
 * The memoized Firestore handle, shared by every reader and writer.
 *
 * VITE_FIRESTORE_DATABASE selects a named (non-default) database and must match
 * the pipeline's FIRESTORE_DATABASE — otherwise the SPA silently reads an empty
 * "(default)". Unset -> the default database. This lives here rather than in
 * data.js because a second caller (prefs.js) would otherwise have to duplicate
 * the choice, and a copy that drifts fails silently in exactly that way.
 */
export async function firestoreDb() {
  if (_db) return _db;
  const { getFirestore } = await import("firebase/firestore");
  const app = await firebaseApp();
  const databaseId = import.meta.env.VITE_FIRESTORE_DATABASE;
  _db = databaseId ? getFirestore(app, databaseId) : getFirestore(app);
  return _db;
}
