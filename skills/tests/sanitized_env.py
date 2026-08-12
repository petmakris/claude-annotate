"""Build a PATH that deliberately lacks python3.

The install-robustness work claims our shell entry points fail quietly when
no interpreter exists. That claim is only worth anything if a test watches
the failure, so these helpers construct a PATH containing the tools our
scripts genuinely need and nothing else.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Claude Code reports hook failures as coming from /usr/bin/bash, but that
# path does not exist on macOS (bash is /bin/bash there). Resolve it instead
# of hardcoding, or every test in this suite fails on a Mac for the wrong
# reason.
BASH = shutil.which("bash") or "/bin/bash"

# Tools our shell scripts legitimately call. python3 is deliberately absent.
# `dirname` matters: skills/annotate/ensure_server.sh:3 calls it before
# anything else, so omitting it would make the preflight test fail for the
# wrong reason.
_NEEDED = (
    "sh", "bash", "env", "cat", "sed", "grep", "mkdir", "rm", "rmdir",
    "date", "stat", "sleep", "seq", "ps", "curl", "uname", "tr",
    "dirname", "basename", "head", "cut", "nohup",
)


def sanitized_path_dir(tmp: Path, *, with_python: bool = False,
                       spy: bool = False) -> Path:
    """Create a bin directory to use as the whole PATH.

    with_python=False -> no python3 at all (the reported user's machine).
    with_python=True, spy=False -> the real python3, symlinked.
    with_python=True, spy=True -> a shell script named python3 that records
        that it ran, so a test can prove the gate never spawned it.
    """
    bin_dir = tmp / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name in _NEEDED:
        real = shutil.which(name)
        if real:
            link = bin_dir / name
            if not link.exists():
                link.symlink_to(real)
    if with_python:
        target = bin_dir / "python3"
        if spy:
            marker = tmp / "python3-was-spawned"
            target.write_text(
                "#!/bin/sh\n"
                f"echo spawned > '{marker}'\n"
                "exit 0\n"
            )
            target.chmod(0o755)
        else:
            real = shutil.which("python3")
            assert real, "the test host must have python3"
            target.symlink_to(real)
    return bin_dir


def pythonless_home(home: Path, bin_dir: Path, *, profile_extra: str = "") -> Path:
    """Make the LOGIN shell python-less too, not just the PATH we hand over.

    Sanitizing PATH only sanitizes the *non-interactive* view. `bash -l` still
    sources /etc/profile, which on macOS runs path_helper and puts
    /usr/bin/python3 back — so a fixture claiming "this machine has no python3"
    was quietly describing a machine that has one in the login shell.

    doctor.sh now distinguishes those two situations, because they need
    opposite remedies (install one / expose the one you have). So the fixture
    has to distinguish them as well. ~/.bash_profile is sourced after
    /etc/profile, so pinning PATH there yields a login shell that genuinely
    finds no interpreter.

    `profile_extra` is prepended, for tests that need the profile itself to
    misbehave (e.g. a bare `read`).
    """
    home.mkdir(parents=True, exist_ok=True)
    (home / ".bash_profile").write_text(
        f'{profile_extra}PATH="{bin_dir}"\nexport PATH\n'
    )
    return home


def spy_marker(tmp: Path) -> Path:
    """Path the spy python3 writes to when it is executed."""
    return tmp / "python3-was-spawned"


def hook_command() -> str:
    """The PostToolUse command exactly as shipped in hooks/hooks.json."""
    data = json.loads((REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    entries = data["hooks"]["PostToolUse"]
    commands = [h["command"] for e in entries for h in e["hooks"]]
    assert len(commands) == 1, f"expected exactly one PostToolUse command, got {commands}"
    return commands[0]


def hook_env(home: Path, bin_dir: Path) -> dict:
    """Environment mimicking how Claude Code invokes a plugin hook."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = str(bin_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return env
