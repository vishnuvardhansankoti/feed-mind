// The per-user document, `users/{uid}` — the only place the browser is ever
// allowed to write. Everything else in this app is public-read / write:false.
//
// Everything for one user lives on ONE document: `bookmarks` (a capped array)
// and, next, followed sources. That shape is deliberate — see BOOKMARK_LIMIT in
// constants.js for why the cap and the single document imply each other.
//
// Mirrors data.js's two-backend split, so `npm run dev` (mock, no Firebase
// keys) is fully usable: the mock backend keeps the same document in
// localStorage.

import { firestoreDb } from "./firebase.js";
import { BOOKMARK_LIMIT } from "./constants.js";

const SOURCE = import.meta.env.VITE_DATA_SOURCE || "mock";
const isMock = SOURCE !== "firestore";

/**
 * Whether this user is on the allowlist.
 *
 * The allowlist lives in firestore.rules and nowhere else — deliberately. The
 * client could carry a copy for an instant answer, but that ships real email
 * addresses in a public bundle and creates two lists that drift. Instead the
 * client *probes*: read the user's own document and let the rules answer. A
 * document that doesn't exist yet still reads successfully when allowed, so a
 * brand-new user is correctly recognized without writing anything.
 *
 * Only `permission-denied` means "not allowed". Any other failure (offline, a
 * transient Firestore error) resolves true: signing someone out over a network
 * blip is worse than letting them in, and it is not a security decision anyway
 * — the rules still reject every write from an account that isn't listed.
 *
 * @returns {Promise<boolean>}
 */
export async function probeAccess(uid) {
  if (isMock) return true; // mock: everyone is allowed
  try {
    const { doc, getDoc } = await import("firebase/firestore");
    await getDoc(doc(await firestoreDb(), "users", uid));
    return true;
  } catch (e) {
    if (e?.code === "permission-denied") return false;
    return true;
  }
}

/** Thrown by saveBookmark() when the user is already at BOOKMARK_LIMIT. */
export class BookmarkLimitError extends Error {
  constructor() {
    super(`Bookmark limit reached (${BOOKMARK_LIMIT})`);
    this.name = "BookmarkLimitError";
  }
}

/**
 * A stable id for one saved item, namespaced by type so a paper and a video
 * can never collide. Deterministic, like the pipeline's document ids — saving
 * the same card twice is a no-op rather than a duplicate.
 */
export function bookmarkIdFor(type, item) {
  const raw =
    type === "paper" ? item.arxiv_id
    : type === "news" ? item.article_id
    : item.video_id;
  return `${type}_${raw ?? ""}`;
}

/**
 * The stored form of a saved item: everything the Saved view needs to render
 * it, and nothing else.
 *
 * This is a COPY, not a reference, because every source collection is on a TTL
 * — runs expire after 45 days, articles and videos after 90 — and papers are
 * not even documents (they live inside the `papers` array of a run doc, so
 * there is nothing to point at). A saved item therefore has to carry its own
 * content or it rots. The tradeoff is that a snapshot never updates: if the
 * pipeline later backfills an `ai_summary`, the saved copy won't have it.
 *
 * Fields are whitelisted per type rather than spread, so Date objects, full
 * abstracts, and future unrelated fields stay out of the document. Every value
 * is coerced to a string — Firestore rejects `undefined` outright.
 */
export function snapshotOf(type, item) {
  const base = {
    id: bookmarkIdFor(type, item),
    type,
    title: str(item.title),
    url: str(item.url),
    saved_at: new Date().toISOString(),
  };
  if (type === "paper") {
    return { ...base, arxiv_id: str(item.arxiv_id), summary: str(item.summary) };
  }
  if (type === "news") {
    return {
      ...base,
      feed_source: str(item.feed_source),
      summary: str(item.summary),
      published_at: str(item.processed_at || item.published_at),
    };
  }
  return {
    ...base,
    channel: str(item.channel),
    thumbnail_url: str(item.thumbnail_url),
    published_at: str(item.published_at),
  };
}

/**
 * Read the user's saved items, newest save first.
 * Returns an empty list rather than throwing when the document doesn't exist.
 */
export async function loadBookmarks(uid) {
  const items = isMock ? mockRead(uid) : await firestoreRead(uid);
  return [...items].sort((a, b) => (b.saved_at ?? "").localeCompare(a.saved_at ?? ""));
}

/**
 * Save one item. Throws BookmarkLimitError at the cap — deliberately NOT
 * evicting the oldest: silently deleting something the user chose to keep is
 * worse than refusing, and the UI points them at the Saved view to free a slot.
 * Re-saving an already-saved item is a no-op.
 *
 * @returns {Promise<Array>} the updated list
 */
