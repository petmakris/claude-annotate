#!/usr/bin/env python3
"""/journey: a sandbox's journey canvas as a webcompanion session, answered by the Claude session the user attached.

A journey belongs to a sandbox, not to an app (14 November 2026). Every sandbox (on a machine with no sandboxes,
every checkout) that runs its app's journey has, on the machine that runs its journeys:

  * its canvas: the folder its run builds, registered by `journey.py register`, key `<app>-<name>`. It is the page
    of a webcompanion session of kind `journey`, slug = the key, at https://<webcompanion host>/s/<key>/.
    Comments are its threads, one per board; Send and Re-run are events on it.
  * the Claude session attached to it, if any: ~/.local/state/journey/<key>/claude-session, and `owner.json`
    beside it (the session id, the machine it runs on, its folder, since when).

The canvas is a notepad (22 November 2026). The user pins comments, then presses Send: that marks every comment
not sent yet with one send time (`sentAt`) and posts one `comments` event. A batch is the comments sent at the same
time and still waiting for Claude (`batches`): it lives in the comments, so it waits as long as it takes, the
event is only a doorbell, and nothing is lost when nobody listens. Only a Claude Code session the user started
answers: `/journey <canvas>` attaches it (`attach`, then `watch`), from this machine or another one (config
`canvas_hosts`: every command for a canvas not registered here runs over ssh on the host that has it). Nothing
wakes a session by itself, and nothing here builds anything.

The apps file (apps.example.json beside this file, or your own at ~/.config/claude-annotate/journey/apps.json)
says, for each app, what the canvas calls it, where its features are listed and how a Re-run runs them.
Removing a sandbox archives its canvas (`journey.py archive`): its link keeps opening, and it runs nothing.

Commands (all print plain text unless --json):

  apps                                   every canvas: folder, attached session, link (and those of canvas_hosts)
  register APP --name N --checkout DIR --canvas DIR   a sandbox's canvas, key APP-N, as its session's page
  archive CANVAS --to DIR                a removed sandbox's canvas: copied to DIR, its page, no Re-run
  ensure CANVAS                          find or make the canvas's session and register its page

CANVAS (written APP below) is a canvas key, `<app>-<sandbox name>`.
  link APP                               the canvas links
  attach APP [--session ID --machine M --cwd DIR]   this Claude session answers the canvas from now on
  watch APP [--session ID]               webcompanion watch, ended when another session attaches
  pending APP [--json]                   events waiting, batches waiting for Claude, comments not sent, run states
  batches APP                            every batch waiting for Claude, each comment in full
  event APP EVENT_ID                     one event, in full
  comment APP COMMENT_ID                 one comment: where, its words, its thread, its board's images
  reply APP COMMENT_ID [--event EID] TEXT   Claude's answer in the comment's thread
  ack APP EVENT_ID                       the event is read (archived when no watcher will)
  rerun APP FEATURE... | all [--event EID]  run the features in a sandbox and publish
  status APP                             write and print Claude's state for the canvas
  purge APP COMMENT_ID                   remove a comment and its every op from its thread (test cleanup)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The skill and the app CLIs run this file by path (also over ssh from another machine), not
# through bin/claude-annotate, so the plugin root is not on PYTHONPATH.
sys.path.insert(0, str(HERE.parents[1]))
from skills._shared import atomic, devdomains  # noqa: E402
from skills._shared import webcompanion_client as wc  # noqa: E402

try:
    from . import store  # noqa: E402
except ImportError:  # run as a script
    import store  # type: ignore  # noqa: E402

KIND = "journey"
HOME = Path.home()
HERE_CONFIG = HOME / ".config" / "claude-annotate" / "journey"
# Your own settings live outside the repo: ~/.config/claude-annotate/journey/config.json (JOURNEY_CONFIG names
# another file). Keys, all optional: host (the only machine whose hostname may run sessions; unset: any),
# machine (this machine's short name, shown on the canvas for a session attached from here), home (the session
# home), tooling_home (a folder holding bin/@devdomains), cli (the app CLI path, relative to home), cli_probe
# ({"file", "needle"}: the file of the CLI's source that must contain the needle for the CLI to run named
# journeys; unset: every CLI does), canvas_hosts (ssh targets whose canvases this machine can attach to, tried
# in order for a canvas not registered here), remote_journey (journey.py on those hosts; default
# ~/projects/claude-annotate/skills/journey/journey.py) and remote_python (default python3).
CONFIG_FILE = Path(os.environ.get("JOURNEY_CONFIG") or HERE_CONFIG / "config.json")
try:
    CONFIG = json.loads(CONFIG_FILE.read_text())
except (OSError, ValueError):
    CONFIG = {}
TOOLING_HOME = Path(os.path.expanduser(os.environ.get("JOURNEY_TOOLING_HOME") or CONFIG.get("tooling_home") or HOME / ".config" / "claude-annotate"))
# The session home: the app's CLI picks a sandbox of the app and runs the journey there; the sessions live here.
APP_HOME = Path(os.path.expanduser(os.environ.get("JOURNEY_APP_HOME") or CONFIG.get("home") or HOME / "projects" / "journey"))
STATE_ROOT = Path(os.environ.get("JOURNEY_STATE") or HOME / ".local" / "state" / "journey")
WC_STATE = HOME / ".claude" / "webcompanion"
HOST = CONFIG.get("host") or ""
MACHINE = CONFIG.get("machine") or "main"

# The journey apps, as data: where each one's sandbox and canvas are, how its features are listed and run.
_OWN_APPS = HERE_CONFIG / "apps.json"
APPS_FILE = Path(os.environ.get("JOURNEY_APPS") or (_OWN_APPS if _OWN_APPS.exists() else HERE / "apps.example.json"))
APPS = {k: v for k, v in json.loads(APPS_FILE.read_text()).items() if not k.startswith("_")}

LISTENING_S = 90  # a watcher heartbeat younger than this is someone listening
# Bounds for the commands run to completion: a build or a journey run is slow, a hung one must not
# hold the session for ever.
RERUN_TIMEOUT_S = 2 * 3600
AFTER_TIMEOUT_S = 30 * 60
TIMED_OUT = 124  # the exit code of a command that was stopped for running too long, as timeout(1) gives it
REMOTE_TIMEOUT_S = 15 * 60  # one command run on a canvas host (a re-run gets RERUN_TIMEOUT_S)
CACHE = Path(os.environ.get("JOURNEY_CACHE") or HOME / ".cache" / "claude-annotate" / "journey")


class Refused(Exception):
    """A command that cannot go on; its message is for the person."""


# ── canvases: one per sandbox (or checkout) of an app ───────────────────────
#
# A journey belongs to a sandbox, not to an app (Petros, 14 November 2026). Each sandbox (on a machine with no
# sandboxes, each checkout) that runs its journey has its own canvas: the folder its run builds, registered by
# `journey.py register APP --name NAME --checkout DIR --canvas DIR`. Its key is `<app>-<name>`: the slug of its
# webcompanion session (/s/<key>/), its state folder and its Claude session.

def need_app(app: str) -> dict:
    if app not in APPS:
        raise Refused(f"no journey app {app!r}: one of {', '.join(APPS)}")
    return APPS[app]


def name_slug(name: str) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def canvas_key(app: str, name: str | None) -> str:
    """A canvas's key: `<app>-<name>`."""
    need_app(app)
    slug = name_slug(name or "")
    if not slug:
        raise Refused("a canvas needs a name: the sandbox's, or on a machine with no sandboxes the checkout's")
    return f"{app}-{slug}"


