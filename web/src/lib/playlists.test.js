// @vitest-environment node
//
// The queue builders decide what "Listen All" and "Listen Top Summaries"
// actually play. They are pure, so the rules that matter — silent items are
// dropped, the cap counts playable items, open-source contributes nothing —
// are pinned here rather than through a rendered feed.
import { describe, it, expect } from "vitest";
import {
  tracksFrom,
  paperTracks,
  topSummaryTracks,
  TOP_PER_SOURCE,
  TOP_PER_FLAT_CATEGORY,
  FLAT_CATEGORIES,
} from "./playlists.js";

const TODAY = new Date("2026-08-25T09:00:00Z");
const YESTERDAY = new Date("2026-08-24T09:00:00Z");

const article = (over = {}) => ({
  article_id: "a1",
  title: "An article",
  feed_category: "academic",
  feed_source: "arXiv Blog",
  audio_url: "https://storage.googleapis.com/b/a.mp3",
  processed_date: TODAY,
  ...over,
});

const paper = (over = {}) => ({
  arxiv_id: "2401.00001",
  title: "A paper",
  audio_url: "https://storage.googleapis.com/b/p.mp3",
  ...over,
});

describe("tracksFrom", () => {
  it("drops items with no audio and keeps display order", () => {
    const tracks = tracksFrom(
      [
        article({ title: "first", audio_url: "" }),
        article({ title: "second", audio_url: "u2" }),
        article({ title: "third", audio_url: "u3" }),
      ],
      "Academic",
    );
    expect(tracks.map((t) => t.title)).toEqual(["second", "third"]);
    expect(tracks[0]).toEqual({ url: "u2", title: "second", context: "Academic" });
  });

  it("tolerates missing input and null entries", () => {
    expect(tracksFrom(undefined)).toEqual([]);
    expect(tracksFrom([null, article({ audio_url: "" })])).toEqual([]);
  });
});

describe("paperTracks", () => {
  it("walks the lenses of a latest map in order", () => {
    const tracks = paperTracks({
      AIML: { papers: [paper({ title: "ml" })] },
      NLP: { papers: [paper({ title: "nlp" })] },
      CV: { papers: [paper({ title: "cv" })] },
    });
    expect(tracks.map((t) => t.title)).toEqual(["ml", "nlp", "cv"]);
    expect(tracks[1].context).toBe("NLP");
  });

  it("flattens every run of an archive map when many is set", () => {
    const tracks = paperTracks(
      {
        AIML: [
          { papers: [paper({ title: "wk2" })] },
          { papers: [paper({ title: "wk1" })] },
        ],
      },
      { many: true },
    );
    expect(tracks.map((t) => t.title)).toEqual(["wk2", "wk1"]);
  });

  it("survives lenses with no run at all", () => {
    expect(paperTracks({})).toEqual([]);
    expect(paperTracks({ AIML: null })).toEqual([]);
  });
});