export async function saveBookmark(uid, type, item) {
  const current = await loadBookmarks(uid);
  const snap = snapshotOf(type, item);
  if (current.some((b) => b.id === snap.id)) return current;
  if (current.length >= BOOKMARK_LIMIT) throw new BookmarkLimitError();
  return write(uid, [snap, ...current]);
}

/** Remove one saved item by id. Removing something absent is a no-op. */
export async function removeBookmark(uid, id) {
  const current = await loadBookmarks(uid);
  return write(uid, current.filter((b) => b.id !== id));
}

/**
 * Which sources the user has switched OFF, as `{ news: [...], video: [...] }`.
 *
 * Stored as the *unfollowed* set rather than the followed one, which is the
 * whole trick: the source catalog is not ours — it lives in feed-mind's
 * config.py and grows whenever a feed or channel is added there. A stored
 * "followed" list would silently hide every new source from existing users,
 * and there is no migration step in a client-only app to fix that. Storing the
 * exclusions instead means absence = followed, so a new feed shows up for
 * everyone automatically and a user with no preferences at all sees everything
 * — the same degrade-rather-than-break rule the optional card fields follow.
 */
export async function loadUnfollowed(uid) {
  const raw = isMock ? mockReadUnfollowed(uid) : await firestoreReadUnfollowed(uid);
  return { news: raw?.news ?? [], video: raw?.video ?? [] };
}

/** Persist the unfollowed set. Returns what was written. */
export async function saveUnfollowed(uid, unfollowed) {
  const clean = {
    news: [...new Set(unfollowed.news ?? [])].map(str),
    video: [...new Set(unfollowed.video ?? [])].map(str),
  };
  if (isMock) mockWriteUnfollowed(uid, clean);
  else await firestoreWriteUnfollowed(uid, clean);
  return clean;
}

// --- backends --------------------------------------------------------------

function write(uid, items) {
  return isMock ? mockWrite(uid, items) : firestoreWrite(uid, items);
}

async function firestoreReadUnfollowed(uid) {
  const { doc, getDoc } = await import("firebase/firestore");
  const snap = await getDoc(doc(await firestoreDb(), "users", uid));
  return snap.exists() ? snap.data().unfollowed : null;
}

async function firestoreWriteUnfollowed(uid, unfollowed) {
  const { doc, setDoc } = await import("firebase/firestore");
  // merge:true, so writing preferences never clobbers `bookmarks` on the same
  // document — the mirror image of firestoreWrite().
  await setDoc(doc(await firestoreDb(), "users", uid), { unfollowed }, { merge: true });
}

const mockPrefsKey = (uid) => `fm-unfollowed-${uid}`;

function mockReadUnfollowed(uid) {
  try {
    return JSON.parse(localStorage.getItem(mockPrefsKey(uid)) ?? "null");
  } catch {
    return null;
  }
}

function mockWriteUnfollowed(uid, unfollowed) {
  try {
    localStorage.setItem(mockPrefsKey(uid), JSON.stringify(unfollowed));
  } catch {
    /* storage unavailable — the preference just isn't remembered */
  }
}

async function firestoreRead(uid) {
  const { doc, getDoc } = await import("firebase/firestore");
  const snap = await getDoc(doc(await firestoreDb(), "users", uid));
  return snap.exists() ? (snap.data().bookmarks ?? []) : [];
}

async function firestoreWrite(uid, items) {
  const { doc, setDoc } = await import("firebase/firestore");
  // merge:true so writing bookmarks never clobbers `followed` on the same
  // document. Read-modify-write is last-write-wins across tabs, which is an
  // acceptable trade for a five-item list; the rules' size() check is the
  // backstop if a stale read ever tries to push a sixth.
  await setDoc(doc(await firestoreDb(), "users", uid), { bookmarks: items }, { merge: true });
  return items;
}

const mockKey = (uid) => `fm-bookmarks-${uid}`;

function mockRead(uid) {
  try {
    return JSON.parse(localStorage.getItem(mockKey(uid)) ?? "[]");
  } catch {
    return []; // unparseable or storage unavailable — start empty, never throw
  }
}

function mockWrite(uid, items) {
  try {
    localStorage.setItem(mockKey(uid), JSON.stringify(items));
  } catch {
    /* storage unavailable — the save just isn't remembered */
  }
  return items;
}

const str = (v) => (v == null ? "" : String(v));
