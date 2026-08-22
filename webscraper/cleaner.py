"""Pruning the page chrome: ads, nav, sidebars, share bars, comments.

Everything here is heuristic, so the rules are kept as data (three regexes and
a tag set) to make them easy to tune without touching the traversal.
"""

from __future__ import annotations

import re

from .dom import link_density, prose_length

# Tags whose content is never part of the article.
DROP_TAGS = {
    "script", "style", "noscript", "template", "svg", "canvas", "iframe",
    "object", "embed", "form", "input", "button", "select", "textarea",
    "nav", "header", "footer", "aside", "menu", "dialog", "figcaption",
}

# class/id substrings that are always junk, however much text they hold.
HARD_NOISE_RE = re.compile(
    r"(^|[-_ ])(ad|ads|adbox|adslot|advert|advertisement|banner|sponsor|"
    r"sponsored|promo|popup|modal|overlay|cookie|consent|gdpr|paywall|"
    r"subscribe|signup|newsletter|social|share|sharing|disqus)([-_ ]|$)",
    re.I,
)

# class/id substrings that usually mark chrome, but can be wrong (see below).
NOISE_RE = re.compile(
    r"(^|[-_ ])(ad|ads|adbox|advert|advertisement|banner|sponsor|promo|"
    r"popup|modal|overlay|cookie|consent|gdpr|paywall|subscribe|signup|"
    r"newsletter|social|share|sharing|follow|related|recommend|trending|"
    r"popular|sidebar|widget|breadcrumb|pagination|pager|nav|navbar|menu|"
    r"masthead|header|footer|comment|comments|disqus|utility|toolbar|"
    r"skip-link|hidden|meta|byline|tags|taxonomy)([-_ ]|$)",
    re.I,
)

# ...unless the same signature also looks like the article itself.
KEEP_RE = re.compile(
    r"(^|[-_ ])(article|articlebody|post|postbody|post-content|entry|"
    r"entry-content|content|main|story|storybody|body-copy|blog|text|"
    r"markdown|prose|readme)([-_ ]|$)",
    re.I,
)

NOISE_ROLES = {
    "navigation", "banner", "complementary", "contentinfo", "search", "dialog",
}

SIGNATURE_ATTRS = ("class", "id", "role", "data-testid", "aria-label")

# A soft-noise wrapper holding at least this much low-link prose is kept.
PROSE_RESCUE_CHARS = 400
PROSE_RESCUE_LINK_DENSITY = 0.5


def signature(node):
    """The attribute text used to judge whether a node is chrome."""
    return " ".join(node.attrs.get(key, "") for key in SIGNATURE_ATTRS)


def is_hidden(node):
    if node.attrs.get("aria-hidden", "").lower() == "true":
        return True
    style = node.attrs.get("style", "").replace(" ", "").lower()
    return "display:none" in style


def looks_like_noise(node):
    """True when the node is page chrome rather than article content."""
    marks = signature(node)
    if not marks.strip():
        return False

    if HARD_NOISE_RE.search(marks):
        return True
    if KEEP_RE.search(marks):
        return False

    soft_noise = (
        node.attrs.get("role", "").lower() in NOISE_ROLES
        or bool(NOISE_RE.search(marks))
    )
    if not soft_noise:
        return False

    # A "widget"/"meta"/"tags" wrapper that is full of prose is really the
    # article in disguise (Blogger, WordPress themes) - keep it.
    rescued = (
        prose_length(node) > PROSE_RESCUE_CHARS
        and link_density(node) < PROSE_RESCUE_LINK_DENSITY
    )
    return not rescued


def clean(root):
    """Drop noisy subtrees, in place. Returns the same root for chaining."""
    def prune(node):
        kept = []
        for child in node.children:
            if child.is_text:
                kept.append(child)
                continue
            if child.tag in DROP_TAGS or is_hidden(child) or looks_like_noise(child):
                continue
            prune(child)
            kept.append(child)
        node.children = kept

    prune(root)
    return root
