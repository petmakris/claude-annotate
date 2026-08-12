"""Every skill's bootstrap block must fail with a named message, not a trace.

The bootstrap resolves PLUGIN_ROOT with python3 and runs before
ensure_server.sh, so it is the first thing to break on a machine with no
interpreter. These tests execute the block exactly as shipped.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

DOCS = [
    "skills/annotate/references/pushing.md",
    "skills/walkthrough/SKILL.md",
    "skills/interactive_review/SKILL.md",
]

BLOCK_RE = re.compile(r"```bash\n(.*?PLUGIN_ROOT=.*?)```", re.DOTALL)


def bootstrap_block(rel: str) -> str:
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    match = BLOCK_RE.search(text)
    assert match, f"no bootstrap bash block found in {rel}"
    return match.group(1)


class BootstrapGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bootstrap-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def _run(self, script: str, bin_dir: Path) -> subprocess.CompletedProcess:
        path = self.tmp / "block.sh"
        path.write_text(script)
        return subprocess.run(
            [str(bin_dir / "bash"), str(path)],
            capture_output=True, text=True, timeout=20,
            # LC_ALL/LANG pinned to C so bash's own diagnostics (e.g. "command
            # not found") are always English — otherwise this test's meaning
            # depends on the developer's locale instead of the guard.
            env={"HOME": str(self.home), "PATH": str(bin_dir),
                 "LC_ALL": "C", "LANG": "C"},
        )

    def test_each_bootstrap_names_the_plugin_and_the_fix(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        for rel in DOCS:
            with self.subTest(doc=rel):
                result = self._run(bootstrap_block(rel), bin_dir)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("claude-annotate", result.stderr)
                self.assertIn("python3", result.stderr)
                self.assertIn("/annotate-doctor", result.stderr)

    def test_no_raw_command_not_found_reaches_the_user(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        for rel in DOCS:
            with self.subTest(doc=rel):
                result = self._run(bootstrap_block(rel), bin_dir)
                self.assertNotIn("command not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
