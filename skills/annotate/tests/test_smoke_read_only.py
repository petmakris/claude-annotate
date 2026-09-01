"""Structural guards for how a shared, read-only link renders.

The server refuses the writes regardless — that is tested in the engine. What
these guard is the page not *offering* what will be refused. There used to be
one exception, the private fold; compact replaced it, and compact is an edit,
so a guest is now offered nothing at all.

Source-string checks matching the repo's other smoke tests (see
test_smoke_dismiss_lock.py). Live behavior is manual via the demo push.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
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
PUSHING_MD = REPO / "skills" / "annotate" / "references" / "pushing.md"


def test_feedback_controls_are_hidden_for_a_guest():
    """Removed, not disabled: a greyed-out trash can invites a click and then
    explains itself with a 403."""
    css = STYLE_CSS.read_text()
    assert "body.read-only .hover-actions button," in css, \
        "block feedback controls are still offered on a read-only link"
    assert "body.read-only .unit-strip button," in css, \
        "sub-unit feedback controls are still offered on a read-only link"
    assert "body.read-only #round-dock" in css, \
        "the submit dock is still shown on a read-only link"


def test_a_guest_is_offered_no_exception():
    """The fold was the one thing a guest could still do, because it never
    reached the server. Compact is an edit and belongs to the owner, so the
    carve-outs that kept the fold alive must be gone rather than retargeted."""
    css = STYLE_CSS.read_text()
    assert ":not(.hover-read)" not in css, \
        "the header read-only rule still exempts a control"
    assert ":not(.unit-read)" not in css, \
        "the sub-unit read-only rule still exempts a control"
    assert ":not(.hover-compact)" not in css and ":not(.unit-compact)" not in css, \
        "the fold exemption was retargeted at compact instead of removed"


def test_the_page_says_it_is_read_only():
    server = SERVER_PY.read_text()
    assert "read-only-badge" in server, "no read-only indicator in the page shell"
    assert "Read-only" in server, "the badge does not name the mode"
    # The fold was the one thing the badge could truthfully promise a guest,
    # because it never left their browser. Compact replaced it and compact is
    # an owner-only edit, so nothing is left for the tooltip to promise beyond
    # "read, not write" — a resurrected promise of a private reading aid, in
    # any wording, is the bug this guards against.
    badge = re.search(
        r'class="read-only-badge"\s+title="([^"]*)"', server)
    assert badge, "could not find the read-only badge's tooltip text"
    # The source wraps the title attribute across two adjacent f-string
    # literals for line length, so the raw match still carries the closing
    # `'` / newline / indent / opening `f'` of that split. Python folds those
    # back into one string at parse time; fold them back here too so the
    # comparison below is against the string a guest actually reads.
    tooltip = re.sub(r"'\s*\n\s*f'", "", badge.group(1))
    # Pinned to the exact string, not a keyword blacklist: this tooltip is the
    # only thing a guest is told about what they can do here, so ANY change to
    # it — reworded or not — has to be re-checked against what a guest can
    # actually do, and this assertion updated deliberately rather than
    # reflexively loosened to let a new wording through.
    assert tooltip == "This link can read the document but not change it.", \
        f"the read-only badge's tooltip changed: {tooltip!r}"


def test_pushing_doc_separates_the_shareable_url_from_the_owner_one():
    """The whole feature fails if the announcing Claude pastes owner_url into
    a chat, so the instruction has to be explicit."""
    doc = PUSHING_MD.read_text()
    assert "owner_url" in doc, "pushing.md does not mention the owner URL"
    assert "read-only" in doc, "pushing.md does not say which URL is read-only"
    assert "Never print `owner_url`" in doc, \
        "pushing.md does not warn against announcing the credential-bearing URL"
