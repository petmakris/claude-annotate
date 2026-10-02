"""Structural guards for the delete control + page-lock feature.

Source-string checks matching the repo's other smoke tests; live behavior
is exercised by tests/e2e/delete-lock.e2e.cjs (manual).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STYLE_CSS = REPO / "skills" / "annotate" / "static" / "style.css"
SCRIPT_JS = REPO / "skills" / "annotate" / "static" / "script.js"
SUBUNITS_JS = REPO / "skills" / "annotate" / "static" / "subunits.js"


def test_busy_and_editing_css_present():
    css = STYLE_CSS.read_text()
    for needle in ("body.is-busy", ".busy-banner"):
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
    sel = (SCRIPT_JS.parent / "selection.js").read_text()
    assert "toggleBlockMark" in sel and "setSpanMark" in sel, \
        "selection.js does not route its marks into the round"


def test_pending_delete_is_reversible():
    """A pending delete is greyed and struck through, not removed."""
    css = STYLE_CSS.read_text()
    assert 'section.block[data-block-mark="delete"]' in css, \
        "style.css has no pending block-delete styling"
    assert "::highlight(annotate-delete)" in css, \
        "style.css has no pending span-delete styling"
    sel = (SCRIPT_JS.parent / "selection.js").read_text()
    assert 'button("remove"' in sel and "removeMarkByKey" in sel, \
        "the selection menu offers no way to take back an existing mark"


def test_busy_lock_consumed_in_script():
    src = SCRIPT_JS.read_text()
    assert "data.busy" in src, "script.js does not read data.busy from poll"
    assert "is-busy" in src, "script.js does not toggle the is-busy lock"


def test_single_editor_guard_in_script():
    src = SCRIPT_JS.read_text()
    assert "is-editing" in src, "script.js does not toggle the is-editing state"


def test_submit_is_blocked_while_a_comment_is_open():
    """Drafts and round marks live in separate stores and submitRound reads
    only the second, so submitting with an editor open silently omits the
    comment the user believes they left."""
    src = SUBUNITS_JS.read_text()
    i = src.index("btn.disabled")
    assert "is-editing" in src[i:i + 200], \
        "the dock can still submit while a comment editor is open"


def test_the_dead_session_banner_does_not_claim_the_round_was_lost():
    """The event stays queued and a fresh watcher re-emits it. Saying it was
    not processed invites the user to submit the same round twice."""
    src = SCRIPT_JS.read_text()
    assert "was not processed" not in src, \
        "the dead-session banner still claims the submission was lost"
    assert "annotate resume" in src, \
        "the banner does not name the way to pick the page back up"


def test_the_dock_repaints_the_moment_an_editor_opens():
    """Disabling Submit while `is-editing` is only half the fix.

    `renderDock()` reads that class to decide `disabled`, but it otherwise
    runs on the 1s poll — so toggling the class without repainting leaves a
    window where an editor is open and Submit is still live, which silently
    drops the comment being written. Every site that moves `is-editing` has
    to repaint the dock in the same tick."""
    src = SCRIPT_JS.read_text()
    sites = [i for i in range(len(src)) if src.startswith('classList.toggle("is-editing"', i)]
    assert sites, "script.js no longer toggles is-editing at all"
    for i in sites:
        window = src[i:i + 600]
        assert "renderDock" in window, \
            "an is-editing toggle site does not repaint the dock in the same tick"
