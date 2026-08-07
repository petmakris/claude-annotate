"""Structural guards for the compact control.

Compact replaced the private fold. Its first guarantee is therefore a
negative one: the fold apparatus must be gone, not merely unreferenced.
A surviving `data-read` rule or an orphaned `toggleUnitRead` is how a
replaced feature comes back to life six months later.

Source-string checks matching the repo's other smoke tests (see
test_smoke_dismiss_lock.py). Live behavior is manual via the demo push.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SUBUNITS_JS = STATIC / "subunits.js"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"
SERVER_PY = REPO / "skills" / "annotate" / "server.py"

# Every identifier the fold owned. None may survive in any form.
FOLD_JS_SYMBOLS = (
    "annotate.read.", "READ_KEY", "loadRead", "saveRead",
    "toggleUnitRead", "toggleBlockRead", "applyReadState", "applyBlockRead",
    "readKeyForUnit", "foldable", "READ_ICON", "READ_TITLE",
)
FOLD_CSS_SELECTORS = ('[data-read="1"]', ".unit-read", ".hover-read")


def test_the_private_fold_is_gone_from_the_javascript():
    for path in (SUBUNITS_JS, SCRIPT_JS):
        src = path.read_text()
        for dead in FOLD_JS_SYMBOLS:
            assert dead not in src, f"{path.name} still carries {dead!r}"


def test_the_private_fold_is_gone_from_the_css():
    css = STYLE_CSS.read_text()
    for dead in FOLD_CSS_SELECTORS:
        assert dead not in css, f"style.css still styles {dead!r}"


def test_the_round_store_survived_the_removal():
    """The fold had its own key space. Deleting it must not have taken the
    marks store with it."""
    src = SUBUNITS_JS.read_text()
    assert "annotate.round." in src, "the round storage key vanished"


def test_no_control_survives_a_read_only_link():
    """The fold used to be the one thing a guest could do, because it never
    reached the server. Compact is an edit, so nothing is left to exempt."""
    css = STYLE_CSS.read_text()
    assert "body.read-only .hover-actions button," in css, \
        "read-only no longer hides every header control"
    assert "body.read-only .unit-strip button," in css, \
        "read-only no longer hides every sub-unit control"
    assert ":not(.hover-read)" not in css and ":not(.unit-read)" not in css, \
        "a read-only carve-out for the deleted fold survived"


def test_the_busy_lock_covers_every_strip_button():
    """Folding was exempt from the busy lock because it changed nothing
    Claude would see. Every remaining control is feedback, so none is."""
    css = STYLE_CSS.read_text()
    assert "body.is-busy .unit-strip button { display: none; }" in css, \
        "the busy lock still exempts something from the strip"


def test_the_legend_does_not_advertise_a_private_control():
    src = SERVER_PY.read_text()
    assert ">Fold<" not in src, "the legend still lists the removed fold"
    assert "legend-private" not in src, \
        "the legend still marks a row as private to the browser"
    assert "Claude is never told" not in src, \
        "the legend still promises a control that sends nothing"
