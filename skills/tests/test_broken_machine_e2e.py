"""What a machine with no python3 actually experiences, end to end.

One test per thing the reporting user hit, so a regression in any single
layer is legible without reading four other files.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import (
    REPO_ROOT, pythonless_home, sanitized_path_dir,
)


class BrokenMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="broken-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = sanitized_path_dir(self.tmp, with_python=False)

    def test_the_doctor_still_runs_and_explains(self):
        # The reported machine had no python3 at all, so the login shell has
        # none either — otherwise this fixture is a shim machine, which the
        # doctor deliberately diagnoses differently.
        pythonless_home(self.home, self.bin)
        doctor = REPO_ROOT / "skills" / "annotate-doctor" / "doctor.sh"
        result = subprocess.run(
            [str(self.bin / "sh"), str(doctor)],
            capture_output=True, text=True, timeout=30,
            env={"HOME": str(self.home), "PATH": str(self.bin)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("python3", result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertIn("xcode-select --install", result.stdout)


if __name__ == "__main__":
    unittest.main()
