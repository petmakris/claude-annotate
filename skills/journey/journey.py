#!/usr/bin/env python3
"""/journey: an app's journey canvas as a webcompanion session, answered by one Claude session per app.

Every app with a journey (mealy, billpod, tunatutor) has, on petros-main only:

  * a webcompanion session of kind `journey`, slug = the app, whose page is the
    app's published canvas (~/.local/share/lomem/journey-canvas/<app>, built by
    lomem's `<app> journey publish` with claude-annotate's canvas viewer), at
    https://webcompanion.main.okimotus.com/s/<app>/. Comments are its threads,
    one per board; Send to Claude and Re-run are events on it.
  * a journey checkout, ~/projects/lomem-checkouts/<nn>-petros-journey-<app>
    (env's machines/claude-sessions, line `main journey-<app> <dir>`).
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

  apps                                   every app: checkout, session, owner, state
  ensure APP                             find or make the app's session and register its page
  link APP                               the canvas links
  claim APP [--session ID --pid PID --mode interactive|headless] [--cwd DIR]
  watch APP [--session ID]               webcompanion watch, ended when another session claims the app
  pending APP [--json]                   events waiting, comments waiting for Claude, run states
  event APP EVENT_ID                     one event, in full
  comment APP COMMENT_ID                 one comment: where, its words, its thread, its board's images
  reply APP COMMENT_ID --event EID TEXT  Claude's answer in the comment's thread
  ack APP EVENT_ID                       the event is answered (archived when no watcher will)
  rerun APP FEATURE... | all [--event EID]  run the features in the journey checkout and publish
  status APP                             write and print Claude's state for the canvas
  launch APP                             the interactive session (`@claude on main journey-<app>`)
  doorman [--once]                       the wake-up loop
  install-doorman                        the systemd user unit, the env repo's way
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
sys.path.insert(0, str(HERE.parent))  # skills/, for _shared
from _shared import webcompanion_client as wc  # noqa: E402

try:
    from . import store  # noqa: E402
except ImportError:  # run as a script
    import store  # type: ignore  # noqa: E402

KIND = "journey"
HOME = Path.home()
ENV_HOME = Path(os.environ.get("ENV_HOME") or HOME / "projects" / "env")
STATE_ROOT = Path(os.environ.get("JOURNEY_STATE") or HOME / ".local" / "state" / "journey")
# Where lomem's `<app> journey publish` writes each app's canvas (one folder per app).
CANVASES = Path(os.environ.get("JOURNEY_CANVASES") or HOME / ".local" / "share" / "lomem" / "journey-canvas")
WC_STATE = HOME / ".claude" / "webcompanion"
HOST = "petros-main"
MACHINE = "main"

APPS = {
    "mealy": {"name": "Mealy", "frontend": "apps/mealy/frontend", "scopes": {"app": "This app", "both": "Both apps"}},
    "billpod": {"name": "Billpod", "frontend": "apps/billpod/frontend", "scopes": {"app": "This app", "both": "Both apps"}},
    "tunatutor": {"name": "tunatutor", "frontend": "apps/tunatutor/frontend", "scopes": None},
}

LISTENING_S = 90  # a watcher heartbeat younger than this is someone listening
LOCK_WAIT_S = 15 * 60
HEADLESS_TIMEOUT_S = 2 * 3600
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
    return os.environ.get("JOURNEY_HOST", socket.gethostname()) == HOST


def need_main() -> None:
    if not on_main():
        raise Refused("journey sessions live only on petros-main. From here:\n"
                      "  @claude on main journey-mealy      (or journey-billpod, journey-tunatutor)\n"
                      "or in the Claude app on the phone: the session main-journey-<app>.")


def checkout(app: str) -> Path:
    """The app's journey checkout: `main journey-<app> <dir>` in env's machines/claude-sessions."""
    need_app(app)
    f = ENV_HOME / "machines" / "claude-sessions"
    try:
        for line in f.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 3 and not line.lstrip().startswith("#") and parts[0] == MACHINE and parts[1] == f"journey-{app}":
                return Path(os.path.expanduser(parts[2]))
    except OSError:
        pass
    raise Refused(f"{f} names no `{MACHINE} journey-{app} <dir>`: the app has no journey checkout")


def state_dir(app: str) -> Path:
    d = STATE_ROOT / app
    d.mkdir(parents=True, exist_ok=True)
    return d


def canvas_dir(app: str) -> Path:
    return CANVASES / app


def stable_link(app: str) -> str:
    """The canvas's one link: its session's page by slug, which opens the canvas."""
    return f"{public_base().rstrip('/')}/s/{app}/"


def now_iso() -> str:
    return store.now_iso()


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
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, p)


def claude_session(app: str) -> str | None:
    try:
        v = (state_dir(app) / "claude-session").read_text().strip()
    except OSError:
        return None
    return v if re.match(r"^[0-9a-f-]{36}$", v) else None


def set_claude_session(app: str, sid: str) -> None:
    p = state_dir(app) / "claude-session"
    tmp = p.with_name(".claude-session.tmp")
    tmp.write_text(sid + "\n")
    os.replace(tmp, p)


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
    f = open(state_dir(app) / "lock", "a+")
    deadline = time.monotonic() + wait_s
    told = False
    while True:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                f.close()
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
        f.close()


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
        row = wc.request("POST", "/api/sessions", {"kind": KIND, "cwd": str(checkout(app)), "slug": app,
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
    try:
        out = subprocess.run([str(ENV_HOME / "bin" / "@devdomains"), "url", "webcompanion"], capture_output=True,
                             text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out if out.startswith("http") else "http://127.0.0.1:3080"


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
    try:
        while child.poll() is None:
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


# ── pending work, comments, replies, acks ──────────────────────────────────

def board_files(app: str, board) -> list[str]:
    if not isinstance(board, str) or "/" not in board:
        return []
    base = canvas_dir(app) / board
    return [str(p) for p in (base.with_suffix(".png"), base.parent / f"{base.name}.phone.png") if p.exists()]


def board_link(app: str, board) -> str:
    return f"{stable_link(app)}#board-{board}"


def describe(app: str, sid: str, c: dict) -> dict:
    return {
        "id": c["id"], "number": c["number"], "board": c["board"], "boardTitle": c.get("boardTitle"),
        "feature": c.get("chapter"), "shot": c["shot"], "point": [c["fx"], c["fy"]], "scope": c["scope"],
        "status": c["status"], "text": c["text"], "createdAt": c["createdAt"],
        "replies": [{"by": r.get("by", "petros"), "text": r["text"], "at": r["createdAt"]} for r in c["replies"]],
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
    return {"app": app, "sid": sid, "checkout": str(checkout(app)), "events": events,
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
    """journey.feature's features in order: {id, name, skip} (lomem's features.ts parseFeatures)."""
    f = checkout(app) / APPS[app]["frontend"] / "e2e" / "journey" / "journey.feature"
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


def out_dir(app: str) -> Path:
    return checkout(app) / APPS[app]["frontend"] / "e2e" / "journey" / ".out"


def rerun(app: str, wanted: list[str], event_id: str | None = None) -> dict:
    """Run the features in the journey checkout (`<app> journey <ids> --publish`), with each one's
    state on the canvas, then bring the dev stack down. Only ids journey.feature has are run."""
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
    co = checkout(app)
    started = now_iso()
    for f in chosen:
        put_item(sid, f"run/{f}", {"state": "running", "at": started, "event": event_id})
    bin_ = co / "tools" / "lomem" / "bin" / app
    argv = [str(bin_), "journey", *([] if chosen == ids else chosen), "--publish"]
    logs = state_dir(app) / "runs"
    logs.mkdir(exist_ok=True)
    logf = logs / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    env = {**os.environ, "LOMEM_HOME": str(co), "FORCE_COLOR": "0"}
    log(app, f"rerun {' '.join(chosen)}: {' '.join(argv)} > {logf}")
    t0 = time.time()
    with open(logf, "w") as lf:
        code = subprocess.run(argv, cwd=co, stdout=lf, stderr=subprocess.STDOUT, env=env).returncode
        subprocess.run([str(bin_), "kill"], cwd=co, stdout=lf, stderr=subprocess.STDOUT, env=env)
    tail = logf.read_text(errors="replace").splitlines()[-25:]
    results = {}
    for f in chosen:
        man = read_json(out_dir(app) / f / "manifest.json", {})
        ok = man.get("status") == "passed" and (man.get("finishedAt") or "") >= started[:19]
        state = "passed" if ok else "failed"
        err = None if ok else (man.get("error") or f"`{app} journey` exited {code}; see {logf}")
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
    for c in (HOME / ".claude" / "bin" / "claude-launch", ENV_HOME / "libexec" / "claude" / "launch"):
        if c.exists():
            return str(c)
    raise Refused("no claude-launch (env's libexec/claude/launch) on this machine")


def launch(app: str) -> None:
    """Start or resume the app's Claude session here, interactive, with Remote Control on, and
    run /journey <app> in it. Waits for a headless answer to finish first."""
    need_main()
    co = checkout(app)
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
        cwd = o.get("cwd") if o.get("cwd") and Path(o["cwd"]).is_dir() and resume else str(checkout(app))
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
    lib = ENV_HOME / "lib" / "service.sh"
    if not lib.exists():
        raise Refused(f"{lib} is missing: this needs the env repo")
    path = ":".join([str(HOME / ".local" / "bin"), str(ENV_HOME / "bin"), str(ENV_HOME / "claude" / "bin"),
                     str(HERE.parents[1] / "bin"), "/usr/local/bin", "/usr/bin", "/bin"])
    script = "\n".join([
        "set -e", '. "$LIB"',
        'service_install journey-doorman com.petros.journey-doorman "$HOME" -- /usr/bin/python3 "$SCRIPT" doorman',
        "systemctl --user --no-pager status journey-doorman | head -5",
    ])
    env = {**os.environ, "LIB": str(lib), "SCRIPT": str(Path(__file__).resolve()), "SERVICE_PATH": path,
           "ENV_HOME": str(ENV_HOME)}
    return subprocess.run(["bash", "-c", script], env=env).returncode


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
                rows.append({"app": app, "checkout": str(checkout(app)), "session": (row or {}).get("sid"),
                             "claude": claude_session(app), "owner": owner(app).get("mode"), "link": stable_link(app)})
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
