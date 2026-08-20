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


if __name__ == "__main__":
    unittest.main()
