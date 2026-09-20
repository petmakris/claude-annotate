import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text()


class TestCodePaneCss(unittest.TestCase):
    def test_pane_classes_exist(self):
        for sel in [".codepane", ".cp-head", ".cp-body", ".cp-row",
                    ".cp-line", ".cp-status", ".cp-chip"]:
            self.assertIn(sel, CSS, "%s missing from style.css" % sel)

    def test_card_prose_rules_keep_their_main_prose_prefix(self):
        # `main.prose p` sets padding-right: 140px at specificity (0,1,2) --
        # room for hover buttons that now live in the card header. A bare
        # `.card-body p` is (0,1,1) and LOSES to it, which is how the reserve
        # survived unnoticed until it was measured in a browser. The prefix is
        # what makes these rules (0,2,2) and lets them win; "simplifying" it
        # off silently restores 140px of dead gutter inside every card.
        # e2e item 13 catches it for real; this catches it in a second.
        for tag in ("p", "li", "blockquote"):
            self.assertIn("main.prose .card-body %s" % tag, CSS,
                          "the .card-body %s padding rule lost its main.prose "
                          "prefix and now loses to main.prose %s" % (tag, tag))

    def test_the_pane_paints_no_line_numbers_and_no_caption(self):
        # Both were tried, rendered, and reversed. The header line already
        # states `file:134`, and the prose beside the pane is where a gloss
        # belongs -- what is left above the code is one band.
        # Matched as RULES (a selector followed by `{` or `,`), not as bare
        # strings: the comments deliberately keep saying why these were
        # removed, and a history note is not a live rule.
        SCRIPT = (Path(__file__).resolve().parents[1] / "static" / "script.js").read_text()
        for gone in ("cp-num", "cp-note", "cp-gutter"):
            self.assertIsNone(
                re.search(r"\.%s\s*[{,]" % gone, CSS),
                "%s still has a live rule in style.css" % gone)
            self.assertNotIn(gone, SCRIPT, "%s is still rendered by script.js" % gone)

    def test_code_rows_are_inset_clear_of_the_anchor_bar(self):
        # The gutter used to provide this inset. Without it the anchored
        # row's 3px inset box-shadow would paint over the first glyph, so the
        # padding moved onto .cp-row -- where it is real geometry the e2e can
        # measure, rather than padding inside the text span.
        i = CSS.index(".cp-row { display: flex;")
        self.assertIn("padding-left", CSS[i:CSS.index("}", i)])

    def test_split_is_gated_on_the_block_having_code(self):
        # An anchorless document must render exactly as annotate does today.
        self.assertIn('[data-has-code="1"]', CSS)

    def test_wide_column_is_gated_too(self):
        # 1180px must not apply to prose-only pages.
        self.assertIn('body[data-has-code="1"]', CSS)
        self.assertIn("1180px", CSS)

    def test_anchor_row_is_distinguished_from_context(self):
        self.assertIn(".cp-row.is-anchor", CSS)
        self.assertIn(".cp-row.is-context", CSS)

    def test_read_only_does_not_hide_the_panes(self):
        # Spec decision 3: the shared link serves panes too. A shared page
        # that dropped them would be the detached document this feature
        # exists to eliminate. body.read-only hides controls by CSS, so the
        # pane must not be swept up with them.
        for line in CSS.splitlines():
            if "body.read-only" in line:
                self.assertNotIn(".code-col", line)
                self.assertNotIn(".codepane", line)


class TestCollapseGuard(unittest.TestCase):
    """Fix round 1: a rule that sets display:grid on .card-body must not
    win over section.block.card.collapsed .card-body { display: none; } —
    both selectors tie at specificity (0,4,1), so source order decides,
    and an unguarded grid rule appended later in the file would silently
    break card folding for any block that carries code anchors."""

    RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")

    def test_grid_display_rules_on_card_body_respect_collapsed(self):
        offenders = []
        for selector, body in self.RULE_RE.findall(CSS):
            if ".card-body" not in selector:
                continue
            if "display: grid" not in body and "display:grid" not in body:
                continue
            if ":not(.collapsed)" not in selector:
                offenders.append(selector.strip())
        self.assertEqual(
            offenders, [],
            "rule(s) set display:grid on .card-body without excluding "
            ".collapsed, so a collapsed code-anchored card would not fold: "
            "%r" % offenders,
        )


