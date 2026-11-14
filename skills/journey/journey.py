#!/usr/bin/env python3
"""/journey: an app's journey canvas as a webcompanion session, answered by one Claude session per app.

Every app with a journey (the apps file: apps.example.json beside this file, or your own at
~/.config/claude-annotate/journey/apps.json) has, on the configured host only:

  * a webcompanion session of kind `journey`, slug = the app, whose page is the
    app's published canvas (the apps file's `canvas` folder: the app publishes into it, built with
    claude-annotate's canvas viewer), at https://<webcompanion host>/s/<app>/. Comments are its
    threads, one per board; Send to Claude and Re-run are events on it.
  * a sandbox the journey runs in. Any sandbox of the app can run it. The app's own CLI
    (the apps file's `run`), run from the session home, picks the sandbox the canvas was captured on,
    else the app's only one, and never makes one. Each publish writes source.json beside the canvas: the sandbox, branch, folder and HEAD it was
    captured on; this tool reads the sandbox's folder from it.
  * a session home (config `home`), where the session starts and stays, so a ship that removes a sandbox never orphans it.
  * one Claude session, whose id is ~/.local/state/journey/<app>/claude-session.
    `owner.json` beside it says who has it open (pid, interactive or headless)
    and `lock` is held by whoever is starting Claude on it, so two processes
    never resume it at once.

The doorman (`journey.py doorman`, the systemd user unit journey-doorman)
wakes an app's Claude session when an event waits and nobody listens: no
watcher heartbeat for 90 s, the owner is no live Claude process, no process
has the session id on its command line, and the lock is free. It then runs one
fixed command, `claude-launch -p --resume <id> "/journey <app> resume"`, which
answers every waiting event and exits.

Commands (all print plain text unless --json):

  apps                                   every app: folder, session, owner, state
  ensure APP                             find or make the app's session and register its page
  link APP                               the canvas links
  claim APP [--session ID --pid PID --mode interactive|headless] [--cwd DIR]
  watch APP [--session ID]               webcompanion watch, ended when another session claims the app
  pending APP [--json]                   events waiting, comments waiting for Claude, run states
  event APP EVENT_ID                     one event, in full
  comment APP COMMENT_ID                 one comment: where, its words, its thread, its board's images
  reply APP COMMENT_ID --event EID TEXT  Claude's answer in the comment's thread
  ack APP EVENT_ID                       the event is answered (archived when no watcher will)
  rerun APP FEATURE... | all [--event EID]  run the features in a sandbox and publish
  status APP                             write and print Claude's state for the canvas
  launch APP                             the interactive session (`@claude on main journey-<app>`)
  doorman [--once]                       the wake-up loop
  install-doorman                        the systemd user unit, through the service library of your tooling home
  migrate FILE [--apply]                 carry the journey-comments store over
  purge APP COMMENT_ID                   remove a comment and its every op from its thread (test cleanup)
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The doorman (a systemd unit), the launchers and `journey.py` by path run this file directly, not
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
# machine (its short name in session names), home (the session home), tooling_home (a folder holding
# lib/service.sh, bin/@devdomains and libexec/claude/launch for install-doorman and the launcher), cli (the app
# CLI path, relative to home), cli_probe ({"file", "needle"}: the file of the CLI's source that must contain
# the needle for the CLI to run named journeys; unset: every CLI does).
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
LOCK_WAIT_S = 15 * 60
HEADLESS_TIMEOUT_S = 2 * 3600
# Bounds for the commands run to completion: a build or a journey run is slow, a hung one must not
# hold the doorman (and the app's lock) for ever.
RERUN_TIMEOUT_S = 2 * 3600
AFTER_TIMEOUT_S = 30 * 60
SERVICE_INSTALL_TIMEOUT_S = 10 * 60
TIMED_OUT = 124  # the exit code of a command that was stopped for running too long, as timeout(1) gives it
# A wake that leaves its events unanswered is tried again after this, then backs off.
RETRY_S = (60, 300, 1800)


class Refused(Exception):
    """A command that cannot go on; its message is for the person."""


# ── where things are ────────────────────────────────────────────────────────

def need_app(app: str) -> dict:
    if app not in APPS:
        raise Refused(f"no journey app {app!r}: one of {', '.join(APPS)}")
    return APPS[app]


def on_main() -> bool:
    return not HOST or os.environ.get("JOURNEY_HOST", socket.gethostname()) == HOST


def need_main() -> None:
    if not on_main():
        first, *rest = APPS
        raise Refused(f"journey sessions live only on {HOST}. From here, start the session there:\n"
                      f"  journey-{first}      (or {', '.join('journey-' + a for a in rest)})")


def expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def app_cli() -> Path:
    return APP_HOME / (CONFIG.get("cli") or "bin/app")


def canvas_source(app: str) -> dict:
    """The published canvas's source.json: {app, sandbox, branch, path, head, ranAt, ended?}, or {}."""
    return read_json(canvas_dir(app) / "source.json", {})


