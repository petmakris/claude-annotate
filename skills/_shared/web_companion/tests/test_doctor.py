"""The doctor must run on a machine where nothing else does."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import REPO_ROOT, sanitized_path_dir

DOCTOR = REPO_ROOT / "skills" / "_shared" / "web_companion" / "doctor.sh"


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="doctor-"))
        self.home = self.tmp / "home"
        self.home.mkdir()

    def _run(self, bin_dir: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(bin_dir / "sh"), str(DOCTOR)],
            capture_output=True, text=True, timeout=30,
            env={"HOME": str(self.home), "PATH": str(bin_dir)},
        )

    def test_is_executable_and_posix_sh(self):
        self.assertTrue(DOCTOR.exists())
        self.assertTrue(DOCTOR.stat().st_mode & 0o111, "doctor.sh must be executable")
        self.assertEqual(DOCTOR.read_text().splitlines()[0], "#!/bin/sh")

    def test_contains_no_python_and_no_jq(self):
        # It diagnoses the absence of python3. It cannot depend on it.
        body = "\n".join(
            line for line in DOCTOR.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertNotIn("jq ", body)
        self.assertNotIn("python3 -c", body)
        self.assertNotIn("python3 -m", body)

    def test_runs_and_reports_when_python_is_missing(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=False))
        self.assertNotEqual(result.returncode, 0, "must exit non-zero on a broken machine")
        out = result.stdout
        self.assertIn("FAIL", out)
        self.assertIn("python3", out)
        self.assertIn("xcode-select --install", out)

    def test_passes_python_check_on_a_healthy_machine(self):
        result = self._run(sanitized_path_dir(self.tmp, with_python=True))
        python_lines = [l for l in result.stdout.splitlines() if "python3" in l]
        self.assertTrue(python_lines, "doctor must report on python3")
        self.assertTrue(
            any(l.startswith("ok") for l in python_lines),
            f"python3 should pass on this host: {python_lines}",
        )

    def test_never_writes_outside_state_dir(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=True)
        before = sorted(p.name for p in self.home.iterdir())
        self._run(bin_dir)
        after = sorted(p.name for p in self.home.iterdir())
        self.assertEqual(before, after, "doctor must not create anything")


if __name__ == "__main__":
    unittest.main()
