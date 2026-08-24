"""Read a deck .html into an addressable outline.

Read-only by design. This module never emits HTML: round-tripping a real deck
through a serialiser rewrites 144 of 705 lines, because decks mix HTML
entities with their literal characters and SVG attribute case does not
survive. Callers get line ranges and read the file themselves.

Addressability rule, deliberately narrow:
  * every direct child of `section.slide` that carries a class, except `.num`
    (the harness renumbers it at runtime, so it is not content)
  * every outermost `<p>` and `<li>` inside one of those children

That covers prose, bullets and speaker notes without inventing a schema for
markup nobody has written yet. A table is one target, not one per row: <td>
is not a leaf tag, so the whole block is addressed at once.

An element carries THREE numbers, because one is not enough:

  `ord`        its position among the elements on that slide sharing its
               `path`. (slide, path, ord) is the address a comment travels as.
  `block_ord`  the position of its OWNING BLOCK among the slide's direct
               children whose first class matches. Not the same number: a
               block with leaves is not itself an element, so the emitted
               `.col` may be the slide's second `.col` while its `ord` is 0.
  `leaf_n`     which <p>/<li> inside that block, counted the way this module
               counts them — outermost only.

The browser resolves with `block_ord`/`leaf_n`, never by running `path` as a
CSS selector: `>` means direct child to CSS but "anywhere inside" here, and
CSS `nth-of-type` counts nested elements this module deliberately skips.

Malformed input must not raise. An open tag stack (rather than a depth
counter) means a stray `</div>` is ignored and an unclosed `<li>` is closed by
the next one, so one bad slide costs that slide, not the rest of the file.
"""
from __future__ import annotations

from html.parser import HTMLParser

ADDRESSABLE_LEAF_TAGS = ("p", "li")
_SKIP_CLASSES = {"num"}

# Tags that separate words. Text is captured as a flat run, so without this a
# table reads "NowLater" and a two-cell row loses the gap between its cells.
# Inline tags are deliberately absent: <b> inside a sentence must not split it.
_SEPARATORS = {"p", "li", "tr", "td", "th", "div", "br", "section", "aside",
               "ul", "ol", "table", "h1", "h2", "h3", "h4", "blockquote"}

# Never content, and never a container of content. `svg` is here because a
# deck's diagrams are drawn with tags this module would otherwise have to
# enumerate (`line`, `polygon`, `use`, …) to keep the stack balanced.
_OPAQUE = {"script", "style", "template", "svg"}

# HTML void elements: they never close, so they must never be pushed.
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}

# HTMLParser does no implied-end-tag inference and decks are written by hand,
# so this module has to do what a browser does — and do it the SAME way, or
# the browser and the model disagree about which element a comment addressed.
#
# HTML's "special" category. The spec's <li> algorithm walks outward and gives
# up at any special element other than address/div/p, which is why a nested
# <ul> protects the <li> it sits in: no browser closes the outer item, so this
# module must not either.
_SPECIAL = {
    "address", "applet", "area", "article", "aside", "base", "basefont",
    "bgsound", "blockquote", "body", "br", "button", "caption", "center",
    "col", "colgroup", "dd", "details", "dir", "div", "dl", "dt", "embed",
    "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset",
    "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr",
    "html", "iframe", "img", "input", "keygen", "li", "link", "listing",
    "main", "marquee", "menu", "meta", "nav", "noembed", "noframes",
    "noscript", "object", "ol", "p", "param", "plaintext", "pre", "script",
    "section", "select", "source", "style", "summary", "table", "tbody", "td",
    "template", "textarea", "tfoot", "th", "thead", "title", "tr", "track",
    "ul", "wbr", "xmp"}
_LI_WALK_CONTINUES = {"address", "div", "p"}

# Start tags that close an open <p>. An unclosed lede followed by a <div> is
# ordinary hand-written markup; without this the <p> swallowed its siblings.
_CLOSES_P = {
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol",
    "p", "pre", "section", "summary", "table", "ul"}


def _classes(attrs: list[tuple[str, str | None]]) -> list[str]:
    for name, value in attrs:
        if name == "class" and value:
            return value.split()
    return []


