import unittest

from skills.annotate import anchors


def _ok(**over):
    a = {"file": "skills/annotate/render.py", "line": 22,
         "snippet": "def render_block(blk: dict) -> dict:"}
    a.update(over)
    return a


class TestAnchorProblem(unittest.TestCase):
    def test_valid_anchor_has_no_problem(self):
        self.assertIsNone(anchors.anchor_problem(_ok()))

    def test_valid_anchor_with_optionals(self):
        self.assertIsNone(anchors.anchor_problem(_ok(end_line=33)))  # valid span after `line`

    def test_a_leftover_note_key_is_tolerated_not_refused(self):
        # `note` used to be a real field, rendered as a caption above the pane,
        # and was removed after being seen in place. Validation is a list of
        # checks rather than a reject-unknown-keys gate, so a blocks.json
        # written before the removal still passes -- it just stops rendering.
        # Refusing those would break every workspace that already has one.
        self.assertIsNone(anchors.anchor_problem(_ok(note="written before the removal")))

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
        self.assertIn("end_line", anchors.anchor_problem(_ok(end_line=21)))  # BEFORE `line`

    def test_end_line_equal_to_line_is_fine(self):
        self.assertIsNone(anchors.anchor_problem(_ok(end_line=22)))  # equal to `line`

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

    def test_note_is_not_carried_into_the_pane(self):
        # The caption it fed is gone from the UI, so carrying it would be
        # payload nobody reads -- and would keep the reference telling Claude
        # to spend tokens authoring one.
        out = anchors.resolve_anchor(self.anchor(note="the second one"), self.root)
        self.assertNotIn("note", out)

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


class TestSizeAndLineCaps(AnchorFixture):
    """I2: the /raw poll refetches every anchor's file once a second, per
    open tab, on the read-only link. Nothing bounded how big that file (or
    any one line in it) could be."""

    def test_huge_file_is_refused_rather_than_read(self):
        big = self.root / "huge.py"
        # One byte past the cap -- proves the boundary, not just "very big".
        big.write_text("x" * (anchors.MAX_BYTES + 1))
        out = anchors.resolve_anchor(
            {"file": "huge.py", "line": 1, "snippet": "x"}, self.root)
        self.assertEqual(out["status"], "missing")
        self.assertIn("too large to anchor", out["message"])
        self.assertIn("huge.py", out["message"])
        self.assertNotIn("lines", out)

    def test_file_at_exactly_the_cap_is_still_read(self):
        # The boundary is inclusive: MAX_BYTES itself must not be refused.
        at_cap = self.root / "at_cap.py"
        at_cap.write_text("x" * anchors.MAX_BYTES)
        out = anchors.resolve_anchor(
            {"file": "at_cap.py", "line": 1, "snippet": "x" * anchors.MAX_BYTES},
            self.root)
        self.assertEqual(out["status"], "ok")

    def test_oversized_line_is_truncated_with_a_visible_marker(self):
        wide = self.root / "wide.py"
        long_line = "x" * (anchors.MAX_LINE_CHARS + 500)
        wide.write_text(long_line + "\n")
        out = anchors.resolve_anchor(
            {"file": "wide.py", "line": 1, "snippet": long_line}, self.root)
        self.assertEqual(out["status"], "ok")
        text = out["lines"][0]["text"]
        self.assertLess(len(text), len(long_line))
        self.assertIn("truncated", text)
        self.assertTrue(text.startswith("x" * 100))

    def test_short_line_is_not_touched_by_the_cap(self):
        out = anchors.resolve_anchor(self.anchor(), self.root)
        text = next(l["text"] for l in out["lines"] if l["n"] == 8)
        self.assertEqual(text, "def beta():")

    def test_drift_search_does_not_look_past_the_radius(self):
        # A match that exists but sits outside DRIFT_RADIUS must not be
        # found -- proves the scan is genuinely bounded, not just filtered.
        body = ["x"] * (8 + anchors.DRIFT_RADIUS + 5)
        body[7] = "def beta():"     # line 8, the authored line -- erased below
        body[7] = "# moved away"
        body[8 + anchors.DRIFT_RADIUS + 4] = "def beta():"  # far outside the radius
        self.root.joinpath("pkg", "mod.py").write_text("\n".join(body) + "\n")
        out = anchors.resolve_anchor(self.anchor(), self.root)
        self.assertEqual(out["status"], "stale")


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

    def test_empty_file(self):
        (self.root / "empty.py").write_text("")
        out = anchors.resolve_anchor(
            {"file": "empty.py", "line": 1, "snippet": "anything"}, self.root)
        # Pinned, not just membership: the anchored line can never be FOUND
        # in an empty file, which is what "the line moved or vanished" means.
        self.assertEqual(out["status"], "stale")

    def test_binary_content(self):
        (self.root / "binary.dat").write_bytes(b"\x00\x01\x02\xff\xfe")
        out = anchors.resolve_anchor(
            {"file": "binary.dat", "line": 1, "snippet": "anything"}, self.root)
        # Decoded with errors="replace" and then searched like any text --
        # the snippet won't match the mojibake, so this is "not found", too.
        self.assertEqual(out["status"], "stale")

    def test_line_past_eof(self):
        out = anchors.resolve_anchor(self.anchor(line=9999), self.root)
        # Same shape as the two above: nothing at or near that line matches.
        self.assertEqual(out["status"], "stale")

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
        # An OS-level read failure, not a content mismatch -- "missing", not
        # "stale".
        self.assertEqual(out["status"], "missing")

    def test_root_does_not_exist(self):
        missing_root = self.root / "does" / "not" / "exist"
        out = anchors.resolve_anchor(self.anchor(), missing_root)
        # is_file() is False under a root that doesn't exist -- same
        # "missing" as any other file-not-there case.
        self.assertEqual(out["status"], "missing")

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
