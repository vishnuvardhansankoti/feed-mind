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

/**
 * The Top Summaries queue: the first `per` playable items of every news
 * category, then of every paper lens.
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

  for (const c of NEWS_CATEGORIES) {
    const inCat = articles.filter(
      (a) => a?.feed_category === c.code && isFollowed("news", a?.feed_source),
    );
    tracks.push(...tracksFrom(inCat, c.label).slice(0, per));
  }

  for (const lens of LENSES) {
    const papers = latest?.[lens.code]?.papers ?? [];
    tracks.push(...tracksFrom(papers, lens.label).slice(0, per));
  }

  return tracks;
}
