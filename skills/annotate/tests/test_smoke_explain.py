"""Source-level guards for the `explain` kind's renderer and stylesheet.

These are cheap checks for the wiring and for the two invariants that are
easy to "simplify" away later and hard to notice when they break. The visual
behaviour is measured in the browser, not here — see the note on overlays.
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
CSS = (STATIC / "style.css").read_text()
SCRIPT = (STATIC / "script.js").read_text()


class TestExplainWiring(unittest.TestCase):
    def test_the_kind_is_dispatched(self):
        self.assertIn('kind === "explain"', SCRIPT)
        self.assertIn("renderExplain(content, blk)", SCRIPT)

    def test_classes_exist_in_the_stylesheet(self):
        for sel in [".ex-row", ".ex-uline", ".ex-badge", ".ex-lbl",
                    ".ex-lad", ".ex-stem", ".ex-elbow", ".ex-notes",
                    ".ex-range", ".ex-brk"]:
            self.assertIn(sel, CSS, "%s missing from style.css" % sel)

    def test_the_kind_is_registered_python_side(self):
        blocks = (Path(__file__).resolve().parents[1] / "blocks.py").read_text()
        self.assertIn('"explain"', blocks)
        render = (Path(__file__).resolve().parents[1] / "render.py").read_text()
        self.assertIn('kind == "explain"', render)


class TestExplainInvariants(unittest.TestCase):
    def test_marks_are_overlays_and_never_wrap_the_code_text(self):
        # Wrapping a span would mean splitting highlight.js output at a
        # character offset, and an inline element inside a `white-space: pre`
        # row shifts every glyph after it — so the underline would drift off
        # the span it measures, which is the one thing this kind must never
        # do. The overlay needs .ex-row to be a positioning context.
        self.assertRegex(CSS, r"\.ex-row\s*\{[^}]*position:\s*relative")
        self.assertRegex(CSS, r"\.ex-uline\s*\{[^}]*position:\s*absolute")
        self.assertRegex(CSS, r"\.ex-badge--onspan\s*\{[^}]*position:\s*absolute")

    def test_tracking_is_zeroed_on_the_annotated_rows(self):
        # `ch` is the advance of "0" and knows nothing about letter-spacing,
        # so core.css's -0.003em on `body` makes rendered text narrower than
        # the `ch` count positioning the overlay — a drift that compounds with
        # the column index (measured: 2.3px by column 51). Every offset in
        # this kind assumes 1 character == 1ch; this rule is what makes that
        # true. Looks like dead tidy-up; is load-bearing.
        self.assertRegex(CSS, r"\.ex-row \.cp-line\s*\{[^}]*letter-spacing:\s*0")

    def test_the_stem_consumes_no_width(self):
        # Gap widths are whole `ch` counts with no pixel bookkeeping, which is
        # only true while a stem draws at its column without occupying one.
        # Drop the negative margin and every ladder row with two stems shifts
        # its elbow 2px right of the span it points at.
        m = re.search(r"\.ex-stem\s*\{([^}]*)\}", CSS)
        self.assertIsNotNone(m, ".ex-stem rule missing")
        self.assertIn("width: 1px", m.group(1))
        self.assertIn("margin-left: -1px", m.group(1))

    def test_column_offsets_carry_the_row_padding(self):
        # .cp-row pads 12px on the left; an overlay positioned at a bare
        # `Nch` would sit 12px left of its span. Both offsets must add it.
        self.assertIn("calc(12px + ${m.col}ch)", SCRIPT)
        self.assertIn("calc(12px + ${m.col + m.len}ch)", SCRIPT)

    def test_the_pane_uses_theme_variables_rather_than_fixed_colours(self):
        # The kind inherits Daylight/Midnight/Parchment/Contrast for free only
        # while every colour comes from the pane's own variables. A literal hex
        # in this section looks right in whichever theme it was written under
        # and wrong in the other three.
        section = CSS.split("=== kind: explain ===")[1].split("--- Themes ---")[0]
        # Strip comments first: the rationale above deliberately names colours.
        live = re.sub(r"/\*.*?\*/", "", section, flags=re.S)
        self.assertEqual(
            [], re.findall(r"#[0-9a-fA-F]{3,8}\b", live),
            "the explain section hardcodes a colour instead of using a --cp-* variable")


class TestTheWalk(unittest.TestCase):
    """The walk is a layer OVER the static pane, never a replacement for it."""

    def test_walk_classes_exist_in_the_stylesheet(self):
        for sel in [".ex-tray", ".ex-bar", ".ex-pin", ".ex-pip"]:
            self.assertIn(sel, CSS, "%s missing from style.css" % sel)

    def test_the_pane_opens_already_walking(self):
        # Chosen over "all labels, with a walk button": a control nobody finds
        # is a feature nobody has.
        self.assertIn('wrap.dataset.walk = "1"', SCRIPT)

    def test_walking_is_an_attribute_so_removing_it_restores_the_whole_pane(self):
        # Everything the walk hides is hidden by a rule scoped to the attribute
        # — labels, ladders and the marks that are not current. Drop the
        # attribute and the pane is exactly what it was before anyone stepped,
        # which is what the export relies on. Hiding them per element instead
        # would leave the export to undo each one.
        self.assertRegex(CSS, r"\[data-walk\][^{]*\.ex-lad[^{]*\{[^}]*display:\s*none")
        self.assertRegex(CSS, r"\[data-walk\][^{]*\.ex-uline[^{]*\{[^}]*opacity:\s*0")

    def test_the_export_takes_the_walk_apart(self):
        # `.ex-at` is the pins' container; stripping it takes the buttons with
        # it. That the exported file really carries no pin, and really shows
        # every label, is measured on a rendered clone in test_browser_explain.
        export = (STATIC / "export.js").read_text()
        for sel in ['".ex-bar"', '".ex-tray"', '".ex-at"']:
            self.assertIn(sel, export, "%s is not stripped from the export" % sel)
        self.assertIn('"data-walk"', export)

    def test_the_tray_is_measured_after_the_webfonts_land(self):
        # Reserving the tray against the fallback face comes out one line short
        # and the pane grows on the first long note, shoving the rest of the
        # page down mid-read. Measured in Chromium: 326px then 344px.
        self.assertIn("document.fonts", SCRIPT)
        self.assertIn("reserveTray", SCRIPT)

    def test_an_echo_is_underlined_but_never_numbered(self):
        # An echo has no label, so a badge on it would number an entry that is
        # not in the list beside it.
        self.assertIn("m.echo", SCRIPT)


class TestExplainLabelsAreNotModelHtml(unittest.TestCase):
    def test_the_label_subset_is_rendered_server_side(self):
        # innerHTML on a label is only safe because explain.py escaped the
        # text and then re-introduced exactly <b> and <code>. If the renderer
        # ever starts taking raw spec text here, that guarantee is gone.
        self.assertIn("el.innerHTML = html", SCRIPT)
        explain = (Path(__file__).resolve().parents[1] / "explain.py").read_text()
        self.assertIn("def label_html", explain)
        self.assertRegex(explain, r"_escape\(str\(text or \"\"\)\)")
