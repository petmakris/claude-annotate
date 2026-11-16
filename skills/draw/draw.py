#!/usr/bin/env python3
"""/draw: one drawing pad at a link that never changes.

The pad is a webcompanion session of kind `draw`, slug `draw`, whose page is
static/draw.js plus annotate's drawpad.js. The Claude session that last ran
`claim` owns it: its `watch` gets every Update, and an older session's watch
ends with DRAW_SUPERSEDED.

  claim --session ID     make this Claude session the pad's owner; prints {sid, url, previous}
  watch --session ID     webcompanion watch for the pad, until another session claims it
  event --event-id ID    the drawing an Update sent: {event_id, image, at}
  latest                 the newest drawing sent: {image, at}, or {} when none
  link                   the pad's link
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from skills._shared import devdomains  # noqa: E402
from skills._shared import webcompanion_client as wc  # noqa: E402

KIND = "draw"
SLUG = "draw"
HOME = Path.home()
STATE = HOME / ".claude" / "draw"
CONFIG = HOME / ".config" / "claude-annotate" / "draw.json"
PAD_FILES = [HERE.parent / "annotate" / "static" / "drawpad.js", HERE.parent / "annotate" / "static" / "drawpad.css"]
WC_STATE = HOME / ".claude" / "webcompanion"


class Refused(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def link() -> str:
    """The pad's one link. A machine whose tablet reaches webcompanion another way (the Mac, through main)
    names it in ~/.config/claude-annotate/draw.json as {"link": "..."}."""
    configured = read_json(CONFIG, {}).get("link")
    if configured:
        return configured
    base = devdomains.webcompanion_url(str(HOME / "projects" / "env" / "bin" / "@devdomains")) or "http://127.0.0.1:3080"
    return f"{base.rstrip('/')}/s/{SLUG}/"


def find_session() -> dict | None:
    rows = [r for r in wc.all_sessions(KIND) if r.get("slug") == SLUG]
    return next((r for r in rows if r.get("state", "live") == "live"), rows[0] if rows else None)


def ensure() -> str:
    """The pad's live session, reopened or made, with today's page files registered. Returns its sid."""
    row = find_session()
    if row is not None and row.get("state", "live") != "live":
        wc.request("POST", f"/s/{row['sid']}/api/unfinish")
    if row is None:
        row = wc.request("POST", "/api/sessions", {"kind": KIND, "cwd": str(HOME), "slug": SLUG, "title": "Drawing"})
        if row.get("slug") != SLUG:
            raise Refused(f"asked webcompanion for slug {SLUG} and got {row.get('slug')}")
    # The page's files are copied, not served from the plugin: the pad lives in annotate's folder, and a
    # renderer serves one folder. Copying on every claim keeps the page as new as the plugin.
    static = STATE / "static"
    static.mkdir(parents=True, exist_ok=True)
    for f in [*sorted((HERE / "static").iterdir()), *PAD_FILES]:
        shutil.copyfile(f, static / f.name)
    wc.register_assets(row["sid"], str(static), "draw.js", kind=KIND)
    return row["sid"]


def owner() -> str:
    return read_json(STATE / "owner.json", {}).get("session") or ""


def session_dirs(sid: str) -> dict:
    d = read_json(WC_STATE / "sessions.json", {}).get(sid)
    if not d:
        raise Refused(f"webcompanion's registry has no session {sid}")
    return d


def pending_events(sid: str) -> list[str]:
    d = session_dirs(sid)
    ev, done = Path(d["events_dir"]), Path(d["consumed_dir"])
    return [p.stem for p in sorted(ev.glob("*.json")) if not (done / f"{p.stem}.ack").exists()] if ev.is_dir() else []


def claim(session_id: str) -> dict:
    if not re.match(r"^[0-9a-f-]{36}$", session_id or ""):
        raise Refused(f"not a Claude session id: {session_id!r}")
    sid = ensure()
    before = owner()
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "owner.json").write_text(json.dumps({"session": session_id, "since": now_iso()}))
    # Updates nobody answered are drawings nobody saw; the new owner starts from the pad as it is now.
    dropped = 0
    for eid in pending_events(sid):
        subprocess.run([webcompanion(), "ack", "--sid", sid, "--event-id", eid], capture_output=True)
        dropped += 1
    return {"sid": sid, "url": link(), "previous": before if before and before != session_id else None,
            "dropped_updates": dropped}


def webcompanion() -> str:
    return shutil.which("webcompanion") or str(HOME / ".local" / "bin" / "webcompanion")


def watch(session_id: str) -> int:
    sid = ensure() if find_session() is None else find_session()["sid"]
    child = subprocess.Popen([webcompanion(), "watch", "--kind", KIND, "--sid", sid], stdout=sys.stdout)
    try:
        while child.poll() is None:
            now = owner()
            if session_id and now and now != session_id:
                child.terminate()
                child.wait(10)
                print(f"DRAW_SUPERSEDED by={now}", flush=True)
                return 0
            time.sleep(2)
        return child.returncode or 0
    finally:
        if child.poll() is None:
            child.terminate()


def event(event_id: str) -> dict:
    row = find_session()
    if row is None:
        raise Refused("the pad has no session yet: run /draw")
    out = subprocess.run([webcompanion(), "event", "--sid", row["sid"], "--event-id", event_id],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise Refused(out.stderr.strip() or f"no event {event_id}")
    rec = json.loads(out.stdout)
    images = [i.get("path") if isinstance(i, dict) else i for i in rec.get("images") or []]
    image = resolve_image(row["sid"], images[0]) if images else None
    return {"event_id": event_id, "sid": row["sid"], "image": image, "at": stamp(Path(image)) if image else None}


def stamp(p: Path) -> str | None:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def resolve_image(sid: str, ref: str) -> str:
    p = Path(ref)
    if p.is_absolute():
        return str(p)
    return str(Path(session_dirs(sid)["state_dir"]) / ref)


def latest() -> dict:
    row = find_session()
    if row is None:
        return {}
    up = Path(session_dirs(row["sid"])["state_dir"]) / "images"
    files = sorted(up.glob("*.png"), key=lambda p: p.stat().st_mtime) if up.is_dir() else []
    if not files:
        return {}
    return {"image": str(files[-1]), "at": stamp(files[-1])}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("claim").add_argument("--session", required=True)
    sub.add_parser("watch").add_argument("--session", required=True)
    sub.add_parser("event").add_argument("--event-id", required=True)
    sub.add_parser("latest")
    sub.add_parser("link")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "claim":
            print(json.dumps(claim(a.session)))
        elif a.cmd == "watch":
            return watch(a.session)
        elif a.cmd == "event":
            print(json.dumps(event(a.event_id)))
        elif a.cmd == "latest":
            print(json.dumps(latest()))
        elif a.cmd == "link":
            print(link())
    except (Refused, wc.DaemonError) as e:
        print(f"draw: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
