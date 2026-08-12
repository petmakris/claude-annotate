"""Tests for the /annotate-doctor skill's doctor.sh locator.

The locator must find doctor.sh in multiple installation scenarios:
- --plugin-dir installs where <plugin-root>/bin is on PATH
- marketplace installs where ~/.claude/plugins/cache/*/claude-annotate/bin is on PATH
- environments where CLAUDE_PLUGIN_ROOT happens to be set (e.g. hook execution)

This is critical because the most common failure diagnosis (missing python3)
requires the script to run without Python itself.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Import from same directory
sys.path.insert(0, str(Path(__file__).parent))
from sanitized_env import REPO_ROOT

DOCTOR_PATH = REPO_ROOT / "skills" / "_shared" / "web_companion" / "doctor.sh"


def _extract_bash_block(skill_md: Path) -> str:
    """Extract the bash block from the skill markdown."""
    text = skill_md.read_text(encoding="utf-8")
    # Find the bash block after "## Run it"
    match = re.search(r"## Run it\s+```bash\n(.*?)```", text, re.DOTALL)
    if not match:
        raise ValueError("Could not find bash block in SKILL.md")
    return match.group(1)


class TestDoctorLocator(unittest.TestCase):
    """Test the doctor.sh locator from annotate-doctor/SKILL.md."""

    def setUp(self):
        """Extract the locator script."""
        skill_md = REPO_ROOT / "skills" / "annotate-doctor" / "SKILL.md"
        self.locator = _extract_bash_block(skill_md)

    def test_locates_doctor_via_plugin_root_bin_on_path(self):
        """The locator finds doctor.sh when plugin-root/bin is on PATH.

        This is the primary scenario: --plugin-dir installs where Claude Code
        adds <plugin-root>/bin to PATH, or marketplace installs where the
        plugin's bin is on PATH.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Simulate a plugin install: copy repo layout
            plugin_root = tmp / "plugin-root"
            plugin_bin = plugin_root / "bin"
            plugin_bin.mkdir(parents=True)

            # Copy the actual doctor.sh to the simulated location
            doctor_src = REPO_ROOT / "skills" / "_shared" / "web_companion" / "doctor.sh"
            doctor_dest = plugin_root / "skills" / "_shared" / "web_companion" / "doctor.sh"
            doctor_dest.parent.mkdir(parents=True)
            doctor_dest.write_bytes(doctor_src.read_bytes())

            # Create a dummy executable in bin/ so PATH is valid
            (plugin_bin / "sh").symlink_to("/bin/sh")

            # Run the locator with plugin_bin on PATH
            env = {
                "PATH": str(plugin_bin),
                "HOME": str(tmp),
            }
            result = subprocess.run(
                ["sh", "-c", self.locator],
                env=env,
                capture_output=True,
                text=True,
            )

            # Should succeed (exit 0) because doctor.sh runs and all checks pass
            # or fail gracefully. The key is it finds and runs doctor.sh.
            self.assertIn("ok  ", result.stdout + result.stderr,
                         "locator should find and run doctor.sh")
            # Doctor.sh exits 0 only when all checks pass; on this machine
            # in a temp sandbox it will likely fail some checks (python3, curl, etc)
            # but it should run. Just verify it ran by checking output exists.
            self.assertTrue(
                result.stdout or result.stderr,
                "doctor.sh should produce output"
            )

    def test_fails_clearly_when_doctor_not_found(self):
        """The locator fails with clear message when doctor.sh is missing.

        This catches configuration errors and broken installs.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            # Create a plugin-like structure but WITHOUT doctor.sh
            plugin_root = tmp / "plugin-root"
            plugin_bin = plugin_root / "bin"
            plugin_bin.mkdir(parents=True)
            (plugin_bin / "sh").symlink_to("/bin/sh")

            # Run the locator with plugin_bin on PATH but no doctor.sh
            env = {
                "PATH": str(plugin_bin),
                "HOME": str(tmp),
            }
            result = subprocess.run(
                ["sh", "-c", self.locator],
                env=env,
                capture_output=True,
                text=True,
            )

            # Should fail (non-zero exit)
            self.assertNotEqual(result.returncode, 0,
                               "locator should fail when doctor.sh not found")

            # Should report clearly
            self.assertIn("could not locate doctor.sh",
                         result.stdout + result.stderr,
                         "locator should report clear error message")
