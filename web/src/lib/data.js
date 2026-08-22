// Data-source abstraction (PRD §3.5 / §4.3).
//
// Same three functions back both the Latest and Archive views. The source is
// chosen by VITE_DATA_SOURCE: "firestore" reads Firestore directly from the
// browser (the production Path-A contract); "mock" reads bundled JSON fixtures
// so the UI runs with no cloud project.

import {
  LENS_CODES,
  NEWS_WINDOW_DAYS,
  NEWS_MAX_ARTICLES,
  STATIC_NEWS_LINKS,
  VIDEO_WINDOW_DAYS,
  VIDEO_MAX_ITEMS,
} from "./constants.js";

const SOURCE = import.meta.env.VITE_DATA_SOURCE || "mock";

// --- public API -----------------------------------------------------------

/** Latest run per lens -> { AIML: run|null, NLP: ..., CV: ... } */
export function getLatest() {
  return SOURCE === "firestore" ? firestoreLatest() : mockPerLens(1);
}

/** Last 5 runs per lens -> { AIML: run[], NLP: run[], CV: run[] } */
export function getArchive() {
  return SOURCE === "firestore" ? firestoreArchive() : mockArchive();
}

/** Most recent run_status doc, or null. */
export function getStatus() {
  return SOURCE === "firestore" ? firestoreStatus() : mockStatus();
}

/**
 * Last NEWS_WINDOW_DAYS of news articles from `processed_articles`, newest
 * first. One read backs both the News "Latest" (newest day) and "Archive"
 * (whole window) views; the UI slices/groups client-side.
 * -> { articles: Article[] }
 */
export function getNews() {
  return SOURCE === "firestore" ? firestoreNews() : mockNews();
}

/**
 * Last VIDEO_WINDOW_DAYS of YouTube videos from `youtube_videos`, newest first.
 * One read backs both the Videos "Latest" (newest day) and "Archive" (whole
 * window) tabs; the UI slices/groups client-side.
 * -> { videos: Video[] }
 */
export function getVideos() {
  return SOURCE === "firestore" ? firestoreVideos() : mockVideos();
}

// --- Firestore source ------------------------------------------------------

let _db = null;
async function db() {
  if (_db) return _db;
  const { initializeApp } = await import("firebase/app");
  const { getFirestore } = await import("firebase/firestore");
  const app = initializeApp({
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    appId: import.meta.env.VITE_FIREBASE_APP_ID,
  });
  // VITE_FIRESTORE_DATABASE selects a named (non-default) database, and must
  // match the pipeline's FIRESTORE_DATABASE — otherwise the SPA reads an empty
  // "(default)". Unset -> the default database.
  const databaseId = import.meta.env.VITE_FIRESTORE_DATABASE;
  _db = databaseId ? getFirestore(app, databaseId) : getFirestore(app);
  return _db;
}

async function firestoreLatest() {
  const out = {};
  await Promise.all(LENS_CODES.map(async (code) => {
    out[code] = (await latestRuns(code, 1))[0] ?? null;
  }));
  return out;
}

async function firestoreArchive() {
  const out = {};
  await Promise.all(LENS_CODES.map(async (code) => {
    out[code] = await latestRuns(code, 5);
  }));
  return out;
}

async function latestRuns(code, n) {
  const { collection, query, where, orderBy, limit, getDocs } =
    await import("firebase/firestore");
  const q = query(
    collection(await db(), "runs"),
    where("category", "==", code),
    orderBy("run_date", "desc"),
    limit(n),
  );
  const snap = await getDocs(q);
  return snap.docs.map((d) => normalizeRun(d.data()));
}

async function firestoreStatus() {
  const { collection, query, orderBy, limit, getDocs } =
    await import("firebase/firestore");
  const q = query(
    collection(await db(), "run_status"),
    orderBy("run_date", "desc"),
    limit(1),
  );
  const snap = await getDocs(q);
  return snap.empty ? null : snap.docs[0].data();
}

async function firestoreNews() {
  const { collection, query, where, orderBy, limit, getDocs } =
    await import("firebase/firestore");
  // processed_at is a uniform UTC ISO string, so a lexicographic >= range is
  // chronological. Single-field inequality + orderBy needs no composite index.
  const cutoff = newsCutoffIso();
  const q = query(
    collection(await db(), "processed_articles"),
    where("processed_at", ">=", cutoff),
    orderBy("processed_at", "desc"),
    limit(NEWS_MAX_ARTICLES),
  );
  const snap = await getDocs(q);
  return { articles: withPinnedLinks(snap.docs.map((d) => d.data())) };
}

async function firestoreVideos() {
  const { collection, query, where, orderBy, limit, getDocs } =
    await import("firebase/firestore");
  // published_at is a uniform UTC ISO string, so a lexicographic >= range is
  // chronological. Single-field inequality + orderBy needs no composite index.
  const cutoff = videoCutoffIso();
  const q = query(
    collection(await db(), "youtube_videos"),
    where("published_at", ">=", cutoff),
    orderBy("published_at", "desc"),
    limit(VIDEO_MAX_ITEMS),
  );
  const snap = await getDocs(q);
  return { videos: snap.docs.map((d) => normalizeVideo(d.data())) };
}

// --- Mock source (bundled fixtures) ---------------------------------------

