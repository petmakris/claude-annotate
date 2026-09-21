"""The two modules that write THROUGH their button, not to an attribute on it.

`export.js` swaps the button's text for "Preparing…" and back; `fullscreen.js`
swaps its innerHTML between two icons. Both are correct for a button whose
whole content is that one thing, and both destroy a menu row, which is an icon
AND a label. Each learns to prefer a slot, and to fall back to the button
itself when there is none — so this change is invisible to any caller that
never adds a slot.
"""
import unittest
from pathlib import Path

from .shell_source import shell_html

STATIC = Path(__file__).resolve().parents[1] / "static"
SHELL = shell_html()
EXPORT = (STATIC / "export.js").read_text()
FULLSCREEN = (STATIC / "fullscreen.js").read_text()


class TestExportWritesToItsLabel(unittest.TestCase):
    def test_it_looks_for_a_label_slot(self):
        self.assertIn('querySelector("[data-label]")', EXPORT)

    def test_it_falls_back_to_the_button(self):
        # A caller that never adds a slot must see exactly today's behaviour.
        self.assertIn('querySelector("[data-label]") || btn', EXPORT)

    def test_it_no_longer_writes_the_buttons_whole_text(self):
        self.assertNotIn('btn.textContent = "Preparing', EXPORT)
        self.assertNotIn("const label = btn.textContent", EXPORT)


class TestFullscreenWritesToItsIcon(unittest.TestCase):
    def test_it_looks_for_an_icon_slot(self):
        self.assertIn('querySelector("[data-icon]")', FULLSCREEN)

    def test_it_falls_back_to_the_button(self):
        self.assertIn('querySelector("[data-icon]") || btn', FULLSCREEN)

    def test_it_no_longer_writes_the_buttons_whole_html(self):
        self.assertNotIn("btn.innerHTML =", FULLSCREEN)

    def test_the_visible_label_follows_the_accessible_one(self):
        # The row read "Full screen" while announcing "Exit full screen". As
        # an icon-only button there was no visible label to disagree with;
        # as a row there is. Same slot-or-nothing shape as the icon above.
        self.assertIn('querySelector("[data-label]")', FULLSCREEN)
        self.assertIn('labelSlot.textContent = on ? "Exit full screen"', FULLSCREEN)
        self.assertIn('data-label>Full screen', SHELL)
