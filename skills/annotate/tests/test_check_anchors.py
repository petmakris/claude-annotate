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

    # --- Fix round 1: malformed `blocks` must never crash and never pass ---

    def test_blocks_non_iterable_int_is_reported_not_raised(self):
        doc = {"response_id": "r", "title": "t", "blocks": 5}
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("blocks", problems[0])

    def test_blocks_non_iterable_bool_is_reported_not_raised(self):
        doc = {"response_id": "r", "title": "t", "blocks": True}
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("blocks", problems[0])

    def test_blocks_string_is_reported_not_silently_passed(self):
        # A string is iterable (character by character) — the exact shape
        # that used to slip through silently rather than crash.
        doc = {"response_id": "r", "title": "t", "blocks": "not-a-list"}
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("blocks", problems[0])

    def test_blocks_dict_is_reported_not_silently_passed(self):
        doc = {"response_id": "r", "title": "t", "blocks": {}}
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("blocks", problems[0])

    def test_blocks_null_is_reported_not_silently_passed(self):
        doc = {"response_id": "r", "title": "t", "blocks": None}
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("blocks", problems[0])

    def test_blocks_missing_key_is_reported_not_silently_passed(self):
        doc = {"response_id": "r", "title": "t"}
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("blocks", problems[0])

    def test_blocks_empty_list_is_still_valid(self):
        # Regression guard: an empty document is valid; an unreadable one
        # is not. This must keep exiting clean.
        doc = {"response_id": "r", "title": "t", "blocks": []}
        self.assertEqual(check_anchors.check(doc, self.root), [])

    def test_non_dict_block_entry_is_reported_not_dropped(self):
        doc = {"response_id": "r", "title": "t",
               "blocks": ["not-a-block",
                          {"id": "section-1", "markdown": "hi", "code": []}]}
        problems = check_anchors.check(doc, self.root)
        self.assertEqual(len(problems), 1)
        self.assertIn("0", problems[0])


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

    def test_non_list_blocks_reported_cleanly_not_traceback(self):
        # This is the only place the old crash was reachable: check() is
        # called from inside main(), and an uncaught TypeError there would
        # dump a raw Python traceback into the author's turn.
        self.blocks.write_text(json.dumps({"blocks": 5}))
        res = self._run()
        self.assertEqual(res.returncode, 1)
        self.assertNotIn("Traceback", res.stderr)
        self.assertIn("blocks", res.stderr)

    def test_empty_blocks_list_exits_zero_through_cli(self):
        self.blocks.write_text(json.dumps({"blocks": []}))
        self.assertEqual(self._run().returncode, 0)


class TestDeriveWorkspaceRoot(unittest.TestCase):
    """I3: blocks.json's own path on disk names the workspace it belongs to
    -- <root>/.claude/annotate/<sid>/response/blocks.json -- independent of
    whatever root the caller happens to pass."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_shaped_path_derives_the_root(self):
        root = Path(self.tmp.name) / "myrepo"
        blocks = root / ".claude" / "annotate" / "sid123" / "response" / "blocks.json"
        blocks.parent.mkdir(parents=True)
        blocks.write_text("{}")
        self.assertEqual(check_anchors._derive_workspace_root(blocks), root.resolve())

    def test_unshaped_path_derives_nothing(self):
        blocks = Path(self.tmp.name) / "blocks.json"
        blocks.write_text("{}")
        self.assertIsNone(check_anchors._derive_workspace_root(blocks))

    def test_shaped_prefix_but_wrong_filename_derives_nothing(self):
        blocks = (Path(self.tmp.name) / "myrepo" / ".claude" / "annotate"
                  / "sid123" / "response" / "other.json")
        blocks.parent.mkdir(parents=True)
        blocks.write_text("{}")
        self.assertIsNone(check_anchors._derive_workspace_root(blocks))


class TestCliWorkspaceRootAgreement(unittest.TestCase):
    """I3: `/annotate resume <slug>` from a different directory used to
    validate against the wrong repo silently -- the check passed while the
    server read a different one. Now the check refuses instead of guessing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "myrepo"
        (self.root / ".claude" / "annotate" / "sid1" / "response").mkdir(parents=True)
        (self.root / "mod.py").write_text("a = 1\n")
        self.blocks = self.root / ".claude" / "annotate" / "sid1" / "response" / "blocks.json"
        self.blocks.write_text(json.dumps({"blocks": [
            {"id": "section-1", "markdown": "hi",
             "code": [{"file": "mod.py", "line": 1, "snippet": "a = 1"}]}]}))

    def _run(self, root_arg):
        return subprocess.run(
            [sys.executable, "-m", "skills.annotate.check_anchors",
             str(self.blocks), str(root_arg)],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )

    def test_agreeing_root_validates_normally(self):
        res = self._run(self.root)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_mismatched_root_fails_loudly_naming_both_paths(self):
        other = Path(self.tmp.name) / "other-repo"
        other.mkdir()
        res = self._run(other)
        self.assertEqual(res.returncode, 1)
        self.assertIn(str(self.root.resolve()), res.stderr)
        self.assertIn(str(other.resolve()), res.stderr)
        self.assertIn("does not match", res.stderr)
        # It refuses outright -- it must not also report per-anchor problems
        # as if it had picked a root and gone ahead.
        self.assertNotIn("anchor problem", res.stderr)


if __name__ == "__main__":
    unittest.main()
