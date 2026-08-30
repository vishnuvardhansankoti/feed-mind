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

/** How many playable items each category contributes to Top Summaries. */
export const TOP_PER_CATEGORY = 3;

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
 * The Top Summaries queue: the first `per` playable items of every news
 * category *from the newest ingest day only*, then of every paper lens from the
 * latest run only.
 *
 * The day anchor is the whole point. `articles` is the entire 7-day window, so
 * filtering by category alone lets a category with fewer than `per` items today
 * reach back into previous days to fill its quota — the queue then reads out
 * archived material under a "today's top summaries" label. Papers never had
 * this problem because `latest` is already one run per lens.
 *
 * The anchor is global rather than per-category, so nothing older than the most
 * recent batch can play. A category with nothing in that batch contributes
 * nothing, rather than falling back to whenever it last published.
 *
 * Note the order of operations — items are filtered for audio *before* being
 * capped, so a category whose newest article has no audio still contributes
 * three spoken summaries rather than two. The alternative (cap, then drop the
 * silent ones) reads "first 3 items" more literally but delivers fewer clips
 * than the button promises.
 *
 * `open-source` contributes nothing: its only entry is the client-pinned
 * GitHub Trending link, which has no pipeline-generated audio at all.
 */
export function topSummaryTracks({
  articles = [],
  latest = {},
  isFollowed = () => true,
  per = TOP_PER_CATEGORY,
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
    tracks.push(...tracksFrom(inCat, c.label).slice(0, per));
  }

  for (const lens of LENSES) {
    const papers = latest?.[lens.code]?.papers ?? [];
    tracks.push(...tracksFrom(papers, lens.label).slice(0, per));
  }

  return tracks;
}
