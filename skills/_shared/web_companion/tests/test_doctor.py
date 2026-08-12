"""The doctor must run on a machine where nothing else does."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

from skills.tests.sanitized_env import (
    REPO_ROOT, pythonless_home, sanitized_path_dir,
)

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
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        # No python3 anywhere — including the login shell. Without this the
        # fixture describes a *shim* machine, which is a different fault with
        # a different remedy.
        pythonless_home(self.home, bin_dir)
        result = self._run(bin_dir)
        self.assertNotEqual(result.returncode, 0, "must exit non-zero on a broken machine")
        out = result.stdout
        self.assertIn("FAIL", out)
        self.assertIn("python3", out)
        self.assertIn("xcode-select --install", out)

    def test_one_fault_produces_one_failure(self):
        # A pyenv/asdf user: python3 lives only on the login shell's PATH.
        # They must get exactly one FAIL, and it must not be "install Python"
        # — they already have it. Before this, they got both messages, with
        # the wrong remedy printed first.
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        shims = self.tmp / "shims"
        shims.mkdir()
        (shims / "python3").symlink_to(shutil.which("python3"))
        pythonless_home(self.home, bin_dir)
        (self.home / ".bash_profile").write_text(
            f'PATH="{shims}:{bin_dir}"\nexport PATH\n'
        )
        out = self._run(bin_dir).stdout
        python_fails = [l for l in out.splitlines()
                        if l.startswith("FAIL") and "python3" in l]
        self.assertEqual(len(python_fails), 1,
                         f"one fault, one FAIL: {python_fails}")
        self.assertIn("NOT by a non-interactive shell", python_fails[0])
        self.assertNotIn("xcode-select --install", out,
                         "never tell someone who has python3 to install it")

    def test_a_login_profile_that_reads_stdin_cannot_hang_the_doctor(self):
        # Reproduces the reviewer's rc=124: the doctor sources the user's login
        # profile to detect the shim trap, and a profile containing a bare
        # `read` blocked forever on the inherited terminal. The child's stdin
        # is a pipe this test keeps open, so a missing </dev/null hangs.
        bin_dir = sanitized_path_dir(self.tmp, with_python=False)
        pythonless_home(self.home, bin_dir, profile_extra="read -r ignored\n")
        read_fd, write_fd = os.pipe()
        # Own process group: when this regresses, the blocked reader is the
        # grandchild `bash -l`, which survives killing `sh` and holds the
        # stdout pipe open — so a plain proc.kill() would wedge the suite
        # instead of failing it.
        proc = subprocess.Popen(
            [str(bin_dir / "sh"), str(DOCTOR)],
            stdin=read_fd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env={"HOME": str(self.home), "PATH": str(bin_dir)},
            start_new_session=True,
        )
        os.close(read_fd)
        try:
            try:
                out, _ = proc.communicate(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.communicate(timeout=10)
                self.fail("doctor.sh hung on a login profile that reads stdin")
        finally:
            os.close(write_fd)
        self.assertIn("python3", out)

    def test_a_healthy_machine_never_sources_the_login_profile(self):
        # The shim probe is only meaningful when python3 is missing, and
        # sourcing someone's whole login profile has side effects. It must not
        # run on a machine that is fine.
        bin_dir = sanitized_path_dir(self.tmp, with_python=True)
        witness = self.tmp / "profile-was-sourced"
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / ".bash_profile").write_text(f"touch '{witness}'\n")
        self._run(bin_dir)
        self.assertFalse(witness.exists(),
                         "doctor sourced the login profile on a healthy machine")

    def test_reports_the_hook_wiring(self):
        bin_dir = sanitized_path_dir(self.tmp, with_python=True)
        out = self._run(bin_dir).stdout
        hook_lines = [l for l in out.splitlines() if " hook " in l]
        self.assertTrue(hook_lines, "doctor must report on the hook wiring")
        self.assertTrue(hook_lines[0].startswith("ok"),
                        f"this checkout wires the hook: {hook_lines}")

    def test_an_install_missing_its_hooks_file_says_reinstall(self):
        # Copy just doctor.sh into a plugin-shaped tree with no hooks/.
        fake = self.tmp / "fake-plugin"
        dest = fake / "skills" / "_shared" / "web_companion" / "doctor.sh"
        dest.parent.mkdir(parents=True)
        shutil.copy2(DOCTOR, dest)
        bin_dir = sanitized_path_dir(self.tmp, with_python=True)
        result = subprocess.run(
            [str(bin_dir / "sh"), str(dest)],
            capture_output=True, text=True, timeout=30,
            env={"HOME": str(self.home), "PATH": str(bin_dir)},
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hooks/hooks.json is missing", result.stdout)
        self.assertIn("Reinstall", result.stdout)

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
