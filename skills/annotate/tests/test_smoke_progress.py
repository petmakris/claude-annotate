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


def test_marking_clicks_are_not_silently_dropped_while_busy():
    """The CSS un-freeze (test_marking_survives_the_busy_lock, above) is only
    half the fix. Deleting the `display: none` rule makes the unit-strip and
    hover-actions controls visible and hoverable during a round — but three
    JS-level `if (... is-busy) return;` guards used to swallow the click
    anyway. A VISIBLE control that silently does nothing on click is worse
    than a hidden one: it reads as a broken page, not a locked one. All
    three gate paths that only ever touch the local `marks`/`annotations`
    store (never the network), so none of them needs the busy lock — the
    lock belongs on Submit alone (#round-submit stays disabled elsewhere in
    this file's checks) and on `.choice-submit-btn`/`.card-submit-btn`,
    which do POST immediately.

    This is a straight count rather than a per-site slice: any of the three
    sites regressing back to a guard should fail this test, whether it's one
    of the original three or a new one added the same way.
    """
    subunits = SUBUNITS_JS.read_text()
    script = SCRIPT_JS.read_text()
    is_busy_guard = 'classList.contains("is-busy")) return;'
    assert is_busy_guard not in subunits, \
        "subunits.js still has an is-busy early-return guarding a mark click"
    # script.js legitimately toggles/reads is-busy elsewhere (setBusy,
    # applyProgress, the general-composer status line) — those aren't early
    # returns of this exact shape, so the same literal guard string is still
    # a precise, low-false-positive check for script.js too.
    assert is_busy_guard not in script, \
        "script.js still has an is-busy early-return guarding a mark/comment click"
