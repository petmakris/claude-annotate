"""The bar is three controls and a mode indicator. Everything else is in the menu.

The bar reached twelve controls twice — see the comment above SETTINGS in
script.js, which describes the first cut, from twelve to nine. These are the
tests that make the second cut stick: an inventory of what the bar may hold,
and a check that every element the behaviour modules look up still exists
somewhere in the shell after being moved into the menu.
"""
import re
import unittest
from pathlib import Path

from .shell_source import shell_html

STATIC = Path(__file__).resolve().parents[1] / "static"
SHELL = shell_html()
CSS = (STATIC / "style.css").read_text()
CORE = (STATIC / "core.css").read_text()
JS = (STATIC / "script.js").read_text()


def header_html():
    """Just the <header>, so 'in the bar' means what it says."""
    m = re.search(r"<header class=\"page-header\">(.*?)</header>", SHELL, re.S)
    assert m, "the shell no longer has a page-header"
    return m.group(1)


def bar_html():
    """The header MINUS the menu panel — what a reader actually sees."""
    h = header_html()
    i = h.index('id="menu-pop"')
    # back up to the opening tag of the panel, forward to its end
    start = h.rindex("<div", 0, i)
    return h[:start] + h[h.index('<button id="done-btn"'):]


class TestTheBarIsThreeControls(unittest.TestCase):
    def test_the_bar_holds_only_what_it_is_allowed_to(self):
        # Deliberately an inventory, not a count: a count passes while one
        # control is swapped for another, which is exactly how a bar grows.
        allowed = {"block-search", "block-search-clear", "highlighter-toggle",
                   "menu-toggle", "done-btn", "hdr-title", "hdr-respid"}
        found = set(re.findall(r'id="([^"]+)"', bar_html()))
        self.assertEqual(found - allowed, set(),
                         "a control came back into the bar")

    def test_the_separators_are_gone(self):
        self.assertNotIn("header-sep", SHELL)

    def test_the_watching_pill_is_gone(self):
        self.assertNotIn("watcher-badge", SHELL)
        self.assertNotIn(".watcher-badge", CORE)


class TestTheHighlighterKeepsItsIndicator(unittest.TestCase):
    """The one escape. The highlighter is a MODE — it changes what dragging
    over text does — and a mode with no indicator is a bug, not a
    simplification. highlighter.js already maintains aria-pressed on it."""

    def test_the_toggle_is_still_in_the_bar(self):
        self.assertIn('id="highlighter-toggle"', bar_html())

    def test_it_is_invisible_unless_armed(self):
        self.assertIn('#highlighter-toggle:not([aria-pressed="true"])', CSS)

    def test_the_eraser_did_not_get_the_same_escape(self):
        # Clearing is a command, not a mode. It lives in the menu.
        self.assertNotIn('id="highlighter-clear"', bar_html())
        self.assertIn('id="highlighter-clear"', SHELL)


class TestTheMovedElementsSurvived(unittest.TestCase):
    """The decision this whole change rests on: the behaviour modules keep
    their elements, so moving one into the menu changes nothing they observe.
    Derived by grepping the modules rather than hand-maintained, so a new
    getElementById in any of them is covered the day it is written."""

    def test_every_id_the_modules_look_up_still_exists(self):
        wanted = set()
        for f in sorted(STATIC.glob("*.js")):
            if f.name.endswith(".min.js"):
                continue
            for m in re.finditer(r'getElementById\("([a-z0-9-]+)"\)', f.read_text()):
                wanted.add(m.group(1))
        # Elements the page BUILDS at runtime rather than shipping in the
        # shell, so they are looked up but never in shell.js. Derived by
        # running this grep against the tree, not guessed: each of the first
        # five is assigned with `el.id = ...` in script.js or subunits.js.
        # `highlighter-palette` is a dead lookup left over from when the
        # palette was re-homed as #palette-pop — guarded, inert, and out of
        # this plan's scope (see ledger Ruling P3).
        runtime = {"attached-pill", "busy-banner", "change-bar", "round-dock",
                   "watcher-dead-banner", "highlighter-palette"}
        missing = sorted(i for i in wanted - runtime
                         if f'id="{i}"' not in SHELL)
        self.assertEqual(missing, [],
                         f"the shell lost ids the page code still reaches for: {missing}")


class TestThePanesAreOnePanel(unittest.TestCase):
    def test_the_panel_declares_a_pane(self):
        self.assertIn('id="menu-pop"', SHELL)
        self.assertIn('data-pane="root"', SHELL)

    def test_settings_and_help_are_panes_of_it(self):
        self.assertIn('data-pane-to="settings"', SHELL)
        self.assertIn('data-pane-to="help"', SHELL)
        self.assertIn('data-pane-to="root"', SHELL)

    def test_the_old_toggles_are_gone(self):
        for dead in ("settings-toggle", "legend-toggle", "resume-toggle"):
            self.assertNotIn(f'id="{dead}"', SHELL, f"#{dead} should be gone")

    def test_the_menu_joins_the_existing_panel_machinery(self):
        # Esc, click-outside, one-at-a-time and aria-expanded all come from
        # initTopPanels. A second implementation of any of them is a bug.
        body = JS[JS.index("function initTopPanels()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn('getElementById("menu-pop")', body)
        self.assertIn("dismissOnOutsideClick: true", body)

    def test_the_menu_reopens_at_the_root(self):
        self.assertIn("initMenuPanes", JS)

    def test_the_panel_is_the_agreed_width(self):
        pop = CSS[CSS.index(".menu-pop {"):]
        pop = pop[:pop.index("}")]
        self.assertIn("288px", pop)
        self.assertIn("overflow-y: auto", pop)


class TestTheHighlighterRowIsAProxy(unittest.TestCase):
    """The one row in the menu that is not the real element, because the real
    element has to stay in the bar. It clicks the bar button and mirrors it,
    so highlighter.js remains the only owner of the state."""

    def test_the_row_exists_and_defers_to_the_button(self):
        self.assertIn('id="menu-highlighter"', SHELL)
        body = JS[JS.index("function initHighlighterMenuRow()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn('getElementById("highlighter-toggle")', body)
        self.assertIn("btn.click()", body)
        self.assertIn("aria-pressed", body)

    def test_it_disappears_with_the_feature(self):
        # highlighter.js hides the toggle when the browser has no Highlight
        # API. A menu row for a feature that cannot run is worse than none.
        body = JS[JS.index("function initHighlighterMenuRow()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn("row.hidden = btn.hidden", body)
