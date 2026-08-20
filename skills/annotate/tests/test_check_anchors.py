import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from skills.annotate import check_anchors

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text("a = 1\nb = 2\n")
        self.addCleanup(self.tmp.cleanup)

    def _doc(self, code):
        return {"response_id": "r", "title": "t",
                "blocks": [{"id": "section-1", "markdown": "hi", "code": code}]}

    def test_good_anchor_reports_nothing(self):
        doc = self._doc([{"file": "mod.py", "line": 1, "snippet": "a = 1"}])
        self.assertEqual(check_anchors.check(doc, self.root), [])

    def test_moved_anchor_is_not_a_failure(self):
        # Moving is handled at render time; it is information, not a defect.
        (self.root / "mod.py").write_text("# new\na = 1\nb = 2\n")
        doc = self._doc([{"file": "mod.py", "line": 1, "snippet": "a = 1"}])
        self.assertEqual(check_anchors.check(doc, self.root), [])

    def test_stale_anchor_is_reported_with_its_block(self):
        doc = self._doc([{"file": "mod.py", "line": 1, "snippet": "gone()"}])
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("section-1", problems[0])

    def test_shape_problem_is_reported(self):
        doc = self._doc([{"file": "mod.py", "line": 0, "snippet": "a = 1"}])
        problems = check_anchors.check(doc, self.root)
        self.assertTrue(any("line" in p for p in problems))

    def test_escape_is_reported(self):
        doc = self._doc([{"file": "../x.py", "line": 1, "snippet": "a"}])
        problems = check_anchors.check(doc, self.root)
        self.assertTrue(any("outside the workspace" in p for p in problems))


class TestCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "mod.py").write_text("a = 1\n")
        self.blocks = self.root / "blocks.json"
        self.addCleanup(self.tmp.cleanup)

    def _run(self):
        return subprocess.run(
            [sys.executable, "-m", "skills.annotate.check_anchors",
             str(self.blocks), str(self.root)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )

    def test_exit_zero_when_clean(self):
        self.blocks.write_text(json.dumps({"blocks": [
            {"id": "section-1", "markdown": "hi",
             "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}]}))
        self.assertEqual(self._run().returncode, 0)

    def test_exit_one_and_names_the_block(self):
        self.blocks.write_text(json.dumps({"blocks": [
            {"id": "section-1", "markdown": "hi",
             "code": [{"file": "mod.py", "line": 1, "snippet": "gone()"}]}]}))
        res = self._run()
        self.assertEqual(res.returncode, 1)
        self.assertIn("section-1", res.stderr)

    def test_missing_blocks_file_is_an_error_not_a_pass(self):
        res = self._run()
        self.assertEqual(res.returncode, 1)


if __name__ == "__main__":
    unittest.main()
