import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    svelte(),
    // PWA: installable + offline app shell. registerType "autoUpdate" swaps in a
    // new service worker as soon as a fresh build is deployed, so users are never
    // pinned to a stale cached shell (important for a client-rendered SPA).
    VitePWA({
      registerType: "autoUpdate",
      // injectManifest, not generateSW: push notifications need `push` and
      // `notificationclick` handlers, and a generated worker cannot carry them.
      // src/sw.js reproduces the precache + SPA-fallback behaviour by hand.
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.js",
      // Static assets that live in public/ and must be precached alongside the
      // hashed build output (globPatterns handles dist/assets/*).
      includeAssets: ["favicon.svg", "apple-touch-icon.png", "og.png", "robots.txt"],
      manifest: {
        name: "feed-mind",
        short_name: "feed-mind",
        description:
          "A personalized digest of daily tech news and weekly arXiv research, ranked to your interests and summarized by AI.",
        start_url: "/",
        scope: "/",
        display: "standalone",
        theme_color: "#0b0d12",
        background_color: "#0b0d12",
        icons: [
          { src: "/pwa-192.png", sizes: "192x192", type: "image/png" },
          { src: "/pwa-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/pwa-maskable-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      // injectManifest reads this instead of `workbox`; the SPA fallback moved
      // into src/sw.js, which registers the NavigationRoute itself.
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,svg,png,webmanifest}"],
      },
      // Only generate/register the service worker in production builds; a caching
      // SW during `npm run dev` causes stale-asset headaches.
      devOptions: { enabled: false },
    }),
  ],
  build: { outDir: "dist" },
  // Component tests mount real Svelte components, so they need a DOM and the
  // browser export condition (without it Svelte resolves its SSR build and
  // `mount()` renders nothing). Lib tests opt back out with a
  // `@vitest-environment node` docblock — they only touch plain functions.
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.js"],
  },
  resolve: process.env.VITEST ? { conditions: ["browser"] } : undefined,
});
