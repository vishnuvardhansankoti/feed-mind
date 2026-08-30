// Queue builders for "Listen All" and "Listen Top Summaries".
//
// Kept out of the components so the slicing rules are testable without
// rendering anything, and so the two buttons cannot drift apart in what they
// consider playable.
//
// "Top" currently means *first in display order* — there is no ranking yet, by
// design. When real ranking arrives it reorders the input to these functions;
// nothing here changes.

import { NEWS_CATEGORIES, LENSES } from "./constants.js";

/**
 * Top News quotas.
 *
 * Most categories draw per *source*, so one prolific feed cannot crowd the
 * others out of the queue — "Academic" is four different blogs, and the newest
 * from each beats three from whichever posted most recently. At one per source
 * the queue is a headline sweep: broad coverage, bounded by how many feeds
 * published that day rather than by how much any one of them wrote.
 *
 * `top_stories` is the exception: it is a single feed today, so grouping by
 * source there would just be a cap of one story. It draws a flat count from the
 * category instead. When it grows real sub-sources, moving it out of
 * FLAT_CATEGORIES is the whole change.
 */
export const TOP_PER_SOURCE = 1;
export const TOP_PER_FLAT_CATEGORY = 3;
export const FLAT_CATEGORIES = ["top_stories"];

/**
 * Turn feed items (articles or papers) into playable tracks, dropping anything
 * with no audio.
 *
 * `context` labels the group on the mini-player ("Academic", "NLP") so a
 * listener who has scrolled away still knows which category is speaking.
 */
export function tracksFrom(items, context = "") {
  return (items ?? [])
    .filter((i) => i && i.audio_url)
    .map((i) => ({ url: i.audio_url, title: i.title ?? "", context }));
}

/**
 * Every playable paper in a lens-keyed map of runs.
 *
 * Handles both shapes App holds: `latest` is { CODE: run } and `archive` is
 * { CODE: [run, …] }, so callers pass whichever they are showing.
 */
export function paperTracks(byLens, { many = false } = {}) {
  return LENSES.flatMap((lens) => {
    const entry = byLens?.[lens.code];
    const runs = many ? (entry ?? []) : entry ? [entry] : [];
    return runs.flatMap((run) => tracksFrom(run?.papers, lens.label));
  });
}

/** The calendar day an article was ingested, matching NewsFeed's grouping. */
function dayKey(article) {
  const d = article?.processed_date;
  return d instanceof Date && !isNaN(d) ? d.toDateString() : null;
}

/** The most recent ingest day among `items`, or null if none is parseable. */
function newestDay(items) {
  let best = null;
  for (const a of items) {
    const d = a?.processed_date;
    if (d instanceof Date && !isNaN(d) && (!best || d > best)) best = d;
  }
  return best ? best.toDateString() : null;
}

/**
 * Up to `perSource` playable items from each distinct feed_source, in feed
 * order.
 *
 * Feed order is preserved rather than regrouped source-by-source: the set of
 * tracks is identical either way, and keeping the newest-first sequence matches
 * how the same articles are laid out on screen.
 */
function perSourceTracks(items, context, perSource) {
  const taken = new Map();
  const out = [];
  for (const a of items) {
    if (!a.audio_url) continue;
    const key = a.feed_source ?? "";
    const n = taken.get(key) ?? 0;
    if (n >= perSource) continue;
    taken.set(key, n + 1);
    out.push(...tracksFrom([a], context));
  }
  return out;
}

/**
 * The Top News queue, drawn from the newest ingest day only.
 *
 * Two quotas, by category shape:
 *   - most categories -> TOP_PER_SOURCE per distinct feed_source, so one busy
 *     blog cannot fill "Academic" on its own; the category's length is then set
 *     by how many of its feeds published, not by how much any one wrote
 *   - FLAT_CATEGORIES (top_stories) -> TOP_PER_FLAT_CATEGORY from the category,
 *     since it is one feed and per-source grouping would be a cap of one
 *
 * News only — papers are deliberately excluded. The digest is weekly, so the
 * same nine papers would ride along in every daily listen; the Papers tab has
 * its own Listen All (see paperTracks) for when they are what you want.
 *
 * The day anchor is the whole point. `articles` is the entire 7-day window, so
 * filtering by category alone lets a category short of its quota today reach
 * back into previous days to fill it — the queue then reads out archived
 * material under a "top news" label.
 *
 * The anchor is global rather than per-category, so nothing older than the most
 * recent batch can play. A category with nothing in that batch contributes
 * nothing, rather than falling back to whenever it last published.
 *
 * Items are filtered for audio *before* being capped, so a source whose newest
 * article has no audio still contributes its full quota of spoken summaries
 * rather than silently short-changing it.
 *
 * `open-source` contributes nothing: its only entry is the client-pinned
 * GitHub Trending link, which has no pipeline-generated audio at all.
 */
export function topSummaryTracks({
  articles = [],
  isFollowed = () => true,
  perSource = TOP_PER_SOURCE,
  perFlatCategory = TOP_PER_FLAT_CATEGORY,
} = {}) {
  const tracks = [];

  // Follows are applied before the anchor is chosen: a day the user has
  // unfollowed into emptiness should not become the batch everyone is pinned to.
  const followed = articles.filter((a) => a && isFollowed("news", a.feed_source));

  // Anchor on the newest day that has something to *play*, not merely the
  // newest day present. `withPinnedLinks` stamps the pinned GitHub Trending
  // link with a fresh "now" every load, so the newest day is always today and
  // often contains nothing but that link — which has no audio. Anchoring on it
  // would empty the queue of news entirely on any day feed-mind did not run.
  const day = newestDay(followed.filter((a) => a.audio_url));

  for (const c of NEWS_CATEGORIES) {
    const inCat = followed.filter(
      // No parseable date anywhere means there is no notion of "latest" to
      // anchor to; fall back to the whole list rather than an empty queue.
      (a) => a.feed_category === c.code && (day === null || dayKey(a) === day),
    );

    if (FLAT_CATEGORIES.includes(c.code)) {
      tracks.push(...tracksFrom(inCat, c.label).slice(0, perFlatCategory));
    } else {
      tracks.push(...perSourceTracks(inCat, c.label, perSource));
    }
  }

  return tracks;
}
