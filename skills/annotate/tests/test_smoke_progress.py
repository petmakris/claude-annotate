"""Structural guards for round progress and the un-freezing of marking.

Two separate promises. First: a round must register its event id, or the
progress labels the hook publishes and /poll serves are computed and thrown
away — which is what happened for the whole life of the round feature.
Second: marking is local until Submit, so only Submit ever needed the busy
lock; freezing the whole vocabulary took away work the user could still do.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SUBUNITS_JS = STATIC / "subunits.js"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"


def test_a_round_registers_its_event_id():
    """Without this the label never reaches applyProgress."""
    subunits = SUBUNITS_JS.read_text()
    assert "registerRoundEvent" in subunits, \
        "submitRound does not register its event id for progress"


def test_the_page_exposes_a_way_to_register():
    script = SCRIPT_JS.read_text()
    assert "registerRoundEvent" in script, \
        "script.js exposes no round registration hook"
    assert "AnnotatePage" in script, "no page export object for subunits.js"


def test_progress_labels_reach_the_banner():
    script = SCRIPT_JS.read_text()
    assert "bb-label" in script, "the busy banner has no live label element"


def test_marking_survives_the_busy_lock():
    """Marks are local; only Submit talks to Claude."""
    css = STYLE_CSS.read_text()
    assert "body.is-busy .unit-strip button { display: none; }" not in css, \
        "the busy lock still hides every marking control"


def test_the_block_being_rewritten_is_still_locked():
    """Un-freezing the page must not make a mid-rewrite block markable."""
    css = STYLE_CSS.read_text()
    assert "section.block.is-updating" in css, \
        "the per-block updating lock disappeared with the page-wide one"
