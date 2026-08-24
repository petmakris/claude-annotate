"""Read a deck .html into an addressable outline.

Read-only by design. This module never emits HTML: round-tripping a real deck
through a serialiser rewrites 144 of 705 lines, because decks mix HTML
entities with their literal characters and SVG attribute case does not
survive. Callers get line ranges and read the file themselves.

Addressability rule, deliberately narrow:
  * every direct child of `section.slide` that carries a class, except `.num`
    (the harness renumbers it at runtime, so it is not content)
  * every `<p>` and `<li>` inside one of those children

That covers prose, bullets and speaker notes without inventing a schema for
markup nobody has written yet. A table is one target, not one per row: <td>
is not a leaf tag, so the whole block is addressed at once.
"""
from __future__ import annotations

from html.parser import HTMLParser

ADDRESSABLE_LEAF_TAGS = ("p", "li")
_SKIP_CLASSES = {"num"}
# Tags that separate words. Text is captured as a flat run, so without this a
# table reads "NowLater" and a two-cell row loses the gap between its cells.
# Inline tags are deliberately absent: <b> inside a sentence must not split it.
_SEPARATORS = {"p", "li", "tr", "td", "th", "div", "br", "section", "aside", "ul", "ol"}
_VOID = {"br", "hr", "img", "meta", "link", "input", "source", "path", "circle", "rect"}


def _classes(attrs: list[tuple[str, str | None]]) -> list[str]:
    for name, value in attrs:
        if name == "class" and value:
            return value.split()
    return []


class _DeckParser(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs decodes &mdash; for display. The file is untouched.
        super().__init__(convert_charrefs=True)
        self.slides: list[dict] = []
        self._slide: dict | None = None
        self._slide_depth = 0
        self._depth = 0
        self._block: dict | None = None   # the current direct child of the slide
        self._leaf: dict | None = None    # the current <p>/<li> inside it
        self._leaf_counts: dict[str, int] = {}
        self._buf: list[str] = []

    # -- helpers ---------------------------------------------------------
    def _start_capture(self) -> None:
        self._buf = []

    def _captured(self) -> str:
        return " ".join("".join(self._buf).split())

    def _emit(self, target: dict, end_line: int) -> None:
        target["text"] = self._captured()
        target["line_end"] = end_line
        assert self._slide is not None
        self._slide["elements"].append(target)

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        cls = _classes(attrs)

        if tag == "section" and "slide" in cls:
            kind = "cover" if "tslide" in cls else "divider" if "divider" in cls else "content"
            self._slide = {"index": len(self.slides) + 1, "kind": kind,
                           "title": "", "elements": []}
            self.slides.append(self._slide)
            self._slide_depth = self._depth
            self._block = None
            self._leaf = None
            self._leaf_counts = {}

        elif self._slide is not None and self._depth == self._slide_depth + 1 and cls:
            if cls[0] not in _SKIP_CLASSES:
                self._block = {"slide": self._slide["index"], "path": "." + cls[0],
                               "component": cls[0], "line_start": line,
                               "line_end": line, "text": ""}
                self._leaf_counts = {}
                self._start_capture()

        elif self._block is not None and tag in ADDRESSABLE_LEAF_TAGS and self._leaf is None:
            n = self._leaf_counts.get(tag, 0) + 1
            self._leaf_counts[tag] = n
            self._leaf = {"slide": self._slide["index"],
                          "path": f"{self._block['path']} > {tag}:nth-of-type({n})",
                          "component": self._block["component"],
                          "line_start": line, "line_end": line, "text": ""}
            self._start_capture()

        self._separate(tag)
        if tag not in _VOID:
            self._depth += 1

    def handle_startendtag(self, tag, attrs):
        pass  # self-closing: never opens a block or a leaf

    def handle_endtag(self, tag):
        self._separate(tag)
        if tag not in _VOID:
            self._depth -= 1
        line = self.getpos()[0]

        if self._leaf is not None and tag in ADDRESSABLE_LEAF_TAGS:
            self._emit(self._leaf, line)
            self._leaf = None
            self._start_capture()
            return

        if self._block is not None and self._slide is not None \
                and self._depth == self._slide_depth + 1:
            # a block with addressable leaves is a container, not a target
            has_leaves = any(e["path"].startswith(self._block["path"] + " > ")
                             for e in self._slide["elements"])
            if not has_leaves:
                self._emit(self._block, line)
            self._block = None
            return

        if tag == "section" and self._slide is not None and self._depth == self._slide_depth:
            self._slide = None

    def _separate(self, tag: str) -> None:
        if tag in _SEPARATORS and (self._leaf is not None or self._block is not None):
            self._buf.append(" ")

    def handle_data(self, data):
        if self._leaf is not None or self._block is not None:
            self._buf.append(data)


def parse_deck(html: str) -> dict:
    """Return {"slides": [...]}. See module docstring for the addressing rule."""
    parser = _DeckParser()
    parser.feed(html)
    parser.close()
    for slide in parser.slides:
        slide["title"] = _title_for(slide)
    return {"slides": parser.slides}


def _title_for(slide: dict) -> str:
    by_path = {e["path"]: e["text"] for e in slide["elements"]}
    for path in (".title", ".dname", ".dkick"):
        if by_path.get(path):
            return by_path[path]
    return ""
