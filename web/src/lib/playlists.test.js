// @vitest-environment node
//
// The queue builders decide what "Listen All" and "Listen Top Summaries"
// actually play. They are pure, so the rules that matter — silent items are
// dropped, the cap counts playable items, open-source contributes nothing —
// are pinned here rather than through a rendered feed.
import { describe, it, expect } from "vitest";
import { tracksFrom, paperTracks, topSummaryTracks, TOP_PER_CATEGORY } from "./playlists.js";

const article = (over = {}) => ({
  article_id: "a1",
  title: "An article",
  feed_category: "academic",
  feed_source: "arXiv Blog",
  audio_url: "https://storage.googleapis.com/b/a.mp3",
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
  it("takes the first three playable items per category, then per lens", () => {
    const articles = [
      ...Array.from({ length: 5 }, (_, i) =>
        article({ title: `ac${i}`, feed_category: "academic" }),
      ),
      ...Array.from({ length: 5 }, (_, i) =>
        article({ title: `in${i}`, feed_category: "industry" }),
      ),
    ];
    const tracks = topSummaryTracks({
      articles,
      latest: { AIML: { papers: [paper({ title: "ml0" }), paper({ title: "ml1" })] } },
    });

    expect(tracks.map((t) => t.title)).toEqual([
      "ac0", "ac1", "ac2",
      "in0", "in1", "in2",
      "ml0", "ml1",
    ]);
    expect(TOP_PER_CATEGORY).toBe(3);
  });

  it("counts playable items, not raw ones, when applying the cap", () => {
    // A category whose newest article has no audio should still contribute
    // three spoken summaries — otherwise the button under-delivers silently.
    const articles = [
      article({ title: "silent", audio_url: "" }),
      article({ title: "a" }),
      article({ title: "b" }),
      article({ title: "c" }),
      article({ title: "d" }),
    ];
    const tracks = topSummaryTracks({ articles });
    expect(tracks.map((t) => t.title)).toEqual(["a", "b", "c"]);
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

  it("returns an empty queue when nothing anywhere has audio", () => {
    expect(topSummaryTracks({ articles: [article({ audio_url: "" })] })).toEqual([]);
    expect(topSummaryTracks()).toEqual([]);
  });
});