describe("topSummaryTracks", () => {
  it("takes the newest one per source, so one busy feed cannot fill it", () => {
    const articles = [
      ...Array.from({ length: 4 }, (_, i) =>
        article({ title: `hf${i}`, feed_category: "academic", feed_source: "HF" }),
      ),
      ...Array.from({ length: 4 }, (_, i) =>
        article({ title: `gr${i}`, feed_category: "academic", feed_source: "Google Research" }),
      ),
      ...Array.from({ length: 4 }, (_, i) =>
        article({ title: `oa${i}`, feed_category: "industry", feed_source: "OpenAI" }),
      ),
    ];

    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual([
      "hf0", "gr0", "oa0",
    ]);
    expect(TOP_PER_SOURCE).toBe(1);
  });

  it("keeps feed order rather than regrouping by source", () => {
    const articles = [
      article({ title: "b1", feed_source: "B" }),
      article({ title: "a1", feed_source: "A" }),
      article({ title: "b2", feed_source: "B" }),
      article({ title: "c1", feed_source: "C" }),
    ];
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual([
      "b1", "a1", "c1",
    ]);
  });

  it("gives top_stories a flat count, since it is a single feed", () => {
    // Grouping by source there would be a cap of one; it has no sub-sources yet.
    const articles = Array.from({ length: 5 }, (_, i) =>
      article({ title: `ts${i}`, feed_category: "top_stories", feed_source: "TOI Top Stories" }),
    );
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual([
      "ts0", "ts1", "ts2",
    ]);
    expect(TOP_PER_FLAT_CATEGORY).toBe(3);
    expect(FLAT_CATEGORIES).toEqual(["top_stories"]);
  });

  it("excludes papers entirely — they have their own Listen All", () => {
    // The digest is weekly, so the same papers would ride along in every daily
    // listen. paperTracks still serves the Papers tab.
    const tracks = topSummaryTracks({
      articles: [article({ title: "news-1" })],
      latest: { AIML: { papers: [paper({ title: "should-not-play" })] } },
    });
    expect(tracks.map((t) => t.title)).toEqual(["news-1"]);
  });

  it("counts playable items, not raw ones, when applying the cap", () => {
    // A source whose newest article has no audio should still contribute its
    // full quota — otherwise the button under-delivers silently.
    const articles = [
      article({ title: "silent", audio_url: "" }),
      article({ title: "a" }),
      article({ title: "b" }),
    ];
    const tracks = topSummaryTracks({ articles });
    expect(tracks.map((t) => t.title)).toEqual(["a"]);
  });

  it("contributes nothing for open-source, which has no generated audio", () => {
    const tracks = topSummaryTracks({
      articles: [
        article({ title: "gh", feed_category: "open-source", audio_url: "" }),
        article({ title: "ac" }),
      ],
    });
    expect(tracks.map((t) => t.title)).toEqual(["ac"]);
  });

  it("honours the follow filter", () => {
    const articles = [
      article({ title: "kept", feed_source: "Keep" }),
      article({ title: "hidden", feed_source: "Drop" }),
    ];
    const tracks = topSummaryTracks({
      articles,
      isFollowed: (_kind, name) => name !== "Drop",
    });
    expect(tracks.map((t) => t.title)).toEqual(["kept"]);
  });

  it("plays only the newest ingest day, never reaching into the archive", () => {
    // The regression: `articles` is the whole 7-day window, so a category with
    // fewer than 3 items today used to top up from previous days and read out
    // archived material under a "top summaries" label.
    const articles = [
      article({ title: "today-1" }),
      article({ title: "yesterday-1", processed_date: YESTERDAY }),
      article({ title: "yesterday-2", processed_date: YESTERDAY }),
      article({ title: "yesterday-3", processed_date: YESTERDAY }),
    ];
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual(["today-1"]);
  });

  it("anchors globally, so a category silent today contributes nothing", () => {
    const articles = [
      article({ title: "ac-today", feed_category: "academic" }),
      article({ title: "in-old", feed_category: "industry", processed_date: YESTERDAY }),
    ];
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual(["ac-today"]);
  });

  it("picks the anchor day from followed sources only", () => {
    // An unfollowed source publishing today must not pin the anchor to a day
    // the user cannot see anything from.
    const articles = [
      article({ title: "hidden-today", feed_source: "Drop" }),
      article({ title: "shown-yesterday", feed_source: "Keep", processed_date: YESTERDAY }),
    ];
    const tracks = topSummaryTracks({
      articles,
      isFollowed: (_kind, name) => name !== "Drop",
    });
    expect(tracks.map((t) => t.title)).toEqual(["shown-yesterday"]);
  });

  it("is not anchored to today by the pinned open-source link", () => {
    // withPinnedLinks stamps GitHub Trending with a fresh "now" on every load,
    // so it is always the newest article and always has no audio. Anchoring on
    // it emptied the news half of the queue completely.
    const articles = [
      article({
        title: "GitHub Trending",
        feed_category: "open-source",
        audio_url: "",
        processed_date: new Date("2026-08-29T12:00:00Z"),
      }),
      // Distinct sources, so the per-source cap does not confound the anchor.
      article({ title: "real-1", feed_source: "A" }),
      article({ title: "real-2", feed_source: "B" }),
    ];
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual([
      "real-1",
      "real-2",
    ]);
  });

  it("falls back to the last day that has audio when today has none", () => {
    const articles = [
      article({ title: "today-silent", audio_url: "" }),
      article({ title: "yesterday-audible", processed_date: YESTERDAY }),
    ];
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual([
      "yesterday-audible",
    ]);
  });

  it("falls back to the whole list when no date is parseable", () => {
    // With no usable dates there is no "latest" to anchor to; an empty queue
    // would be worse than an unanchored one.
    const articles = [
      // Distinct sources, so the per-source cap does not confound the fallback.
      article({ title: "a", processed_date: null, feed_source: "A" }),
      article({ title: "b", processed_date: new Date("nonsense"), feed_source: "B" }),
    ];
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual(["a", "b"]);
  });

  it("drops undateable items when a real anchor day exists", () => {
    const articles = [
      article({ title: "today" }),
      article({ title: "undateable", processed_date: null }),
    ];
    expect(topSummaryTracks({ articles }).map((t) => t.title)).toEqual(["today"]);
  });

  it("is empty when there is no news, even with papers available", () => {
    const tracks = topSummaryTracks({
      articles: [],
      latest: { NLP: { papers: [paper({ title: "p1" }), paper({ title: "p2" })] } },
    });
    expect(tracks).toEqual([]);
  });

  it("returns an empty queue when nothing anywhere has audio", () => {
    expect(topSummaryTracks({ articles: [article({ audio_url: "" })] })).toEqual([]);
    expect(topSummaryTracks()).toEqual([]);
  });
});
