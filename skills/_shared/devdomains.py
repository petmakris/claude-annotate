"""The webcompanion daemon's public address, as `@devdomains url webcompanion` reports it."""
from __future__ import annotations

import subprocess

URL_TIMEOUT_S = 20


def webcompanion_url(tool: str) -> str:
    """What `<tool> url webcompanion` prints when it gives an http(s) address, else "".

    `tool` is the path of the `@devdomains` command. A missing tool, a failure or a timeout
    gives "" so the caller falls back to loopback."""
    try:
        out = subprocess.run([tool, "url", "webcompanion"], capture_output=True, text=True,
                             timeout=URL_TIMEOUT_S).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return out if out.startswith("http") else ""
