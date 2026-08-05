"""Structural guards for granular sub-unit marks + batched review rounds.

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


def test_subunits_js_exists_with_public_api():
    src = SUBUNITS_JS.read_text()
    for needle in ("window.AnnotateSubunits", "decorate", "onPoll",
                   '"round"', "reactions", "localStorage"):
        assert needle in src, f"subunits.js missing {needle!r}"


def test_subunits_selectors_cover_all_four_unit_types():
    src = SUBUNITS_JS.read_text()
    for needle in (":scope > ul > li", ":scope > ol > li",
                   ":scope > p", ":scope > pre", "tbody tr"):
        assert needle in src, f"subunits.js missing unit selector {needle!r}"


def test_subunits_skips_authored_annotate_ids():
    assert "data-annotate-id" in SUBUNITS_JS.read_text()


def test_subunits_marks_are_ordinal_aware():
    """Same-text units in one block must not collide on a shared markKey,
    and the wire prefix/suffix must be computed for the clicked occurrence
    (not always the first) — see design spec § "Duplicate unit text"."""
    src = SUBUNITS_JS.read_text()
    for needle in ("unitOrdinal", "nthIndexOf", "::${ordinal}"):
        assert needle in src, f"subunits.js missing ordinal guard {needle!r}"
    # The in-flight round id / sentinel must never leak the ordinal onto
    # the wire payload built in submitRound.
    assert "ordinal" not in src.split("function submitRound")[1].split(
        "function clearRound")[0]


def test_subunits_prunes_orphan_marks_before_submit_and_render():
    """A block/unit Claude has already removed must never reach the wire —
    server.py's _handle_round 422s the WHOLE round on the first unknown
    block_id, so an unpruned orphan would wedge Submit forever."""
    src = SUBUNITS_JS.read_text()
    for needle in ("pruneMarks", "booted", "main.prose section.block",
                   ".block-content"):
        assert needle in src, f"subunits.js missing prune guard {needle!r}"
    # pruneMarks must run at the top of both call sites the reviewer named.
    assert "function renderDock() {\n    pruneMarks();" in src
    assert "function submitRound() {\n    pruneMarks();" in src


def test_subunits_resets_pending_round_on_dead_watcher():
    """Mirrors script.js's WATCHER_DEAD_AFTER_S handling — a dead watcher
    means no ack is ever coming, so the dock must not stay wedged forever."""
    src = SUBUNITS_JS.read_text()
    for needle in ("watcher_age_s", "WATCHER_DEAD_AFTER_S"):
        assert needle in src, f"subunits.js missing {needle!r}"


def test_subunits_surfaces_submit_failure():
    assert "roundError" in SUBUNITS_JS.read_text()


def test_script_js_calls_decorate_on_both_render_paths():
    src = SCRIPT_JS.read_text()
    assert src.count("AnnotateSubunits.decorate") >= 2, \
        "script.js must decorate in createBlockSection AND updateBlockContent"
    assert "AnnotateSubunits.onPoll" in src


def test_server_page_includes_subunits_script():
    assert "subunits.js" in SERVER_PY.read_text()


def test_style_css_has_subunit_styles():
    css = STYLE_CSS.read_text()
    for needle in (".sub-unit", ".unit-strip", '[data-mark="delete"]',
                   '[data-mark="keep"]', ".unit-chip", "#round-dock",
                   "body.is-busy .unit-strip"):
        assert needle in css, f"style.css missing {needle!r}"


def test_one_vocabulary_at_both_scopes():
    """The card header and the sub-unit strip must offer the same three
    controls. The original confusion was two overlapping strips with
    different verbs (comment/reject/dismiss vs agree/dismiss/comment), so
    a drift back to different verb sets is the regression to catch."""
    subunits = SUBUNITS_JS.read_text()
    script = SCRIPT_JS.read_text()
    for kind in ("delete", "keep", "comment"):
        assert f'"{kind}"' in subunits, f"subunits.js lost the {kind!r} control"
        assert f'id: "{kind}"' in script, f"script.js header strip lost {kind!r}"
    for gone in ("agree", "reject"):
        assert f'"{gone}"' not in subunits, \
            f"subunits.js still uses the retired {gone!r} vocabulary"


def test_the_two_strips_cannot_overlap():
    """Block controls live in the card header, unit controls in the body, so
    they occupy disjoint pixels and need no pointer-priority override.

    The old `:has(.sub-unit:hover)` rule blanked the block strip whenever a
    sentence was hovered. With the header split that is both unnecessary and
    harmful — it would hide a pending block mark's indicator on hover — so
    its absence is the thing worth guarding."""
    css = STYLE_CSS.read_text()
    assert "section.block:has(.sub-unit:hover) .hover-actions" not in css, \
        "the obsolete unit-over-block pointer-priority override is back"


def test_block_controls_reveal_from_anywhere_in_the_header():
    """The reveal keys off .card-head, not .card-title.

    Title-only scoping was tried and rejected: it makes a target only as wide
    as the bold text, which the pointer keeps missing. It only ever existed to
    stop a far-right strip lighting up from a distant pointer, and the strip
    now mounts beside the title, so the band-wide trigger is the correct one."""
    css = STYLE_CSS.read_text()
    assert ".card-head:hover .hover-actions" in css, \
        "block controls no longer reveal from header hover"
    assert ".card-head .card-title:hover ~ .hover-actions" not in css, \
        "block controls are back to the title-only trigger that was rejected"
