"""ensure_server.sh must name the plugin and the fix, not leak bash errors."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

# Was annotate's launcher until annotate moved onto the webcompanion daemon
# and stopped shipping a server. The behaviour under test belongs to the
# shared launcher, not to any one skill, so this now points at deck — one of
# the four skills that still run a server of their own.
SCRIPT = REPO_ROOT / "skills" / "deck" / "ensure_server.sh"


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="preflight-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def _run(self, bin_dir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(bin_dir / "bash"), str(SCRIPT)],
            capture_output=True, text=True, timeout=20,
            # LC_ALL/LANG pinned to C so bash's own diagnostics (e.g. "command
            # not found") are always English — otherwise this test's meaning
            # depends on the developer's locale instead of the guard.
            env={"HOME": str(self.home), "PATH": str(bin_dir),
                 "LC_ALL": "C", "LANG": "C"},
        )

    def test_reports_missing_python_and_stops(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=False))
        self.assertNotEqual(result.returncode, 0)
        err = result.stderr
        self.assertIn("claude-annotate", err)
        self.assertIn("python3", err)
        self.assertIn("3.9", err)
        # A remedy the user can act on, not just a complaint.
        self.assertIn("xcode-select --install", err)

    def test_message_is_one_block_not_a_bash_trace(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=False))
        self.assertNotIn("command not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