JS = (Path(__file__).resolve().parents[1] / "static" / "script.js").read_text()


class TestCodePaneJs(unittest.TestCase):
    def test_renderer_exists(self):
        self.assertIn("function renderCodeColumn", JS)

    def test_status_pane_shows_no_lines(self):
        # Guard the rule, not the wording: a failing pane must branch on
        # status before it ever touches `lines`.
        self.assertIn('pane.status !== "ok" && pane.status !== "moved"', JS)

    def test_promotion_is_persisted(self):
        self.assertIn("annotate.codewide:", JS)

    def test_body_flag_is_set_for_the_wide_column(self):
        self.assertIn('dataset.hasCode', JS)

    def test_export_strips_the_widen_control_but_not_the_code(self):
        exp = (Path(__file__).resolve().parents[1] / "static" / "export.js").read_text()
        self.assertIn('".cp-widen"', exp)
        self.assertNotIn('".cp-body"', exp)
        self.assertNotIn('".code-col"', exp)

    def test_export_strips_the_ide_jump_link(self):
        # I1: an exported file has no owner, and a dead jetbrains:// href
        # (it names a path that only ever existed on the author's machine)
        # would otherwise leak that path into a document meant to be shared.
        exp = (Path(__file__).resolve().parents[1] / "static" / "export.js").read_text()
        self.assertIn('".cp-jump"', exp)

    def test_update_path_repaints_panes(self):
        # A rewritten block must not keep the previous version's panes.
        self.assertIn("renderCodeColumn", JS.split("function updateBlockContent")[1])

    def test_a_rewrite_that_drops_the_last_anchor_clears_the_wide_flag_too(self):
        # A card that goes anchorless on a rewrite must not keep
        # data-code-wide from a previous version -- otherwise a later
        # rewrite that brings code back arrives already "wide" for no
        # reason anyone chose.
        body = JS.split("function updateBlockContent")[1]
        else_branch = body.split("delete section.dataset.hasCode;", 1)[1]
        else_branch = else_branch.split("}", 1)[0]
        self.assertIn("delete section.dataset.codeWide;", else_branch)

    def test_mockup_blocks_never_get_a_code_column(self):
        # I4: a mockup renders in a sandboxed iframe at width:100% -- giving
        # it a code column halves its card to ~440px. The guard must be the
        # first thing renderCodeColumn does, before it ever looks at panes.
        body = JS.split("function renderCodeColumn(blk) {", 1)[1]
        body = body.split("\n  }", 1)[0]
        guard_pos = body.find('blk.kind === "mockup"')
        panes_pos = body.find("blk.code")
        self.assertNotEqual(guard_pos, -1, "renderCodeColumn lost its mockup guard")
        self.assertLess(guard_pos, panes_pos,
                         "the mockup guard must run before panes are read")


