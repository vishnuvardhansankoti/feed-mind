"""The extraction pipeline: parse -> clean -> pick -> render."""

from __future__ import annotations

import re

from .cleaner import clean
from .dom import parse
from .renderer import render, wrap_blocks
from .scorer import pick_content

TITLE_MATCH_CHARS = 40  # how much of the title must match the h1 to dedupe it


class Article:
    """The result of extracting one page."""

    __slots__ = ("title", "blocks")

    def __init__(self, title, blocks):
        self.title = title
        self.blocks = blocks

    def __bool__(self):
        return bool(self.blocks)

    def text(self, width=100):
        """Render as one plain-text string, wrapped to `width` columns."""
        blocks = list(self.blocks)
        heading = blocks[0].lstrip("# ").strip().lower() if blocks else ""
        if self.title and not heading.startswith(self.title.lower()[:TITLE_MATCH_CHARS]):
            rule = "=" * min(len(self.title), width if width else 80)
            blocks[:0] = [self.title, rule]
        return "\n\n".join(wrap_blocks(blocks, width)).strip()


def extract_article(html):
    """HTML string -> Article."""
    root, raw_title = parse(html)
    clean(root)
    blocks = render(pick_content(root))
    return Article(re.sub(r"\s+", " ", raw_title).strip(), blocks)


def extract(html, width=100):
    """HTML string -> readable text string."""
    return extract_article(html).text(width=width)
