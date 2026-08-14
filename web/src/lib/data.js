// Data-source abstraction (PRD §3.5 / §4.3).
//
// Same three functions back both the Latest and Archive views. The source is
// chosen by VITE_DATA_SOURCE: "firestore" reads Firestore directly from the
// browser (the production Path-A contract); "mock" reads bundled JSON fixtures
// so the UI runs with no cloud project.

import { LENS_CODES } from "./constants.js";

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

// --- helpers ---------------------------------------------------------------

function normalizeRun(run) {
  return { ...run, run_date: toDate(run.run_date) };
}

// Firestore Timestamp | ISO string | Date -> Date
function toDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (typeof value.toDate === "function") return value.toDate(); // Firestore Timestamp
  return new Date(value);
}
