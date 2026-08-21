"""Code pane themes: Daylight, Midnight, Parchment, Contrast.

Source-presence checks. The behaviour — that each theme actually repaints the
pane, and that none of them escapes onto the page's ordinary fenced code
blocks — is measured in `tests/e2e/view-controls.e2e.cjs`.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "style.css").read_text()
SCRIPT = (ROOT / "static" / "script.js").read_text()
SERVER = (ROOT / "server.py").read_text()
EXPORT = (ROOT / "static" / "export.js").read_text()

THEMES = ("daylight", "midnight", "parchment", "contrast")
# Every colour the pane paints comes from one of these. A pane rule that
# hardcodes a hex instead is a rule the theme picker silently cannot reach.
CP_VARS = (
    "--cp-ground", "--cp-chrome", "--cp-divider", "--cp-anchor-bg", "--cp-accent",
    "--cp-text", "--cp-dim", "--cp-muted", "--cp-punct", "--cp-number",
    "--cp-keyword", "--cp-string", "--cp-comment", "--cp-moved-fg",
    "--cp-moved-bg", "--cp-bad-fg", "--cp-bad-bg",
)


class TestThemesAreComplete(unittest.TestCase):
    def test_every_theme_redeclares_every_variable(self):
        # A theme that forgets one inherits Daylight's value for it — which on
        # Midnight means, say, a near-black comment on a near-black ground.
        # Silent, and only visible on the one token that was missed.
        for name in THEMES[1:]:                      # daylight IS the defaults
            block = re.search(
                r'body\[data-pane-theme="%s"\] \.codepane \{(.*?)\}' % name, CSS, re.S)
            self.assertIsNotNone(block, "theme %s has no rule block" % name)
            for var in CP_VARS:
                self.assertIn(var, block.group(1),
                              "theme %s does not set %s — it will inherit "
                              "Daylight's value for that one colour" % (name, var))

    def test_daylight_defaults_live_on_the_pane_itself(self):
        block = re.search(r'\.codepane \{(.*?)\}', CSS, re.S)
        self.assertIsNotNone(block)
        for var in CP_VARS:
            self.assertIn(var, block.group(1),
                          "%s has no default on .codepane" % var)


class TestThemesStayScoped(unittest.TestCase):
    def test_no_theme_rule_escapes_the_codepane(self):
        # code-theme.css paints ordinary fenced blocks across the whole page.
        # A theme selector that does not end inside `.codepane` recolours them
        # too — and Midnight would look perfectly correct while doing it.
        for name in THEMES:
            for m in re.finditer(r'body\[data-pane-theme="%s"\][^{]*\{' % name, CSS):
                selector = m.group(0)
                self.assertIn(".codepane", selector,
                              "theme rule escapes the pane: %s" % selector.strip())


class TestPickerIsWired(unittest.TestCase):
    def test_server_offers_every_theme(self):
        for name in THEMES:
            self.assertIn('"%s"' % name, SERVER, "%s is not offered" % name)
        self.assertIn('id="panetheme-toggle"', SERVER)
        self.assertIn('id="panetheme-pop"', SERVER)

    def test_script_knows_the_same_four(self):
        block = re.search(r"const PANE_THEMES = \[(.*?)\]", SCRIPT, re.S)
        self.assertIsNotNone(block)
        for name in THEMES:
            self.assertIn(name, block.group(1))

    def test_the_theme_travels_into_an_export(self):
        # An export has no picker and no JS; the palette it was written in has
        # to be baked onto <body> like the width and layout are.
        self.assertIn("paneTheme", EXPORT)
        self.assertIn("data-pane-theme", EXPORT)


if __name__ == "__main__":
    unittest.main()
