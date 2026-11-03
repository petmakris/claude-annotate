"""The header and the toolbar under it. The ☰ menu is gone.

The menu put one click in front of everything: Comment, the highlighter,
Share, the keys and every setting. Now the header carries the title, the
status pill, Search and four icons (Fold all, the highlighter while armed,
Full screen, the toolbar button) and Done. Every command sits in the toolbar
under it, in three named groups, with the three settings read most often. The
toolbar button hides the toolbar, and the choice is the reader's.

Checked in a browser: at 1440px the toolbar fits with words and group names;
at 1024px it is icons only; at 390px it fits as eight icons, the width slider
left out; the toolbar's slider and the drawer's move together; the two
popovers open under their buttons and close each other.
"""
import re
import unittest
from pathlib import Path

from .shell_source import shell_html
from skills.annotate.tests.page_source import SCRIPT_JS, STYLE_CSS

STATIC = Path(__file__).resolve().parents[1] / "static"
SHELL = shell_html()
CSS = STYLE_CSS.read_text()
JS = SCRIPT_JS.read_text()
SETTINGS_JS = (STATIC / "script-settings.js").read_text()


def header_html():
    m = re.search(r'<header class="page-header">(.*?)</header>', SHELL, re.S)
    assert m, "the shell no longer has a page-header"
    return m.group(1)


def toolbar_html():
    m = re.search(r'<nav id="toolbar" class="toolbar"[^>]*>(.*?)</nav>', SHELL, re.S)
    assert m, "the shell no longer has the toolbar"
    return m.group(1)


def fn(name):
    body = JS[JS.index(f"function {name}()"):]
    return body[:body.index("\n})();")]


class TestTheMenuIsGone(unittest.TestCase):
    def test_no_menu_button_panel_or_panes(self):
        for gone in ('id="menu-toggle"', 'id="menu-pop"', "menu-pane", "menu-tile",
                     "data-pane-to"):
            self.assertNotIn(gone, SHELL)
        self.assertNotIn("initMenuPanes", JS)
        self.assertNotIn(".menu-tile", CSS)


class TestTheHeader(unittest.TestCase):
    def test_the_header_holds_only_what_it_is_allowed_to(self):
        # An inventory, not a count: a count passes while one control is
        # swapped for another, which is how a bar grows. The status popover's
        # own ids ride along inside the pill's wrapper.
        allowed = {"hdr-title", "hdr-respid", "status-toggle", "status-word", "status-pop",
                   "status-block", "status-title", "status-sub", "status-resume",
                   "resume-cwd", "resume-cmd", "resume-copy", "resume-status",
                   "block-search", "block-search-clear", "fold-all", "highlighter-toggle",
                   "fullscreen-toggle", "toolbar-toggle", "done-btn"}
        found = set(re.findall(r'id="([^"]+)"', header_html()))
        self.assertEqual(found - allowed, set(), "a control came into the header")

    def test_fold_all_is_an_icon_that_shows_what_a_click_does(self):
        tag = re.search(r'<button id="fold-all"[^>]*>', SHELL).group(0)
        self.assertIn('class="icon-btn fold-all-btn"', tag)
        self.assertIn('class="fold-in"', SHELL)
        self.assertIn('class="fold-out"', SHELL)
        self.assertIn('.fold-all-btn[data-next="unfold"] .fold-out { display: block; }', CSS)
        # The script must not write words into the button: that would wipe
        # its icons.
        blocks = (STATIC / "script-blocks.js").read_text()
        self.assertNotIn('all.textContent', blocks)
        self.assertIn('all.setAttribute("aria-label"', blocks)

    def test_the_status_pill_follows_the_title(self):
        h = header_html()
        self.assertLess(h.index('id="hdr-title"'), h.index('id="status-toggle"'))
        self.assertLess(h.index('id="status-toggle"'), h.index('class="header-actions"'))
        # Its popover hangs out of the title block, so the block must not clip.
        self.assertIn(".header-title { min-width: 0; }", CSS)

    def test_the_highlighter_keeps_its_indicator(self):
        # The highlighter is a MODE; its header button shows while armed,
        # even with the toolbar hidden.
        self.assertIn('id="highlighter-toggle"', header_html())
        self.assertIn('#highlighter-toggle:not([aria-pressed="true"])', CSS)


