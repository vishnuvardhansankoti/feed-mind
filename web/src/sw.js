/// <reference lib="webworker" />
//
// The app's service worker.
//
// vite-plugin-pwa used to generate this file wholesale (`generateSW`). Push
// notifications need `push` and `notificationclick` handlers, which a generated
// worker has no way to carry, so the plugin switched to `injectManifest` and
// this file became ours. Everything above the push section is the behaviour the
// generated worker had — precache the build output, serve the SPA shell for any
// uncached navigation — reproduced by hand.
//
// `self.__WB_MANIFEST` is replaced at build time with the precache manifest.

import { precacheAndRoute, createHandlerBoundToURL } from "workbox-precaching";
import { NavigationRoute, registerRoute } from "workbox-routing";
import { clientsClaim } from "workbox-core";

// registerType "autoUpdate" in the plugin config expects the worker to take
// over immediately rather than waiting for every tab to close — a
// client-rendered SPA pinned to a stale shell is the failure this avoids.
self.skipWaiting();
clientsClaim();

precacheAndRoute(self.__WB_MANIFEST);

// SPA fallback: any navigation we have not cached resolves to the app shell,
// so deep links like /#/papers work offline and on a cold start.
registerRoute(new NavigationRoute(createHandlerBoundToURL("index.html")));

// ---------------------------------------------------------------------------
// Push
// ---------------------------------------------------------------------------

const FALLBACK = {
  title: "feed-mind",
  body: "New content is ready.",
  url: "/",
};

/**
 * Read the push payload defensively.
 *
 * A push can arrive with no data at all (some services strip it, and a
 * mis-sent push may carry none), and the spec allows any bytes. Anything
 * unparseable falls back to a generic notification rather than throwing —
 * throwing inside a push handler drops the notification entirely, and on some
 * platforms shows a browser-generated "site updated in the background" one
 * instead, which is worse than a vague message of our own.
 */
function payloadOf(event) {
  try {
    const data = event.data?.json();
    if (!data || typeof data !== "object") return FALLBACK;
    return {
      title: typeof data.title === "string" && data.title ? data.title : FALLBACK.title,
      body: typeof data.body === "string" && data.body ? data.body : FALLBACK.body,
      url: typeof data.url === "string" && data.url.startsWith("/") ? data.url : FALLBACK.url,
      tag: typeof data.tag === "string" ? data.tag : undefined,
    };
  } catch {
    return FALLBACK;
  }
}

self.addEventListener("push", (event) => {
  const p = payloadOf(event);
  event.waitUntil(
    self.registration.showNotification(p.title, {
      body: p.body,
      icon: "/pwa-192.png",
      badge: "/pwa-192.png",
      // A tag collapses repeats: a second push for the same run replaces the
      // first rather than stacking two notifications for one batch.
      tag: p.tag,
      data: { url: p.url },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = event.notification.data?.url || "/";

  // Focus an open tab rather than opening a second one — the app is a single
  // page, so a duplicate tab is never what the user wanted.
  event.waitUntil(
    (async () => {
      const clients = await self.clients.matchAll({
        type: "window",
        includeUncontrolled: true,
      });
      for (const client of clients) {
        if ("focus" in client) {
          await client.focus();
          if ("navigate" in client) await client.navigate(target).catch(() => {});
          return;
        }
      }
      await self.clients.openWindow(target);
    })(),
  );
});
