"""Structural guards for the fold (read marker) and the control legend.

Folding answers "do I still need to look at this?"; the three round controls
answer "what should Claude do with this?". The whole value of the feature is
that those two axes never touch — a reader who folds a paragraph they
understood must not thereby delete it from the document. These tests guard the
separation, since nothing about the UI itself makes an accidental merge
obvious.

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


def test_read_state_has_its_own_store():
    """A separate localStorage key, not a kind inside the round store.

    Sharing the store is the failure mode this feature exists to avoid: a
    fold that lands in `marks` becomes a reaction on the wire, and Claude
    deletes or protects a passage the user only wanted off their screen."""
    src = SUBUNITS_JS.read_text()
    assert "annotate.read." in src, "no dedicated read-state storage key"
    assert "annotate.round." in src, "round storage key vanished"
    assert "loadRead" in src and "saveRead" in src, \
        "read state is not persisted through its own load/save pair"


def test_read_is_not_a_round_kind():
    """CONTROL_SPECS is the wire vocabulary — `read` must never appear in it."""
    src = SUBUNITS_JS.read_text()
    start = src.index("const CONTROL_SPECS")
    end = src.index("const CONTROLS")
    assert '"read"' not in src[start:end], \
        "the fold control leaked into the round-kind vocabulary"
    for kind in ('"delete"', '"keep"', '"comment"'):
        assert kind in src[start:end], f"round vocabulary lost {kind}"


def test_both_scopes_offer_the_fold_control():
    """Header strip and sub-unit strip, same glyph, imported from one place."""
    subunits = SUBUNITS_JS.read_text()
    script = SCRIPT_JS.read_text()
    assert "READ_ICON" in subunits, "subunits.js does not define the fold glyph"
    assert "toggleBlockRead" in subunits, "no block-scope fold toggle"
    assert "toggleUnitRead" in subunits, "no unit-scope fold toggle"
    assert "AnnotateSubunits?.READ_ICON" in script, \
        "the header strip draws its own fold glyph instead of sharing one"
    assert "toggleBlockRead" in script, "header strip does not wire the fold control"


def test_folded_block_springs_back_when_rewritten():
    """A fold records the version it was made against.

    You marked the wording you read as read — not whatever replaces it. So a
    version bump has to drop the fold rather than hide fresh content."""
    src = SUBUNITS_JS.read_text()
    assert "applyBlockRead" in src, "no block fold application pass"
    assert "dataset.version" in src, \
        "block folds do not record the version they were made against"


def test_folding_is_not_gated_on_the_busy_lock():
    """The round controls disappear mid-round; the reading aid must not.

    Folding changes nothing Claude will ever see, so locking it while a round
    is in flight would take a reading aid away for no reason."""
    css = STYLE_CSS.read_text()
    assert "body.is-busy .unit-strip button:not(.unit-read)" in css, \
        "the busy lock hides the fold control along with the round controls"


def test_legend_covers_all_four_controls_and_names_the_private_one():
    src = SERVER_PY.read_text()
    assert "_LEGEND_HTML" in src, "no legend on the page"
    for label in (">Trash<", ">Check<", ">Comment<", ">Fold<"):
        assert label in src, f"legend missing the {label!r} row"
    assert "legend-private" in src, \
        "the legend does not set the private control apart from the feedback ones"
    assert "Claude is never told" in src, \
        "the legend does not say that folding sends nothing"


def test_legend_uses_the_real_glyphs():
    """A legend the reader cannot match to the button in front of them is
    worse than no legend, so the icons are the production ones."""
    server = SERVER_PY.read_text()
    script = SCRIPT_JS.read_text()
    subunits = SUBUNITS_JS.read_text()
    check = '<polyline points="20 6 9 17 4 12"/>'
    eye_off = '<line x1="1" y1="1" x2="23" y2="23"/>'
    assert check in server and check in script, \
        "legend check glyph drifted from the one the button draws"
    assert eye_off in server and eye_off in subunits, \
        "legend fold glyph drifted from the one the button draws"
