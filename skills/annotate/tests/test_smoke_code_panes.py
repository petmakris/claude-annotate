import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text()


class TestCodePaneCss(unittest.TestCase):
    def test_pane_classes_exist(self):
        for sel in [".codepane", ".cp-head", ".cp-body", ".cp-row",
                    ".cp-num", ".cp-line", ".cp-status"]:
            self.assertIn(sel, CSS, "%s missing from style.css" % sel)

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
