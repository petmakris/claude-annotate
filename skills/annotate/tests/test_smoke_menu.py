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
    """The header MINUS the menu panel — what a reader actually sees.

    The panel is cut out by balancing its own <div>s. It used to be cut by
    jumping from the panel's opening tag straight to #done-btn, which drops
    everything between the panel's close and Done as well — and that gap is
    exactly where a new control would be written, in the one test the spec
    calls the only real defence against the bar growing back.
    """
    h = header_html()
    i = h.index('id="menu-pop"')
    start = h.rindex("<div", 0, i)
    depth = 0
    for m in re.finditer(r"<div\b|</div>", h[start:]):
        depth += 1 if m.group(0) != "</div>" else -1
        if depth == 0:
            return h[:start] + h[start + m.end():]
    raise AssertionError("the menu panel's <div> is never closed")


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
        # six is assigned with `el.id = ...` in script.js or subunits.js.
        # `highlighter-palette` is a dead lookup left over from when the
        # palette was re-homed as #palette-pop — guarded, inert, and out of
        # this plan's scope (see ledger Ruling P3).
        runtime = {"attached-pill", "busy-banner", "change-bar", "round-dock",
                   "round-submit", "watcher-dead-banner", "highlighter-palette"}
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

    def test_the_panel_does_not_claim_to_be_a_dialog(self):
        # It had role="dialog" with no aria-modal and no focus move on open —
        # a role claiming three things none of which were true. It is a
        # disclosure hung off a button that already carries aria-expanded and
        # aria-controls, which needs no role at all.
        self.assertNotIn('role="dialog"', SHELL)

    def test_pushing_a_pane_moves_the_caret(self):
        # Measured in test_browser_review.py; this is the deletion guard.
        # Without it, switching a pane left activeElement on the row it had
        # just made display:none.
        body = JS[JS.index("function initMenuPanes()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn(".menu-back", body)
        self.assertIn("focus()", body)

    def test_the_panel_is_the_agreed_width(self):
        pop = CSS[CSS.index(".menu-pop {"):]
        pop = pop[:pop.index("}")]
        # Four 72px tiles, three 4px gaps, the pane's padding and the border.
        self.assertIn("318px", pop)
        self.assertIn("overflow-y: auto", pop)

    def test_focus_reaching_search_dismisses_the_open_panel(self):
        # The `/` shortcut in search.js calls input.focus() with no click, so
        # the click-outside handler below never fires for it. Without a
        # focus-based dismissal, an open menu would only be masked by the
        # takeover's CSS and would resurface, still open, once the field
        # loses its takeover.
        body = JS[JS.index("function initTopPanels()"):]
        body = body[:body.index("\n  })();")]
        self.assertIn('"focusin"', body)
        self.assertIn('"block-search"', body)


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


def root_pane_html():
    m = re.search(r'<div class="menu-pane" data-pane-name="root">(.*?)'
                  r'<div class="menu-pane" data-pane-name="settings">', SHELL, re.S)
    assert m, "the root pane is not followed by the settings pane any more"
    return m.group(1)


class TestTheRootPaneIsTiles(unittest.TestCase):
    """The first level is a 4-column grid of icon tiles under the status
    block, not three headed lists of rows. Measured in test_browser_review.py;
    these are the deletion guards."""

    ORDER = ['id="composer-toggle"', 'id="menu-highlighter"',
             'id="highlighter-clear"', 'id="fullscreen-toggle"',
             'data-pane-to="settings"', 'id="export-btn"', 'data-pane-to="help"']

    def test_the_section_headings_are_gone(self):
        self.assertNotIn("menu-sec", SHELL)
        self.assertNotIn(".menu-sec", CSS)

    def test_the_status_block_comes_before_the_tiles(self):
        root = root_pane_html()
        self.assertLess(root.index('id="menu-status"'), root.index('class="menu-tiles"'))

    def test_seven_tiles_in_the_agreed_order(self):
        tiles = re.findall(r'<button [^>]*class="menu-tile"[^>]*>', root_pane_html())
        self.assertEqual(len(tiles), 7, tiles)
        for tag, want in zip(tiles, self.ORDER):
            self.assertIn(want, tag)

    def test_every_tile_names_itself_in_full(self):
        # The caption is one short word; the accessible name and the tooltip
        # carry the whole thing.
        for tag in re.findall(r'<button [^>]*class="menu-tile"[^>]*>', root_pane_html()):
            self.assertIn("aria-label=", tag, tag)
            self.assertIn("title=", tag, tag)

    def test_the_comment_tile_still_teaches_its_key(self):
        root = root_pane_html()
        comment = root[root.index('id="composer-toggle"'):]
        comment = comment[:comment.index("</button>")]
        self.assertRegex(comment, r'class="menu-tile-kbd"[^>]*>G<')

    def test_the_grid_is_four_columns(self):
        rule = CSS[CSS.index(".menu-tiles {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("display: grid", rule)
        self.assertIn("repeat(4,", rule)

    def test_a_hidden_tile_really_hides(self):
        # The highlighter tile is hidden on a browser with no Highlight API;
        # an author display rule beats the UA [hidden] at equal specificity.
        self.assertIn(".menu-tile[hidden] { display: none; }", CSS)

    def test_the_highlighter_tile_keeps_no_state_word(self):
        # The on/off hint was a row's; a tile says it with colour.
        self.assertNotIn("data-state", root_pane_html())
        body = JS[JS.index("function initHighlighterMenuRow()"):]
        body = body[:body.index("\n  })();")]
        self.assertNotIn('"on" : "off"', body)


class TestTheHeaderIconsAreBare(unittest.TestCase):
    def test_the_header_overrides_the_framed_icon_button(self):
        rule = CSS[CSS.index(".page-header .icon-btn {"):]
        rule = rule[:rule.index("}")]
        self.assertIn("border: 0", rule)
        self.assertIn("background: transparent", rule)
        self.assertIn("width: 28px", rule)

    def test_the_resting_field_paints_nothing(self):
        sel = ('.page-header:not([data-searching="1"]):not([data-searching="filtered"])'
               ' .search-input {')
        rule = CSS[CSS.index(sel):]
        rule = rule[:rule.index("}")]
        self.assertIn("padding: 0", rule)
        self.assertIn("border-color: transparent", rule)
        self.assertIn("background: transparent", rule)
