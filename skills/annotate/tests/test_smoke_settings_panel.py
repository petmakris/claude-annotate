"""The gear, and the four controls it replaced.

The header carried twelve controls, four of which were preferences nobody
touches twice: a button that cycled the page width, a toggle for the pane
layout, a popover for the code theme, another for the highlight colour. They
are one gear now and the bar is down to nine.

One spec in script.js drives the markup, the persistence and the painting, so
a new preference is a row in SETTINGS rather than a new control in the bar.
The interesting field is `scope`: "doc" keeps a choice per response, "global"
keeps it for the reader across every document.

Source-string checks matching the repo's other smoke tests. Verified in a
browser against a live daemon: the panel opens inside the viewport, each row
paints its data-* attribute, choosing Source Serif and JetBrains changes the
computed font-family of the prose and of a code line, Large moves the prose
from 15.5px to 17.36px while the header stays at 13px, the font and size
choices survive a reload under keys with no response id in them, and the
width lands under one that has it.
"""
import json
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "script.js").read_text()


from .shell_source import shell_html

SHELL = shell_html()
CSS = (STATIC / "style.css").read_text()
CORE_CSS = (STATIC / "core.css").read_text()
HIGHLIGHTER = (STATIC / "highlighter.js").read_text()


class TestTheBarIsSmaller(unittest.TestCase):
    def test_the_four_preference_controls_are_gone_from_the_bar(self):
        for gone in ("width-toggle", "codelayout-toggle", "panetheme-toggle",
                     "highlighter-palette"):
            self.assertNotIn(gone, SHELL, f"{gone} is back in the header")

    def test_the_gear_and_its_panel_are_there(self):
        self.assertIn('id="settings-toggle"', SHELL)
        self.assertIn('id="settings-pop"', SHELL)
        self.assertIn('id="settings-groups"', SHELL)

    def test_the_panel_is_wired_into_the_one_panel_machinery(self):
        # Esc, click-outside and one-panel-at-a-time all come from initTopPanels.
        panels = JS[JS.index("function initTopPanels()"):]
        panels = panels[:panels.index("const isOpen")]
        self.assertIn('getElementById("settings-toggle")', panels)
        self.assertIn('getElementById("settings-pop")', panels)


class TestTheSettingsSpec(unittest.TestCase):
    def _spec(self):
        return JS[JS.index("const SETTINGS = ["):JS.index("// A global setting drops")]

    def test_every_setting_declares_a_scope(self):
        spec = self._spec()
        # The width row names its key through a const (WIDTH_KEY), because the
        # stop names were reused and the storage key had to move with them.
        # The pattern accepts a bare identifier for that reason: a row that
        # silently stops matching is a row this no longer guards.
        keys = re.findall(r'\{ key: "?([A-Za-z_]+)"?', spec)
        scopes = re.findall(r'scope: "(doc|global)"', spec)
        self.assertEqual(len(keys), len(scopes),
                         "a setting was added without a scope — it would be "
                         "stored per document by accident or not at all")
        self.assertEqual(keys, ["WIDTH_KEY", "codelayout", "panetheme",
                                "prosefont", "codefont", "textsize"])

    def test_reader_preferences_are_global_and_document_ones_are_not(self):
        spec = self._spec()
        rows = re.findall(r'\{ key: "?([A-Za-z_]+)"?.*?scope: "(doc|global)"',
                          spec, re.S)
        self.assertEqual(len(rows), spec.count("scope:"))
        for key, scope in rows:
            expected = "global" if key in ("prosefont", "codefont", "textsize") else "doc"
            self.assertEqual(scope, expected,
                             f"{key} changed scope: a typeface is the reader's "
                             f"and a measure is the document's")

    def test_a_global_key_carries_no_response_id(self):
        fn = JS[JS.index("function settingKey(s)"):]
        fn = fn[:fn.index("\n  }")]
        self.assertIn('`annotate.view:${s.key}`', fn)
        self.assertIn("viewKey(s.key)", fn)


