"""Picking the node that holds the article.

A readability-style heuristic: paragraphs earn points for length and comma
count, those points bubble up to ancestors with halving weight, and the
totals are discounted by link density so navigation columns lose.
"""

from __future__ import annotations

from .dom import link_density

# Tags that can hold the article.
CANDIDATE_TAGS = {"div", "article", "section", "main", "td", "blockquote", "body"}

# Tags whose text counts as prose when scoring.
SCORED_TAGS = {"p", "pre", "blockquote", "li", "h1", "h2", "h3", "h4", "h5", "h6"}

MIN_SCORED_CHARS = 25        # ignore paragraphs shorter than this
MAX_LENGTH_POINTS = 3.0      # cap the reward for one very long paragraph
HEADING_WEIGHT = 0.5         # headings anchor a block but aren't the block
MAX_ANCESTOR_DEPTH = 4       # how far points bubble up
PARENT_PREFERENCE = 0.85     # climb to a parent scoring at least this ratio


def score_paragraph(text, tag):
    """Points a single block of text contributes to its ancestors."""
    score = 1 + text.count(",") + min(len(text) / 100.0, MAX_LENGTH_POINTS)
    return score * HEADING_WEIGHT if tag.startswith("h") else score


def collect_scores(root):
    """Map of id(node) -> [points, node] for every candidate container."""
    scores = {}
    for node in root.iter():
        if node.tag not in SCORED_TAGS:
            continue
        text = node.inner_text().strip()
        if len(text) < MIN_SCORED_CHARS:
            continue

        points = score_paragraph(text, node.tag)
        ancestor, weight, depth = node.parent, 1.0, 0
        while ancestor is not None and depth < MAX_ANCESTOR_DEPTH:
            if ancestor.tag in CANDIDATE_TAGS:
                entry = scores.setdefault(id(ancestor), [0.0, ancestor])
                entry[0] += points * weight
                weight /= 2.0
                depth += 1
            ancestor = ancestor.parent
    return scores


def pick_content(root):
    """Return the node most likely to hold the article body."""
    scores = collect_scores(root)
    if not scores:
        return root

    ranked = sorted(
        ((points * (1.0 - link_density(node)), node) for points, node in scores.values()),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best = ranked[0]
    lookup = {id(node): points for points, node in ranked}

    # Prefer a parent that scores nearly as well - it usually wraps the whole
    # article instead of a single column of it.
    parent = best.parent
    while parent is not None and id(parent) in lookup:
        if lookup[id(parent)] >= best_score * PARENT_PREFERENCE:
            best, best_score = parent, lookup[id(parent)]
        parent = parent.parent

    return best
