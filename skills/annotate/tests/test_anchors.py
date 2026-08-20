import unittest

from skills.annotate import anchors


def _ok(**over):
    a = {"file": "skills/annotate/server.py", "line": 801,
         "snippet": "def _render_block_for_raw(blk: dict, version: int) -> dict:"}
    a.update(over)
    return a


class TestAnchorProblem(unittest.TestCase):
    def test_valid_anchor_has_no_problem(self):
        self.assertIsNone(anchors.anchor_problem(_ok()))

    def test_valid_anchor_with_optionals(self):
        self.assertIsNone(anchors.anchor_problem(_ok(end_line=812, note="the dispatch point")))

    def test_not_a_dict(self):
        self.assertIn("object", anchors.anchor_problem("nope"))

    def test_missing_file(self):
        a = _ok()
        del a["file"]
        self.assertIn("file", anchors.anchor_problem(a))

    def test_absolute_file_is_refused(self):
        self.assertIn("relative", anchors.anchor_problem(_ok(file="/etc/passwd")))

    def test_line_must_be_positive_int(self):
        self.assertIn("line", anchors.anchor_problem(_ok(line=0)))
        self.assertIn("line", anchors.anchor_problem(_ok(line="801")))

    def test_bool_is_not_a_line_number(self):
        # bool is an int subclass; True must not sail through as line 1.
        self.assertIn("line", anchors.anchor_problem(_ok(line=True)))

    def test_end_line_must_not_precede_line(self):
        self.assertIn("end_line", anchors.anchor_problem(_ok(end_line=800)))

    def test_end_line_equal_to_line_is_fine(self):
        self.assertIsNone(anchors.anchor_problem(_ok(end_line=801)))

    def test_snippet_must_be_non_empty(self):
        self.assertIn("snippet", anchors.anchor_problem(_ok(snippet="   ")))


class TestBlockProblems(unittest.TestCase):
    def test_no_code_field_is_valid(self):
        self.assertEqual(anchors.block_problems({"id": "section-1"}), [])

    def test_empty_list_is_valid(self):
        self.assertEqual(anchors.block_problems({"id": "section-1", "code": []}), [])

    def test_code_must_be_a_list(self):
        problems = anchors.block_problems({"id": "section-1", "code": {}})
        self.assertEqual(len(problems), 1)
        self.assertIn("list", problems[0])

    def test_fourth_anchor_is_a_failure_not_a_silent_drop(self):
        blk = {"id": "section-1", "code": [_ok(), _ok(), _ok(), _ok()]}
        problems = anchors.block_problems(blk)
        self.assertTrue(any("at most 3" in p for p in problems))

    def test_mockup_takes_no_anchors(self):
        blk = {"id": "section-1", "kind": "mockup", "code": [_ok()]}
        problems = anchors.block_problems(blk)
        self.assertTrue(any("mockup" in p for p in problems))

    def test_problem_is_indexed(self):
        blk = {"id": "section-1", "code": [_ok(), _ok(line=0)]}
        problems = anchors.block_problems(blk)
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("code[1]: "))



import os
import tempfile
from pathlib import Path


class AnchorFixture(unittest.TestCase):
    """A throwaway repo with one known file, so line numbers are ours."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "pkg").mkdir()
        (self.root / "pkg" / "mod.py").write_text(
            "\n".join([
                "import os",            # 1
                "",                     # 2
                "",                     # 3
                "def alpha():",         # 4
                "    return 1",         # 5
                "",                     # 6
                "",                     # 7
                "def beta():",          # 8
                "    return 2",         # 9
                "",                     # 10
            ]) + "\n"
        )
        self.addCleanup(self.tmp.cleanup)

    def anchor(self, **over):
        a = {"file": "pkg/mod.py", "line": 8, "snippet": "def beta():"}
        a.update(over)
        return a


class TestResolveConfinement(AnchorFixture):
    def test_escaping_the_root_is_refused(self):
        out = anchors.resolve_anchor(self.anchor(file="../outside.py"), self.root)
        self.assertEqual(out["status"], "refused")
        self.assertIn("outside the workspace", out["message"])
        self.assertNotIn("lines", out)

    def test_symlink_escaping_the_root_is_refused(self):
        outside = Path(self.tmp.name).parent / "escape-target.py"
        outside.write_text("SECRET\n")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        os.symlink(outside, self.root / "link.py")
        out = anchors.resolve_anchor(
            self.anchor(file="link.py", line=1, snippet="SECRET"), self.root)
        self.assertEqual(out["status"], "refused")

    def test_missing_file(self):
        out = anchors.resolve_anchor(self.anchor(file="pkg/gone.py"), self.root)
        self.assertEqual(out["status"], "missing")
        self.assertIn("pkg/gone.py", out["message"])


class TestResolveWindow(AnchorFixture):
    def test_single_line_anchor_carries_context_either_side(self):
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["actual_line"], 8)
        self.assertEqual([l["n"] for l in out["lines"]], [6, 7, 8, 9, 10])

    def test_the_anchor_line_is_marked(self):
        out = anchors.resolve_anchor(self.anchor(), self.root)
        roles = {l["n"]: l["role"] for l in out["lines"]}
        self.assertEqual(roles[8], "anchor")
        self.assertEqual(roles[6], "context")
        self.assertEqual(roles[10], "context")

    def test_end_line_widens_the_window(self):
        out = anchors.resolve_anchor(self.anchor(end_line=9), self.root)
        roles = {l["n"]: l["role"] for l in out["lines"]}
        self.assertEqual(roles[9], "window")

    def test_context_clamps_at_the_start_of_file(self):
        out = anchors.resolve_anchor(
            self.anchor(line=1, snippet="import os"), self.root)
        self.assertEqual(out["lines"][0]["n"], 1)

    def test_text_is_verbatim(self):
        out = anchors.resolve_anchor(self.anchor(line=9, snippet="return 2"), self.root)
        got = {l["n"]: l["text"] for l in out["lines"]}
        self.assertEqual(got[9], "    return 2")

    def test_note_is_passed_through(self):
        out = anchors.resolve_anchor(self.anchor(note="the second one"), self.root)
        self.assertEqual(out["note"], "the second one")

    def test_oversized_window_is_truncated_with_a_count(self):
        big = self.root / "big.py"
        big.write_text("\n".join("x = %d" % i for i in range(1, 101)) + "\n")
        out = anchors.resolve_anchor(
            {"file": "big.py", "line": 1, "end_line": 100, "snippet": "x = 1"},
            self.root)
        self.assertEqual(out["status"], "ok")
        window = [l for l in out["lines"] if l["role"] in ("anchor", "window")]
        self.assertEqual(len(window), anchors.MAX_WINDOW)
        self.assertEqual(out["truncated"], 100 - anchors.MAX_WINDOW)

if __name__ == "__main__":
    unittest.main()
