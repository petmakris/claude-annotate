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


class TestDrift(AnchorFixture):
    def _rewrite(self, body: str):
        (self.root / "pkg" / "mod.py").write_text(body)

    def test_indentation_change_is_not_drift(self):
        self._rewrite("\n".join([
            "import os", "", "", "def alpha():", "    return 1", "", "",
            "        def beta():",   # line 8, re-indented
            "    return 2", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["actual_line"], 8)

    def test_moved_line_is_found_and_reported(self):
        self._rewrite("\n".join([
            "import os", "", "", "# a new comment", "# and another",
            "def alpha():", "    return 1", "", "",
            "def beta():",   # was 8, now 10
            "    return 2", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "moved")
        self.assertEqual(out["line"], 8)
        self.assertEqual(out["actual_line"], 10)
        self.assertIn("now at line 10", out["message"])

    def test_moved_window_moves_with_it(self):
        self._rewrite("\n".join([
            "import os", "", "", "# a new comment", "# and another",
            "def alpha():", "    return 1", "", "",
            "def beta():", "    return 2", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(end_line=9), self.root)
        roles = {l["n"]: l["role"] for l in out["lines"]}
        # authored span was 8..9; shifted by +2 it is 10..11.
        self.assertEqual(roles[10], "anchor")
        self.assertEqual(roles[11], "window")

    def test_vanished_line_is_stale_and_shows_no_code(self):
        self._rewrite("\n".join([
            "import os", "", "", "def alpha():", "    return 1", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "stale")
        self.assertNotIn("lines", out)
        self.assertIn("def beta():", out["message"])

    def test_stale_rather_than_confidently_wrong(self):
        # The killer case: line 8 still exists and holds something else.
        # Rendering it would be a lie the reader cannot detect.
        self._rewrite("\n".join([
            "import os", "", "", "def alpha():", "    return 1", "", "",
            "def gamma():", "    return 3", "",
        ]) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "stale")

    def test_nearest_match_wins_when_the_line_is_duplicated(self):
        body = ["import os", "", "", "def alpha():", "    return 1", "", ""]
        body += ["def beta():", "    return 2"]        # 8, 9
        body += ["x = 0"] * 5                          # 10..14
        body += ["def beta():", "    return 2"]        # 15, 16
        self._rewrite("\n".join(body) + "\n")
        out = anchors.resolve_anchor(self.anchor(line=14), self.root)
        # 15 is one away, 8 is six away.
        self.assertEqual(out["actual_line"], 15)


class TestNeverRaises(AnchorFixture):
    """anchors.py's docstring promises resolve_anchor never raises — a
    failure is always a status, never an exception. Task 2's reviewer
    confirmed five edge cases stay exception-free with a one-off live probe;
    this class is what keeps that guarantee from regressing silently."""

    _STATUSES = {"ok", "moved", "stale", "missing", "refused"}

    def test_empty_file(self):
        (self.root / "empty.py").write_text("")
        out = anchors.resolve_anchor(
            {"file": "empty.py", "line": 1, "snippet": "anything"}, self.root)
        self.assertIn(out["status"], self._STATUSES)

    def test_binary_content(self):
        (self.root / "binary.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
        out = anchors.resolve_anchor(
            {"file": "binary.dat", "line": 1, "snippet": "anything"}, self.root)
        self.assertIn(out["status"], self._STATUSES)

    def test_line_past_eof(self):
        out = anchors.resolve_anchor(self.anchor(line=9999), self.root)
        self.assertIn(out["status"], self._STATUSES)

    def test_permission_denied_file(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores file permissions")
        p = self.root / "locked.py"
        p.write_text("secret = 1\n")
        os.chmod(p, 0o000)
        self.addCleanup(lambda: os.chmod(p, 0o644))
        if os.access(str(p), os.R_OK):
            self.skipTest("filesystem does not enforce the permission bit")
        out = anchors.resolve_anchor(
            {"file": "locked.py", "line": 1, "snippet": "secret = 1"}, self.root)
        self.assertIn(out["status"], self._STATUSES)

    def test_root_does_not_exist(self):
        missing_root = self.root / "does" / "not" / "exist"
        out = anchors.resolve_anchor(self.anchor(), missing_root)
        self.assertIn(out["status"], self._STATUSES)

    def test_none_root_is_refused_not_a_typeerror(self):
        # dirs.get("_cwd") can legitimately be absent (Task 5's server
        # wiring). Path(None) raises TypeError, which used to escape
        # resolve_anchor uncaught -- that violates the module's own promise.
        out = anchors.resolve_anchor(self.anchor(), None)
        self.assertEqual(out["status"], "refused")

    def test_root_resolution_oserror_message_has_no_absolute_path(self):
        # Review finding 2: the resolve()/confinement except block (the
        # sibling of Fix B's read-failure branch) must not echo the raw
        # exception either. A real OSError's __str__() embeds .filename when
        # set -- exactly the leak Fix B closed three lines below -- so
        # simulate one via mock rather than relying on a symlink loop
        # actually raising on every platform/Python version in the CI matrix.
        from unittest import mock

        hidden = "/Users/someone/secret/repo/mod.py"
        err = OSError(13, "Permission denied", hidden)
        with mock.patch("skills.annotate.anchors.Path.resolve", side_effect=err):
            out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "refused")
        self.assertNotIn(hidden, out["message"])


class TestReadFailureMessage(AnchorFixture):
    def test_unreadable_file_message_has_no_absolute_path(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores file permissions")
        p = self.root / "locked.py"
        p.write_text("secret = 1\n")
        os.chmod(p, 0o000)
        self.addCleanup(lambda: os.chmod(p, 0o644))
        if os.access(str(p), os.R_OK):
            self.skipTest("filesystem does not enforce the permission bit")
        out = anchors.resolve_anchor(
            {"file": "locked.py", "line": 1, "snippet": "secret = 1"}, self.root)
        self.assertEqual(out["status"], "missing")
        self.assertIn("locked.py", out["message"])
        self.assertNotIn(str(self.root), out["message"])

    def test_strerror_less_oserror_falls_back_to_class_name_not_str(self):
        # Review finding 3: `detail = e.strerror or str(e)` re-opens the leak
        # Fix B closed, because a plain OSError.__str__() embeds .filename
        # when set. Real read failures always set strerror, so drive the
        # fallback directly via mock rather than relying on a strerror-less
        # OSError occurring naturally.
        from unittest import mock

        hidden = str(self.root / "pkg" / "mod.py")
        err = OSError()
        err.filename = hidden  # strerror left None -- the fallback path
        with mock.patch("skills.annotate.anchors._read_lines", side_effect=err):
            out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "missing")
        self.assertNotIn(hidden, out["message"])
        self.assertIn("OSError", out["message"])


if __name__ == "__main__":
    unittest.main()
