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


def test_the_busy_lock_no_longer_covers_every_strip_button():
    """Superseded by the annotate-ux-pass Task 2 reversal: marks are local
    and only Submit ever needed the lock, so the strip stays live while a
    round is in flight (see test_smoke_progress.py's
    test_marking_survives_the_busy_lock, which guards the same rule)."""
    css = STYLE_CSS.read_text()
    assert "body.is-busy .unit-strip button { display: none; }" not in css, \
        "the busy lock still hides every marking control"


def test_the_legend_does_not_advertise_a_private_control():
    src = SERVER_PY.read_text()
    assert ">Fold<" not in src, "the legend still lists the removed fold"
    assert "legend-private" not in src, \
        "the legend still marks a row as private to the browser"
    assert "Claude is never told" not in src, \
        "the legend still promises a control that sends nothing"


EYE_OFF = '<line x1="1" y1="1" x2="23" y2="23"/>'


def test_compact_is_in_the_wire_vocabulary():
    """CONTROL_SPECS is the list of kinds that reach Claude. Compact belongs
    in it — that is precisely the difference from the fold it replaced."""
    src = SUBUNITS_JS.read_text()
    start = src.index("const CONTROL_SPECS")
    end = src.index("const CONTROLS")
    spec = src[start:end]
    for kind in ('"delete"', '"keep"', '"comment"', '"compact"'):
        assert kind in spec, f"round vocabulary is missing {kind}"


def test_the_strip_can_render_an_icon_glyph():
    """The three original controls are emoji, compact is an SVG. A strip loop
    that assigns textContent silently renders the SVG source as text."""
    src = SUBUNITS_JS.read_text()
    assert "b.textContent = glyph" not in src, \
        "the strip loop still assigns glyphs as text; the SVG will not render"
    assert "b.innerHTML = glyph" in src, "the strip loop does not render glyphs"


def test_both_scopes_offer_compact_with_the_same_glyph():
    subunits = SUBUNITS_JS.read_text()
    script = SCRIPT_JS.read_text()
    assert "COMPACT_ICON" in subunits, "subunits.js does not define the glyph"
    assert EYE_OFF in subunits, "the sub-unit glyph is not the eye-off icon"
    assert EYE_OFF in script, "the header glyph is not the eye-off icon"
    assert '{ id: "compact"' in script, \
        "the header strip does not carry compact in ACTION_TYPES"


def test_compact_is_gated_on_the_busy_lock():
    """It is a round control, so it must not be clickable mid-round. Guarded
    by the shared rule from Task 2 plus the loop's own guard."""
    src = SUBUNITS_JS.read_text()
    start = src.index("for (const [kind, glyph, title] of CONTROLS.unit)")
    end = src.index("el.appendChild(strip)")
    assert 'classList.contains("is-busy")' in src[start:end], \
        "the strip loop lost its busy guard"


def test_table_rows_can_be_compacted():
    """The fold excluded <tr> because a row cannot be height-clamped. Compact
    clamps nothing, so the exclusion must not have been carried over."""
    src = SUBUNITS_JS.read_text()
    assert 'tagName !== "TR"' not in src, \
        "the fold's table-row exclusion survived into compact"


def test_compact_has_its_own_pending_appearance():
    """Delete strikes through, keep tints green. Compact must not be
    mistakable for either — it is the only one that is lossy AND silent."""
    css = STYLE_CSS.read_text()
    assert '.sub-unit[data-mark="compact"]' in css, \
        "a pending unit-scope compact is invisible"
    assert 'section.block[data-block-mark="compact"]' in css, \
        "a pending block-scope compact does not light its control"


def test_the_legend_explains_compact_honestly():
    """The legend is the only place the lossiness is stated. If it claims
    nothing is lost, the control is mis-sold."""
    src = SERVER_PY.read_text()
    assert ">Compact<" in src, "the legend does not list compact"
    assert "_ICON_COMPACT" in src, "the legend draws no compact glyph"
    assert EYE_OFF in src, "the legend glyph drifted from the button's"


def test_the_dead_private_legend_style_is_gone():
    css = STYLE_CSS.read_text()
    assert ".legend-private" not in css, \
        "styling survives for a legend row that no longer exists"
