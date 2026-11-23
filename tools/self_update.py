#!/usr/bin/env python3
"""Keep claude-annotate checkouts on the latest main, driven by events, never by a timer.

Two events call this:

- **A push to main.** `.githooks/pre-push` starts `self_update.py all --wait <sha>`
  in the background once the suite passed. It waits until GitHub holds the pushed commit,
  updates this machine's own checkout, then every other machine in the fleet's `machines.json`
  over ssh.
- **A canvas build.** `tools/canvas.py build` (which every Lomem journey runs) calls `here`
  first, so a journey on a machine outside the fleet (a colleague's laptop) also gets the
  latest viewer.

`here` never blocks the work that called it and never goes over local work: on another branch,
with uncommitted changes, with local commits, or without network, it says so in one line and
leaves the checkout as it is. It always exits 0. `CLAUDE_ANNOTATE_NO_UPDATE=1` turns it off;
it is also off inside pytest.

`@claude fleet-update` (env repo) runs `all` by hand.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence

REPO = Path(__file__).resolve().parent.parent


def home_checkout() -> Path:
    """The machine's own checkout, which skills run from (a push may come from a worktree)."""
    p = Path(os.environ.get("CLAUDE_ANNOTATE_HOME") or Path.home() / "projects" / "claude-annotate").expanduser()
    return p if (p / ".git").exists() else REPO
FETCH_TIMEOUT = 20


def _git(repo: Path, *args: str, timeout: int = FETCH_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def _out(repo: Path, *args: str) -> str:
    r = _git(repo, *args)
    return r.stdout.strip() if r.returncode == 0 else ""


def disabled() -> bool:
    return bool(os.environ.get("CLAUDE_ANNOTATE_NO_UPDATE") or os.environ.get("PYTEST_CURRENT_TEST"))


def here(repo: Path = REPO, say=print, force: bool = False) -> bool:
    """Fast-forward this checkout to origin/main when that is safe. True when HEAD moved."""
    if disabled() and not force:
        return False
    try:
        if not (repo / ".git").exists():
            return False
        branch = _out(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if branch != "main":
            say(f"claude-annotate: on branch {branch or '?'}, not main; not updating")
            return False
        if _out(repo, "status", "--porcelain", "--untracked-files=no"):
            say("claude-annotate: uncommitted changes; not updating")
            return False
        if _git(repo, "fetch", "-q", "origin", "main").returncode != 0:
            say("claude-annotate: could not reach origin; using the checkout as it is")
            return False
        ahead = _out(repo, "rev-list", "--count", "origin/main..HEAD")
        behind = _out(repo, "rev-list", "--count", "HEAD..origin/main")
        if ahead not in ("", "0"):
            say(f"claude-annotate: {ahead} local commit(s) not on origin; not updating")
            return False
        if behind in ("", "0"):
            return False
        old = _out(repo, "rev-parse", "HEAD")
        if _git(repo, "merge", "--ff-only", "-q", "origin/main").returncode != 0:
            say("claude-annotate: fast-forward failed; using the checkout as it is")
            return False
        new = _out(repo, "rev-parse", "HEAD")
        say(f"claude-annotate: updated {old[:7]}..{new[:7]} ({behind} commit(s))")
        return True
    except (OSError, subprocess.SubprocessError) as e:
        say(f"claude-annotate: update skipped ({e.__class__.__name__})")
        return False


def wait_for_origin(repo: Path, sha: str, tries: int = 24, pause: float = 5.0) -> bool:
    """Wait until origin's main is `sha` (the push landed). False when it never does."""
    for _ in range(tries):
        line = _out(repo, "ls-remote", "origin", "refs/heads/main")
        if line.split("\t")[0] == sha:
            return True
        time.sleep(pause)
    return False


def fleet_machines(fleet_home: Optional[Path] = None) -> List[tuple]:
    """(name, ssh host) of every other machine in the fleet's machines.json."""
    home = fleet_home or Path(os.environ.get("FLEET_HOME") or Path.home() / ".claude" / "fleet")
    try:
        d = json.loads((home / "machines.json").read_text())
    except (OSError, ValueError):
        return []
    me = d.get("self", "")
    return [(k, v["ssh"]) for k, v in d.items() if k != "self" and k != me and isinstance(v, dict) and v.get("ssh")]


# What each other machine runs: this script when its checkout has it, else a plain fast-forward
# pull (a checkout from before this script existed), which then brings the script along.
REMOTE = (
    "cd ~/projects/claude-annotate && if [ -f tools/self_update.py ]; "
    "then CLAUDE_ANNOTATE_NO_UPDATE= python3 tools/self_update.py here; "
    "else git pull -q --ff-only && echo 'pulled (no self_update.py there yet)'; fi"
)


def everywhere(repo: Path = REPO, say=print, fleet_home: Optional[Path] = None) -> int:
    status = 0
    here(repo, say=say, force=True)
    for name, host in fleet_machines(fleet_home):
        try:
            r = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, REMOTE],
                capture_output=True, text=True, timeout=120,
            )
            text = (r.stdout + r.stderr).strip()
            say(f"{name}: {text or ('up to date' if r.returncode == 0 else f'exit {r.returncode}')}")
            status |= int(r.returncode != 0)
        except (OSError, subprocess.SubprocessError) as e:
            say(f"{name}: not reached ({e.__class__.__name__})")
            status = 1
    return status


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("here", help="fast-forward this checkout when it is safe (the default)")
    a = sub.add_parser("all", help="this checkout, then every machine in the fleet's machines.json")
    a.add_argument("--wait", default="", help="first wait until origin's main is this commit (after a push)")
    a.add_argument("--since", default="", help=argparse.SUPPRESS)  # an older pre-push hook still passes it
    args = ap.parse_args(argv)
    if args.cmd == "all":
        repo = home_checkout()
        if args.wait and not wait_for_origin(repo, args.wait):
            print(f"claude-annotate: origin never showed {args.wait[:7]}; nothing updated")
            return 1
        return everywhere(repo)
    here(REPO, force=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
