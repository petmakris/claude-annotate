"""Structural guards for the fold-all / unfold-all chords (⌘K ⌘0 / ⌘K ⌘J).

Source-string checks in the repo's smoke-test idiom; everything that needs a
rendered page (chord keystrokes, computed styles, localStorage) is asserted
in tests/e2e/fold-shortcuts.e2e.cjs.
"""
from pathlib import Path
from skills.annotate.tests.page_source import SCRIPT_JS, STYLE_CSS

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"


def test_the_fold_chord_exists_and_reuses_the_fold_machinery():
    """The whole point of the chord going through applyFolds + collapseKey
    is that fold-all state and per-heading state are ONE state: a fold-all
    survives reload and a later fold click toggles one part. A rewrite that
    folds parts by toggling classList directly would pass a bare existence
    check and silently fork the state."""
    src = SCRIPT_JS.read_text()
    assert "foldAll" in src, "no fold-all implementation in script.js"
    assert "collapseKey(section.dataset.blockId)" in src, (
        "fold-all no longer writes the fold button's own localStorage keys — "
        "fold state and button state have forked"
    )
    assert "applyFolds()" in src, (
        "fold-all no longer repaints through applyFolds"
    )


def test_the_chord_intercepts_the_browser_defaults():
    """⌘K focuses Chrome's address bar and ⌘0 resets zoom; without
    preventDefault the chord types into the omnibox instead of folding."""
    src = SCRIPT_JS.read_text()
    start = src.index("Fold-all / unfold-all chords")
    body = src[start:src.index("})();", start)]
    assert body.count("e.preventDefault()") >= 3, (
        "the chord block preventDefaults fewer than 3 times (⌘K, ⌘0, ⌘J) — "
        "a browser default is leaking through"
    )


def test_the_chord_pill_is_styled_and_actually_hides():
    """Same cascade trap test_the_collapsed_composer_is_actually_hidden
    guards: `pill.hidden = true` does nothing against an author display
    rule, so .chord-pill needs its own [hidden] { display: none }."""
    css = STYLE_CSS.read_text()
    assert ".chord-pill" in css, "style.css missing .chord-pill"
    assert ".chord-pill[hidden]" in css, (
        ".chord-pill has no [hidden] display:none rule — the pill's author "
        "display rule beats the bare hidden attribute and it never dismisses"
    )


def test_the_fold_button_is_a_plain_square_that_hangs_left_of_the_heading():
    """A 24px target with no outline: the dashed circle read as a placeholder.
    It sits in the margin, so the heading's text starts where the paragraph's
    does."""
    css = STYLE_CSS.read_text()
    start = css.index(".fold-btn {")
    rule = css[start:css.index("}", start)]
    for needle in ("width: 24px", "height: 24px", "border-radius: 6px", "border: 0"):
        assert needle in rule, f".fold-btn lost {needle!r}"
    assert "dashed" not in rule
    assert "main.prose h2.block-heading { padding-right: 0; margin-left: -28px; }" in css


def test_fold_all_is_a_visible_button_that_hides_with_no_headings():
    shell = (STATIC / "shell.js").read_text()
    assert 'id="fold-all"' in shell
    src = SCRIPT_JS.read_text()
    assert "all.hidden = !heads.length" in src, "Fold all shows on a page with no headings"
    css = STYLE_CSS.read_text()
    assert ".fold-all-btn[hidden]" in css


def test_a_search_shows_its_matches_inside_folds():
    search = (STATIC / "search.js").read_text()
    assert 'document.body.classList.toggle("searching", active)' in search
    css = STYLE_CSS.read_text()
    assert "body.searching section.block.fold-hidden" in css
    assert "body.searching section.block.collapsed .block-body" in css


def test_every_jump_unfolds_the_part_it_jumps_to():
    src = SCRIPT_JS.read_text()
    assert "function unfoldFor(" in src
    i = src.index("const go = (d) =>")
    assert "unfoldFor(changed[idx].blockId)" in src[i:i + 500], "the change bar scrolls to a folded part"
    sub = (STATIC / "subunits.js").read_text()
    i = sub.index("function jumpToMark(")
    assert "unfoldFor?.(m.block_id)" in sub[i:i + 500], "the dock scrolls to a folded part"
    assert "unfoldFor(openId)" in (STATIC / "maximize.js").read_text()