class TestCodePaneReading(unittest.TestCase):
    """How the pane presents code: scrolled, not folded, and dark by default.

    Both decisions were measured in a browser across all nine panes of a real
    document before being written down here — these are the source-side guards
    on what that measurement settled.
    """

    def test_code_scrolls_sideways_and_never_wraps(self):
        # A folded line stops looking like the file it came from, and a
        # continuation starting at column 0 reads as a statement of its own.
        i = CSS.index(".cp-line {")
        rule = CSS[i:CSS.index("}", i)]
        self.assertIn("white-space: pre;", rule,
                      "code lines wrap again — they must scroll instead")
        self.assertNotIn("pre-wrap", rule)
        self.assertNotIn("overflow-wrap: anywhere", rule,
                         "anywhere-breaking reintroduces wrapping by the back door")

        j = CSS.index(".cp-body {")
        body_rule = CSS[j:CSS.index("}", j)]
        self.assertIn("overflow-x: auto", body_rule,
                      "the pane no longer offers a horizontal scroll")

    def test_rows_stretch_to_the_full_scrolled_width(self):
        # Measured: with the track clamped to the visible width, every row
        # ends at 582px inside a 708px scroll -- so an anchored row's band and
        # inset bar stop mid-pane as soon as you scroll. minmax(max-content,
        # 1fr) floors the track at the longest line AND still fills the column
        # when the code is shorter than it; minmax(100%, max-content) reads
        # like the same thing and measured as the broken case.
        j = CSS.index(".cp-body {")
        body_rule = CSS[j:CSS.index("}", j)]
        self.assertIn("grid-template-columns: minmax(max-content, 1fr)", body_rule,
                      "the pane's grid track changed — re-measure row widths "
                      "against scrollWidth before accepting it")

    def test_midnight_is_the_default_pane_theme(self):
        self.assertIn('const DEFAULT_PANE_THEME = "midnight"', JS,
                      "the default code theme is no longer Midnight")
        # The array is the popover's ORDER and the validity list; reading a
        # default off its first element is what tied the two together before.
        i = JS.index("function effectivePaneTheme()")
        fn = JS[i:JS.index("\n  }", i)]
        self.assertIn("DEFAULT_PANE_THEME", fn)
        self.assertNotIn("PANE_THEMES[0]", fn,
                         "the default is being read off the popover's order again")


class TestPageWidthNaming(unittest.TestCase):
    """Wide is the default column, so the narrow one is called Narrow.

    Verified in the browser across all three settings: the labels cycle
    Wide -> Extra -> Narrow, --content-max reads 1180 / 1600 / 1040, a stored
    legacy "normal" resolves to Narrow, and an unrecognised value falls back
    to Wide.
    """

    def test_the_narrow_column_is_not_called_normal(self):
        self.assertIn('const VIEW_WIDTHS = ["narrow", "wide", "extra"]', JS)
        self.assertIn('narrow: "Narrow"', JS)
        self.assertNotIn('normal: "Normal"', JS,
                         'the first stop is labelled "Normal" again, which '
                         'names the non-default column as the normal one')
        self.assertIn('body[data-width="narrow"]', CSS)
        self.assertNotIn('body[data-width="normal"]', CSS,
                         "the stylesheet still keys the narrow column on the "
                         "old name — the control renames, the column does not")

    def test_wide_stays_the_default(self):
        self.assertIn('const DEFAULT_WIDTH = "wide"', JS)

    def test_a_width_stored_before_the_rename_survives_it(self):
        # Renaming a stored value silently discards the reader's one explicit
        # choice: "normal" stops matching VIEW_WIDTHS and falls through to the
        # default, which is the WIDEST column -- the opposite of what they set.
        self.assertIn('const LEGACY_WIDTHS = { normal: "narrow" }', JS)
        i = JS.index("function effectiveWidth()")
        fn = JS[i:JS.index("\n  }", i)]
        self.assertIn("LEGACY_WIDTHS", fn,
                      "effectiveWidth no longer maps the pre-rename value")

    def test_the_width_choice_lives_in_the_settings_panel(self):
        # There is no width button in the bar any more — the three stops are
        # rows in the settings popover, built from VIEW_WIDTHS above. What this
        # used to assert (the cycling button's tooltip) no longer exists.
        shell = (Path(__file__).resolve().parents[1] / "static" / "shell.js").read_text()
        self.assertNotIn("width-toggle", shell,
                         "the width button is back in the bar")
        self.assertIn("settings-toggle", shell)
        self.assertIn('{ key: "width", attr: "width", label: "Page width"', JS,
                      "the settings panel no longer offers a width")
