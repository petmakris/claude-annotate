"""Structural guards for how a shared, read-only link renders.

The server refuses the writes regardless — that is tested in the engine. What
these guard is the page not *offering* what will be refused, and one specific
exception: folding must survive read-only mode, because it is the reading aid
a guest actually needs and it never leaves their browser.

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
    assert "body.read-only .hover-actions button:not(.hover-read)" in css, \
        "block feedback controls are still offered on a read-only link"
    assert "body.read-only .unit-strip button:not(.unit-read)" in css, \
        "sub-unit feedback controls are still offered on a read-only link"
    assert "body.read-only #round-dock" in css, \
        "the submit dock is still shown on a read-only link"


def test_folding_survives_read_only():
    """The one thing a guest can still do. It is browser-local and never
    reaches the server, so read-only mode must not take it away."""
    css = STYLE_CSS.read_text()
    assert "body.read-only .hover-actions .hover-read { opacity: 1; pointer-events: auto; }" in css, \
        "the fold control was hidden along with the feedback controls"
    for kept in ("button:not(.hover-read)", "button:not(.unit-read)"):
        assert kept in css, f"read-only rule stopped exempting {kept}"


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
