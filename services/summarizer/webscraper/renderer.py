"""Turning the chosen subtree into plain text blocks, and wrapping them."""

from __future__ import annotations

import re
import textwrap

from .dom import BLOCK_TAGS, HEADING_TAGS

# Whole lines that are leftover chrome rather than content.
BOILERPLATE_LINE_RE = re.compile(
    r"^(advertisement|sponsored|share this|read more|related articles?|"
    r"sign up|subscribe|newsletter|follow us|cookie policy|accept all|"
    r"loading\.*)$",
    re.I,
)

MIN_BLOCK_CHARS = 2
DEDUPE_MAX_CHARS = 120  # only short repeats are treated as nav noise
BULLET = "- "


def _prefix_for(tag, list_depth):
    if tag in HEADING_TAGS:
        return "#" * int(tag[1]) + " "
    if tag == "li":
        return "  " * max(list_depth - 1, 0) + BULLET
    if tag == "blockquote":
        return "> "
    return ""


def to_blocks(node):
    """Flatten a subtree into a list of text blocks."""
    blocks, buffer = [], []

    def flush():
        if buffer:
            line = re.sub(r"\s+", " ", " ".join(buffer)).strip()
            if line:
                blocks.append(line)
            buffer.clear()

    def walk(current, list_depth=0):
        if current.is_text:
            buffer.append(current.text)
            return
        if current.tag == "br":
            flush()
            return

        is_block = current.tag in BLOCK_TAGS
        if is_block:
            flush()

        prefix = _prefix_for(current.tag, list_depth)
        if prefix:
            buffer.append(prefix)

        depth = list_depth + 1 if current.tag in {"ul", "ol"} else list_depth
        for child in current.children:
            walk(child, depth)

        if is_block:
            flush()

    walk(node)
    flush()
    return blocks


def tidy(blocks):
    """Drop boilerplate lines and repeated labels, then group bullet runs."""
    kept, seen = [], set()
    for block in blocks:
        stripped = block.lstrip("#>- ").strip()
        if len(stripped) < MIN_BLOCK_CHARS or BOILERPLATE_LINE_RE.match(stripped):
            continue
        key = stripped.lower()
        if key in seen and len(stripped) < DEDUPE_MAX_CHARS:
            continue
        seen.add(key)
        kept.append(block)

    grouped = []
    for block in kept:
        if block.lstrip().startswith(BULLET) and grouped and grouped[-1].lstrip().startswith(BULLET):
            grouped[-1] += "\n" + block
        else:
            grouped.append(block)
    return grouped


def wrap_blocks(blocks, width):
    """Hard-wrap each block to `width` columns; width 0 disables wrapping."""
    if not width or width <= 0:
        return list(blocks)

    wrapped = []
    for block in blocks:
        lines = []
        for line in block.split("\n"):
            indent = ""
            if line.lstrip().startswith(BULLET):
                indent = " " * (len(line) - len(line.lstrip()) + len(BULLET))
            lines.append(
                "\n".join(textwrap.wrap(line, width=width, subsequent_indent=indent))
                or line
            )
        wrapped.append("\n".join(lines))
    return wrapped


def render(node):
    """Subtree -> tidy list of text blocks."""
    return tidy(to_blocks(node))
