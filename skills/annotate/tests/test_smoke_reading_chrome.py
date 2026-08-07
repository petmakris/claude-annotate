"""Structural guards for the reading surface.

Three problems, one theme: the document was not the most prominent thing on
its own page. The composer held the space above the fold, nothing told a
first-time reader the page was interactive, and a long plan had no shape.

Source-string checks matching the repo's other smoke tests.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"
SERVER_PY = REPO / "skills" / "annotate" / "server.py"


def test_the_composer_starts_collapsed():
    server = SERVER_PY.read_text()
    assert "composer-collapsed" in server, \
        "the general composer still opens as a full textarea"


def test_a_first_run_hint_exists():
    src = SCRIPT_JS.read_text()
    assert "discover-hint" in src, "nothing tells a first-time reader the page is interactive"
    assert "annotate.hint." in src, "the hint's dismissal is not remembered"


def test_a_document_map_is_rendered():
    src = SCRIPT_JS.read_text()
    assert "map-rail" in src, "no document map"
    assert "map-item" in src, "the map has no section entries"


def test_the_map_shows_pending_marks():
    """The rail is the surface every other signal reuses."""
    src = SCRIPT_JS.read_text()
    assert "map-dot" in src, "the map shows no per-section state"


def test_the_reading_chrome_is_styled():
    css = STYLE_CSS.read_text()
    for needle in (".map-rail", ".map-item", ".composer-collapsed", ".discover-hint"):
        assert needle in css, f"style.css missing {needle}"


def test_the_discover_hint_lands_outside_the_shell():
    """Regression guard (round-1 fix): renderMapRail() wraps proseEl in
    .reading-shell before renderDiscoverHint() runs, so `proseEl.parentNode`
    is the shell by the time the hint inserts itself. Anchoring on proseEl
    directly makes the hint a third flex child squeezed between the rail and
    the document — measured in a real browser at 830px total shell width
    with main.prose down to ~408px instead of 1040px. The hint must anchor
    on the shell itself (or its absence) so it renders as page chrome above
    the shell, not a column inside it."""
    src = SCRIPT_JS.read_text()
    start = src.index("function renderDiscoverHint")
    end = src.index("\n  }\n", start)
    body = src[start:end]
    # The exact functional call, not just the word "reading-shell" appearing
    # anywhere in the function (a stale explanatory comment can carry the
    # word "reading-shell" long after the code it describes reverts to the
    # bug — this happened while writing this very guard).
    assert 'proseEl.closest(".reading-shell")' in body, (
        "renderDiscoverHint doesn't resolve the shell via proseEl.closest("
        '".reading-shell") — once renderMapRail has wrapped proseEl, '
        "inserting relative to proseEl directly puts the hint inside the "
        "flex shell as a third column"
    )
    assert "proseEl.parentNode?.insertBefore(hint, proseEl)" not in body, (
        "renderDiscoverHint still anchors directly on proseEl — that is "
        "the shell's own child once renderMapRail runs first"
    )


def test_the_collapsed_composer_is_actually_hidden():
    """Regression guard (round-1 fix): core.css's base rule is
    `.general-composer { display: flex; ... }` (specificity 0,1,0). The
    bare `hidden` attribute this task relies on to collapse the composer
    has no effect against it — an author stylesheet rule beats the UA
    default `[hidden] { display: none }` at equal specificity, so the full
    textarea rendered at the same time as the collapsed trigger button.
    A rule targeting `[hidden]` explicitly (specificity 0,2,0) is required
    to actually hide it — verified in a real browser via getComputedStyle,
    which is the only way this class of bug shows up at all."""
    css = STYLE_CSS.read_text()
    assert ".general-composer[hidden] { display: none; }" in css, (
        "no CSS rule forces .general-composer to display:none when hidden — "
        "the bare [hidden] attribute alone does nothing against core.css's "
        "`.general-composer { display: flex }` base rule"
    )