def sandbox_folder(app: str) -> Path | None:
    """The folder of the sandbox the app's canvas was captured on, while it exists and has not ended, or None."""
    src = canvas_source(app)
    path = src.get("path")
    if not isinstance(path, str) or not path or src.get("ended"):
        return None
    p = Path(path)
    return p if p.is_absolute() and p.is_dir() else None


def place(app: str) -> dict:
    """Where the app's journey ran last, and how it runs: {from, folder, run, after, env}. The folder is the
    sandbox the canvas was captured on (None: none yet, or it ended); the app CLI picks the sandbox."""
    spec = need_app(app)
    return {"from": "sandbox", "folder": sandbox_folder(app), "run": spec["run"], "after": spec.get("after"),
            "env": spec.get("env") or {}}


def features_root(app: str) -> Path:
    """Where the app's feature list is read: the sandbox the canvas was captured on, else the session home."""
    return sandbox_folder(app) or APP_HOME


def session_folder(app: str) -> Path:
    """The folder the app's Claude session runs in: the session home, never a sandbox, which a ship removes."""
    need_app(app)
    return APP_HOME


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


def line_folder(app: str) -> Path:
    """The folder the session list (config `sessions_file`) should start `<machine> journey-<app>` in: the session home."""
    return APP_HOME


def sessions_line(app: str) -> str | None:
    """The folder the session list (config `sessions_file`) gives `<machine> journey-<app>`, for `apps` to check."""
    if not CONFIG.get("sessions_file"):
        return None
    try:
        for line in Path(os.path.expanduser(CONFIG["sessions_file"])).read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and not line.lstrip().startswith("#") and parts[0] == MACHINE and parts[1] == f"journey-{app}":
                return str(Path(os.path.expanduser(parts[2])))
    except OSError:
        pass
    return None


def state_dir(app: str) -> Path:
    d = STATE_ROOT / app
    d.mkdir(parents=True, exist_ok=True)
    return d


def canvas_dir(app: str) -> Path:
    return Path(os.path.expanduser(need_app(app)["canvas"]))


def stable_link(app: str) -> str:
    """The canvas's one link: its session's page by slug, which opens the canvas."""
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


def cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode(errors="replace") for a in raw.split(b"\0") if a]


def is_claude(pid) -> bool:
    """A live process that is Claude Code (the CLI, or the launcher that execs it)."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    argv = cmdline(pid)
    return any(Path(a).name in ("claude", "claude-launch") or "/claude/versions/" in a for a in argv[:3])


def processes_naming(session_id: str) -> list[int]:
    """Every process whose command line names the session id (a `claude --resume <id>`)."""
    found = []
    me = os.getpid()
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        argv = cmdline(int(p.name))
        if any(session_id in a for a in argv) and not any(a.endswith("journey.py") for a in argv[:3]):
            found.append(int(p.name))
    return found


@contextlib.contextmanager
def app_lock(app: str, wait_s: float = LOCK_WAIT_S, say=None):
    """Hold the app's lock: whoever starts Claude on its session holds it first. Waits `wait_s`
    (0: not at all) and raises Refused when it stays taken."""
    with open(state_dir(app) / "lock", "a+") as f:
        deadline = time.monotonic() + wait_s
        told = False
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Refused(f"{app}'s Claude session is being started or answered by another process "
                                  f"(lock {state_dir(app) / 'lock'})")
                if say and not told:
                    say(f"waiting: {app}'s Claude session is busy (the doorman is answering); this starts when it is done")
                    told = True
                time.sleep(1)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def lock_free(app: str) -> bool:
    try:
        with app_lock(app, 0):
            return True
    except Refused:
        return False


def transcript_exists(session_id: str) -> bool:
    return any((HOME / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))


# ── the webcompanion session of an app ─────────────────────────────────────

def find_session(app: str) -> dict | None:
    rows = [r for r in wc.all_sessions(KIND) if r.get("slug") == app]
    return next((r for r in rows if r.get("state", "live") == "live"), rows[0] if rows else None)


def ensure(app: str) -> dict:
    """The app's live session, reopened or made, with the published canvas as its page."""
    need_app(app)
    row = find_session(app)
    if row is not None and row.get("state", "live") != "live":
        wc.request("POST", f"/s/{row['sid']}/api/unfinish")
    if row is None:
        row = wc.request("POST", "/api/sessions", {"kind": KIND, "cwd": str(APP_HOME), "slug": app,
                                                   "title": f"{APPS[app]['name']} journey"})
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
        raise Refused(f"{app} has no journey session yet: run `journey.py ensure {app}` (or publish its canvas)")
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
    return {c["id"]: c for c in st["comments"] if c["app"] == app}


