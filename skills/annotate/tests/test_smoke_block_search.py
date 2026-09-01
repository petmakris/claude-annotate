"""Structural guard for the client-side block-search feature.

Asserts the search box markup and its script/style hooks exist. These are
string/source checks (matching the repo's other smoke tests) — the live
behavior is covered by tests/e2e/search.e2e.cjs.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# The page shell and its asset list used to be printed by server.py; they now
# live in the renderer the daemon loads — shell.js for the markup, entry.js for
# which stylesheets and scripts are pulled in and in what order. These tests
# assert against the page's source either way, so they read both.
class _PageSource:
    """The page's markup and its asset list, as a single string to assert on.

    shell.js holds the markup as a JSON-encoded JS string literal, so reading
    the file raw would hand these tests `id=\\"block-search\\"` and every
    markup assertion would fail on the escaping rather than on the thing it
    is checking. The literal is decoded back to real HTML here, and entry.js
    (which lists the stylesheets and scripts, in load order) is appended.
    """

    def __init__(self, repo):
        static = repo / "skills" / "annotate" / "static"
        self._shell = static / "shell.js"
        self._entry = static / "entry.js"

    def read_text(self, *a, **k):
        import json
        src = self._shell.read_text(*a, **k)
        m = re.search(r"export const SHELL_HTML = (\".*\");", src, re.S)
        html = json.loads(m.group(1)) if m else src
        return html + "\n" + self._entry.read_text(*a, **k)


SERVER_PY = _PageSource(REPO)
STYLE_CSS = REPO / "skills" / "annotate" / "static" / "style.css"
SEARCH_JS = REPO / "skills" / "annotate" / "static" / "search.js"
FUSE_JS = REPO / "skills" / "annotate" / "static" / "fuse.min.js"


def test_search_box_markup_in_server():
    src = SERVER_PY.read_text()
    assert 'id="block-search"' in src, "search input missing from rendered header"
    assert "header-search" in src, "search wrapper missing from header"


def test_search_scripts_included():
    src = SERVER_PY.read_text()
    assert "fuse.min.js" in src, "fuse.min.js not in the page's asset list"
    assert "search.js" in src, "search.js not in the page's asset list"


def test_search_static_files_exist():
    assert FUSE_JS.exists(), "vendored fuse.min.js missing"
    assert SEARCH_JS.exists(), "search.js missing"


def test_search_css_present():
    css = STYLE_CSS.read_text()
    for needle in (".header-search", ".search-input", ".search-hidden",
                   "mark.search-hit", ".search-count"):
        assert needle in css, f"style.css missing {needle!r}"
