"""ensure_server.sh must name the plugin and the fix, not leak bash errors."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

# Was annotate's launcher, then deck's, then walkthrough's, then ask_diff's,
# until each in turn moved onto the webcompanion daemon and stopped shipping
# a server of its own. ask_diff was the last one (see its Task 4 migration),
# so this now runs the shared launcher directly instead of through any
# skill's thin wrapper -- the behaviour under test always belonged to the
# shared script, never to whichever skill happened to still call it.
SCRIPT = REPO_ROOT / "skills" / "_shared" / "web_companion" / "ensure_server.sh"

# The thin per-skill wrapper used to export these before sourcing SCRIPT.
# python3 is checked before any of them are used, so their exact values
# don't matter -- they only need to be present so the script's `: "${VAR:?}"`
# guards don't fire before preflight() gets a chance to.
WRAPPER_ENV = {"SKILL": "test", "MODULE": "skills.test.server",
              "BANNER": "test-server", "PLUGIN_ROOT": str(REPO_ROOT)}


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
                 "LC_ALL": "C", "LANG": "C", **WRAPPER_ENV},
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
