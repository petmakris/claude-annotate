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

    def test_no_code_slot_exists(self):
        self.assertIn(".no-code-slot", CSS)

    def test_read_only_does_not_hide_the_panes(self):
        # Spec decision 3: the shared link serves panes too. A shared page
        # that dropped them would be the detached document this feature
        # exists to eliminate. body.read-only hides controls by CSS, so the
        # pane must not be swept up with them.
        for line in CSS.splitlines():
            if "body.read-only" in line:
                self.assertNotIn(".code-col", line)
                self.assertNotIn(".codepane", line)
