"""Narration: what Claude is doing, while the page waits.

A reader comments on a block and Claude goes away for minutes. The page has a
spinner and a ticking timer, and until now nothing else: `applyProgress` in
script.js had been receiving `undefined` since the daemon cutover, and the
PostToolUse hook that used to produce its labels (`hooks/hooks.json` and
`skills/annotate/hooks/progress_publish.py`) went dormant in the same move.
Both files are gone; this module is what replaced them.

This is the writing half of the replacement. Claude calls it between steps and
the line appears on the page within milliseconds, because the daemon already
pushes every item write down its SSE stream.

Why an ITEM and not a new daemon route: the daemon is a separate package,
pipx-installed, shared with deck, dataflow and walkthrough. Carrying strings
through the item channel it already has costs one anchor; a first-class
progress channel costs a release, a reinstall, and version skew in every
client. The anchor's `__` prefix is what keeps it out of the document —
compat.js:51 skips `__`-prefixed ids when building the block list and
compat.js:207 strips them from the version map — so it can never be mistaken
for a block.
"""
from __future__ import annotations

import argparse
import sys
import time

from skills._shared import webcompanion_client as wc

ANCHOR = "__progress__"
# Shorter than a push's: a narration line that cannot land in ten seconds is
# not worth holding up the turn it narrates.
TIMEOUT_S = 10

# A long session can answer many events. The panel shows a window, not a
# transcript, and an unbounded list would grow the item forever and make every
# subsequent write larger than the last.
MAX_STEPS = 200


def _load(sid: str) -> dict | None:
    # allow_missing on the READ only: "there is no trail yet" is the ordinary
    # case on the first line of a round, and 404 is how the daemon says so. A
    # 404 on the WRITE means the session id is wrong, and swallowing it once
    # narrated into the void and exited 0 — a typo in `--sid` looked exactly
    # like a working narration channel.
    one = wc.get_item(sid, ANCHOR, allow_missing=True, timeout=TIMEOUT_S)
    if not one:
        return None
    body = one.get("body")
    return body if isinstance(body, dict) else None


def _blank(now: int, event_id: str | None) -> dict:
    return {
        "id": ANCHOR,
        "kind": "progress",
        "state": "working",
        "started_at": now,
        "ended_at": None,
        "event_id": event_id,
        "steps": [],
    }


def note(sid: str, text: str, event_id: str | None = None) -> dict:
    """Append one narration line. Starts a fresh trail if the last one is closed."""
    now = int(time.time())
    cur = _load(sid)
    # A finished trail belongs to work the reader has already seen answered.
    # Appending to it would show a feed that starts mid-way through a round
    # that is over.
    if not cur or cur.get("state") == "done":
        cur = _blank(now, event_id)
    if event_id and not cur.get("event_id"):
        cur["event_id"] = event_id
    steps = cur.get("steps")
    if not isinstance(steps, list):
        steps = []
    steps.append({"t": now, "text": str(text)})
    cur["steps"] = steps[-MAX_STEPS:]
    cur["state"] = "working"
    cur["ended_at"] = None
    wc.put_item(sid, ANCHOR, cur, timeout=TIMEOUT_S)
    return cur


def finish(sid: str) -> dict:
    """Close the trail. The steps stay — how the answer was reached is evidence."""
    now = int(time.time())
    cur = _load(sid) or _blank(now, None)
    cur["state"] = "done"
    cur["ended_at"] = now
    wc.put_item(sid, ANCHOR, cur, timeout=TIMEOUT_S)
    return cur


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.progress")
    ap.add_argument("--sid", required=True)
    ap.add_argument("--text", help="one narration line")
    ap.add_argument("--event-id", dest="event_id")
    ap.add_argument("--done", action="store_true", help="close the trail")
    a = ap.parse_args(argv)
    if not a.text and not a.done:
        print("progress: pass --text or --done", file=sys.stderr)
        return 2
    # Narration must never take down the turn it is narrating. A failure is
    # reported and returns non-zero; the caller is a shell step that ignores it.
    if a.text:
        _, rc = wc.run_cli("progress", note, a.sid, a.text, a.event_id)
        if rc:
            return rc
    if a.done:
        _, rc = wc.run_cli("progress", finish, a.sid)
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
