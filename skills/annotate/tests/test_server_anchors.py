import tempfile
import unittest
from pathlib import Path

from skills.annotate import server


class TestRenderBlockAnchors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text("a = 1\nb = 2\nc = 3\n")
        self.addCleanup(self.tmp.cleanup)

    def test_block_without_anchors_has_no_code_key(self):
        out = server._render_block_for_raw(
            {"id": "section-1", "markdown": "hi"}, 1, self.root)
        self.assertNotIn("code", out)

    def test_resolved_anchor_carries_the_real_lines(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "mod.py", "line": 2, "snippet": "b = 2"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(len(out["code"]), 1)
        pane = out["code"][0]
        self.assertEqual(pane["status"], "ok")
        texts = [l["text"] for l in pane["lines"]]
        self.assertIn("b = 2", texts)

    def test_a_bad_anchor_is_a_status_not_an_exception(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "../escape.py", "line": 1, "snippet": "x"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(out["code"][0]["status"], "refused")
        # The block itself still rendered.
        self.assertEqual(out["markdown"], "hi")

    def test_anchors_on_a_flowchart_block_still_resolve(self):
        blk = {"id": "section-1", "kind": "flowchart",
               "spec": {"nodes": [], "edges": []},
               "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}
        out = server._render_block_for_raw(blk, 1, self.root)
        self.assertEqual(out["code"][0]["status"], "ok")

    def test_no_repo_root_means_no_panes_rather_than_a_crash(self):
        blk = {"id": "section-1", "markdown": "hi",
               "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}
        out = server._render_block_for_raw(blk, 1, None)
        self.assertNotIn("code", out)


if __name__ == "__main__":
    unittest.main()
