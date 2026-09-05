// Web Push subscription management.
//
// Mirrors the two-backend split in data.js / auth.js / prefs.js on the same
// VITE_DATA_SOURCE: `npm run dev` forces mock with empty Firebase keys *and*
// disables the service worker, so without a mock path the entire notification
// UI would be unreachable and untestable outside production.
//
// The subscription itself is stored on `users/{uid}` (see prefs.js) — the only
// document the browser may write, already gated by the allowlist in
// firestore.rules. That is why notifications are signed-in only: there is no
// other place a browser is permitted to put one, and a publicly writable
// collection would be an open spam target with no rule able to tell a real
// subscription from junk.

import { savePushSubscription, clearPushSubscription } from "./prefs.js";

const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY ?? "";
const isMock = (import.meta.env.VITE_DATA_SOURCE ?? "mock") === "mock";

/**
 * Why the browser cannot take a subscription, or "" when it can.
 *
 * Distinguishing these matters: "your browser cannot do this" and "you have
 * blocked notifications" need different things from the user, and a single
 * disabled toggle telling them neither is a dead end.
 */
export function pushUnavailableReason() {
  if (isMock) return ""; // the mock backend simulates everything below
  if (typeof window === "undefined") return "unsupported";
  if (!("serviceWorker" in navigator)) return "unsupported";
  if (!("PushManager" in window)) return "unsupported";
  if (!("Notification" in window)) return "unsupported";
  // iOS delivers push only to a PWA added to the home screen. Safari exposes
  // PushManager either way, so the install state is the only tell.
  if (isIosSafari() && !isStandalone()) return "ios-needs-install";
  if (Notification.permission === "denied") return "denied";
  if (!VAPID_PUBLIC_KEY) return "unconfigured";
  return "";
}

function isStandalone() {
  return (
    window.matchMedia?.("(display-mode: standalone)").matches === true ||
    window.navigator.standalone === true
  );
}

function isIosSafari() {
  const ua = navigator.userAgent || "";
  // iPadOS 13+ reports as Macintosh; the touch-point check separates it.
  const iOS = /iPad|iPhone|iPod/.test(ua) ||
    (ua.includes("Macintosh") && navigator.maxTouchPoints > 1);
  return iOS && !/CriOS|FxiOS/.test(ua);
}

/** VAPID keys travel as base64url; PushManager wants raw bytes. */
function urlBase64ToUint8Array(base64) {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** The stored shape — plain JSON, because Firestore cannot hold a PushSubscription. */
function serialize(subscription) {
  const json = subscription.toJSON();
  return {
    endpoint: String(json.endpoint ?? ""),
    p256dh: String(json.keys?.p256dh ?? ""),
    auth: String(json.keys?.auth ?? ""),
    updated_at: new Date().toISOString(),
  };
}

/** Whether this device currently holds a subscription. */
export async function isSubscribed(uid) {
  if (isMock) return mockIsSubscribed(uid);
  if (pushUnavailableReason()) return false;
  const reg = await navigator.serviceWorker.ready;
  return (await reg.pushManager.getSubscription()) !== null;
}

/**
 * Ask for permission and subscribe. **Must be called from a user gesture** —
 * every browser rejects a permission prompt that is not, and Safari does so
 * silently.
 *
 * Returns "" on success, or a reason string.
 */
export async function enablePush(uid) {
  if (!uid) return "signed-out";
  if (isMock) return mockEnable(uid);

  const blocked = pushUnavailableReason();
  if (blocked) return blocked;

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return permission === "denied" ? "denied" : "dismissed";

  const reg = await navigator.serviceWorker.ready;
  const existing = await reg.pushManager.getSubscription();
  const subscription =
    existing ??
    (await reg.pushManager.subscribe({
      // Required to be true by every browser that implements push: a silent
      // push is not permitted, so each one must show a notification.
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
    }));

  await savePushSubscription(uid, serialize(subscription));
  return "";
}

/** Unsubscribe this device and forget it server-side. */
export async function disablePush(uid) {
  if (isMock) return mockDisable(uid);
  if (!("serviceWorker" in navigator)) return;

  const reg = await navigator.serviceWorker.ready;
  const subscription = await reg.pushManager.getSubscription();
  if (!subscription) return;

  const { endpoint } = serialize(subscription);
  // Drop the server's copy first: a subscription the browser has forgotten but
  // the sender still holds produces pushes nobody can receive, and the sender
  // only learns it is dead from a 410 much later.
  if (uid) await clearPushSubscription(uid, endpoint);
  await subscription.unsubscribe().catch(() => {});
}

// -- mock backend -----------------------------------------------------------
// `npm run dev` has no service worker at all, so real subscription is
// impossible there. localStorage stands in, which keeps the settings UI and its
// tests exercisable without a deployed build.

const mockKey = (uid) => `fm-push-${uid ?? "anon"}`;

function mockIsSubscribed(uid) {
  try {
    return localStorage.getItem(mockKey(uid)) !== null;
  } catch {
    return false;
  }
}

async function mockEnable(uid) {
  try {
    localStorage.setItem(mockKey(uid), JSON.stringify({ endpoint: `mock:${uid}` }));
  } catch {
    return "unsupported";
  }
  return "";
}

async function mockDisable(uid) {
  try {
    localStorage.removeItem(mockKey(uid));
  } catch {
    /* nothing to undo */
  }
}
