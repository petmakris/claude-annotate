"""Structural guards for the reading surface.

The surface is deliberately minimal: a collapsed general composer, a
first-run discovery hint, and the document itself. A sticky "document map"
rail used to sit beside the prose; it was removed on request (the sections
are self-describing cards and the rail cost a quarter of the viewport), and
a guard below keeps it from quietly coming back.

Source-string checks matching the repo's other smoke tests. Anything that
can only be seen by rendering the page — computed styles, box geometry,
paint order — is asserted in `tests/e2e/reading-chrome.e2e.cjs` instead;
these checks guard the exact code patterns whose absence caused a bug that
a rendered page caught and a source string did not.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"
SERVER_PY = REPO / "skills" / "annotate" / "server.py"


def _hides_when_hidden(css, selector):
    """True if `selector[hidden]` is declared display:none, whatever the spacing.

    Matched by pattern rather than by an exact literal so reformatting the
    stylesheet cannot silently retire the guard — the rule is what matters,
    not the spaces in it.
    """
    pattern = re.escape(selector) + r"\[hidden\]\s*\{[^}]*display:\s*none"
    return re.search(pattern, css) is not None


def test_the_composer_starts_closed():
    """The composer must not render expanded on load.

    The trigger row this test used to guard is gone — the composer now opens
    from #composer-toggle in the page header (see test_smoke_top_panels.py).
    What survives unchanged is the cascade trap underneath it: a bare `hidden`
    attribute does NOTHING against core.css's author rule `.general-composer {
    display: flex }`, because the UA's `[hidden] { display: none }` loses to an
    author rule of equal specificity whatever the source order. Without an
    explicit `[hidden]` rule the full textarea paints on load, which is exactly
    the bug that shipped twice.
    """
    css = STYLE_CSS.read_text()
    assert _hides_when_hidden(css, ".general-composer"), (
        "nothing makes .general-composer display:none when hidden — the "
        "composer renders expanded on load, before anyone opened it"
    )


def test_the_composer_band_sits_flush_under_the_bar():
    """Inverted on purpose, and worth saying why.

    While the composer lived below the fold it needed a top margin, or it read
    as glued to the header. It is now deliberately part of that chrome — a
    third band of the top bar — so the requirement flips: any top margin would
    open a stripe of page background between the statstrip and the band and
    break the one-object reading the bar is supposed to have.
    """
    css = STYLE_CSS.read_text()
    start = css.index(".general-composer {")
    rule = css[start:css.index("}", start)]
    m = re.search(r"margin:\s*([^;]+);", rule)
    assert m, ".general-composer no longer pins its margin — core.css's " \
               "`margin: 0 auto 8px` leaks back in and detaches the band"
    assert m.group(1).strip() == "0", (
        f".general-composer has margin {m.group(1).strip()!r} — the band must "
        "sit flush under the statstrip, with no page background between them"
    )


def test_a_first_run_hint_exists():
    src = SCRIPT_JS.read_text()
    assert "discover-hint" in src, "nothing tells a first-time reader the page is interactive"
    assert "annotate.hint." in src, "the hint's dismissal is not remembered"


def test_the_map_rail_stays_removed():
    """The document map rail was removed on explicit request (2026-08-09):
    it consumed a quarter of the viewport to restate the card titles. Its
    CSS tokens (--rail-gutter/--rail-shell-max) and the .reading-shell flex
    wrapper went with it — every centred box now derives from
    --content-max alone. If any of these names reappear, someone is
    resurrecting the rail; that needs a deliberate decision, not a merge
    accident."""
    src = SCRIPT_JS.read_text()
    css = STYLE_CSS.read_text()
    for needle in ("map-rail", "renderMapRail", "reading-shell"):
        assert needle not in src, f"script.js grew {needle!r} back"
    for needle in ("map-rail", "reading-shell", "--rail-gutter", "--rail-shell-max"):
        assert needle not in css, f"style.css grew {needle!r} back"


def test_the_reading_chrome_is_styled():
    css = STYLE_CSS.read_text()
    for needle in (".legend-pop", ".discover-hint"):
        assert needle in css, f"style.css missing {needle}"


def test_the_collapsed_composer_is_actually_hidden():
    """Regression guard (round-1 fix): core.css's base rule is
    `.general-composer { display: flex; ... }` (specificity 0,1,0). The
    bare `hidden` attribute this task relies on to collapse the composer
    has no effect against it — an author stylesheet rule beats the UA
    default `[hidden] { display: none }` at equal specificity, so the full
    textarea rendered at the same time as the collapsed trigger button.
    A rule targeting `[hidden]` explicitly (specificity 0,2,0) is required
    to actually hide it — verified in a real browser via getComputedStyle,
    which is the only way this class of bug shows up at all.

    Matched as a pattern, not as one exact literal with its exact spacing:
    the rule is the guarantee, and reformatting the stylesheet should not be
    able to retire this test without anyone noticing."""
    css = STYLE_CSS.read_text()
    assert _hides_when_hidden(css, ".general-composer"), (
        "no CSS rule forces .general-composer to display:none when hidden — "
        "the bare [hidden] attribute alone does nothing against core.css's "
        "`.general-composer { display: flex }` base rule"
    )


def test_the_sticky_ribbons_span_the_document_column():
    """With the rail gone the three sticky ribbons (.change-bar,
    .busy-banner, .watcher-dead-banner) go back to plain content-column
    geometry: width capped at --content-max, centred with auto margins.
    The old rail-gutter offset math must not linger on any of them — it
    would shove the ribbon right of centre for a rail that no longer
    exists."""
    css = STYLE_CSS.read_text()
    for selector in (".change-bar", ".busy-banner", ".watcher-dead-banner"):
        start = css.index(selector + " {")
        rule = css[start:css.index("}", start)]
        assert "max-width: var(--content-max)" in rule, (
            f"{selector} no longer caps at the content column"
        )
        assert "rail" not in rule, (
            f"{selector} still carries rail-offset geometry"
        )


def test_the_sequence_card_keeps_the_card_surface():
    """A prose-era override forced `section.block[data-kind="sequence"]` to
    background: transparent in all four hover/engaged states. On the card
    layout that read as a gray card that flashed white on hover — the only
    block on the page that did. The override is gone; sequence blocks are
    ordinary cards (constant var(--surface)), and the hover affordance
    lives on the diagram's own steps in diagram.css."""
    css = STYLE_CSS.read_text()
    assert 'section.block[data-kind="sequence"]' not in css, (
        "a sequence-specific background override is back in style.css — "
        "the card surface rules already handle hover/engaged states, and "
        "this exact override is what made sequence cards flash on hover"
    )


def test_the_discover_hint_glyphs_are_never_blank():
    """Regression guard (round-2 fix): the hint's fourth glyph (compact) read
    `window.AnnotateSubunits?.COMPACT_ICON || ""`. That export never existed
    — subunits.js defines COMPACT_ICON as a module-local const and its
    window.AnnotateSubunits export block never lists it — so the expression
    was always `undefined || ""` and rendered an empty box. Measured live:
    glyphs = ["🗑", "✓", "💬", ""]. compact is the newest, lossiest control
    the hint exists to explain, so a blank glyph there is the worst place
    for this bug to land. Guard every glyph the hint advertises, not just
    the one that broke, and forbid the dead cross-module reach outright so
    it can't quietly return under a different property name."""
    src = SCRIPT_JS.read_text()
    start = src.index("function renderDiscoverHint")
    end = src.index("\n  }\n", start)
    body = src[start:end]
    # The three fixed emoji glyphs are literal characters, never a lookup,
    # so they cannot silently go blank the way compact did.
    for glyph in ("🗑", "✓", "💬"):
        assert glyph in body, f"discover hint dropped the {glyph!r} glyph"
    # compact IS a lookup — the one glyph source that can resolve to nothing
    # — and must resolve to a value script.js owns outright (its own ICON
    # map), never a reach into another module's export.
    assert "ICON.compact" in body, (
        "the compact glyph no longer reads from script.js's own ICON map"
    )


def test_no_dead_compact_icon_export_reach_remains():
    """AnnotateSubunits.COMPACT_ICON was never exported anywhere in this
    client (subunits.js keeps it as a module-local const; its export block
    never lists it, nor a COMPACT_TITLE). Checking the exact dotted access
    pattern rather than the bare word COMPACT_ICON on purpose: a legitimate
    comment documenting this very bug (see renderDiscoverHint) is allowed to
    say the word without tripping the guard meant for the code that reads
    it — this is the same "comment vs. code" trap the round-1 fix for this
    file's discover-hint anchoring ran into, one level removed."""
    src = SCRIPT_JS.read_text()
    for prop in ("COMPACT_ICON", "COMPACT_TITLE"):
        for accessor in (f"AnnotateSubunits?.{prop}", f"AnnotateSubunits.{prop}"):
            assert accessor not in src, (
                f"a dead window.{accessor} reach exists in script.js — that "
                "export was never added to subunits.js's window.AnnotateSubunits "
                "block, so reading it always silently returns undefined"
            )


def test_the_discover_hint_compact_glyph_is_an_outline_not_a_blob():
    """Regression guard (round-3 fix): round 2 fixed the compact glyph from
    empty to a real SVG (script.js's ICON.compact), but that SVG carries no
    fill/stroke of its own — it depends entirely on CSS, the same way
    `.unit-strip button[data-kind="compact"] svg` and `.hover-actions button
    svg` do for every other rendering of this icon. With no matching rule
    for the hint, the SVG fell back to its default (fill: black, stroke:
    none) and painted a solid blob instead of the eye-off outline. Measured
    live before this fix: `.discover-hint .dh-glyphs svg` computed
    `fill: rgb(0,0,0); stroke: none`; the strip's copy computed
    `fill: none; stroke: rgb(131,134,143)` — they disagreed. Checking glyph
    presence alone (round 2's test) cannot see this: the glyph was
    non-empty and still wrong. Check the CSS treatment exists, not just
    that the markup does — the third time in this task something passed
    its test and was visibly wrong on screen."""
    css = STYLE_CSS.read_text()
    assert ".discover-hint .dh-glyphs svg" in css, (
        "no rule styles the compact icon inside the discovery hint's glyph "
        "row — it renders with the SVG default (solid black fill)"
    )
    start = css.index(".discover-hint .dh-glyphs svg")
    end = css.index("}", start)
    rule = css[start:end]
    assert "fill: none" in rule, (
        ".discover-hint .dh-glyphs svg has no fill:none — the compact "
        "glyph paints as a solid blob instead of an outline"
    )
    assert "stroke: currentColor" in rule, (
        ".discover-hint .dh-glyphs svg has no stroke — the eye-off outline "
        "needs a visible stroke to read as anything at all"
    )


def test_the_round_dock_summary_compact_glyph_is_styled():
    """Found auditing every other render site for the compact icon, as
    asked in round 3, prompted by the discover-hint blob bug: renderDock()
    (subunits.js) inserts CONTROL_SPECS' raw COMPACT_ICON svg into the
    round dock's per-kind count chips (`.rd-summary span.innerHTML =
    \\`${glyph} <b>...\\``) with no wrapping class at all. Unlike `.rd-k` —
    the round drawer's per-ROW kind chip, styled a few lines below this one
    in style.css — the summary's per-kind COUNT chip had no size and no
    fill/stroke rule whatsoever, so it rendered at the browser's default
    SVG size and painted solid black. Not the bug the coordinator
    originally reported, but the same bug class, found by checking every
    other site rather than stopping at the one that was reported."""
    css = STYLE_CSS.read_text()
    assert ".rd-summary svg" in css, (
        "no rule styles the compact icon inside the round dock's summary "
        "count chips — it renders unsized and filled solid black"
    )
    start = css.index(".rd-summary svg")
    end = css.index("}", start)
    rule = css[start:end]
    assert "fill: none" in rule and "stroke: currentColor" in rule, (
        ".rd-summary svg exists but doesn't give the compact glyph the "
        "fill:none/stroke outline treatment"
    )
