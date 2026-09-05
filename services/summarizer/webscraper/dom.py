"""A tiny forgiving DOM: the tree, the parser that builds it, and the two
metrics (link density, prose length) that the rest of the pipeline scores with.
"""

from __future__ import annotations

from html.parser import HTMLParser

# Tags that never have a closing tag.
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}

# Tags that force a line break in the rendered output.
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "dl", "dd", "dt",
    "fieldset", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
}

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Tags whose text is paragraph prose rather than labels or navigation.
PARAGRAPH_TAGS = {"p", "pre", "blockquote"}


class Node:
    """A minimal DOM node. `tag == ""` marks a text node."""

    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag, attrs=None, parent=None, text=""):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []
        self.parent = parent
        self.text = text

    def __repr__(self):  # pragma: no cover - debugging aid
        if self.is_text:
            return f"<text {self.text[:30]!r}>"
        return f"<{self.tag} {len(self.children)} children>"

    @property
    def is_text(self):
        return self.tag == ""

    def iter(self):
        """Yield this node and every descendant, depth first."""
        yield self
        for child in self.children:
            yield from child.iter()

    def inner_text(self):
        return " ".join(node.text for node in self.iter() if node.is_text)


class DOMBuilder(HTMLParser):
    """Builds a tree out of real-world (i.e. broken) HTML.

    Only the auto-closing rules that matter for text extraction are
    implemented - unclosed `<p>`, `<li>`, `<td>` and `<tr>`.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("[document]")
        self.stack = [self.root]
        self.title = ""
        self._in_title = False

    # -- helpers ---------------------------------------------------------
    @property
    def current(self):
        return self.stack[-1]

    def _open_tags(self):
        return [node.tag for node in self.stack]

    def _close_through(self, tag):
        """Pop up to and including `tag`, if it is actually open."""
        if tag not in self._open_tags():
            return
        while len(self.stack) > 1:
            if self.stack.pop().tag == tag:
                return

    def _implicit_close(self, tag):
        open_tags = self._open_tags()
        if tag in BLOCK_TAGS and open_tags[-1] == "p":
            self.stack.pop()
        elif tag == "li" and open_tags[-1] == "li":
            self.stack.pop()
        elif tag in {"td", "th"} and open_tags[-1] in {"td", "th"}:
            self.stack.pop()
        elif tag == "tr" and open_tags[-1] == "tr":
            self.stack.pop()

    # -- HTMLParser hooks -------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
            return
        self._implicit_close(tag)
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.current)
        self.current.children.append(node)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if tag not in VOID_TAGS:
            self._close_through(tag)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif data.strip():
            self.current.children.append(Node("", parent=self.current, text=data))


def parse(html):
    """HTML string -> (root node, page title)."""
    builder = DOMBuilder()
    builder.feed(html)
    builder.close()
    return builder.root, builder.title


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------
def link_density(node):
    """Fraction of the node's text that sits inside links. 1.0 means empty."""
    total = len(node.inner_text())
    if total == 0:
        return 1.0
    linked = sum(
        len(child.inner_text()) for child in node.iter() if child.tag == "a"
    )
    return min(linked / total, 1.0)


def prose_length(node):
    """Characters of real paragraph text inside `node`."""
    return sum(
        len(child.inner_text().strip())
        for child in node.iter()
        if child.tag in PARAGRAPH_TAGS
    )
