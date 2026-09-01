"""Structural guards for the maximize control.

The behavioural proof — that clicking the button promotes the card, that the
block is never duplicated or moved, that Fit width is exact, and that every
close path restores the page — lives in `tests/e2e/maximize.e2e.cjs`, which
drives a real browser:

    NODE_PATH=$(npm root -g) node skills/annotate/tests/e2e/maximize.e2e.cjs

What is asserted here is only what a source read can actually see: that the
asset ships and is wired in the right order, that prose is excluded, that the
control is stripped from an export, and that the module never reparents a
block. That last one is the load-bearing rule of the whole feature — moving the
card out of `main.prose` makes script.js's render loop paint a replacement for
the block it finds missing, so the document ends up carrying it twice.
"""
# NOTE: the browser-driven proof this file used to point at is gone. The 19
# e2e suites spawned annotate's own server, which was deleted when annotate
# moved onto the webcompanion daemon. They are recoverable from git history
# and are repointable — the page they drove is unchanged, only the way it is
# served — but until they are, what remains below is static assertion only.
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
MAXIMIZE_JS = STATIC / "maximize.js"
EXPORT_JS = STATIC / "export.js"
STYLE_CSS = STATIC / "style.css"
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


def _strip_comments(js: str) -> str:
    """Drop // and /* */ comments so a guard cannot be satisfied by prose.

    The comments in this module name the rejected designs explicitly, so a
    plain substring search over the source would keep passing after one of
    them came back."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in js.splitlines())


def test_served_after_script_js():
    """maximize.js reads section[data-kind] and mounts into .card-head, both
    built by script.js. Both tags are `defer`, so document order is execution
    order — the ordering is the dependency."""
    head = SERVER_PY.read_text()
    # Order still matters and is still asserted: maximize.js mounts into
    # DOM script.js builds. entry.js loads the list in array order,
    # awaiting each, so position in that array IS execution order.
    i_script = head.index('"script.js"')
    i_max = head.index('"maximize.js"')
    assert i_max > i_script, "maximize.js must be tagged after script.js"


def test_prose_is_not_maximizable():
    """Width buys prose nothing — it is set to a max measure, so a wider column
    only makes lines harder to track back to the left edge."""
    code = _strip_comments(MAXIMIZE_JS.read_text())
    m = re.search(r"MAXIMIZABLE\s*=\s*new Set\(\[(.*?)\]\)", code, re.S)
    assert m, "MAXIMIZABLE set not found"
    kinds = set(re.findall(r'"([a-z]+)"', m.group(1)))
    assert "sequence" in kinds
    assert "markdown" not in kinds and "choice" not in kinds


def test_module_never_reparents_a_block():
    """The card is promoted in place with position:fixed. Appending or
    inserting the <section> anywhere reintroduces the duplicate-block bug."""
    code = _strip_comments(MAXIMIZE_JS.read_text())
    for pattern in (r"appendChild\(\s*section\s*\)",
                    r"insertBefore\(\s*section\b",
                    r"replaceChild\([^)]*\bsection\b",
                    r"\bsection\.remove\(\)"):
        assert not re.search(pattern, code), \
            f"maximize.js reparents the block ({pattern}) — it must promote in place"


def test_promotion_is_position_fixed():
    css = STYLE_CSS.read_text()
    m = re.search(r"section\.block\.card\.is-maximized\s*\{(.*?)\}", css, re.S)
    assert m, ".is-maximized rule not found in style.css"
    assert "position: fixed" in m.group(1)


def test_export_strips_the_control():
    """A shared export carries no JS, so a button that does nothing must not
    travel with it."""
    strip = EXPORT_JS.read_text()
    assert '".max-toggle"' in strip
    assert '".max-chrome"' in strip or '".max-overlay"' in strip


def test_button_is_not_hover_gated():
    """Unlike .hover-actions (feedback verbs, hidden on purpose), this is a view
    control — and one you cannot see is one nobody uses."""
    css = STYLE_CSS.read_text()
    m = re.search(r"\n\.max-toggle\s*\{(.*?)\}", css, re.S)
    assert m, ".max-toggle rule not found"
    assert "opacity: 0" not in m.group(1)
