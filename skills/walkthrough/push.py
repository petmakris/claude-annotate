"""Push a steps.json document to the webcompanion daemon.

Replaces the old flow -- a per-skill server serving steps.json and per-step
threads off disk. There is no walkthrough server any more: the daemon owns
storage, comment threads and the event queue, and this module is the only
thing that knows how a walkthrough document maps onto it.

The mapping:

    __steps__    the full steps.json body, unchanged shape (see steps.py)

Usage:
    python3 -m skills.walkthrough.push --steps <steps.json> --cwd <repo root>
                                       [--slug <slug>] [--title <title>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills.walkthrough import steps as steps_module

KIND = "walkthrough"
STEPS_ANCHOR = "__steps__"


def push(steps_path: Path, cwd: str, slug: str | None = None,
        title: str | None = None) -> dict:
    doc = json.loads(steps_path.read_text())

    errors = steps_module.validate(doc)
    if errors:
        raise ValueError(
            "steps.json failed validation:\n" + "\n".join("  - " + e for e in errors))

    title = title or doc.get("question") or "Walkthrough"

    # Unlike dataflow, walkthrough turns supersede on: the IDE panel shows
    # exactly one tour per project, and the current (pre-daemon) SKILL.md
    # already cancels any pre-existing walkthrough session for this cwd on
    # every new invocation, regardless of which Claude conversation created
    # it -- supersede=True is an atomic replacement for that already-accepted
    # behavior, not a new one. See the plan's Global Constraints for the one
    # named behavior change (no more cross-cwd auto-cancel within one Claude
    # conversation).
    res = wc.create_or_attach(KIND, cwd, title=title, slug=slug, supersede=True)
    sid = res["sid"]

    wc.put_items(sid, {STEPS_ANCHOR: doc}, kind=KIND, replace=True)

    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.walkthrough.push")
    ap.add_argument("--steps", required=True, help="path to steps.json")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.steps), a.cwd, a.slug, a.title)
    except ValueError as e:
        print("walkthrough push: %s" % e, file=sys.stderr)
        return 1
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch) as e:
        print("walkthrough push: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
