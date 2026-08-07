"""Structural guards for how a shared, read-only link renders.

The server refuses the writes regardless — that is tested in the engine. What
these guard is the page not *offering* what will be refused. There used to be
one exception, the private fold; compact replaced it, and compact is an edit,
so a guest is now offered nothing at all.

Source-string checks matching the repo's other smoke tests (see
test_smoke_dismiss_lock.py). Live behavior is manual via the demo push.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
STYLE_CSS = STATIC / "style.css"
SERVER_PY = REPO / "skills" / "annotate" / "server.py"
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


def test_pushing_doc_separates_the_shareable_url_from_the_owner_one():
    """The whole feature fails if the announcing Claude pastes owner_url into
    a chat, so the instruction has to be explicit."""
    doc = PUSHING_MD.read_text()
    assert "owner_url" in doc, "pushing.md does not mention the owner URL"
    assert "read-only" in doc, "pushing.md does not say which URL is read-only"
    assert "Never print `owner_url`" in doc, \
        "pushing.md does not warn against announcing the credential-bearing URL"
