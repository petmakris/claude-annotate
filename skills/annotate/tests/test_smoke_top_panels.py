"""Structural guards for the two on-demand panels that live in the top bar.

Two controls used to sit in the reading column above the first word: a
full-width "Comment on the whole response" trigger row, and a centred
"What do the buttons do?" legend pill. Both are one-shot controls, both
were permanently on screen, and together they cost ~92px before the
document started. They now hang off two icon buttons in the page header:

  #composer-toggle  💬  opens the general composer as a band of the top bar
  #legend-toggle    ?   opens the button legend as a popover under the icon

Source-string checks in the house style. Anything that can only be seen by
rendering — computed display, box geometry, focus, whether a panel overlays
the document or shoves it down — is asserted in `tests/e2e/top-panels.e2e.cjs`
instead, because every bug this area has produced passed a source check
while being visibly wrong on screen.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT_JS = STATIC / "script.js"
STYLE_CSS = STATIC / "style.css"
# The page shell and its asset list used to be printed by server.py; they now
# live in the renderer the daemon loads — shell.js for the markup, entry.js for
# which stylesheets and scripts are pulled in and in what order. These tests
# assert against the page's source either way, so they read both.
class _PageSource:
    """The page's markup and its asset list, as a single string to assert on.

    shell.js holds the markup as a JSON-encoded JS string literal, so reading
    the file raw would hand these tests `id=\\"block-search\\"` and every
    markup assertion would fail on the escaping rather than on the thing it
    is checking. The literal is decoded back to real HTML here, and entry.js
    (which lists the stylesheets and scripts, in load order) is appended.
    """

    def __init__(self, repo):
        static = repo / "skills" / "annotate" / "static"
        self._shell = static / "shell.js"
        self._entry = static / "entry.js"

    def read_text(self, *a, **k):
        import json
        src = self._shell.read_text(*a, **k)
        m = re.search(r"export const SHELL_HTML = (\".*\");", src, re.S)
        html = json.loads(m.group(1)) if m else src
        return html + "\n" + self._entry.read_text(*a, **k)


SERVER_PY = _PageSource(REPO)


def _hides_when_hidden(css, selector):
    """True if `selector[hidden]` is declared display:none, whatever the spacing."""
    pattern = re.escape(selector) + r"\[hidden\]\s*\{[^}]*display:\s*none"
    return re.search(pattern, css) is not None


def test_both_panel_toggles_are_rendered():
    """A deletion guard, and only that.

    Whether the buttons actually land INSIDE the header — rather than in some
    other part of the shell — is geometry, and is asserted in the e2e by
    comparing their bounding boxes against the header's. A source check cannot
    see it: the header markup is assembled from _HEADER_PANEL_TOGGLES, so the
    ids never appear between the literal `<header>` and `</header>` strings no
    matter how right or wrong the placement is. An earlier draft of this test
    sliced the source that way and failed against correct code.
    """
    server = SERVER_PY.read_text()
    for ident in ("composer-toggle", "legend-toggle"):
        assert f'id="{ident}"' in server, (
            f"#{ident} is not rendered — the control it replaces was removed "
            "from the reading column, so nothing opens that panel at all"
        )


def test_the_collapsed_composer_trigger_row_is_gone():
    """The full-width trigger row is what the bubble icon replaces. Leaving it
    behind means two controls that do the same thing, and the 92px stay spent."""
    server = SERVER_PY.read_text()
    css = STYLE_CSS.read_text()
    assert "composer-collapsed" not in server, \
        "the old full-width composer trigger row is still rendered"
    assert "composer-collapsed" not in css, \
        "dead .composer-collapsed styling is still in style.css"


def test_the_legend_is_a_popover_not_a_details_in_the_reading_column():
    """The legend pill sat centred above the document. It is now a popover
    anchored to its header button; the <details> wrapper goes with it."""
    server = SERVER_PY.read_text()
    assert '<details class="legend"' not in server, \
        "the legend is still a <details> block sitting in the reading column"
    assert "legend-pop" in server, "no legend popover is rendered"


def test_the_legend_popover_hard_hides_when_hidden():
    """The exact cascade bug that bit .general-composer and .composer-collapsed,
    now one element further on. A bare `hidden` attribute does NOTHING against
    an author `display: flex/block` rule — the author rule beats the UA's
    `[hidden] { display: none }` at equal specificity, whatever the source
    order. Without a rule targeting `[hidden]` explicitly, the legend table
    paints over the document from the moment the page loads."""
    css = STYLE_CSS.read_text()
    assert _hides_when_hidden(css, ".legend-pop"), (
        "nothing makes .legend-pop display:none when hidden — the popover "
        "renders open on load, over the first block"
    )


def test_the_composer_band_spans_the_header_gutters():
    """Opening the composer must read as a third band of the top bar, not as a
    floating box in the reading column. That means the header's own gutter
    formula, not the centred `margin: 0 auto` content-column box it had while
    it lived below the fold."""
    css = STYLE_CSS.read_text()
    start = css.index(".general-composer {")
    rule = css[start:css.index("}", start)]
    # Checked against the measure the HEADER uses, not against a named
    # variable: the chrome moved off --content-max onto --chrome-max so the
    # bar stops following the reading column, and an assertion naming the old
    # variable would have failed for a change that kept the two in step. What
    # has to stay true is that they use the same one.
    header_start = css.index("body .page-header {")
    header_rule = css[header_start:css.index("}", header_start)]
    measure = "--chrome-max" if "--chrome-max" in header_rule else "--content-max"
    assert "--content-gutter" in rule and measure in rule, (
        ".general-composer uses a different measure (%s) from the header (%s) — "
        "it will not line up with the bar above it" % (rule.strip(), measure)
    )


def test_the_composer_toggle_is_hidden_for_a_read_only_reader():
    """`body.read-only` already hides .general-composer, so a visible bubble
    icon would be a button that opens nothing at all."""
    css = (STYLE_CSS.read_text()
           + (REPO / "skills" / "_shared" / "web_companion" / "static" / "core.css").read_text())
    assert re.search(r"body\.read-only[^{]*#composer-toggle", css), (
        "the composer toggle survives read-only mode, where the panel it "
        "opens is display:none — it is a button that does nothing"
    )
