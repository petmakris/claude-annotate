"""Create a webcompanion session of kind `specimen` and register its renderer.

The daemon is reached by spawning its own CLI, which is the route wp-atlas already
takes from a different repo. Nothing here copies webcompanion's HTTP client and
nothing imports across repos.

There is no fallback. If the CLI is absent the caller is told, and stops. A silent
downgrade to a plain HTML file would take away the only thing this page has that a
printout does not: you can ask it a question.
"""

from __future__ import annotations

import shutil
import subprocess

KIND = 'specimen'


class DaemonMissing(Exception):
    """`webcompanion` is not on PATH."""


class PushFailed(Exception):
    """The CLI ran and refused."""


def binary() -> str | None:
    return shutil.which('webcompanion')


def _eval_lines(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if line.startswith(('WC_SID=', 'WC_URL=', 'WC_SLUG=')):
            key, _, value = line.partition('=')
            out[key[3:].lower()] = value.strip()
    return out


def push(items_path: str, cwd: str, title: str, static_root: str,
         entry: str = 'entry.js') -> dict:
    exe = binary()
    if exe is None:
        raise DaemonMissing(
            'webcompanion is not on PATH, so there is no page to open. '
            'Install it, or run `webcompanion doctor`.')

    created = subprocess.run(
        [exe, 'push', '--kind', KIND, '--cwd', cwd, '--title', title,
         '--items', items_path, '--supersede', '--eval'],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if created.returncode != 0:
        raise PushFailed(created.stderr.strip() or 'webcompanion push failed')

    session = _eval_lines(created.stdout)
    if 'sid' not in session:
        raise PushFailed('webcompanion push printed no WC_SID')

    registered = subprocess.run(
        [exe, 'assets', '--sid', session['sid'],
         '--static-root', static_root, '--entry', entry],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if registered.returncode != 0:
        raise PushFailed(registered.stderr.strip() or 'webcompanion assets failed')

    return session
