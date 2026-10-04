"""The conversation marker: which annotate sessions this conversation owns.

One file per Claude Code conversation, at
`~/.claude/annotate/pending-<CLAUDE_CODE_SESSION_ID>.json`. The docs had leaned
on it for a long time — cancellation reads it, Done and Cancel clean it up,
resume writes it — but nothing on the push path ever wrote it, so for an
ordinary push it did not exist. push.py writes it now, on every successful
push, and this module is the one place that reads and writes it.

It exists because nothing else survives between Bash calls, or a context
compaction: a shell variable set by one command is gone by the next, so the
sid, the slug, the repo root and the path of the working blocks.json have to
be somewhere Claude can read back. Each entry:

    {"sid", "slug", "cwd", "blocks", "title"}

Usage:
    python3 -m skills.annotate.session show
    python3 -m skills.annotate.session set --sid <sid> --slug <slug> --cwd <repo> [--blocks <path>] [--title <t>]
    python3 -m skills.annotate.session forget --sid <sid>
    python3 -m skills.annotate.session lookup --slug <slug> | --cwd <repo>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from skills._shared import webcompanion_client as wc
from skills.annotate.atomic import write_text_atomic

FIELDS = ("sid", "slug", "cwd", "blocks", "title")


def state_dir() -> Path:
    # The override exists for the tests, so a test run never writes into the
    # marker of the conversation that is running it.
    return Path(os.environ.get("CLAUDE_ANNOTATE_STATE_DIR")
                or os.path.expanduser("~/.claude/annotate"))


def marker_path() -> Path | None:
    conversation = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    if not conversation:
        return None
    return state_dir() / ("pending-%s.json" % conversation)


def entries() -> list[dict]:
    path = marker_path()
    if path is None or not path.exists():
        return []
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    out = []
    for e in raw if isinstance(raw, list) else []:
        # Resume used to write `{"workspace": {"sid", "slug"}}`; read both.
        if isinstance(e, dict) and isinstance(e.get("workspace"), dict):
            e = e["workspace"]
        if isinstance(e, dict) and e.get("sid"):
            out.append({k: e.get(k) for k in FIELDS if e.get(k) is not None})
    return out


def _write(rows: list[dict]) -> None:
    path = marker_path()
    if path is None:
        return
    write_text_atomic(path, json.dumps(rows, indent=2))


def record(entry: dict) -> None:
    """Add or update the entry for `entry["sid"]`. A no-op outside Claude Code."""
    rows = [e for e in entries() if e.get("sid") != entry["sid"]]
    rows.append({k: entry[k] for k in FIELDS if entry.get(k) is not None})
    _write(rows)


def forget(sid: str) -> None:
    _write([e for e in entries() if e.get("sid") != sid])


def lookup(slug: str | None = None, cwd: str | None = None) -> dict:
    """Annotate sessions on the daemon matching a slug, or an exact repo root.

    Every state is returned (`live`, `finished`, `cancelled`); the caller
    decides what a closed one means. Imported late: push.py imports this
    module to record the marker."""
    from skills.annotate.push import KIND
    cfg = wc.load_config()
    hits = [r for r in wc.all_sessions() if r.get("kind") == KIND
            and (slug is None or r.get("slug") == slug)
            and (cwd is None or r.get("cwd") == cwd)]
    return {"index": "http://localhost:%d/" % int(cfg["port"]), "sessions": hits}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.annotate.session")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="print this conversation's sessions as JSON")
    s = sub.add_parser("set", help="record a session (used by /annotate resume)")
    for name in ("sid", "slug", "cwd"):
        s.add_argument("--" + name, required=True)
    s.add_argument("--blocks")
    s.add_argument("--title")
    f = sub.add_parser("forget", help="drop a session (Done, Cancel)")
    f.add_argument("--sid", required=True)
    lk = sub.add_parser("lookup", help="find annotate sessions on the daemon")
    by = lk.add_mutually_exclusive_group(required=True)
    by.add_argument("--slug")
    by.add_argument("--cwd", help="exact repo root the session was created in")
    a = ap.parse_args(argv)
    if a.cmd == "lookup":
        found, rc = wc.run_cli("annotate session", lookup, a.slug, a.cwd)
        if rc:
            return rc
        print(json.dumps(found, indent=2))
        return 0
    if marker_path() is None:
        print("annotate session: CLAUDE_CODE_SESSION_ID is not set, so there is "
              "no conversation marker to read or write", file=sys.stderr)
        return 1
    if a.cmd == "show":
        print(json.dumps(entries(), indent=2))
    elif a.cmd == "set":
        record({"sid": a.sid, "slug": a.slug, "cwd": a.cwd,
                "blocks": a.blocks, "title": a.title})
    else:
        forget(a.sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