def canvas_record(key: str) -> dict:
    """What `register` wrote for the canvas: {app, name, checkout, canvas, archived?, at}, or {}."""
    return read_json(STATE_ROOT / key / "canvas.json", {}) if re.match(r"^[a-z0-9-]+$", key) else {}


def app_of(key: str) -> str:
    """The app a canvas belongs to; refused for a key no canvas has."""
    rec = canvas_record(key)
    app = rec.get("app")
    if app not in APPS:
        raise Refused(f"no journey canvas {key!r}: one of {', '.join(canvas_keys()) or 'none yet'}")
    return app


def canvas_keys() -> list[str]:
    """Every canvas registered on this machine."""
    return sorted(p.parent.name for p in STATE_ROOT.glob("*/canvas.json"))


def register(app: str, name: str, checkout: str, canvas: str) -> dict:
    """Make (or move) a sandbox's canvas: its record, then its webcompanion session with the canvas as its page."""
    key = canvas_key(app, name)
    rec = canvas_record(key)
    write_json(state_dir(key) / "canvas.json", {"app": app, "name": name, "checkout": checkout, "canvas": canvas,
                                                 "at": now_iso(), **({"since": rec["since"]} if rec.get("since") else
                                                                     {"since": now_iso()})})
    return {**ensure(key), "key": key}


def archive(key: str, to: str) -> dict:
    """A removed sandbox's canvas: copied to `to`, which becomes its page, and marked archived (no Re-run)."""
    rec = canvas_record(key)
    if not rec:
        raise Refused(f"{key} is no sandbox's canvas")
    src, dest = Path(rec["canvas"]), Path(os.path.expanduser(to))
    if src.is_dir() and src.resolve() != dest.resolve():
        shutil.copytree(src, dest, dirs_exist_ok=True)
    write_json(state_dir(key) / "canvas.json", {**rec, "canvas": str(dest), "archived": now_iso()})
    return {**ensure(key), "key": key, "archived": str(dest)}


def on_main() -> bool:
    return not HOST or os.environ.get("JOURNEY_HOST", socket.gethostname()) == HOST


def need_main() -> None:
    if not on_main():
        raise Refused(f"journey canvases live on {HOST}, and this runs only there. To answer one from here, "
                      f"attach this session to it: /journey <canvas> (config canvas_hosts names the hosts to ask)")


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def app_cli() -> Path:
    return APP_HOME / (CONFIG.get("cli") or "bin/app")


def sandbox_folder(app: str) -> Path | None:
    """The folder of the sandbox (or checkout) the canvas belongs to, while it exists and is not archived, or None."""
    rec = canvas_record(app)
    p = Path(rec.get("checkout") or "")
    return p if rec and not rec.get("archived") and p.is_absolute() and p.is_dir() else None


def place(app: str) -> dict:
    """Where the app's journey ran last, and how it runs: {from, folder, run, after, env}. The folder is the
    sandbox the canvas was captured on (None: none yet, or it ended); the app CLI picks the sandbox."""
    spec = need_app(app_of(app))
    return {"from": "sandbox", "folder": sandbox_folder(app), "run": spec["run"], "after": spec.get("after"),
            "env": spec.get("env") or {}, "name": canvas_record(app).get("name") or ""}


def features_root(app: str) -> Path:
    """Where the app's feature list is read: the sandbox the canvas was captured on, else the session home."""
    return sandbox_folder(app) or APP_HOME


def session_folder(app: str) -> Path:
    """The folder the canvas's Claude session runs in: its sandbox's (one session per canvas), else the session home."""
    app_of(app)
    return sandbox_folder(app) or APP_HOME


def knows_named_journeys(cli: Path) -> bool:
    """Whether this CLI runs named journeys and never makes a sandbox. Read from its source (config `cli_probe`),
    so nothing runs; with no probe configured, every CLI does."""
    probe = CONFIG.get("cli_probe")
    if not probe:
        return True
    try:
        return probe["needle"] in (cli.parent.parent / probe["file"]).read_text()
    except (OSError, KeyError):
        return False


