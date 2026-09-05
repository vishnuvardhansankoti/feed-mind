// Which videos count as "the latest batch".
//
// Lives outside the component so the rule can be unit-tested directly — it is
// the thing that decides how many videos the Videos tab shows, and it used to
// get this wrong in a way that was invisible except over hours.

import { VIDEO_BATCH_TOLERANCE_HOURS } from "./constants.js";

const isDate = (d) => d instanceof Date && !isNaN(d);

/**
 * The most recent feed-mind ingest batch, anchored to the newest `processed_at`
 * present in `videos` — NOT to the current time.
 *
 * That distinction is the whole point: a clock-relative window ("published in
 * the last 24h") re-evaluates on every render, so videos age out one by one and
 * the tab quietly shrinks as the day passes. Anchoring to the data means the
 * result only changes when feed-mind actually writes a newer batch.
 *
 * feed-mind stamps each doc in a run with its own `now`, so a batch spans a few
 * seconds to a few minutes; VIDEO_BATCH_TOLERANCE_HOURS is the slack that holds
 * one run together while still separating consecutive runs.
 *
 * Videos with no usable `processed_date` cannot be placed in a batch and are
 * omitted (they remain reachable in Archive).
 *
 * @param {Array<{processed_date?: Date}>} videos
 * @returns {Array} the input order, filtered to the newest batch
 */
export function latestBatch(videos = []) {
  const stamped = videos.filter((v) => isDate(v.processed_date));
  if (!stamped.length) return [];
  const newest = Math.max(...stamped.map((v) => v.processed_date.getTime()));
  const cutoff = newest - VIDEO_BATCH_TOLERANCE_HOURS * 3_600_000;
  return stamped.filter((v) => v.processed_date.getTime() >= cutoff);
}
