"""Structural guards for the fold-all / unfold-all chords (⌘K ⌘0 / ⌘K ⌘J).

Source-string checks in the repo's smoke-test idiom; everything that needs a
rendered page (chord keystrokes, computed styles, localStorage) is asserted
in tests/e2e/fold-shortcuts.e2e.cjs.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"


def test_the_fold_chord_exists_and_reuses_the_chevron_machinery():
    """The whole point of the chord going through applyCollapsed +
    collapseKey is that fold-all state and per-chevron state are ONE state:
    a fold-all survives reload and a later chevron click toggles one card.
    A rewrite that folds cards by toggling classList directly would pass a
    bare existence check and silently fork the state."""
    src = SCRIPT_JS.read_text()
    assert "foldAll" in src, "no fold-all implementation in script.js"
    assert 'section.querySelector(".card-chevron")' in src, (
        "fold-all no longer routes through each card's chevron element"
    )
    assert "collapseKey(section.dataset.blockId)" in src, (
        "fold-all no longer writes the chevron's own localStorage keys — "
        "fold state and chevron state have forked"
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