def journey_cli(app: str) -> Path:
    """The CLI that runs the app's journey: the session home's, else the CLI of the sandbox the canvas was
    captured on. An older CLI would make a permanent journey sandbox again: refused."""
    folder = sandbox_folder(app)
    rel = CONFIG.get("cli") or "bin/app"
    for cli in [app_cli()] + ([folder / rel] if folder else []):
        if knows_named_journeys(cli):
            return cli
    raise Refused(f"the CLI in {APP_HOME} cannot run a journey in a named sandbox yet, and the canvas names no "
                  f"sandbox whose CLI can. Run it in a sandbox by hand: <sandbox>/{rel} sandbox journey {app} "
                  f"--name <name> [features] --publish")


def state_dir(app: str) -> Path:
    d = STATE_ROOT / app
    d.mkdir(parents=True, exist_ok=True)
    return d


def canvas_dir(app: str) -> Path:
    """The canvas's folder: the one registered (the sandbox's own, or its archive)."""
    app_of(app)
    return Path(os.path.expanduser(canvas_record(app)["canvas"]))


def stable_link(app: str) -> str:
    """The canvas's one link: its session's page by slug (the canvas key), which opens the canvas."""
    return f"{public_base().rstrip('/')}/s/{app}/"


def now_iso() -> str:
    return store.now_iso()


def run_bounded(argv, timeout_s: float, note=None, **kw) -> int:
    """Run `argv` to completion and give its exit code; TIMED_OUT when it ran past `timeout_s` (the
    process is killed). `note`, a file, is told why."""
    try:
        return subprocess.run(argv, timeout=timeout_s, **kw).returncode
    except subprocess.TimeoutExpired:
        if note is not None:
            note.write(f"\nstopped: ran longer than {timeout_s}s\n")
            note.flush()
        return TIMED_OUT


