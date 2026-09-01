"""Structural guards for the Share button (a standalone HTML export).

Behaviour is proven in tests/e2e/export-share.e2e.cjs, which opens the
PRODUCED FILE in a fresh browser page with the server killed:

    NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/export-share.e2e.cjs

What is worth guarding cheaply here is the one property that makes the file
safe to send: comments are REMOVED from the export, not hidden. `body.read-only`
hides comment cards with CSS, so an export built on that mode would look right
and still carry every private note to whoever received the file.
"""
# NOTE: the browser-driven proof this file used to point at is gone. The 19
# e2e suites spawned annotate's own server, which was deleted when annotate
# moved onto the webcompanion daemon. They are recoverable from git history
# and are repointable — the page they drove is unchanged, only the way it is
# served — but until they are, what remains below is static assertion only.
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EXPORT_JS = REPO / "skills" / "annotate" / "static" / "export.js"
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
CORE_CSS = REPO / "skills" / "_shared" / "web_companion" / "static" / "core.css"


def _strip_selectors():
    """The selectors the export actually deletes.

    Read out of the STRIP array literal rather than the whole file: the module
    comment names several of these selectors while explaining the rule, so a
    file-wide `in src` check would keep passing after the list itself had been
    emptied.
    """
    src = EXPORT_JS.read_text()
    body = src.split("const STRIP = [", 1)[1].split("].join", 1)[0]
    return [line.split("//")[0].strip().strip(",").strip('"')
            for line in body.splitlines() if line.strip().startswith('"')]


def test_the_export_deletes_every_comment_carrier():
    """Each of these renders comment text or review state inside main.prose,
    which is the subtree the export clones. Missing one ships private notes."""
    selectors = _strip_selectors()
    for needle in (".unit-chip",        # a pinned comment's text, in the prose
                   ".inline-comments",  # comment cards, mounted after a block
                   ".unit-composer",    # an open per-unit comment box
                   ".hover-actions", ".unit-strip"):
        assert needle in selectors, f"the export no longer removes {needle!r}"


def test_the_export_strips_review_state_attributes():
    """A block marked "delete" carries data-block-mark, which the stylesheet
    renders struck through and faded. Left on, the reader receives a document
    that looks half-retracted."""
    src = EXPORT_JS.read_text()
    body = src.split("const STATE_ATTRS = [", 1)[1].split("];", 1)[0]
    for needle in ("data-block-mark", "data-mark", "data-engaged-type"):
        assert needle in body, f"the export no longer strips {needle!r}"


def test_the_export_does_not_reuse_read_only_mode():
    """read-only HIDES comment cards; the export must DELETE them. Reaching
    for that class here would silently reintroduce the leak."""
    src = EXPORT_JS.read_text()
    assert 'class="exported"' in src, \
        "the export no longer marks its output body as exported"
    # The prose mentions `body.read-only` to explain WHY it is not used; the
    # code must not actually reach for it.
    assert 'read-only"' not in src.replace("`body.read-only`", ""), \
        "the export is building a read-only page instead of removing the nodes"


def test_fonts_are_embedded_once():
    """The Bricolage face names the same woff2 twice (woff2-variations, then
    woff2). Embedding both costs half a megabyte in every shared file, so the
    src list is deduped — and deduped BEFORE embedding, while a url() still
    holds a comma-free path."""
    src = EXPORT_JS.read_text()
    assert "dedupeFontSrc" in src, "the duplicate-font-src guard is gone"
    order = src.index("embedFonts(dedupeFontSrc(")
    assert order > 0, "dedupe no longer runs before embedding"


def test_the_search_state_is_undone():
    """An active search hides non-matching sections. Copying that into the file
    hands the reader a document with blocks silently missing."""
    src = EXPORT_JS.read_text()
    assert "search-hidden" in src, "the export no longer un-hides filtered blocks"
    assert "search-hit" in src, "the export no longer unwraps highlight marks"


def test_the_button_is_wired_into_the_page():
    server = SERVER_PY.read_text()
    assert 'id="export-btn"' in server, "the Share button is not in the header"
    assert "export.js" in server, "export.js is not in the page's asset list"


def test_share_survives_a_read_only_link():
    """Someone holding a shared link is exactly who wants a copy, and the
    export is built entirely from what their own page already shows."""
    css = CORE_CSS.read_text()
    assert ".export-btn" in css, "the Share button has no styling"
    assert "body.read-only .export-btn" not in css, \
        "Share is hidden on a read-only link, where it would be most useful"


