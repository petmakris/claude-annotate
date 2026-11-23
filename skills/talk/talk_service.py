"""The talk server as a launchd agent, so its settings come from one place and not from whichever
session happened to start it.

A server a session starts inherits that session's environment. A session opened before the launcher
learned TALK_AZURE_KEY_COMMAND starts a server without it, and that server speaks with VoiceStudio
until it exits. Installed as a service, the server's environment is written once into its plist, at
install time, and a launch never starts a server itself: it asks launchd to.

    uv run --script talk.py --install-service     # from a shell that has the speech settings
    uv run --script talk.py --uninstall-service
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "dev.talk"
# What the server reads from its environment. AZURE_SPEECH_KEY is left out on purpose: a plist is a
# plain file, so the key is reached through TALK_AZURE_KEY_COMMAND instead.
PASSED = ("HOME", "PATH", "XDG_DATA_HOME", "TALK_AZURE_KEY_COMMAND", "TALK_AZURE_REGION", "AZURE_SPEECH_REGION",
          "TALK_SPEECH", "TALK_VOICE", "TALK_LANGUAGE", "VOICESTUDIO_URL", "TALK_URL_BASE", "TALK_STAGE_BASE")


class ServiceError(Exception):
    """The service cannot be installed as asked; the message says why and what to do."""


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def target() -> str:
    return f"gui/{os.getuid()}/{LABEL}"


def supported() -> bool:
    return sys.platform == "darwin" and shutil.which("launchctl") is not None


def installed() -> bool:
    """A launch asks launchd for the server only while the plist is there."""
    return supported() and plist_path().is_file()


def service_env(env: dict) -> dict:
    """The settings the plist carries. Refuses an environment that would leave the server on
    VoiceStudio by accident, or that would put the Azure key itself into the file."""
    choice = env.get("TALK_SPEECH", "").strip().lower()
    if not env.get("TALK_AZURE_KEY_COMMAND", "").strip() and choice != "voicestudio":
        if env.get("AZURE_SPEECH_KEY", "").strip():
            raise ServiceError("AZURE_SPEECH_KEY is set, but the service would have to write the key into its plist; "
                               "set TALK_AZURE_KEY_COMMAND to a command that prints it instead")
        raise ServiceError("TALK_AZURE_KEY_COMMAND is not set in this shell, so the service would speak with "
                           "VoiceStudio; install it from a shell that has it, or set TALK_SPEECH=voicestudio "
                           "to mean VoiceStudio")
    return {k: env[k] for k in PASSED if env.get(k)}


def build(script: Path, port: int, uv: str, env: dict, log: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [uv, "run", "-q", "--script", str(script), "--serve", "--stay", "--port", str(port)],
        "WorkingDirectory": str(script.parent),
        "EnvironmentVariables": service_env(env),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }


def launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)


def install(script: Path, port: int, log: Path, env: dict | None = None) -> dict:
    """Write the plist and load it, replacing one loaded before. Returns what it wrote."""
    if not supported():
        raise ServiceError("the service needs launchd, so it is macOS only; elsewhere a launch starts the server")
    uv = shutil.which("uv")
    if not uv:
        raise ServiceError("uv is not on PATH; the service runs talk.py with uv")
    spec = build(script, port, uv, dict(os.environ) if env is None else env, log)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    launchctl("bootout", target())  # not loaded yet is fine
    path.write_bytes(plistlib.dumps(spec))
    done = launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
    if done.returncode:
        raise ServiceError(f"launchctl bootstrap failed: {(done.stderr or done.stdout).strip() or done.returncode}")
    return spec


def uninstall() -> bool:
    """Unload and remove the plist; False when there was none."""
    path = plist_path()
    if not path.is_file():
        return False
    launchctl("bootout", target())
    path.unlink()
    return True


def kickstart(restart: bool = False) -> None:
    """Start the server now; with restart, stop the running one first (it hands its calls over)."""
    done = launchctl("kickstart", *(["-k"] if restart else []), target())
    if done.returncode:
        raise ServiceError(f"launchctl kickstart failed: {(done.stderr or done.stdout).strip() or done.returncode}")