def log(app: str | None, line: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"{stamp} {app or '-'} {line}"
    print(text, file=sys.stderr, flush=True)
    if app:
        with open(state_dir(app) / "journey.log", "a") as f:
            f.write(text + "\n")


# ── the Claude session of an app ───────────────────────────────────────────

def read_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return default


def write_json(p: Path, data) -> None:
    atomic.write_text_atomic(p, json.dumps(data, indent=2) + "\n", mode=0o644)


def claude_session(app: str) -> str | None:
    try:
        v = (state_dir(app) / "claude-session").read_text().strip()
    except OSError:
        return None
    return v if re.match(r"^[0-9a-f-]{36}$", v) else None


def set_claude_session(app: str, sid: str) -> None:
    p = state_dir(app) / "claude-session"
    atomic.write_text_atomic(p, sid + "\n", mode=0o644)


def owner(app: str) -> dict:
    return read_json(state_dir(app) / "owner.json", {})


# ── the webcompanion session of an app ─────────────────────────────────────

def find_session(app: str) -> dict | None:
    rows = [r for r in wc.all_sessions(KIND) if r.get("slug") == app]
    return next((r for r in rows if r.get("state", "live") == "live"), rows[0] if rows else None)


def ensure(app: str) -> dict:
    """The canvas's live session, reopened or made, with the canvas as its page."""
    rec = canvas_record(app)
    name = APPS[app_of(app)]["name"]
    row = find_session(app)
    if row is not None and row.get("state", "live") != "live":
        wc.request("POST", f"/s/{row['sid']}/api/unfinish")
    if row is None:
        row = wc.request("POST", "/api/sessions", {"kind": KIND, "cwd": str(session_folder(app)), "slug": app,
                                                   "title": f"{name} journey" + (f" · {rec['name']}" if rec else "")})
        if row.get("slug") != app:
            raise Refused(f"asked webcompanion for journey session {app} and got {row.get('slug')}")
    folder = canvas_dir(app)
    if folder.is_dir():
        boot = folder / "wc-boot.js"
        if not boot.exists():
            boot.write_text("location.replace('assets/index.html' + location.hash);\n")
        wc.register_assets(row["sid"], str(folder), "wc-boot.js", kind=KIND)
    return {"sid": row["sid"], "slug": app, "url": stable_link(app)}


def sid_of(app: str) -> str:
    row = find_session(app)
    if row is None:
        raise Refused(f"{app} has no journey session yet: run its journey with --publish (or `journey.py ensure {app}`)")
    return row["sid"]


def public_base() -> str:
    return devdomains.webcompanion_url(str(TOOLING_HOME / "bin" / "@devdomains")) or "http://127.0.0.1:3080"


def session_dirs(sid: str) -> dict:
    d = read_json(WC_STATE / "sessions.json", {}).get(sid)
    if not d:
        raise Refused(f"webcompanion's registry has no session {sid}")
    return d


def heartbeat_age(dirs: dict) -> float | None:
    st = Path(dirs["state_dir"])
    try:
        beat = int((st / "watcher_heartbeat").read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        stopped = (st / "watcher_stopped").stat().st_mtime
        if stopped >= beat:
            return None
    except OSError:
        pass
    return max(0.0, time.time() - beat)


def pending_events(dirs: dict) -> list[tuple[str, dict]]:
    """Events in the queue that no one has acked, oldest first."""
    ev, done = Path(dirs["events_dir"]), Path(dirs["consumed_dir"])
    out = []
    for p in sorted(ev.glob("*.json")) if ev.is_dir() else []:
        if (done / f"{p.stem}.ack").exists():
            continue
        out.append((p.stem, read_json(p, {})))
    return out


def event_body(rec: dict) -> dict:
    """The canvas's envelope inside an event record's `text`."""
    try:
        body = json.loads(rec.get("text") or "")
    except ValueError:
        return {"type": "text", "text": rec.get("text") or ""}
    return body if isinstance(body, dict) else {"type": "text", "text": rec.get("text")}


def put_item(sid: str, anchor: str, body: dict) -> None:
    wc.put_item(sid, anchor, body)


def get_item(sid: str, anchor: str) -> dict | None:
    env = wc.get_item(sid, anchor, allow_missing=True)
    return env.get("body") if env else None


def comments_of(app: str, sid: str) -> dict[str, dict]:
    st, _ = store.fold(wc.get_threads(sid, kind=KIND))
    return {c["id"]: c for c in st["comments"] if c["app"] == app_of(app)}


# ── Claude's state, as the canvas shows it ─────────────────────────────────

def claude_state(app: str, dirs: dict) -> dict:
    """Attached (a watcher of the attached session beats) or not. The page also reads the watcher's heartbeat
    itself, so a session that died without a word never shows as attached for long."""
    o = owner(app)
    age = heartbeat_age(dirs)
    attach = f"/journey {app}"
    if age is not None and age < LISTENING_S and o.get("session"):
        where = o.get("machine") or "?"
        return {"state": "attached", "label": f"attached · session {o['session'][:8]} on {where}",
                "session": o["session"][:8], "machine": where, "since": o.get("since"), "attach": attach}
    return {"state": "detached", "label": f"no session attached · Send keeps the comments until one runs {attach}",
            "attach": attach}


def publish_state(app: str, sid: str, dirs: dict, force: bool = False) -> dict:
    st = claude_state(app, dirs)
    key = json.dumps(st, sort_keys=True)
    marker = state_dir(app) / "status.last"
    try:
        same = marker.read_text() == key
    except OSError:
        same = False
    if force or not same:
        put_item(sid, "claude/status", {**st, "at": now_iso()})
        marker.write_text(key)
    return st


# ── attach and watch ───────────────────────────────────────────────────────

SESSION_ID = re.compile(r"^[0-9a-f-]{36}$")


def attach(app: str, session_id: str, machine: str, cwd: str) -> dict:
    """Make `session_id` (a Claude Code session the user started, on `machine`) the one that answers the canvas.
    Returns the session it replaces; that session's watch ends by itself."""
    if not SESSION_ID.match(session_id or ""):
        raise Refused(f"not a Claude session id: {session_id!r} (run this inside a Claude Code session)")
    before = claude_session(app)
    prev = owner(app)
    set_claude_session(app, session_id)
    history = prev.get("history", [])[-9:]
    if before and before != session_id:
        history.append({"session": before, "until": now_iso()})
    write_json(state_dir(app) / "owner.json", {"session": session_id, "machine": machine or MACHINE, "cwd": cwd,
                                                "since": now_iso(), "history": history})
    return {"previous": before if before != session_id else None}


class _Stop(Exception):
    pass


def _stop_on_signals() -> None:
    """SIGTERM (TaskStop) and SIGHUP (the ssh link of a session on another machine closed) end the watch through
    its `finally`, so the canvas says at once that nobody is attached."""
    import signal

    def stop(signum, _frame):
        raise _Stop()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)


def watch(app: str, session_id: str) -> int:
    """`webcompanion watch` for the canvas's session, ended with JOURNEY_SUPERSEDED once another
    Claude session attaches. Its lines pass through unchanged."""
    sid = sid_of(app)
    _stop_on_signals()
    wcbin = shutil.which("webcompanion") or str(HOME / ".local" / "bin" / "webcompanion")
    child = subprocess.Popen([wcbin, "watch", "--kind", KIND, "--sid", sid], stdout=sys.stdout)
    # The canvas's Claude pill follows the watcher.
    # Written only when it changes, so looking every turn costs a few file reads.
    try:
        while child.poll() is None:
            try:
                publish_state(app, sid, session_dirs(sid))
            except (Refused, wc.DaemonError, OSError):
                pass
            now_owner = claude_session(app)
            if session_id and now_owner and now_owner != session_id:
                child.terminate()
                child.wait(10)
                print(f"JOURNEY_SUPERSEDED app={app} by={now_owner}", flush=True)
                return 0
            time.sleep(2)
        return child.returncode or 0
    except _Stop:
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
        try:
            (Path(session_dirs(sid)["state_dir"]) / "watcher_stopped").touch()
            publish_state(app, sid, session_dirs(sid))
        except (Refused, wc.DaemonError, OSError):
            pass


# ── pending work, comments, replies, acks ──────────────────────────────────

def board_files(app: str, board) -> list[str]:
    """The image files of the board a comment is on, from the published canvas's manifest: by the board's
    id, or by its number on a canvas without ids."""
    folder = canvas_dir(app)
    m = read_json(folder / "canvas.json", {})
    for g in m.get("groups") or []:
        for b in g.get("boards") or []:
            if str(b.get("id", b.get("number"))) == str(board):
                return [str(folder / s["file"]) for s in b.get("shots") or [] if (folder / s["file"]).exists()]
    return []


def board_link(app: str, board) -> str:
    return f"{stable_link(app)}#board-{board}"


def describe(app: str, sid: str, c: dict) -> dict:
    return {
        "id": c["id"], "number": c["number"], "board": c["board"], "boardTitle": c.get("boardTitle"),
        "feature": c.get("chapter"), "shot": c["shot"], "point": [c["fx"], c["fy"]], "scope": c["scope"],
        "status": c["status"], "text": c["text"], "createdAt": c["createdAt"], "sentAt": c.get("sentAt"),
        "replies": [{"by": r.get("by", "user"), "text": r["text"], "at": r["createdAt"]} for r in c["replies"]],
        "waiting": store.waiting(c), "images": board_files(app, c["board"]), "link": board_link(app, c["board"]),
    }


def sent_waiting(c: dict) -> bool:
    """Sent with Send and still waiting for Claude: nothing written on it since it was sent."""
    return store.waiting(c) and bool(c.get("sentAt")) and c["sentAt"] >= c.get("askedAt", "")


def batches_of(comments) -> list[dict]:
    """The batches waiting for Claude, oldest first: the comments sent at the same time ({sentAt, comments})."""
    by: dict[str, list[dict]] = {}
    for c in comments:
        if sent_waiting(c):
            by.setdefault(c["sentAt"], []).append(c)
    return [{"sentAt": t, "comments": sorted(cs, key=lambda c: c["number"])} for t, cs in sorted(by.items())]


def batches(app: str) -> list[dict]:
    """Every batch waiting for Claude, each comment described in full."""
    return pending(app)["batches"]


def pending(app: str) -> dict:
    sid = sid_of(app)
    dirs = session_dirs(sid)
    events = [{"event_id": eid, **event_body(rec)} for eid, rec in pending_events(dirs)]
    comments = list(comments_of(app, sid).values())
    waiting_batches = [{"sentAt": b["sentAt"], "count": len(b["comments"]),
                        "comments": [describe(app, sid, c) for c in b["comments"]]} for b in batches_of(comments)]
    not_sent = sorted(c["number"] for c in comments if store.waiting(c) and not sent_waiting(c))
    runs = {}
    for anchor, env in (wc.get_items(sid, kind=KIND) or {}).items():
        if anchor.startswith("run/"):
            runs[anchor[4:]] = env.get("body")
    return {"app": app, "sid": sid, "folder": str(place(app)["folder"] or ""), "events": events,
            "batches": waiting_batches, "not_sent": not_sent, "runs": runs, "canvas": stable_link(app),
            "attached": owner(app).get("session")}


def reply(app: str, comment_id: str, event_id: str, text: str) -> dict:
    sid = sid_of(app)
    c = comments_of(app, sid).get(comment_id)
    if c is None:
        raise Refused(f"no comment {comment_id} on {app}'s canvas")
    text = text.strip()
    if not text:
        raise Refused("the reply is empty")
    key = f"{event_id or 'none'}:{comment_id}:{hashlib.sha1(text.encode()).hexdigest()[:8]}"
    rid = "r" + hashlib.sha1(key.encode()).hexdigest()[:14]
    op = {"kind": "reply", "id": comment_id, "at": now_iso(), "uid": rid, "reply": {"id": rid, "text": text, "by": "claude"}}
    anchor = c["board"] if isinstance(c["board"], str) else f"board-{c['board']}"
    res = wc.request("POST", f"/s/{sid}/threads/{wc.urllib.parse.quote(anchor, safe='')}",
                     {"text": text, "role": "agent", "op": op, "source_event_id": key})
    return {"appended": res.get("appended"), "comment": c["number"], "board": c["board"]}


def progress(app: str, items: dict) -> dict:
    """Write a journey run's live state into the app's canvas session, as the app CLI sends it while it runs:
    `run/<feature>` ({state: queued|running|passed|failed, at, error?}) and `run/__journey__` (the whole run:
    {state, done, failed, total, startedAt, at}). Only those anchors are written; no session yet writes nothing."""
    bad = [k for k in items if not re.match(r"^run/[a-z0-9_-]+$", k)]
    if bad:
        raise Refused(f"progress writes run/<id> items only, not {', '.join(bad)}")
    try:
        sid = sid_of(app)
    except Refused:
        return {"written": 0, "why": f"{app} has no canvas session on this machine"}
    if items:
        wc.put_items(sid, items, kind=KIND)
    return {"written": len(items)}


def ack(app: str, event_id: str) -> dict:
    if "/" in event_id or event_id in ("", ".", ".."):
        raise Refused(f"not an event id: {event_id!r}")
    sid = sid_of(app)
    dirs = session_dirs(sid)
    done = Path(dirs["consumed_dir"])
    done.mkdir(parents=True, exist_ok=True)
    (done / f"{event_id}.ack").touch()
    archived = False
    age = heartbeat_age(dirs)
    src = Path(dirs["events_dir"]) / f"{event_id}.json"
    # With no watcher running, nothing else moves an answered event out of the queue.
    if (age is None or age >= LISTENING_S) and src.exists():
        try:
            os.replace(src, done / f"{event_id}.json")
            (done / f"{event_id}.attempts").unlink(missing_ok=True)
            archived = True
        except OSError:
            pass
    return {"acked": event_id, "archived": archived}


# ── re-runs ────────────────────────────────────────────────────────────────

def feature_id(name: str) -> str:
    return re.sub(r"^-|-$", "", re.sub(r"[^a-z0-9]+", "-", name.lower()))


def features(app: str) -> list[dict]:
    """The app's features in order: {id, name, skip}. apps.json says where from: a journey.feature's
    Scenarios (the Gherkin feature files' Scenario lines)."""
    src = need_app(app_of(app))["features"]
    return gherkin(features_root(app) / src["gherkin"])


def gherkin(f: Path) -> list[dict]:
    out, tags = [], []
    for line in f.read_text().splitlines():
        t = line.strip()
        if t.startswith("#"):
            continue
        if t.startswith("@"):
            tags += [x[1:] for x in t.split()]
            continue
        m = re.match(r"^Scenario:\s*(.+?)\s*$", t)
        if m:
            out.append({"id": feature_id(m.group(1)), "name": m.group(1), "skip": "skip" in tags})
        if t:
            tags = []
    return out


def out_dir(app: str) -> Path | None:
    """The folder the app's last run wrote its results into, in the sandbox the canvas was captured on (None: none)."""
    folder = sandbox_folder(app)
    return folder / need_app(app_of(app))["results"] if folder else None


def fill(text: str, folder: Path | None, name: str = "") -> str:
    """{checkout}, {cli}, {home} and {name} (the canvas's sandbox) of an apps-file word."""
    return (text.replace("{checkout}", str(folder or "")).replace("{home}", str(APP_HOME))
            .replace("{cli}", str(app_cli())).replace("{name}", name))


def argv_of(template: list[str] | None, folder: Path | None, chosen: list[str] | None = None, name: str = "") -> list[str]:
    """An apps.json argv with {features} spread out (nothing for every feature), {--name} as `--name <sandbox>`
    (nothing without one) and its other fields
    filled in; a first word that names a file of the folder is that file."""
    if not template:
        return []
    argv = []
    for a in template:
        if a == "{features}":
            argv += chosen or []
        elif a == "{--name}":
            # The canvas's sandbox, for a CLI that takes --name.
            argv += ["--name", name] if name else []
        else:
            argv.append(fill(a, folder, name))
    argv[0] = os.path.expanduser(argv[0])
    if "/" in argv[0] and not argv[0].startswith("/") and folder:
        argv[0] = str(folder / argv[0])
    return argv


def rerun(app: str, wanted: list[str], event_id: str | None = None) -> dict:
    """Run the features in a sandbox (the apps file's `run`, from the session home, whose CLI picks the sandbox
    and never makes one), with each one's
    state on the canvas, then its `after`.
    Only ids the app's feature list has are run."""
    need_main()
    if canvas_record(app).get("archived"):
        raise Refused(f"{app}'s sandbox was removed: its canvas is archived and runs nothing")
    known = [f for f in features(app) if not f["skip"]]
    ids = [f["id"] for f in known]
    if wanted == ["all"]:
        chosen = ids
    else:
        bad = [w for w in wanted if w not in ids]
        if bad:
            raise Refused(f"{app}'s journey has no feature {', '.join(bad)}; it has: {', '.join(ids)}")
        chosen = [i for i in ids if i in wanted]
    sid = sid_of(app)
    p = place(app)
    # The run runs from the session home, whose CLI picks the sandbox; refused before anything shows running.
    cli = journey_cli(app)
    # A CLI shim may run the CLI of the checkout its working directory is in: run the chosen CLI from its own checkout.
    cwd = cli.parents[3]
    started = now_iso()
    for f in chosen:
        put_item(sid, f"run/{f}", {"state": "running", "at": started, "event": event_id})
    argv = argv_of(p["run"], p["folder"], [] if chosen == ids else chosen, p["name"])
    if argv and argv[0] == str(app_cli()):
        argv[0] = str(cli)
    # A run whose first word is the canvas checkout's own CLI (a relative path in the apps file, as on a machine
    # with no sandboxes) runs from that checkout, for the same reason.
    if argv and p["folder"] and Path(argv[0]).is_relative_to(p["folder"]):
        cwd = p["folder"]
    after = argv_of(p["after"], p["folder"], None, p["name"])
    logs = state_dir(app) / "runs"
    logs.mkdir(exist_ok=True)
    logf = logs / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    env = {**os.environ, "FORCE_COLOR": "0", **{k: fill(v, p["folder"], p["name"]) for k, v in p["env"].items()}}
    log(app, f"rerun {' '.join(chosen)}: {' '.join(argv)} in {cwd} > {logf}")
    t0 = time.time()
    with open(logf, "w") as lf:
        code = run_bounded(argv, RERUN_TIMEOUT_S, lf, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT, env=env)
        if after:
            run_bounded(after, AFTER_TIMEOUT_S, lf, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT, env=env)
    tail = logf.read_text(errors="replace").splitlines()[-25:]
    # Asked again: the publish names the sandbox it ran in.
    out = out_dir(app)
    results = {}
    for f in chosen:
        man = read_json(out / f / "manifest.json", {}) if out else {}
        ok = man.get("status") == "passed" and (man.get("finishedAt") or "") >= started[:19]
        state = "passed" if ok else "failed"
        err = None if ok else (man.get("error") or f"`{' '.join(argv[:4])}` exited {code}; see {logf}")
        results[f] = {"state": state, "boards": len(man.get("boards") or []), **({"error": err} if err else {})}
        put_item(sid, f"run/{f}", {"state": state, "at": now_iso(), "event": event_id, **({"error": err} if err else {})})
    ensure(app)
    put_item(sid, "canvas/build", {"built": page_built(app) or now_iso(), "features": chosen})
    return {"app": app, "features": results, "exit": code, "seconds": round(time.time() - t0),
            "log": str(logf), "canvas": stable_link(app),
            "boards": {f: f"{stable_link(app)}#c-{ids.index(f) + 1}" for f in chosen},
            "tail": tail if code else []}


def page_built(app: str) -> str | None:
    """When the published page was built (its data's `built`): an open canvas older than it reloads,
    and the page it reloads into is this one, so it never reloads again."""
    try:
        html = (canvas_dir(app) / "index.html").read_text()
    except OSError:
        return None
    m = re.search(r'"built":"([0-9T:.\-]+Z)"', html)
    return m.group(1) if m else None


# ── migration from the journey-comments service ────────────────────────────

def purge(app: str, comment_id: str) -> dict:
    """Remove a comment and every op about it from its board's thread (a test comment's cleanup).
    The thread's other messages are put back as they were, with their times."""
    sid = sid_of(app)
    threads = wc.get_threads(sid, kind=KIND)
    removed = 0
    for anchor, t in threads.items():
        msgs = t.get("messages") or []

        def about(m):
            op = m.get("op") or {}
            return op.get("id") == comment_id or (op.get("comment") or {}).get("id") == comment_id

        if not any(about(m) for m in msgs):
            continue
        keep = [m for m in msgs if not about(m)]
        removed += len(msgs) - len(keep)
        wc.delete_thread(sid, anchor, kind=KIND)
        for m in keep:
            wc.request("POST", f"/s/{sid}/threads/{wc.urllib.parse.quote(anchor, safe='')}", m)
    return {"comment": comment_id, "messages_removed": removed}


# ── a canvas on another machine ────────────────────────────────────────────
#
# A session on one machine (the Mac) may attach to a canvas on another (main). Every command for a canvas this
# machine has no record of runs on the first of config `canvas_hosts` that has it, as
# `ssh <host> <remote_python> <remote_journey> <command>`; the board images a comment names are copied here, so
# the session can read them. The watch keeps a terminal on the far side (`ssh -tt`), so closing it (TaskStop,
# a dead session) hangs up the far watch, which then says nobody listens.

REMOTE_CMDS = {"attach", "watch", "pending", "batches", "event", "comment", "reply", "ack", "rerun", "status",
               "link", "ensure", "purge"}
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3"]


def canvas_hosts() -> list[str]:
    hosts = CONFIG.get("canvas_hosts") or []
    return [h for h in hosts if isinstance(h, str) and re.match(r"^[A-Za-z0-9_.@-]+$", h)]


def remote_command(args: list[str]) -> str:
    """The far side's command line: its python, its journey.py (a leading ~/ is its own home) and the args."""
    py = CONFIG.get("remote_python") or "python3"
    path = CONFIG.get("remote_journey") or "~/projects/claude-annotate/skills/journey/journey.py"
    where = '"$HOME"/' + shlex.quote(path[2:]) if path.startswith("~/") else shlex.quote(path)
    return " ".join([shlex.quote(py), where, *(shlex.quote(a) for a in args)])


def ssh_argv(host: str, args: list[str], tty: bool = False) -> list[str]:
    return ["ssh", *SSH_OPTS, *(["-tt"] if tty else []), host, remote_command(args)]


def remote_host(key: str) -> str | None:
    """The canvas host that has the canvas, when this machine has no record of it; None: it is here (or nowhere)."""
    if canvas_record(key):
        return None
    hosts = canvas_hosts()
    if len(hosts) == 1:
        return hosts[0]
    for h in hosts:
        try:
            if subprocess.run(ssh_argv(h, ["has", key]), capture_output=True, timeout=60).returncode == 0:
                return h
        except subprocess.TimeoutExpired:
            continue
    return None


def fetch_images(host: str, key: str, obj, copied: dict | None = None):
    """Every `images` path in obj (a describe, a batch, pending) copied from the host into the cache; the paths
    are replaced by the local copies (a copy that fails keeps the far path and says so)."""
    copied = {} if copied is None else copied
    if isinstance(obj, list):
        return [fetch_images(host, key, x, copied) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if k == "images" and isinstance(v, list):
            local = []
            for far in v:
                if far in copied:
                    local.append(copied[far])
                    continue
                dest = (CACHE / key / (hashlib.sha1(f"{host}:{far}".encode()).hexdigest()[:10] + "-" + Path(far).name)).resolve()
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    ok = subprocess.run(["scp", "-q", *SSH_OPTS, f"{host}:{far}", str(dest)], capture_output=True,
                                        timeout=120).returncode == 0
                except subprocess.TimeoutExpired:
                    ok = False
                copied[far] = str(dest) if ok else f"{host}:{far} (could not be copied)"
                local.append(copied[far])
            out[k] = local
        else:
            out[k] = fetch_images(host, key, v, copied)
    return out


def run_remote(host: str, cmd: str, key: str, args: list[str], as_json: bool, stdin_text: str | None) -> int:
    """Run one command on the canvas host and print its answer here."""
    if cmd == "watch":
        return relay_watch(host, args)
    wants_images = cmd in ("pending", "batches", "comment")
    full = (["--json"] if wants_images or as_json else []) + args
    timeout = RERUN_TIMEOUT_S if cmd == "rerun" else REMOTE_TIMEOUT_S
    try:
        res = subprocess.run(ssh_argv(host, full), input=stdin_text, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Refused(f"{cmd} on {host} ran longer than {timeout}s")
    if res.stderr:
        sys.stderr.write(res.stderr)
    if res.returncode == 255 and not res.stdout:
        raise Refused(f"cannot reach {host} over ssh (exit 255): the canvas {key} lives there")
    if wants_images and res.returncode == 0:
        try:
            show(fetch_images(host, key, json.loads(res.stdout)), as_json)
            return 0
        except ValueError:
            pass
    sys.stdout.write(res.stdout)
    return res.returncode


def relay_watch(host: str, args: list[str]) -> int:
    """The far watch's lines, here, without the carriage returns its terminal adds. Stopped here (TaskStop),
    it hangs up the far side."""
    child = subprocess.Popen(ssh_argv(host, args, tty=True), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             text=True, errors="replace")
    _stop_on_signals()
    try:
        for line in child.stdout:
            print(line.rstrip("\r\n"), flush=True)
        return child.wait()
    except _Stop:
        return 0
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()


def remote_apps() -> list[dict]:
    rows = []
    for h in canvas_hosts():
        try:
            res = subprocess.run(ssh_argv(h, ["--json", "apps", "--here"]), capture_output=True, text=True, timeout=60)
            rows += [{**r, "host": h} for r in json.loads(res.stdout or "[]")]
        except (subprocess.TimeoutExpired, ValueError):
            rows.append({"host": h, "error": "could not be asked"})
    return rows


# ── the command line ───────────────────────────────────────────────────────

def show(obj, as_json: bool) -> None:
    if as_json or not isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False) if not isinstance(obj, str) else obj)
        return
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="journey.py", description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("apps").add_argument("--here", action="store_true", help="this machine's canvases only")
    p = sub.add_parser("register")
    p.add_argument("app")
    p.add_argument("--name", required=True)
    p.add_argument("--checkout", required=True)
    p.add_argument("--canvas", required=True)
    p = sub.add_parser("archive")
    p.add_argument("app")
    p.add_argument("--to", required=True)
    for name in ("ensure", "link", "pending", "batches", "status", "has"):
        sub.add_parser(name).add_argument("app")
    p = sub.add_parser("attach")
    p.add_argument("app")
    p.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    p.add_argument("--machine", default=MACHINE)
    p.add_argument("--cwd", default=os.getcwd())
    p = sub.add_parser("watch")
    p.add_argument("app")
    p.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    p = sub.add_parser("event")
    p.add_argument("app")
    p.add_argument("event_id")
    p = sub.add_parser("comment")
    p.add_argument("app")
    p.add_argument("comment_id")
    p = sub.add_parser("reply")
    p.add_argument("app")
    p.add_argument("comment_id")
    p.add_argument("--event", default="")
    p.add_argument("text", nargs="?", help="the answer; `-` or nothing reads it from stdin")
    p = sub.add_parser("progress")
    p.add_argument("app")
    p = sub.add_parser("ack")
    p.add_argument("app")
    p.add_argument("event_id")
    p = sub.add_parser("rerun")
    p.add_argument("app")
    p.add_argument("features", nargs="+")
    p.add_argument("--event", default=None)
    p = sub.add_parser("purge")
    p.add_argument("app")
    p.add_argument("comment_id")
    a = ap.parse_args(raw)
    try:
        if a.cmd == "has":
            return 0 if canvas_record(a.app) else 1
        if a.cmd in REMOTE_CMDS:
            host = remote_host(a.app)
            if host:
                args = [x for x in raw if x != "--json"]
                if a.cmd == "attach":
                    args += ["--session", a.session, "--machine", a.machine, "--cwd", a.cwd]
                elif a.cmd == "watch":
                    args += ["--session", a.session]
                stdin_text = None
                if a.cmd == "reply" and a.text in (None, "-"):
                    stdin_text = sys.stdin.read()
                return run_remote(host, a.cmd, a.app, args, a.json, stdin_text)
        if a.cmd not in ("apps", "register") and hasattr(a, "app"):
            app_of(a.app)
        if a.cmd == "register":
            need_main()
            show(register(a.app, a.name, str(Path(a.checkout).resolve()), str(Path(a.canvas).resolve())), a.json)
        elif a.cmd == "archive":
            need_main()
            show(archive(a.app, a.to), a.json)
        elif a.cmd == "apps":
            rows = []
            for app in canvas_keys():
                row = find_session(app) if on_main() else None
                p = place(app)
                rows.append({"app": app, "folder": str(p["folder"] or ""), "from": p["from"],
                             "canvas": str(canvas_dir(app)),
                             "session": (row or {}).get("sid"), "attached": claude_session(app),
                             "machine": owner(app).get("machine"), "link": stable_link(app)})
            show(rows + ([] if a.here else remote_apps()), a.json)
        elif a.cmd == "ensure":
            need_main()
            show(ensure(a.app), a.json)
        elif a.cmd == "link":
            sid_of(a.app)
            print(stable_link(a.app))
        elif a.cmd == "attach":
            need_main()
            res = attach(a.app, a.session, a.machine, a.cwd)
            info = ensure(a.app)
            show({**res, **info, "attached": a.session, "machine": a.machine}, a.json)
        elif a.cmd == "watch":
            need_main()
            return watch(a.app, a.session)
        elif a.cmd == "pending":
            show(pending(a.app), a.json)
        elif a.cmd == "batches":
            show(batches(a.app), a.json)
        elif a.cmd == "event":
            dirs = session_dirs(sid_of(a.app))
            for d in (dirs["events_dir"], dirs["consumed_dir"]):
                p = Path(d) / f"{a.event_id}.json"
                if p.exists():
                    rec = read_json(p, {})
                    show({"event_id": a.event_id, "acked": (Path(dirs["consumed_dir"]) / f"{a.event_id}.ack").exists(),
                          **event_body(rec)}, a.json)
                    return 0
            raise Refused(f"no event {a.event_id} on {a.app}'s session")
        elif a.cmd == "comment":
            sid = sid_of(a.app)
            c = comments_of(a.app, sid).get(a.comment_id)
            if c is None:
                raise Refused(f"no comment {a.comment_id} on {a.app}'s canvas")
            show(describe(a.app, sid, c), a.json)
        elif a.cmd == "reply":
            text = a.text if a.text not in (None, "-") else sys.stdin.read()
            show(reply(a.app, a.comment_id, a.event, text), a.json)
        elif a.cmd == "progress":
            show(progress(a.app, json.loads(sys.stdin.read() or "{}")), a.json)
        elif a.cmd == "ack":
            show(ack(a.app, a.event_id), a.json)
        elif a.cmd == "rerun":
            show(rerun(a.app, a.features, a.event), a.json)
        elif a.cmd == "status":
            sid = sid_of(a.app)
            dirs = session_dirs(sid)
            st = publish_state(a.app, sid, dirs, force=True)
            show({**st, "attached": claude_session(a.app), "owner": owner(a.app),
                  "watcher_age_s": heartbeat_age(dirs), "events_waiting": len(pending_events(dirs))}, a.json)
        elif a.cmd == "purge":
            show(purge(a.app, a.comment_id), a.json)
    except Refused as e:
        print(f"journey: {e}", file=sys.stderr)
        return 1
    except wc.DaemonError as e:
        print(f"journey: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
