"""The progress hook must be invisible unless it can do useful work.

It fires on every PostToolUse. On a machine with no python3 it used to print
a bash error per tool call; for a user who installed only claude-ide-review
it spawned an interpreter per tool call for a feature they do not have.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import (
    BASH, hook_command, hook_env, sanitized_path_dir, spy_marker, spy_stdin,
)

PAYLOAD = json.dumps({"tool_name": "Bash", "session_id": "sess-1"})


def _run(bin_dir: Path, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, "-c", hook_command()],
        input=PAYLOAD, capture_output=True, text=True, timeout=10,
        env=hook_env(home, bin_dir),
    )


class HookGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hookgate-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def test_silent_when_no_python3(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        (self.home / ".claude" / "annotate").mkdir(parents=True)
        (self.home / ".claude" / "annotate" / "pending-sess-1.json").write_text("[]")
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_does_not_spawn_python_when_no_pending_rounds(self):
        # The claude-ide-review-only user: python3 exists, annotate does not run.
        bin_dir = sanitized_path_dir(self.tmp, with_python=True, spy=True)
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")
        self.assertFalse(
            spy_marker(self.tmp).exists(),
            "gate must not spawn an interpreter when no round is pending",
        )

    def test_spawns_python_when_a_round_is_pending(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=True, spy=True)
        (self.home / ".claude" / "annotate").mkdir(parents=True)
        (self.home / ".claude" / "annotate" / "pending-sess-1.json").write_text("[]")
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(
            spy_marker(self.tmp).exists(),
            "gate must hand off to the interpreter when work may exist",
        )

    def test_payload_reaches_the_interpreter_on_stdin(self):
        # The gate must not consume stdin: progress_publish.py parses it.
        #
        # This used to assert only returncode == 0 and stderr == "", which
        # proved nothing — progress_publish.py swallows every exception and
        # exits 0 silently, so both held with the payload eaten. Inserting
        # `cat >/dev/null;` before the exec in hooks.json left it green.
        # The spy interpreter records its stdin, so the bytes are checked.
        bin_dir = sanitized_path_dir(self.tmp, with_python=True, spy=True)
        d = self.home / ".claude" / "annotate"
        d.mkdir(parents=True)
        (d / "pending-sess-1.json").write_text("[]")
        result = _run(bin_dir, self.home)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertTrue(spy_marker(self.tmp).exists(),
                        "the gate never reached the interpreter at all")
        self.assertEqual(
            spy_stdin(self.tmp).read_text(),
            PAYLOAD,
            "the gate consumed or altered the PostToolUse payload",
        )


if __name__ == "__main__":
    unittest.main()
