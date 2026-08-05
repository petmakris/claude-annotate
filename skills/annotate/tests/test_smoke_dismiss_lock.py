"""Structural guards for the delete control + page-lock feature.

Source-string checks matching the repo's other smoke tests; live behavior
is exercised by tests/e2e/dismiss.e2e.cjs (manual).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STYLE_CSS = REPO / "skills" / "annotate" / "static" / "style.css"
SCRIPT_JS = REPO / "skills" / "annotate" / "static" / "script.js"
SUBUNITS_JS = REPO / "skills" / "annotate" / "static" / "subunits.js"


def test_busy_and_editing_css_present():
    css = STYLE_CSS.read_text()
    for needle in ("body.is-busy", "body.is-editing", ".busy-banner",
                   ".hover-actions button[data-type=\"delete\"]"):
        assert needle in css, f"style.css missing {needle!r}"


def test_delete_is_queued_not_submitted():
    """Delete must be a pending round mark, never an immediate submission.

    The whole point of the one-timing-model rework: no control may reach
    Claude without going through the round dock's Submit.
    """
    src = SCRIPT_JS.read_text()
    assert 'type: "dismiss"' not in src, \
        "script.js still submits a standalone dismiss event"
    assert "onDismiss" not in src, \
        "script.js still has the immediate-dismiss handler"
    assert "toggleBlockMark" in src, \
        "script.js does not route block controls into the round"


def test_pending_delete_is_reversible():
    """A pending delete is greyed and struck through, not removed."""
    css = STYLE_CSS.read_text()
    assert 'section.block[data-block-mark="delete"]' in css, \
        "style.css has no pending block-delete styling"
    assert '.sub-unit[data-mark="delete"]' in css, \
        "style.css has no pending sub-unit-delete styling"


def test_block_controls_live_next_to_the_card_title():
    """Block scope is taught by position: a strip hugging the title, body left
    for units.

    The strip mounts directly after the title rather than at the header's far
    right. The title is what reveals it, and a trigger 600px from the thing it
    reveals reads as nothing happening.

    (What reveals the strip is asserted in test_smoke_subunits.py — it must
    be title hover specifically, not the full-width header row.)"""
    src = SCRIPT_JS.read_text()
    assert 'titleEl.insertAdjacentElement("afterend", wrap)' in src, \
        "hover-actions strip is not mounted next to the card title"
    assert "head.appendChild(wrap)" not in src, \
        "hover-actions strip is back at the far end of the header row"
    assert 'head.querySelector(".card-title")' in src, \
        "hover listeners are not scoped to the card title"


def test_busy_lock_consumed_in_script():
    src = SCRIPT_JS.read_text()
    assert "data.busy" in src, "script.js does not read data.busy from poll"
    assert "is-busy" in src, "script.js does not toggle the is-busy lock"


def test_single_editor_guard_in_script():
    src = SCRIPT_JS.read_text()
    assert "is-editing" in src, "script.js does not toggle the is-editing state"
