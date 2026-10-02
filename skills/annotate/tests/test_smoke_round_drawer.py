"""Structural guards for the round review drawer.

`Submit round (12)` was the entire record of twelve irreversible decisions
made across six screens. The drawer's job is that the user can see and edit
the batch before it is sent, so the guards are: a manifest exists, a single
mark can be removed from it, and it says nothing has reached Claude yet.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SUBUNITS_JS = STATIC / "subunits.js"
STYLE_CSS = STATIC / "style.css"


def test_the_dock_renders_a_manifest():
    src = SUBUNITS_JS.read_text()
    assert "rd-list" in src, "the drawer renders no mark list"
    assert "rd-row" in src, "the drawer renders no per-mark row"


def test_a_single_mark_can_be_removed():
    src = SUBUNITS_JS.read_text()
    assert "rd-x" in src, "no per-mark remove control"


def test_a_row_can_be_jumped_to():
    src = SUBUNITS_JS.read_text()
    assert "scrollIntoView" in src, "drawer rows do not scroll to their mark"


def test_the_drawer_says_nothing_has_been_sent():
    """The sentence that makes the drawer safe to explore."""
    src = SUBUNITS_JS.read_text()
    assert "undoable until you submit" in src, \
        "the drawer does not tell the user the batch is still local"


def test_the_drawer_is_styled():
    css = STYLE_CSS.read_text()
    for needle in ("#round-dock", ".rd-head", ".rd-list", ".rd-row", ".rd-x"):
        assert needle in css, f"style.css missing {needle}"


def test_removing_a_block_mark_repaints_its_own_card():
    """repaintBlocks() only revisits marks that still exist in `marks`, so a
    mark just deleted from it is invisible to that sweep — the block it
    belonged to would never have its `data-block-mark` attribute cleared and
    the card would stay struck-through/dimmed after the drawer removed it.
    removeMark must therefore repaint the removed mark's own block directly
    (as toggleBlockMark already does) rather than relying solely on the
    repaintBlocks() sweep.
    """
    src = SUBUNITS_JS.read_text()
    start = src.index("function removeMark(key)")
    # removeMark is a small, single-level function — its matching closing
    # brace is the first "\n  }" after the opening one.
    end = src.index("\n  }", start)
    body = src[start:end]
    assert "paintBlock(" in body, \
        "removeMark does not directly repaint the removed mark's block"
    assert "repaintBlocks()" in body, \
        "removeMark should still sweep repaintBlocks() for surviving marks"


def test_a_block_scope_row_does_not_print_its_title_twice():
    """`.rd-where` already carries blockTitleFor(block_id).

    Falling back to the same call for `.rd-text` made every block-scope row
    read "§3 · The retry path" over "§3 · The retry path" — a whole line of
    the manifest spent saying nothing. The second line's job is the SCOPE.

    Behavioural guard: skills/annotate/tests/e2e/round-scope.e2e.cjs asserts
    the two lines differ on a rendered page.
    """
    src = SUBUNITS_JS.read_text()
    start = src.index("text.textContent =")
    stmt = src[start:src.index(";", start)]
    assert "blockTitleFor(" not in stmt, \
        "the rd-text fallback still echoes the row's own rd-where line"
    assert "whole section" in stmt, \
        "a block-scope row does not say that it covers the whole section"


def test_the_disabled_dock_says_why_on_the_button():
    """Browsers suppress mouse events on a disabled button, so a `title` set
    in the is-editing branch can never be shown. The label is the only
    surface the user can actually read — without it Submit greys out and
    nothing anywhere on the page explains it.

    Behavioural guard: round-scope.e2e.cjs reads the rendered button.
    """
    src = SUBUNITS_JS.read_text()
    start = src.index('if (!pendingRound && document.body.classList.contains("is-editing"))')
    body = src[start:src.index("\n    }", start)]
    assert "btn.textContent" in body, \
        "the is-editing branch sets only a tooltip a disabled button cannot show"
