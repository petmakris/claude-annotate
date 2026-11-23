"""The page's own code and stylesheet, as one text each, for tests to read.

script.js and style.css were split along their section markers into parts
that entry.js loads in order (script-*.js after script.js, style-*.css after
style.css). A test asserting "the page does X" means the page, not whichever
part X happens to sit in, so it reads the parts joined, in load order, from
here — the one place that knows which files they are.

SCRIPT_JS and STYLE_CSS stand where `STATIC / "script.js"` and
`STATIC / "style.css"` stood: `.read_text()` gives the joined source.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
ENTRY_JS = STATIC / "entry.js"


def _listed(array: str) -> list[str]:
    src = ENTRY_JS.read_text()
    m = re.search(r"const %s = \[(.*?)\];" % array, src, re.S)
    assert m, f"entry.js has no {array} list"
    body = "\n".join(line.split("//", 1)[0] for line in m.group(1).splitlines())
    return re.findall(r'"([^"]+)"', body)


def script_parts() -> list[str]:
    """The page-code files, in the order entry.js loads them."""
    return [f for f in _listed("JS") if f == "script.js" or f.startswith("script-")]


def style_parts() -> list[str]:
    """The page stylesheet's files, in the order entry.js links them."""
    return [f for f in _listed("CSS") if f == "style.css" or f.startswith("style-")]


class _Joined:
    """Reads like a Path to one file; is every part, joined in load order."""

    def __init__(self, parts, label):
        self._parts = parts
        self.name = label
        self.parent = STATIC

    def files(self) -> list[Path]:
        return [STATIC / f for f in self._parts()]

    def exists(self) -> bool:
        return all(p.exists() for p in self.files())

    def read_text(self, *a, **k) -> str:
        return "\n".join(p.read_text(*a, **k) for p in self.files())

    def __str__(self):
        return " + ".join(str(p) for p in self.files())


SCRIPT_JS = _Joined(script_parts, "script.js")
STYLE_CSS = _Joined(style_parts, "style.css")


def script_source() -> str:
    return SCRIPT_JS.read_text()


def style_source() -> str:
    return STYLE_CSS.read_text()
