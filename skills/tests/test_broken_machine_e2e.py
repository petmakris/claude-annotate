"""What a machine with no python3 actually experiences, end to end.

One test per thing the reporting user hit, so a regression in any single
layer is legible without reading four other files.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import (
    BASH, REPO_ROOT, hook_command, hook_env, pythonless_home,
    sanitized_path_dir,
)

PAYLOAD = json.dumps({"tool_name": "Bash", "session_id": "sess-1"})


class BrokenMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="broken-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = sanitized_path_dir(self.tmp, with_python=False)

    def test_repeated_tool_calls_produce_no_output_at_all(self):
        # The reported symptom: one red line per tool call, forever.
        env = hook_env(self.home, self.bin)
        for _ in range(5):
            result = subprocess.run(
                [BASH, "-c", hook_command()],
                input=PAYLOAD, capture_output=True, text=True, timeout=10, env=env,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout + result.stderr, "")

    def test_the_doctor_still_runs_and_explains(self):
        # The reported machine had no python3 at all, so the login shell has
        # none either — otherwise this fixture is a shim machine, which the
        # doctor deliberately diagnoses differently.
        pythonless_home(self.home, self.bin)
        doctor = REPO_ROOT / "skills" / "_shared" / "web_companion" / "doctor.sh"
        result = subprocess.run(
            [str(self.bin / "sh"), str(doctor)],
            capture_output=True, text=True, timeout=30,
            env={"HOME": str(self.home), "PATH": str(self.bin)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python3", result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("xcode-select --install", result.stdout)

    def test_launching_a_skill_names_the_plugin_once(self):
        script = REPO_ROOT / "skills" / "annotate" / "ensure_server.sh"
        result = subprocess.run(
            [str(self.bin / "bash"), str(script)],
            capture_output=True, text=True, timeout=20,
            env={"HOME": str(self.home), "PATH": str(self.bin)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stderr.count("claude-annotate:"), 1,
                         "say it once, not once per layer")
        self.assertIn("/annotate-doctor", result.stderr)
        # ...and say what "claude-annotate" is, since it is the marketplace
        # name and half the userbase installed claude-ide-review instead.
        self.assertIn("marketplace", result.stderr)
        self.assertIn("claude-ide-review", result.stderr)


if __name__ == "__main__":
    unittest.main()