class TestThePanelPaintsTheDocument(unittest.TestCase):
    def test_every_setting_has_a_stylesheet_rule_to_land_on(self):
        for attr, values in (
            ("data-width", ("normal", "wide")),
            ("data-prose-font", ("inter", "serif", "system")),
            ("data-code-font", ("jetbrains", "system")),
            ("data-text-size", ("small", "large")),
        ):
            for v in values:
                self.assertIn(f'{attr}="{v}"', CSS,
                              f"nothing in style.css responds to {attr}={v}")

    def test_the_families_are_tokens_not_repeated_stacks(self):
        # ~20 rules hardcoded the two stacks before. A family switch that had
        # to find all of them would miss some, which is a page in two fonts.
        self.assertIn("--font-prose:", CORE_CSS)
        self.assertIn("--font-code:", CORE_CSS)
        self.assertIn("font-family: var(--font-prose)", CORE_CSS)
        body = CSS.split("body[data-prose-font=", 1)[0]
        self.assertNotIn("'Monaspace Radon',", body,
                         "a rule names the code font directly again — it will "
                         "not follow the reader's choice")

    def test_reading_size_scales_the_prose_and_not_the_chrome(self):
        # Scaling <body> would grow the header and move the controls out from
        # under a pointer mid-click.
        self.assertIn("main.prose { font-size: calc(15.5px * var(--text-scale));", CSS)
        self.assertNotIn("body { font-size: calc(", CSS)

    def test_every_offered_font_has_a_face_and_a_licence(self):
        fonts = STATIC / "fonts"
        for family, woff2, licence in (
            ("Inter", "Inter-Variable.woff2", "INTER_LICENSE.txt"),
            ("Source Serif 4", "SourceSerif4-Variable.woff2", "SOURCE_SERIF_LICENSE.txt"),
            ("JetBrains Mono", "JetBrainsMono-Variable.woff2", "JETBRAINS_MONO_LICENSE.txt"),
        ):
            self.assertIn(f"font-family: '{family}'", CORE_CSS)
            self.assertTrue((fonts / woff2).is_file(), f"{woff2} is missing")
            self.assertTrue((fonts / licence).is_file(),
                            f"{family} ships without its licence file")


class TestTheHighlighterPaletteMoved(unittest.TestCase):
    def test_the_palette_element_itself_was_re_homed_not_rebuilt(self):
        # highlighter.js finds #palette-pop by id and attaches its own click
        # handlers. Rebuilding the swatches inside the panel would have left
        # those handlers on an element no longer in the document.
        self.assertIn('id="palette-pop"', SHELL)
        self.assertIn('getElementById("palette-pop")', HIGHLIGHTER)
        # Inside the panel, not merely present somewhere in the header. Located
        # by position: the panel's own markup nests spans and divs, so slicing
        # to the first closing tag stops at the section label, well short of it.
        panel_starts = SHELL.index('id="settings-pop"')
        palette_at = SHELL.index('id="palette-pop"')
        next_control = SHELL.index('id="highlighter-toggle"')
        self.assertTrue(panel_starts < palette_at < next_control,
                        "the palette is no longer inside the settings panel")

    def test_the_popover_geometry_is_undone_inside_the_panel(self):
        # .palette-pop is position:absolute as a free-floating popover.
        self.assertIn(".settings-pop .palette-pop", CSS)

    def test_the_colour_row_goes_when_the_highlighter_cannot_run(self):
        fn = JS[JS.index("function wireViewControls()"):]
        self.assertIn("set-group-highlight", fn)
        self.assertIn('getElementById("highlighter-toggle")', fn)


class TestNothingWasLeftBehind(unittest.TestCase):
    """The four removed controls took their stylesheet with them.

    Dead CSS for a control that no longer exists is worse than noise: it reads
    as live styling for something you then cannot find in the markup.
    """

    def test_the_removed_controls_have_no_rules_left(self):
        for cls in ("width-btn", "layout-btn", "icon-split", "icon-stack",
                    "hl-swatch", "swatch-dot", "panetheme-pop"):
            self.assertNotIn(f".{cls}", CSS,
                             f".{cls} styles a control that no longer exists")
            self.assertNotIn(f".{cls}", CORE_CSS, f".{cls} is dead in core.css")

    def test_the_classes_the_panel_still_builds_survived(self):
        # .pt-chip / .pt-name came from the old theme popover and script.js
        # builds the theme buttons out of them; .palette-pop is the moved
        # element itself. Deleting these with the rest would have been easy.
        for cls in (".pt-chip", ".pt-name", ".palette-pop"):
            self.assertIn(cls, CSS, f"{cls} is still used and was deleted")

    def test_a_document_without_code_still_hides_the_pane_layout_choice(self):
        # This lived on #codelayout-toggle, a button that no longer exists. The
        # rule had to MOVE to the panel's section, not be deleted with it.
        self.assertIn('body:not([data-has-code="1"]) .set-group[data-setting="codelayout"]', CSS)
        self.assertNotIn("#codelayout-toggle {", CSS)


