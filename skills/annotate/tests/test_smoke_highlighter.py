"""The reading highlighter: drag-select prose to mark it read.

Source-presence checks only; the behaviour lives in
`tests/e2e/read-highlighter.e2e.cjs`, which is the only place a live
selection and a live paint can be observed. What these buy is speed on the
two decisions that are easy to undo by accident.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "highlighter.js").read_text()
CSS = (ROOT / "static" / "style.css").read_text()
SERVER = (ROOT / "server.py").read_text()
EXPORT = (ROOT / "static" / "export.js").read_text()


class TestItIsLoaded(unittest.TestCase):
    def test_server_ships_the_module_and_both_controls(self):
        self.assertIn("highlighter.js", SERVER)
        self.assertIn('id="highlighter-toggle"', SERVER)
        self.assertIn('id="highlighter-clear"', SERVER)

    def test_the_eraser_only_shows_while_the_highlighter_runs(self):
        self.assertIn('body[data-highlighter="on"] .hl-clear', CSS)


class TestPaintingHasNoDom(unittest.TestCase):
    def test_it_paints_through_the_highlight_registry(self):
        # Wrapper elements would be shredded by subunits.js and search.js,
        # both of which walk and rewrite the same text nodes -- and would
        # leak one reader's progress into an export. Ranges painted from
        # outside the DOM avoid all of it.
        self.assertIn("CSS.highlights.set", JS)
        self.assertIn("::highlight(annotate-read)", CSS)

    def test_every_palette_colour_has_a_paint_rule_and_a_swatch(self):
        # The five are declared in server.py and painted in style.css; a
        # colour offered in the bar with no paint rule would look like a
        # picker that silently does nothing.
        # Whitespace-tolerant: the rules are column-aligned in style.css, so an
        # exact-substring check would fail on the alignment rather than on
        # anything real.
        for name in ("yellow", "green", "orange", "blue", "pink"):
            pattern = r'body\[data-highlight-color="%s"\]\s+::highlight\(annotate-read\)' % name
            self.assertIsNotNone(re.search(pattern, CSS), "%s has no paint rule" % name)
            self.assertIn('"%s"' % name, SERVER, "%s is not offered in the palette" % name)

    def test_the_sentence_hover_wash_is_gone_but_the_strip_cue_is_not(self):
        # The pale blue band across a hovered sentence read as a second kind
        # of highlight, in the same colour family as the selection. The hover
        # cue was never the wash -- it is the control strip appearing.
        self.assertNotIn(".sub-unit:hover { background", CSS)
        self.assertIn(".sub-unit:hover .unit-strip", CSS)

    def test_the_selection_goes_neutral_while_highlighting(self):
        # Accent blue over a marker colour composites into a hue that is in no
        # palette -- measured over yellow it lands on an olive-green.
        self.assertIn('body[data-highlighter="on"] ::selection', CSS)
        i = CSS.index('body[data-highlighter="on"] ::selection')
        self.assertNotIn("0071e3", CSS[i:i + 120])
        self.assertNotIn("0, 113, 227", CSS[i:i + 120])

    def test_the_measured_marker_colour_is_the_one_in_use(self):
        # #fcd34d: body text 7.54:1 AAA, bold 11.67:1 AAA, links 6.05:1 AA,
        # and better separation from the card surface than any softer yellow
        # tried. Changing it means recomputing all four.
        i = CSS.index("::highlight(annotate-read)")
        self.assertIn("#fcd34d", CSS[i:i + 120])

    def test_no_highlights_travel_into_an_export(self):
        # Reading progress is the reader's, and an export has no JS to paint
        # it anyway.
        self.assertNotIn("annotate.read:", EXPORT)
        self.assertNotIn("annotate-read", EXPORT)


class TestOffsetsCountProseOnly(unittest.TestCase):
    def test_ui_text_inside_a_paragraph_is_skipped(self):
        # `.unit-strip` puts 🗑✓💬 INSIDE the paragraph it controls, and
        # `.unit-chip` / `.unit-composer` appear there later, after a reader
        # has already highlighted things. Counting any of them shifts every
        # offset after it -- measured: a highlight reloads onto the wrong
        # words. e2e item 7b reproduces it.
        i = JS.index("const SKIP =")
        skip = JS[i:JS.index(";", i)]
        for sel in (".unit-strip", ".unit-chip", ".unit-composer",
                    ".inline-comments", ".code-col"):
            self.assertIn(sel, skip, "%s is not skipped by the offset walker" % sel)


class TestGestureRules(unittest.TestCase):
    def test_a_control_click_is_not_a_reading_gesture(self):
        # A drag leaves its text selected on purpose, so the next click
        # arrives with a live selection over already-highlighted words.
        # Without this guard that click takes the ERASE branch and destroys
        # the highlight just made.
        i = JS.index("function onMouseUp")
        body = JS[i:i + 1400]
        self.assertIn(".page-header", body)
        self.assertIn("button", body)

    def test_the_selection_is_never_collapsed(self):
        # script.js quotes the live selection into a comment when a
        # hover-action button is clicked; clearing it here would break that
        # while looking perfectly fine.
        self.assertNotIn("removeAllRanges", JS)

    def test_marks_are_dropped_when_the_block_version_moves(self):
        # Once Claude rewrites a block, the text these offsets pointed at is
        # gone; reapplying them would paint whatever now sits there.
        self.assertIn("parsed.v", JS)


if __name__ == "__main__":
    unittest.main()
