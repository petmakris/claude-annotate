"""The dark page theme.

Light is untouched by this change — not re-expressed, not ported: the light
values in core.css are the ones that shipped, and every rule that reads them
keeps reading them. Dark is one extra token block plus the handful of places
that painted a white ground OUTRIGHT rather than through a token, which is
what these tests pin.

Verified in a browser against a live daemon before being written down: the
card lifts 6.3 L* off the page (the same distance the light theme uses), the
code pane clears the card by 5.6, prose reads 10.3:1, the flowchart and
sequence diagrams fill with the card instead of white, and a highlighter mark
keeps dark ink so the words under it survive.
"""
from pathlib import Path
import re
import unittest

STATIC = Path(__file__).resolve().parents[1] / "static"
CORE = (STATIC / "core.css").read_text()
CSS = (STATIC / "style.css").read_text()
DIAGRAM = (STATIC / "diagram.css").read_text()
JS = (STATIC / "script.js").read_text()
EXPORT = (STATIC / "export.js").read_text()

DARK = ':root:has(body[data-page-theme="dark"])'
# The ::highlight rule stays keyed on <body>: it targets a DESCENDANT,
# which :root:has() cannot express.
DARK_BODY = 'body[data-page-theme="dark"]'


class TestTheDarkTokens(unittest.TestCase):
    def test_dark_redefines_the_tokens_the_page_is_built_from(self):
        i = CORE.index(DARK)
        block = CORE[i:CORE.index("\n}", i)]
        for token in ("--bg:", "--surface:", "--border:", "--text:",
                      "--text-dim:", "--accent:", "--diagram-ground:"):
            self.assertIn(token, block, f"dark does not set {token}")

    def test_light_still_declares_its_own_values(self):
        # The whole point of the shape: dark is additive. If light ever starts
        # deriving from dark, or vice versa, one of them changes when the other
        # is touched, and the light theme is the one that already shipped.
        root = CORE[CORE.index(":root {"):CORE.index(DARK)]
        self.assertIn("--bg: #e4e7ed;", root)
        self.assertIn("--surface: #f8f9fb;", root)
        self.assertIn("--diagram-ground: #ffffff;", root)

    def test_the_root_declares_a_colour_scheme_for_dark(self):
        # Without this the scrollbars, form controls and the canvas outside
        # <body> stay light, which is visible the moment the page is short.
        i = CORE.index(DARK)
        self.assertIn("color-scheme: dark;", CORE[i:CORE.index(chr(10) + '}', i)])


class TestNothingPaintsAWhiteGroundOutright(unittest.TestCase):
    def test_diagrams_fill_with_the_ground_not_with_white(self):
        # Five flowchart roles mixed their tint over a literal `white`, and the
        # actor box, step badge and key chip filled with #ffffff. On a dark
        # card every one of them punched a white hole with light text on it.
        self.assertNotIn(",white)", DIAGRAM,
                         "a diagram shape still mixes its tint over white")
        self.assertNotIn("fill: #ffffff", DIAGRAM)
        self.assertGreaterEqual(DIAGRAM.count("var(--diagram-ground)"), 12)

    def test_the_diagram_role_palette_has_a_dark_set(self):
        # The inks are saturated mid-tones chosen against white; --t-edge
        # #3a6d99 on a #212830 card is unreadable.
        i = DIAGRAM.index(DARK)
        block = DIAGRAM[i:DIAGRAM.index("\n}", i)]
        for token in ("--t-edge:", "--t-hot:", "--t-good:", "--t-edge-bg:", "--t-hot-bg:"):
            self.assertIn(token, block)

    def test_no_remaining_color_mix_over_white_anywhere(self):
        for name, text in (("style.css", CSS), ("core.css", CORE), ("diagram.css", DIAGRAM)):
            leftover = re.findall(r"color-mix\([^)]*,\s*white\)", text)
            self.assertEqual(leftover, [], f"{name} still mixes over a literal white")


class TestTheHighlighterSurvivesTheGround(unittest.TestCase):
    def test_a_mark_flips_its_ink_on_dark(self):
        # The five marker colours are pale and stay pale — they are the
        # reader's choice and what a highlighter looks like. What flips is the
        # ink: --text is #d1d7e0 on dark, and light grey over #fcd34d is
        # 1.8:1, which erases the words the mark exists to pick out.
        self.assertIn(f'{DARK_BODY} ::highlight(annotate-read) {{ color: #10141a; }}', CSS)
        # and the marker colours themselves are untouched
        for c in ("#fcd34d", "#6ee7b7", "#fdba74", "#93c5fd", "#f9a8d4"):
            self.assertIn(f"background-color: {c};", CSS)


class TestTheSetting(unittest.TestCase):
    def test_the_page_theme_is_a_global_reader_preference(self):
        i = JS.index('{ key: "pagetheme"')
        row = JS[i:JS.index("},", i)]
        self.assertIn('scope: "global"', row,
                      "a reader who works in the dark does so in every document")
        self.assertIn('def: "light"', row,
                      "the default must stay light: it is what every existing reader has")
        self.assertIn('attr: "pageTheme"', row)

    def test_an_export_carries_the_theme(self):
        # An export has no JS to re-derive a preference and no control to
        # change one, so anything not baked onto <body> is silently lost.
        i = EXPORT.index("const view = [")
        self.assertIn('"pageTheme"', EXPORT[i:i + 200],
                      "an exported document opens light however it was read")


if __name__ == "__main__":
    unittest.main()
