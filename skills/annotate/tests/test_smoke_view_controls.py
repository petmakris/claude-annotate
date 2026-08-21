"""The two page-wide view controls: container width, and code-pane layout.

These are source-presence checks. The behaviour they stand in for is measured
in `tests/e2e/view-controls.e2e.cjs`; what earns these their place is speed —
the ordering test below catches in milliseconds a mistake that otherwise needs
a browser to see.
"""
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
CSS = (STATIC / "style.css").read_text()
SCRIPT = (STATIC / "script.js").read_text()
EXPORT = (STATIC / "export.js").read_text()
SERVER = (Path(__file__).resolve().parents[1] / "server.py").read_text()


class TestWidthRuleOrder(unittest.TestCase):
    def test_width_rules_sit_after_the_code_document_default(self):
        # `body[data-has-code="1"]` and `body[data-width="normal"]` are BOTH
        # specificity (0,1,1). Nothing but source order decides which one
        # paints, so an explicit "Normal" only beats the code-document default
        # while these rules come later in the file. Reorder them and choosing
        # Normal silently stops working on every document that cites code --
        # measured: all three settings collapse to 1180px.
        default = CSS.index('body[data-has-code="1"] { --content-max: 1180px; }')
        for value in ("normal", "wide", "extra"):
            rule = 'body[data-width="%s"]' % value
            self.assertIn(rule, CSS, "%s rule missing" % rule)
            self.assertGreater(
                CSS.index(rule), default,
                "%s is declared ABOVE body[data-has-code=\"1\"]; at equal "
                "specificity the later rule wins, so this one never applies "
                "on a document that cites code" % rule)

    def test_all_three_widths_are_distinct(self):
        values = []
        for value in ("normal", "wide", "extra"):
            i = CSS.index('body[data-width="%s"]' % value)
            values.append(CSS[i:CSS.index("}", i)])
        self.assertEqual(len(set(values)), 3,
                         "two width settings resolve to the same measure: %r" % values)


class TestCodeLayoutOverride(unittest.TestCase):
    def test_wide_mode_overrides_rather_than_rewrites(self):
        # Leaving wide mode must give the reader back exactly the promotions
        # they made by hand, which only holds while the global mode is a body
        # attribute the CSS overrides with -- never a write to per-block state.
        self.assertIn('body[data-code-layout="wide"]', CSS)
        self.assertNotIn("dataset.codeWide", SCRIPT.split("function wireViewControls")[-1]
                         .split("function highlightCodeLine")[0])

    def test_wide_mode_keeps_the_collapse_guard(self):
        # Same trap as the split rule: a card-body rule that forgets
        # :not(.collapsed) lets a folded card keep laying itself out.
        rule = 'body[data-code-layout="wide"] section.block.card[data-has-code="1"]'
        i = CSS.index(rule)
        self.assertIn(":not(.collapsed)", CSS[i:i + 200])

    def test_wide_mode_hides_the_per_pane_promote(self):
        self.assertIn('body[data-code-layout="wide"] .cp-widen', CSS)

    def test_layout_toggle_is_hidden_without_panes(self):
        self.assertIn('body:not([data-has-code="1"]) #codelayout-toggle', CSS)


class TestControlsAreRendered(unittest.TestCase):
    def test_server_renders_both_controls(self):
        self.assertIn('id="width-toggle"', SERVER)
        self.assertIn('id="codelayout-toggle"', SERVER)

    def test_layout_toggle_carries_aria_pressed(self):
        # The glyph swap is CSS; aria-pressed is the same fact for anything
        # not looking at pixels.
        self.assertIn('aria-pressed', SERVER)
        self.assertIn('aria-pressed', SCRIPT)


class TestPreferencesTravel(unittest.TestCase):
    def test_preferences_are_persisted_per_response(self):
        self.assertIn("annotate.view:", SCRIPT)

    def test_export_carries_both_preferences(self):
        # An export has no JS to re-derive these and no control to change
        # them, so the author's layout has to be baked onto <body>.
        self.assertIn("data-code-layout", EXPORT)
        self.assertIn("codeLayout", EXPORT)


if __name__ == "__main__":
    unittest.main()