async function fixture(path) {
  const res = await fetch(`${import.meta.env.BASE_URL}fixtures/${path}`);
  if (!res.ok) throw new Error(`fixture not found: ${path}`);
  return res.json();
}

async function mockManifest() {
  // manifest lists the available run doc ids, newest first.
  return fixture("manifest.json");
}

async function mockPerLens(n) {
  const manifest = await mockManifest();
  const out = {};
  for (const code of LENS_CODES) {
    const ids = (manifest.runs[code] || []).slice(0, n);
    const runs = await Promise.all(ids.map((id) => fixture(`runs/${id}.json`)));
    out[code] = n === 1 ? (runs[0] ?? null) : runs.map(normalizeRun);
  }
  return out;
}

async function mockArchive() {
  const manifest = await mockManifest();
  const out = {};
  for (const code of LENS_CODES) {
    const ids = (manifest.runs[code] || []).slice(0, 5);
    out[code] = await Promise.all(
      ids.map(async (id) => normalizeRun(await fixture(`runs/${id}.json`))),
    );
  }
  return out;
}

async function mockStatus() {
  try {
    const manifest = await mockManifest();
    return await fixture(`run_status/${manifest.latest_status}.json`);
  } catch {
    return null;
  }
}

async function mockNews() {
  // fixtures/news.json holds raw article docs (same shape as Firestore). Unlike
  // the Firestore path we do NOT apply the 7-day window cutoff here: the fixture
  // is a curated, static "this week" set, and cutoff-filtering would make it age
  // out and render empty after a week. We still sort + cap + normalize.
  let docs;
  try {
    docs = await fixture("news.json");
  } catch {
    return { articles: [] };
  }
  return { articles: withPinnedLinks(docs.slice(0, NEWS_MAX_ARTICLES)) };
}

async function mockVideos() {
  // fixtures/videos.json holds raw video docs (same shape as Firestore). Like
  // mockNews, we do NOT apply the window cutoff to the static fixture — we only
  // sort, cap and normalize — so it doesn't age out and render empty.
  let docs;
  try {
    docs = await fixture("videos.json");
  } catch {
    return { videos: [] };
  }
  return {
    videos: [...docs]
      .sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))
      .slice(0, VIDEO_MAX_ITEMS)
      .map(normalizeVideo),
  };
}

// --- helpers ---------------------------------------------------------------

function newsCutoffIso() {
  return new Date(Date.now() - NEWS_WINDOW_DAYS * 86_400_000).toISOString();
}

function videoCutoffIso() {
  return new Date(Date.now() - VIDEO_WINDOW_DAYS * 86_400_000).toISOString();
}

// Merge the reader-pinned static links (e.g. GitHub Trending) into the fetched
// docs so they appear every day. Pinned links get a fresh "now" timestamp (so
// they sort into today's "Latest") and win any article_id collision with a
// pipeline-written doc — so a static link is shown exactly once whether or not
// feed-mind also persisted it. Input docs are raw (Firestore/fixture) shape.
function withPinnedLinks(docs) {
  const nowIso = new Date().toISOString();
  const pinned = STATIC_NEWS_LINKS.map((link) => ({
    ...link,
    processed_at: nowIso,
    published_at: nowIso,
    status: "pinned",
  }));
  const pinnedIds = new Set(pinned.map((p) => p.article_id));
  const rest = docs.filter((d) => !pinnedIds.has(d.article_id));
  return [...pinned, ...rest]
    .sort((a, b) => (b.processed_at ?? "").localeCompare(a.processed_at ?? ""))
    .map(normalizeArticle);
}

function normalizeRun(run) {
  return { ...run, run_date: toDate(run.run_date) };
}

// processed_at drives ordering/grouping; keep the raw ISO string for day
// bucketing and expose a Date for display. `summary` may be absent on docs
// written before feed-mind persisted it; `ai_summary` / `audio_url` likewise,
// and they are absent by design on the pinned `open-source` links, which have
// no pipeline-generated content at all.
function normalizeArticle(a) {
  return {
    ...a,
    summary: a.summary ?? "",
    ai_summary: a.ai_summary ?? "",
    audio_url: publicAudioUrl(a.audio_url),
    processed_date: toDate(a.processed_at),
    published_date: toDate(a.published_at),
  };
}

// feed-mind writes the Cloud Storage object for the audio summary. Accept both
// an already-public https URL and a bare gs:// URI, so the reader keeps working
// whichever form the writer settles on. Anything else -> "" (no audio).
function publicAudioUrl(value) {
  if (typeof value !== "string" || !value) return "";
  if (value.startsWith("https://") || value.startsWith("http://")) return value;
  if (value.startsWith("gs://")) {
    const [bucket, ...object] = value.slice(5).split("/");
    if (!bucket || !object.length) return "";
    const path = object.map(encodeURIComponent).join("/");
    return `https://storage.googleapis.com/${bucket}/${path}`;
  }
  return "";
}

// published_at drives ordering/day-bucketing; keep the raw ISO string and also
// expose a Date for display.
function normalizeVideo(v) {
  return {
    ...v,
    published_date: toDate(v.published_at),
    processed_date: toDate(v.processed_at),
  };
}

// Firestore Timestamp | ISO string | Date -> Date
function toDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (typeof value.toDate === "function") return value.toDate(); // Firestore Timestamp
  return new Date(value);
}
