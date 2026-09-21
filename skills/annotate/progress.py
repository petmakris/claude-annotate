"""Narration: what Claude is doing, while the page waits.

A reader comments on a block and Claude goes away for minutes. The page has a
spinner and a ticking timer, and until now nothing else: `applyProgress` in
script.js has been receiving `undefined` since the daemon cutover, and
hooks/progress_publish.py — which used to produce its labels — went dormant in
the same move.

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
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONTRACT = 1
ANCHOR = "__progress__"

# A long session can answer many events. The panel shows a window, not a
# transcript, and an unbounded list would grow the item forever and make every
# subsequent write larger than the last.
MAX_STEPS = 200


class ProgressError(RuntimeError):
    pass


def _config() -> dict:
    path = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))
    if not path.exists():
        raise ProgressError(
            "webcompanion is not configured on this machine "
            "(~/.claude/webcompanion/config.json is missing).")
    return json.loads(path.read_text())


def _request(cfg: dict, method: str, path: str, body=None):
    url = "http://127.0.0.1:%d%s" % (int(cfg["port"]), path)
    data = None
    headers = {"X-WebCompanion-Contract": str(CONTRACT)}
    if cfg.get("token"):
        headers["X-WebCompanion-Token"] = cfg["token"]
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        detail = e.read().decode(errors="replace").strip()
        raise ProgressError("%s %s -> %d %s" % (method, path, e.code, detail)) from None
    except urllib.error.URLError as e:
        raise ProgressError("webcompanion is not answering: %s" % e.reason) from None
    return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


def _load(cfg: dict, sid: str) -> dict | None:
    one = _request(cfg, "GET", "/s/%s/items/%s" % (sid, ANCHOR))
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
    cfg = _config()
    now = int(time.time())
    cur = _load(cfg, sid)
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
    _request(cfg, "PUT", "/s/%s/items/%s" % (sid, ANCHOR), cur)
    return cur


def finish(sid: str) -> dict:
    """Close the trail. The steps stay — how the answer was reached is evidence."""
    cfg = _config()
    now = int(time.time())
    cur = _load(cfg, sid) or _blank(now, None)
    cur["state"] = "done"
    cur["ended_at"] = now
    _request(cfg, "PUT", "/s/%s/items/%s" % (sid, ANCHOR), cur)
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
    try:
        if a.text:
            note(a.sid, a.text, a.event_id)
        if a.done:
            finish(a.sid)
    except ProgressError as e:
        # Narration must never take down the turn it is narrating. Report and
        # return non-zero; the caller is a shell step that ignores it.
        print("progress: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
