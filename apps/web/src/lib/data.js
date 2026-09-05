// Data-source abstraction (PRD §3.5 / §4.3).
//
// Same three functions back both the Latest and Archive views. The source is
// chosen by VITE_DATA_SOURCE: "firestore" reads Firestore directly from the
// browser (the production Path-A contract); "mock" reads bundled JSON fixtures
// so the UI runs with no cloud project.

import { firestoreDb } from "./firebase.js";
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
export async function getStatus() {
  const doc = SOURCE === "firestore" ? await firestoreStatus() : await mockStatus();
  return normalizeStatus(doc);
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

// The app instance and the named-database choice are shared with auth.js and
// prefs.js (initializeApp() throws on a second call), so both live in
// firebase.js. `db` keeps its old name here to leave the call sites untouched.
const db = firestoreDb;

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
  // Window on `processed_at`, not `published_at`. Both are uniform UTC ISO
  // strings, so either supports a lexicographic >= range — but every doc in one
  // ingest batch shares a `processed_at`, so a batch ages out of the window all
  // at once. Windowing on `published_at` instead dropped videos one by one as
  // the clock advanced, quietly shrinking the tab between refreshes.
  // Single-field inequality + matching orderBy still needs no composite index.
  const cutoff = videoCutoffIso();
  const q = query(
    collection(await db(), "youtube_videos"),
    where("processed_at", ">=", cutoff),
    orderBy("processed_at", "desc"),
    limit(VIDEO_MAX_ITEMS),
  );
  const snap = await getDocs(q);
  return { videos: byPublishedDesc(snap.docs.map((d) => d.data())) };
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
    // Normalize on both branches: the single-run path feeds the same PaperCard,
    // which needs the defaulted ai_summary/audio_url the raw fixture lacks.
    const normalized = runs.map(normalizeRun);
    out[code] = n === 1 ? (normalized[0] ?? null) : normalized;
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
  // Sort before capping, so the cap keeps the newest items rather than
  // whichever ones happened to sit at the head of the fixture.
  return { videos: byPublishedDesc(docs).slice(0, VIDEO_MAX_ITEMS) };
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

// The status doc was the one payload returned raw, which was fine while nothing
// rendered its date: `run_date` arrives as a Firestore Timestamp in production
// but as an ISO string from the fixtures, so anything formatting it would work
// in dev and throw in prod. Coerce it the same way runs and articles are.
function normalizeStatus(doc) {
  if (!doc) return null;
  return {
    ...doc,
    run_date: toDate(doc.run_date),
    categories: doc.categories ?? {},
  };
}

function normalizeRun(run) {
  return {
    ...run,
    run_date: toDate(run.run_date),
    papers: (run.papers ?? []).map(normalizePaper),
  };
}

// Papers carry the same optional `ai_summary` / `audio_url` pair as articles,
// written per-paper inside the run doc. Runs written before the pipeline
// generated them have neither, so both default to "" and the card hides the
// control rather than rendering an empty disclosure or a dead player.
function normalizePaper(p) {
  return {
    ...p,
    ai_summary: p.ai_summary ?? "",
    audio_url: publicAudioUrl(p.audio_url),
  };
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
    // A trailing slash still yields one (empty) segment, so check the joined
    // path rather than the segment count — "gs://bucket/" names no object, and
    // the bucket root would be a dead player rather than audio.
    const path = object.map(encodeURIComponent).join("/");
    if (!bucket || !path) return "";
    return `https://storage.googleapis.com/${bucket}/${path}`;
  }
  return "";
}

// Display order is by publish time, newest first — the query orders by
// `processed_at` (see firestoreVideos), which is uniform within a batch and so
// says nothing useful about the order inside one. Copies the input rather than
// sorting it in place.
function byPublishedDesc(docs) {
  return [...docs]
    .sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""))
    .map(normalizeVideo);
}

// published_at drives ordering/day-bucketing; keep the raw ISO string and also
// expose a Date for display. `processed_at` is the ingest-batch stamp: uniform
// across one feed-mind run, which is what the Latest view groups on.
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