class _Frame:
    """One open element."""

    __slots__ = ("tag", "kind", "element", "leaf_counts", "leaf_seen", "cls",
                 "last_line")

    def __init__(self, tag: str, kind: str | None = None,
                 element: dict | None = None, cls: str = "") -> None:
        self.tag = tag
        self.kind = kind            # None | "slide" | "block" | "leaf"
        self.element = element
        self.cls = cls
        self.leaf_counts: dict[str, int] = {}
        self.leaf_seen = False
        self.last_line = 0


class _DeckParser(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs decodes &mdash; for display. The file is untouched.
        super().__init__(convert_charrefs=True)
        self.slides: list[dict] = []
        self._stack: list[_Frame] = []
        self._buf: list[str] = []
        self._opaque = 0            # depth inside script/style/template/svg
        self._block_counts: dict[str, int] = {}   # per slide, per class

    # -- stack helpers ---------------------------------------------------
    def _find(self, kind: str) -> _Frame | None:
        for frame in reversed(self._stack):
            if frame.kind == kind:
                return frame
        return None

    def _open_slide(self) -> dict | None:
        frame = self._find("slide")
        return frame.element if frame else None

    def _open_block(self) -> _Frame | None:
        # A block is only "open" if no slide was opened after it.
        for frame in reversed(self._stack):
            if frame.kind == "slide":
                return None
            if frame.kind == "block":
                return frame
        return None

    # -- text ------------------------------------------------------------
    def _start_capture(self) -> None:
        self._buf = []

    def _captured(self) -> str:
        return " ".join("".join(self._buf).split())

    def _separate(self, tag: str) -> None:
        if tag in _SEPARATORS and self._stack:
            self._buf.append(" ")

    # -- emit ------------------------------------------------------------
    def _close(self, frame: _Frame, line: int) -> None:
        if frame.kind == "slide":
            return
        if frame.kind not in ("block", "leaf"):
            return
        slide = self._open_slide()
        if slide is None or frame.element is None:
            return
        if frame.kind == "block" and frame.leaf_seen:
            # a block with leaves of its own is a container, not a target
            self._start_capture()
            return
        frame.element["text"] = self._captured()
        frame.element["line_end"] = line
        slide["elements"].append(frame.element)
        self._start_capture()

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if self._opaque:
            if tag in _OPAQUE and tag not in _VOID:
                self._opaque += 1
            return

        line = self.getpos()[0]
        cls = _classes(attrs)

        self._imply_end_tags(tag, line)

        parent = self._stack[-1] if self._stack else None
        # Count EVERY classed direct child of the slide, including the ones no
        # element is made from. The browser resolves a block by its position
        # among the slide's children, so a skipped <svg class="diag"> that is
        # not counted here shifts every later .diag onto the wrong node.
        block_cls = ""
        if parent is not None and parent.kind == "slide" and cls:
            block_cls = cls[0]
            self._block_counts[block_cls] = self._block_counts.get(block_cls, 0) + 1

        if tag in _OPAQUE:
            self._opaque = 1
            return

        kind: str | None = None
        element: dict | None = None

        if tag == "section" and "slide" in cls and self._find("slide") is None:
            # a nested section.slide is markup, not a second slide
            slide = {"index": len(self.slides) + 1,
                     "kind": ("cover" if "tslide" in cls else
                              "divider" if "divider" in cls else "content"),
                     "title": "", "elements": []}
            self.slides.append(slide)
            self._block_counts = {}
            block_cls = ""
            kind, element = "slide", slide

        elif block_cls and block_cls not in _SKIP_CLASSES:
            n = self._block_counts[block_cls] - 1
            kind = "block"
            element = {"slide": self.slides[-1]["index"], "path": "." + block_cls,
                       "component": block_cls, "block_class": block_cls,
                       "block_ord": n, "leaf_tag": None, "leaf_n": None,
                       "line_start": line, "line_end": line, "text": ""}
            self._start_capture()

        elif tag in ADDRESSABLE_LEAF_TAGS:
            block = self._open_block()
            if block is not None and self._find("leaf") is None:
                block.leaf_seen = True
                n = block.leaf_counts.get(tag, 0) + 1
                block.leaf_counts[tag] = n
                assert block.element is not None
                kind = "leaf"
                element = {
                    "slide": block.element["slide"],
                    "path": f"{block.element['path']} > {tag}:nth-of-type({n})",
                    "component": block.element["component"],
                    "block_class": block.element["block_class"],
                    "block_ord": block.element["block_ord"],
                    "leaf_tag": tag, "leaf_n": n,
                    "line_start": line, "line_end": line, "text": ""}
                self._start_capture()

        self._separate(tag)
        if tag not in _VOID:
            frame = _Frame(tag, kind, element, block_cls)
            frame.last_line = line
            self._stack.append(frame)

    def _imply_end_tags(self, tag: str, line: int) -> None:
        """Close what a browser would close when `tag` starts."""
        if tag in _CLOSES_P:
            for frame in reversed(self._stack):
                if frame.tag == "p":
                    self._pop_to("p", line)
                    break
                if frame.kind in ("slide", "block") or frame.tag in _SPECIAL:
                    break

        if tag == "li":
            for frame in reversed(self._stack):
                if frame.tag == "li":
                    self._pop_to("li", line)
                    break
                if frame.kind in ("slide", "block"):
                    break
                # a nested <ul>/<ol>/<table> protects the item it sits in
                if frame.tag in _SPECIAL and frame.tag not in _LI_WALK_CONTINUES:
                    break

        if tag in ("td", "th", "tr"):
            wanted = {"td", "th"} if tag in ("td", "th") else {"tr"}
            for frame in reversed(self._stack):
                if frame.tag in wanted:
                    self._pop_to(frame.tag, line)
                    break
                if frame.kind in ("slide", "block") or frame.tag == "table":
                    break

    def handle_startendtag(self, tag, attrs):
        # Self-closing: never opens a block or a leaf. It is still a child of
        # the slide in the browser's DOM, so it must still be counted, and
        # <br/> must still split words.
        if self._opaque:
            return
        parent = self._stack[-1] if self._stack else None
        cls = _classes(attrs)
        if parent is not None and parent.kind == "slide" and cls:
            self._block_counts[cls[0]] = self._block_counts.get(cls[0], 0) + 1
        self._separate(tag)

    def handle_endtag(self, tag):
        if self._opaque:
            if tag in _OPAQUE:
                self._opaque -= 1
            return
        if tag in _VOID:
            return
        self._separate(tag)
        self._pop_to(tag, self.getpos()[0])

    def _pop_to(self, tag: str, line: int) -> None:
        """Close frames up to and including the innermost `tag`.

        A stray end tag with no matching open frame is ignored, which is what
        keeps a malformed slide from taking the rest of the document with it.
        """
        if not any(frame.tag == tag for frame in self._stack):
            return
        while self._stack:
            frame = self._stack.pop()
            self._close(frame, line)
            if frame.tag == tag:
                return

    def handle_data(self, data):
        if self._opaque:
            return
        if self._stack:
            if data.strip():
                self._stack[-1].last_line = self.getpos()[0]
            self._buf.append(data)

    def close(self):
        super().close()
        # An unclosed document still yields what it managed to open, but the
        # range must not run to end-of-file: Claude replaces a line range, and
        # a range ending at EOF would delete the rest of the deck.
        while self._stack:
            frame = self._stack.pop()
            end = frame.last_line or (
                frame.element["line_start"] if frame.element else 0)
            self._close(frame, end)


def parse_deck(html: str) -> dict:
    """Return {"slides": [...]}. See module docstring for the addressing rule."""
    parser = _DeckParser()
    parser.feed(html)
    parser.close()
    for slide in parser.slides:
        _number_duplicates(slide)
        slide["title"] = _title_for(slide)
    return {"slides": parser.slides}


def _number_duplicates(slide: dict) -> None:
    """Give every element its position among same-path siblings."""
    seen: dict[str, int] = {}
    for element in slide["elements"]:
        n = seen.get(element["path"], 0)
        seen[element["path"]] = n + 1
        element["ord"] = n


def _title_for(slide: dict) -> str:
    # First occurrence wins: a slide with two .title blocks is titled by the
    # one the reader meets first.
    by_path: dict[str, str] = {}
    for e in slide["elements"]:
        by_path.setdefault(e["path"], e["text"])
    for path in (".title", ".dname", ".dkick"):
        if by_path.get(path):
            return by_path[path]
    return ""