# ── Claude's state, as the canvas shows it ─────────────────────────────────

def claude_state(app: str, dirs: dict) -> dict:
    o = owner(app)
    age = heartbeat_age(dirs)
    failing = read_json(state_dir(app) / "doorman.json", {}).get("failures", 0)
    alive = is_claude(o.get("pid"))
    if o.get("mode") == "headless" and alive:
        return {"state": "answering", "label": "answering · woken by the doorman"}
    if age is not None and age < LISTENING_S:
        where = "the terminal" if o.get("mode") == "interactive" else "a session"
        return {"state": "listening", "label": f"listening in {where}"}
    if alive and o.get("mode") == "interactive":
        return {"state": "open", "label": "open in a terminal, not listening · /journey " + app}
    if failing:
        return {"state": "failing", "label": "could not answer · see the doorman log on main"}
    if CONFIG.get("doorman") is False:
        # No doorman on this machine (the Mac): Send waits until a Claude session runs /journey <app>.
        return {"state": "asleep", "label": f"not listening · Send waits for /journey {app} in a Claude session"}
    return {"state": "asleep", "label": "asleep · Send wakes it"}


def publish_state(app: str, sid: str, dirs: dict, force: bool = False) -> dict:
    st = claude_state(app, dirs)
    st["owner"] = (claude_session(app) or "")[:8]
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


# ── claim and watch ────────────────────────────────────────────────────────

def claim(app: str, session_id: str, pid: int, mode: str, cwd: str) -> dict:
    """Make `session_id` the app's Claude session, owned by `pid`. Returns the previous owner."""
    if not re.match(r"^[0-9a-f-]{36}$", session_id or ""):
        raise Refused(f"not a Claude session id: {session_id!r}")
    with app_lock(app, LOCK_WAIT_S, say=lambda m: print(m, file=sys.stderr, flush=True)):
        before = claude_session(app)
        prev = owner(app)
        set_claude_session(app, session_id)
        history = prev.get("history", [])[-9:]
        if before and before != session_id:
            history.append({"session": before, "until": now_iso()})
        write_json(state_dir(app) / "owner.json", {"session": session_id, "pid": pid, "mode": mode, "cwd": cwd,
                                                    "since": now_iso(), "history": history})
    return {"previous": before if before != session_id else None}


def watch(app: str, session_id: str) -> int:
    """`webcompanion watch` for the app's session, ended with JOURNEY_SUPERSEDED once another
    Claude session claims the app. Its lines pass through unchanged."""
    sid = sid_of(app)
    wcbin = shutil.which("webcompanion") or str(HOME / ".local" / "bin" / "webcompanion")
    child = subprocess.Popen([wcbin, "watch", "--kind", KIND, "--sid", sid], stdout=sys.stdout)
    # The canvas's Claude pill follows the watcher: with no doorman (the Mac) nothing else refreshes it.
    last_state = 0.0
    try:
        while child.poll() is None:
            if time.time() - last_state >= 30:
                last_state = time.time()
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
        "status": c["status"], "text": c["text"], "createdAt": c["createdAt"],
        "replies": [{"by": r.get("by", "user"), "text": r["text"], "at": r["createdAt"]} for r in c["replies"]],
        "waiting": store.waiting(c), "images": board_files(app, c["board"]), "link": board_link(app, c["board"]),
    }