class TestTheToolbar(unittest.TestCase):
    ORDER = ["review", "view", "document"]

    def test_it_sits_right_under_the_header(self):
        self.assertTrue(SHELL.split("</header>", 1)[1].lstrip("\\").startswith('<nav id="toolbar"'))

    def test_three_named_groups_in_order(self):
        groups = re.findall(r'class="tb-group" data-group="([a-z]+)"><span class="tb-label">', toolbar_html())
        self.assertEqual(groups, self.ORDER)

    def test_every_command_is_in_it(self):
        bar = toolbar_html()
        for ident in ("composer-toggle", "toolbar-highlighter", "highlighter-clear",
                      "toolbar-view", "settings-open", "export-btn", "keys-toggle"):
            self.assertIn(f'id="{ident}"', bar, f"#{ident} is not in the toolbar")

    def test_every_button_names_itself_in_full(self):
        for tag in re.findall(r'<button [^>]*class="tb-btn"[^>]*>', toolbar_html()):
            self.assertIn("aria-label=", tag, tag)
            self.assertIn("title=", tag, tag)

    def test_comment_still_teaches_its_key(self):
        bar = toolbar_html()
        comment = bar[bar.index('id="composer-toggle"'):]
        comment = comment[:comment.index("</button>")]
        self.assertRegex(comment, r'class="tb-kbd"[^>]*>G<')

    def test_narrow_windows_get_icons_and_phones_lose_the_slider(self):
        mid = CSS[CSS.index("@media (max-width: 1179px)"):]
        mid = mid[:mid.index("\n}\n")]
        self.assertIn(".tb-word, .tb-kbd, .tb-label { display: none; }", mid)
        phone = CSS[CSS.index("@media (max-width: 599px) {\n  .toolbar"):]
        phone = phone[:phone.index("\n}\n")]
        self.assertIn(".tb-width, .tb-sep { display: none; }", phone)

    def test_a_hidden_button_really_hides(self):
        # The highlighter's button is hidden on a browser with no Highlight
        # API; an author display rule beats the UA [hidden] at equal
        # specificity.
        self.assertIn(".tb-btn[hidden] { display: none; }", CSS)


class TestTheToolbarButton(unittest.TestCase):
    def test_it_hides_the_toolbar_for_every_document(self):
        body = fn("initToolbar")
        self.assertIn('const KEY = "annotate.view:toolbar";', body)
        self.assertIn('document.body.dataset.toolbar = on ? "shown" : "hidden";', body)
        self.assertIn('body[data-toolbar="hidden"] .toolbar { display: none; }', CSS)

    def test_it_shows_until_hidden(self):
        self.assertIn('localStorage.getItem(KEY) !== "hidden"', fn("initToolbar"))
        self.assertIn('id="toolbar-toggle" type="button" class="icon-btn" aria-pressed="true"', SHELL)


class TestThePopovers(unittest.TestCase):
    def test_both_join_the_one_panel_machinery(self):
        # Esc, click-outside, one-at-a-time and aria-expanded all come from
        # initTopPanels. A second implementation of any of them is a bug.
        body = fn("initTopPanels")
        for ident in ("status-toggle", "status-pop", "keys-toggle", "keys-pop"):
            self.assertIn(f'getElementById("{ident}")', body)
        self.assertEqual(body.count("dismissOnOutsideClick: true"), 2)

    def test_the_keys_popover_holds_the_legend(self):
        pop = SHELL[SHELL.index('id="keys-pop"'):SHELL.index("</nav>")]
        self.assertIn('id="legend-pop"', pop)

    def test_neither_claims_to_be_a_dialog(self):
        self.assertNotIn('role="dialog"', SHELL)

    def test_on_a_phone_they_span_the_screen(self):
        self.assertIn(".keys-pop, .status-pop { position: fixed;", CSS)

    def test_focus_reaching_search_dismisses_the_open_one(self):
        body = fn("initTopPanels")
        self.assertIn('"focusin"', body)
        self.assertIn('"block-search"', body)


class TestTheHighlighterButtonIsAProxy(unittest.TestCase):
    """The toolbar's Highlight is not the real element, because the real one
    stays in the header as the mode's indicator. It clicks that button and
    mirrors it, so highlighter.js remains the only owner of the state."""

    def test_it_defers_to_the_header_button(self):
        body = fn("initHighlighterToolbarButton")
        self.assertIn('getElementById("toolbar-highlighter")', body)
        self.assertIn('getElementById("highlighter-toggle")', body)
        self.assertIn("btn.click()", body)
        self.assertIn("aria-pressed", body)

    def test_it_disappears_with_the_feature(self):
        self.assertIn("row.hidden = btn.hidden", fn("initHighlighterToolbarButton"))


class TestTheViewGroup(unittest.TestCase):
    def test_it_holds_theme_width_and_reading_size(self):
        body = SETTINGS_JS[SETTINGS_JS.index("function buildToolbarView(view)"):]
        body = body[:body.index("\n}\n")]
        self.assertIn('for (const key of ["pagetheme", WIDTH_KEY, "textsize"])', body)
        self.assertIn("box.dataset.setting = key;", body)

    def test_the_toolbar_and_the_drawer_paint_from_one_value(self):
        body = SETTINGS_JS[SETTINGS_JS.index("function applyViewControls()"):]
        body = body[:body.index("\n}\n")]
        self.assertIn('document.querySelectorAll(`[data-setting="${s.key}"]`)', body)


class TestCardsMountUnderTheToolbar(unittest.TestCase):
    """The "Claude worked" card, the change bar and the two banners used to
    mount right after the header, which put them between the header and the
    toolbar."""

    def test_each_one_anchors_on_the_toolbar_first(self):
        for name, count in (("progress.js", 1), ("script-changes.js", 1), ("script-poll.js", 2)):
            src = (STATIC / name).read_text()
            self.assertEqual(
                src.count('document.getElementById("toolbar") || document.querySelector(".page-header")'),
                count, name)
            self.assertNotIn('const header = document.querySelector(".page-header");', src, name)


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
