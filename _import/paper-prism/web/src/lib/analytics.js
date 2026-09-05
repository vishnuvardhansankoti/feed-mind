// Google Analytics 4 (gtag.js) with Consent Mode v2.
//
// Loaded only when VITE_GA_MEASUREMENT_ID is set at build time — so mock/dev
// builds (whose env leaves it empty) never load the script or send a hit.
// Set the real "G-XXXXXXXXXX" id in .env.prod so it ships with `npm run build`.
//
// Consent Mode v2: every storage type defaults to "denied" *before* gtag loads,
// so no analytics cookies / client-id are set until the visitor accepts via the
// banner (ConsentBanner.svelte). While denied, GA4 sends only cookieless pings;
// grantConsent()/denyConsent() flip the signal and persist the choice so we don't
// ask again. The choice lives in localStorage under CONSENT_KEY.
//
// SPA-aware: GA4's automatic page_view fires once on load and would miss this
// app's hash-router navigations (#/papers, #/videos). We disable the auto view
// and emit one manually on each hashchange, mapping the hash to a clean virtual
// path so sections read as /, /papers, /videos in reports.

const ID = import.meta.env.VITE_GA_MEASUREMENT_ID;
const CONSENT_KEY = "fm-analytics-consent"; // "granted" | "denied"

// Whether analytics is configured at all (drives whether the banner appears).
export const analyticsEnabled = !!ID;

export function getConsent() {
  try {
    return localStorage.getItem(CONSENT_KEY); // "granted" | "denied" | null
  } catch {
    return null;
  }
}

function storeConsent(value) {
  try {
    localStorage.setItem(CONSENT_KEY, value);
  } catch {
    /* private mode / storage disabled — consent just isn't remembered */
  }
}

// "#/papers" -> "/papers"; "#/" or "" -> "/".
function virtualPath() {
  const h = location.hash.replace(/^#/, "");
  return h && h !== "/" ? h : "/";
}

let started = false;

export function initAnalytics() {
  if (!ID || typeof window === "undefined" || started) return; // inert / once
  started = true;

  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  window.gtag = gtag;

  // Consent Mode v2 defaults — deny everything until the visitor decides.
  gtag("consent", "default", {
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    analytics_storage: "denied",
    wait_for_update: 500,
  });

  // Returning visitor who already accepted: upgrade before the first hit.
  if (getConsent() === "granted") {
    gtag("consent", "update", { analytics_storage: "granted" });
  }

  const s = document.createElement("script");
  s.async = true;
  s.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(ID)}`;
  document.head.appendChild(s);

  gtag("js", new Date());
  gtag("config", ID, { send_page_view: false });

  const sendView = () => {
    const path = virtualPath();
    gtag("event", "page_view", {
      page_path: path,
      page_location: location.origin + path,
      page_title: document.title,
    });
  };

  sendView(); // initial view
  window.addEventListener("hashchange", sendView);
}

export function grantConsent() {
  storeConsent("granted");
  window.gtag?.("consent", "update", { analytics_storage: "granted" });
}

export function denyConsent() {
  storeConsent("denied");
  window.gtag?.("consent", "update", { analytics_storage: "denied" });
}