def pending(app: str) -> dict:
    sid = sid_of(app)
    dirs = session_dirs(sid)
    events = [{"event_id": eid, **event_body(rec)} for eid, rec in pending_events(dirs)]
    comments = comments_of(app, sid)
    waiting = [describe(app, sid, c) for c in comments.values() if store.waiting(c)]
    runs = {}
    for anchor, env in (wc.get_items(sid, kind=KIND) or {}).items():
        if anchor.startswith("run/"):
            runs[anchor[4:]] = env.get("body")
    return {"app": app, "sid": sid, "folder": str(place(app)["folder"] or ""), "events": events,
            "waiting_comments": waiting, "runs": runs, "canvas": stable_link(app)}


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
    src = need_app(app)["features"]
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
    return folder / need_app(app)["results"] if folder else None


def fill(text: str, folder: Path | None) -> str:
    """{checkout}, {cli} and {home} of an apps-file word."""
    return (text.replace("{checkout}", str(folder or "")).replace("{home}", str(APP_HOME))
            .replace("{cli}", str(app_cli())))


def argv_of(template: list[str] | None, folder: Path | None, chosen: list[str] | None = None) -> list[str]:
    """An apps.json argv with {features} spread out (nothing for every feature) and its other fields
    filled in; a first word that names a file of the folder is that file."""
    if not template:
        return []
    argv = []
    for a in template:
        if a == "{features}":
            argv += chosen or []
        else:
            argv.append(fill(a, folder))
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
    argv = argv_of(p["run"], p["folder"], [] if chosen == ids else chosen)
    if argv and argv[0] == str(app_cli()):
        argv[0] = str(cli)
    # A run whose first word is the canvas checkout's own CLI (a relative path in the apps file, as on a machine
    # with no sandboxes) runs from that checkout, for the same reason.
    if argv and p["folder"] and Path(argv[0]).is_relative_to(p["folder"]):
        cwd = p["folder"]
    after = argv_of(p["after"], p["folder"])
    logs = state_dir(app) / "runs"
    logs.mkdir(exist_ok=True)
    logf = logs / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    env = {**os.environ, "FORCE_COLOR": "0", **{k: fill(v, p["folder"]) for k, v in p["env"].items()}}
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


# ── the interactive session ────────────────────────────────────────────────

def claude_launch() -> str:
    for c in (HOME / ".claude" / "bin" / "claude-launch", TOOLING_HOME / "libexec" / "claude" / "launch"):
        if c.exists():
            return str(c)
    raise Refused("no claude-launch (libexec/claude/launch of the tooling home) on this machine")


def launch(app: str) -> None:
    """Start or resume the app's Claude session here, interactive, with Remote Control on, and
    run /journey <app> in it. Waits for a headless answer to finish first."""
    need_main()
    co = session_folder(app)
    with app_lock(app, LOCK_WAIT_S, say=lambda m: print(m, flush=True)):
        sid = claude_session(app)
        resume = bool(sid and transcript_exists(sid))
        if not sid:
            sid = str(uuid.uuid4())
            set_claude_session(app, sid)
        prev = owner(app)
        o = {"session": sid, "pid": os.getpid(), "mode": "interactive", "cwd": str(co), "since": now_iso(),
             "history": prev.get("history", [])}
        if prev.get("session") and prev["session"] != sid:
            o["history"] = o["history"][-9:] + [{"session": prev["session"], "until": now_iso()}]
        write_json(state_dir(app) / "owner.json", o)
    os.chdir(co)
    # claude-launch would move a resumed session back to the folder it is filed under (env's session
    # roots); the session belongs in the app's folder, and Claude resumes a session from any folder.
    os.environ["CLAUDE_LAUNCH_HERE"] = "1"
    argv = [claude_launch(), "--remote-control", f"{MACHINE}-journey-{app}",
            *(["--resume", sid] if resume else ["--session-id", sid]), f"/journey {app}"]
    os.execv(argv[0], argv)


# ── the doorman ────────────────────────────────────────────────────────────