class TestReset(unittest.TestCase):
    """One button, everything the panel shows — including the three settings
    that are the reader's rather than the document's.

    That reach is the point and the risk: fonts and reading size are stored
    without a response id, so this one click re-styles every other annotate
    document too. Nothing on screen reveals that, so the button's title says
    it in words.

    Verified in a browser: all seven rows revert, all seven localStorage keys
    are gone, the colour swatch repaints to yellow, the panel stays open so
    the change is watched rather than announced, the reading marks survive and
    so does the highlighter's on/off.
    """

    def test_the_button_is_in_the_panel_and_says_what_it_reaches(self):
        self.assertIn('id="settings-reset"', SHELL)
        panel_at = SHELL.index('id="settings-pop"')
        reset_at = SHELL.index('id="settings-reset"')
        next_control = SHELL.index('id="highlighter-toggle"')
        self.assertTrue(panel_at < reset_at < next_control,
                        "Reset is not inside the settings panel")
        self.assertIn("shared with every", SHELL,
                      "the button no longer warns that it reaches other documents")

    def test_it_clears_every_setting_the_panel_shows(self):
        fn = JS[JS.index("function resetSettings()"):]
        fn = fn[:fn.index("\n  }")]
        self.assertIn("for (const s of SETTINGS)", fn,
                      "reset enumerates settings by hand — a row added to "
                      "SETTINGS would not be reset")
        self.assertIn("removeItem(settingKey(s))", fn)
        self.assertIn('viewKey("highlightcolor")', fn,
                      "the highlight colour is a row of the panel and is not reset")

    def test_it_removes_keys_rather_than_writing_defaults_into_them(self):
        # A stored value means "somebody chose this". Writing the current
        # default into the key makes a reader who never chose indistinguishable
        # from one who chose today's default, and pins them to it if it changes.
        fn = JS[JS.index("function resetSettings()"):]
        fn = fn[:fn.index("\n  }")]
        self.assertNotIn("setItem", fn)

    def test_it_repaints_the_swatches_it_just_cleared(self):
        # body[data-highlight-color] and the swatches' pressed state are both
        # painted by highlighter.js, so clearing the key alone changes nothing.
        fn = JS[JS.index("function resetSettings()"):]
        fn = fn[:fn.index("\n  }")]
        self.assertIn("annotateHighlighter", fn)
        self.assertIn("syncControls", HIGHLIGHTER.split("window.annotateHighlighter =", 1)[1][:120],
                      "syncControls is no longer exported for reset to call")

    def test_it_leaves_the_reading_work_alone(self):
        fn = JS[JS.index("function resetSettings()"):]
        fn = fn[:fn.index("\n  }")]
        # Marks live under annotate.read: and belong to the bar's eraser; the
        # highlighter's on/off is a control in the bar, not a row in the panel.
        self.assertNotIn("annotate.read", fn)
        self.assertNotIn('viewKey("highlighter")', fn)

    def test_the_listener_is_bound_once(self):
        # wireViewControls is safe to call repeatedly; a stacked listener would
        # reset twice, which is invisible here but is how double-fire bugs start.
        fn = JS[JS.index("function wireViewControls()"):]
        self.assertIn("dataset.wired", fn)

    def test_reset_is_an_action_not_a_seventh_row(self):
        self.assertIn(".set-reset", CSS)
        self.assertNotIn('.set-row button, .set-reset', CSS)


class TestTheDefaultFontsAgree(unittest.TestCase):
    """Three files decide what an unset font renders as, and they must agree.

    - script.js's SETTINGS spec paints data-code-font on <body>;
    - core.css's :root token is what a page with no attribute falls back to;
    - export.js decides which @font-face a shared file carries.

    Two of the three agreeing is invisible: the page looks right and the
    export arrives in a different typeface, or the font is embedded and never
    used. The code font's default moved from Monaspace to JetBrains Mono,
    which is exactly the change that can leave one of them behind.
    """

    EXPORT_JS = (STATIC / "export.js").read_text()

    def _spec_default(self, key):
        spec = JS[JS.index("const SETTINGS = ["):JS.index("// A global setting drops")]
        entry = spec[spec.index(f'key: "{key}"'):]
        entry = entry[:entry.index("options:")]
        return re.search(r'def: "([a-z]+)"', entry).group(1)

    def test_the_code_font_default_is_jetbrains_everywhere(self):
        self.assertEqual(self._spec_default("codefont"), "jetbrains")
        self.assertIn('d.codeFont || "jetbrains"', self.EXPORT_JS)
        # Ends at the DECLARATION, not the first mention: the comment above
        # these tokens names --text-scale, so slicing to that cut the block
        # off before the declarations and matched an empty string.
        root = CORE_CSS[CORE_CSS.index(":root {"):CORE_CSS.index("--text-scale: 1;")]
        self.assertIn("--font-code: 'JetBrains Mono'", root)

    def test_the_prose_font_default_is_bricolage_everywhere(self):
        self.assertEqual(self._spec_default("prosefont"), "bricolage")
        self.assertIn('d.proseFont || "bricolage"', self.EXPORT_JS)
        # Ends at the DECLARATION, not the first mention: the comment above
        # these tokens names --text-scale, so slicing to that cut the block
        # off before the declarations and matched an empty string.
        root = CORE_CSS[CORE_CSS.index(":root {"):CORE_CSS.index("--text-scale: 1;")]
        self.assertIn("--font-prose: 'Bricolage Grotesque'", root)

    def test_every_non_default_family_has_a_rule_to_paint_it_back(self):
        # A family that is only the :root default needs no rule — until the
        # default moves, and then choosing it silently does nothing.
        for value in ("jetbrains", "monaspace", "system"):
            self.assertIn(f'body[data-code-font="{value}"]', CSS,
                          f"choosing {value} paints nothing")
        for value in ("inter", "serif", "system"):
            self.assertIn(f'body[data-prose-font="{value}"]', CSS,
                          f"choosing {value} paints nothing")