def headless(app: str, sid: str) -> int:
    """One answer round: resume the app's Claude session with `/journey <app> resume`, under the lock."""
    with app_lock(app, 0):
        session_id = claude_session(app)
        o = owner(app)
        if session_id and processes_naming(session_id):
            return -1
        if is_claude(o.get("pid")):
            return -1
        resume = bool(session_id and transcript_exists(session_id))
        if not session_id:
            session_id = str(uuid.uuid4())
            set_claude_session(app, session_id)
        # Claude resumes a session from any folder; it lives in the session home.
        cwd = str(session_folder(app))
        argv = [claude_launch(), "-p", *(["--resume", session_id] if resume else ["--session-id", session_id]),
                "--output-format", "stream-json", "--verbose", f"/journey {app} resume"]
        logs = state_dir(app) / "runs"
        logs.mkdir(exist_ok=True)
        logf = logs / f"wake-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl"
        log(app, f"wake: {' '.join(argv[1:])} in {cwd} > {logf}")
        with open(logf, "w") as lf:
            proc = subprocess.Popen(argv, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
            write_json(state_dir(app) / "owner.json", {**o, "session": session_id, "pid": proc.pid, "mode": "headless",
                                                        "cwd": cwd, "since": now_iso()})
            dirs = session_dirs(sid)
            publish_state(app, sid, dirs)
            try:
                code = proc.wait(HEADLESS_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, 15)
                code = proc.wait(30)
        o2 = owner(app)
        if o2.get("pid") == proc.pid:
            write_json(state_dir(app) / "owner.json", {**o2, "pid": None, "mode": "asleep", "until": now_iso()})
        log(app, f"wake ended: exit {code}")
        return code


def doorman_tick(app: str, now: float | None = None) -> str:
    """One look at an app: wake its Claude session when an event waits and nobody listens."""
    now = time.time() if now is None else now
    row = find_session(app)
    if row is None:
        return "no session"
    sid = row["sid"]
    dirs = session_dirs(sid)
    waiting = pending_events(dirs)
    st = publish_state(app, sid, dirs)
    if not waiting:
        dj = state_dir(app) / "doorman.json"
        if read_json(dj, {}).get("failures"):
            write_json(dj, {"failures": 0})
            publish_state(app, sid, dirs)
        return "idle"
    if st["state"] in ("listening", "answering", "open"):
        return st["state"]
    session_id = claude_session(app)
    if session_id and processes_naming(session_id):
        return "held"
    dj = state_dir(app) / "doorman.json"
    d = read_json(dj, {})
    failures = d.get("failures", 0)
    if failures and now < d.get("next", 0):
        return "backing off"
    if not lock_free(app):
        return "locked"
    before = {eid for eid, _ in waiting}
    try:
        code = headless(app, sid)
    except Refused:
        return "locked"
    if code == -1:
        return "held"
    left = {eid for eid, _ in pending_events(dirs)} & before
    if left:
        failures += 1
        write_json(dj, {"failures": failures, "next": time.time() + RETRY_S[min(failures, len(RETRY_S)) - 1],
                        "left": sorted(left), "exit": code})
        log(app, f"{len(left)} event(s) still waiting after the wake (exit {code}); next try in "
                 f"{RETRY_S[min(failures, len(RETRY_S)) - 1]} s")
    else:
        write_json(dj, {"failures": 0})
    publish_state(app, sid, dirs, force=True)
    return f"woke (exit {code})"


def doorman(once: bool = False, period: float = 5.0) -> int:
    need_main()
    log(None, f"doorman: watching {', '.join(APPS)}")
    import threading
    last: dict[str, str] = {}
    busy: dict[str, threading.Thread] = {}

    def tick(app: str) -> None:
        try:
            what = doorman_tick(app)
        except (wc.DaemonError, Refused, OSError) as e:
            what = f"error: {e}"
        if what != last.get(app):
            log(app, f"doorman: {what}")
            last[app] = what

    while True:
        # One thread per app, so a long answer (a full re-run) never holds another app's wake-up.
        for app in APPS:
            if app in busy and busy[app].is_alive():
                continue
            busy[app] = threading.Thread(target=tick, args=(app,), daemon=True, name=f"doorman-{app}")
            busy[app].start()
        if once:
            for t in busy.values():
                t.join()
            return 0
        time.sleep(period)


def install_doorman() -> int:
    need_main()
    lib = TOOLING_HOME / "lib" / "service.sh"
    if not lib.exists():
        raise Refused(f"{lib} is missing: this needs the tooling home's service library")
    path = ":".join([str(HOME / ".local" / "bin"), str(TOOLING_HOME / "bin"), str(TOOLING_HOME / "claude" / "bin"),
                     str(HERE.parents[1] / "bin"), "/usr/local/bin", "/usr/bin", "/bin"])
    script = "\n".join([
        "set -e", '. "$LIB"',
        'service_install journey-doorman com.claude-annotate.journey-doorman "$HOME" -- /usr/bin/python3 "$SCRIPT" doorman',
        "systemctl --user --no-pager status journey-doorman | head -5",
    ])
    env = {**os.environ, "LIB": str(lib), "SCRIPT": str(Path(__file__).resolve()), "SERVICE_PATH": path,
           "ENV_HOME": str(TOOLING_HOME)}
    return run_bounded(["bash", "-c", script], SERVICE_INSTALL_TIMEOUT_S, sys.stderr, env=env)


# ── migration from the journey-comments service ────────────────────────────

def migrate(src: Path, apply: bool) -> dict:
    """Every comment of comments.json as ops in its board's thread: create (keeping its id, number,
    time and point), each reply, an edit's time, and resolve. Ids are kept, so a second run adds nothing."""
    old = read_json(src, None)
    if not isinstance(old, dict) or not isinstance(old.get("comments"), list):
        raise Refused(f"{src} is not a journey-comments store")
    plan: dict[str, list] = {}
    for c in old["comments"]:
        app = c.get("app")
        if app not in APPS:
            continue
        anchor = c["board"] if isinstance(c["board"], str) else f"board-{c['board']}"
        msgs = plan.setdefault(app, [])
        create = {"kind": "create", "at": c["createdAt"], "uid": f"m-{c['id']}",
                  "comment": {k: c[k] for k in ("id", "app", "board", "boardTitle", "chapter", "shot", "fx", "fy",
                                                "text", "scope", "number") if k in c}}
        if c.get("audio"):
            create["comment"]["audio"] = c["audio"]
        msgs.append((anchor, {"text": c["text"], "role": "user", "op": create, "source_event_id": f"m-{c['id']}",
                              "migrated_from": "journey-comments"}))
        for r in c.get("replies", []):
            op = {"kind": "reply", "id": c["id"], "at": r["createdAt"], "uid": f"m-{r['id']}",
                  "reply": {"id": r["id"], "text": r["text"], **({"audio": r["audio"]} if r.get("audio") else {})}}
            msgs.append((anchor, {"text": r["text"], "role": "user", "op": op, "source_event_id": f"m-{r['id']}",
                                  "migrated_from": "journey-comments"}))
            if r.get("updatedAt"):
                ed = {"kind": "editReply", "id": c["id"], "replyId": r["id"], "text": r["text"], "at": r["updatedAt"],
                      "uid": f"m-{r['id']}-edit"}
                msgs.append((anchor, {"text": "Edited a reply: " + r["text"], "role": "user", "op": ed,
                                      "source_event_id": f"m-{r['id']}-edit", "migrated_from": "journey-comments"}))
        if c.get("updatedAt") and c.get("updatedAt") != c.get("resolvedAt"):
            ed = {"kind": "update", "id": c["id"], "text": c["text"], "at": c["updatedAt"], "uid": f"m-{c['id']}-edit"}
            msgs.append((anchor, {"text": "Edited: " + c["text"], "role": "user", "op": ed,
                                  "source_event_id": f"m-{c['id']}-edit", "migrated_from": "journey-comments"}))
        if c.get("status") == "resolved":
            op = {"kind": "update", "id": c["id"], "status": "resolved", "at": c.get("resolvedAt") or c.get("updatedAt"),
                  "uid": f"m-{c['id']}-resolved"}
            msgs.append((anchor, {"text": f"Resolved #{c['number']}", "role": "user", "op": op,
                                  "source_event_id": f"m-{c['id']}-resolved", "migrated_from": "journey-comments"}))
    report = {}
    for app, msgs in plan.items():
        sid = ensure(app)["sid"] if apply else (find_session(app) or {}).get("sid")
        appended = 0
        if apply:
            for anchor, body in msgs:
                res = wc.request("POST", f"/s/{sid}/threads/{wc.urllib.parse.quote(anchor, safe='')}", body)
                appended += 1 if res.get("appended") else 0
        report[app] = {"sid": sid, "messages": len(msgs), "appended": appended}
    if apply:
        report["compare"] = compare(old)
    return report


def _comparable(c: dict) -> dict:
    keep = ("id", "number", "app", "board", "boardTitle", "chapter", "shot", "fx", "fy", "text", "scope", "status",
            "createdAt", "resolvedAt", "audio")
    out = {k: c.get(k) for k in keep}
    out["replies"] = [{k: r.get(k) for k in ("id", "text", "createdAt", "audio")} for r in c.get("replies", [])]
    return out


def compare(old: dict) -> dict:
    """The old store's comments against the sessions' folded ones, field by field."""
    result = {"same": 0, "different": [], "missing": []}
    by_app: dict[str, dict] = {}
    for c in old["comments"]:
        app = c.get("app")
        if app not in APPS:
            continue
        if app not in by_app:
            by_app[app] = comments_of(app, sid_of(app))
        now = by_app[app].get(c["id"])
        if now is None:
            result["missing"].append(c["id"])
        elif _comparable(now) != _comparable(c):
            result["different"].append({"id": c["id"], "old": _comparable(c), "new": _comparable(now)})
        else:
            result["same"] += 1
    return result


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


# ── the command line ───────────────────────────────────────────────────────

def show(obj, as_json: bool) -> None:
    if as_json or not isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, ensure_ascii=False) if not isinstance(obj, str) else obj)
        return
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="journey.py", description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("apps")
    for name in ("ensure", "link", "pending", "status", "launch"):
        sub.add_parser(name).add_argument("app")
    p = sub.add_parser("claim")
    p.add_argument("app")
    p.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    p.add_argument("--pid", type=int, default=int(os.environ.get("CLAUDE_PID") or 0))
    p.add_argument("--mode", choices=("interactive", "headless"), default="interactive")
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
    p = sub.add_parser("ack")
    p.add_argument("app")
    p.add_argument("event_id")
    p = sub.add_parser("rerun")
    p.add_argument("app")
    p.add_argument("features", nargs="+")
    p.add_argument("--event", default=None)
    p = sub.add_parser("doorman")
    p.add_argument("--once", action="store_true")
    sub.add_parser("install-doorman")
    p = sub.add_parser("migrate")
    p.add_argument("file", type=Path)
    p.add_argument("--apply", action="store_true")
    p = sub.add_parser("purge")
    p.add_argument("app")
    p.add_argument("comment_id")
    a = ap.parse_args(argv)
    try:
        if a.cmd != "apps" and hasattr(a, "app"):
            need_app(a.app)
        if a.cmd == "apps":
            rows = []
            for app in APPS:
                row = find_session(app) if on_main() else None
                line = sessions_line(app)
                p = place(app)
                rows.append({"app": app, "folder": str(p["folder"] or ""), "from": p["from"],
                             "canvas": str(canvas_dir(app)),
                             "session": (row or {}).get("sid"), "claude": claude_session(app),
                             "owner": owner(app).get("mode"), "link": stable_link(app),
                             **({} if line == str(line_folder(app)) else
                                {"warning": f"sessions file starts journey-{app} in {line or 'no line'}, "
                                            f"not {line_folder(app)}"})})
            show(rows, a.json)
        elif a.cmd == "ensure":
            need_main()
            show(ensure(a.app), a.json)
        elif a.cmd == "link":
            sid_of(a.app)
            print(stable_link(a.app))
        elif a.cmd == "claim":
            need_main()
            res = claim(a.app, a.session, a.pid, a.mode, a.cwd)
            info = ensure(a.app)
            publish_state(a.app, info["sid"], session_dirs(info["sid"]), force=True)
            show({**res, **info, "claude_session": a.session}, a.json)
        elif a.cmd == "watch":
            need_main()
            return watch(a.app, a.session)
        elif a.cmd == "pending":
            show(pending(a.app), a.json)
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
        elif a.cmd == "ack":
            show(ack(a.app, a.event_id), a.json)
        elif a.cmd == "rerun":
            show(rerun(a.app, a.features, a.event), a.json)
        elif a.cmd == "status":
            sid = sid_of(a.app)
            dirs = session_dirs(sid)
            st = publish_state(a.app, sid, dirs, force=True)
            show({**st, "claude_session": claude_session(a.app), "owner": owner(a.app),
                  "watcher_age_s": heartbeat_age(dirs), "lock_free": lock_free(a.app),
                  "events_waiting": len(pending_events(dirs))}, a.json)
        elif a.cmd == "launch":
            launch(a.app)
        elif a.cmd == "doorman":
            return doorman(a.once)
        elif a.cmd == "install-doorman":
            return install_doorman()
        elif a.cmd == "migrate":
            need_main()
            show(migrate(a.file, a.apply), a.json)
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
