#!/usr/bin/env python3
"""fleet: Claude Code sessions you join, that talk to each other.

Stdlib only, Python 3.9+. Store: $FLEET_HOME (default ~/.claude/fleet) / fleet.db.
Sessions are read from $FLEET_SESSIONS_DIR (default ~/.claude/sessions).
Run `fleet --help`.
"""
import argparse
import concurrent.futures
import contextlib
import io
import glob
import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import fleet_history as hist
import fleet_profiles as prof

PREVIEW = 300  # a message as one line of a list (`fleet inbox`)
WAKE_MAX = 2000  # the text a message carries into the receiver's conversation; longer is cut, naming its thread
PETROS = "petros"  # the user: a reserved member name with no session, only an inbox
INBOX_KINDS = ("ask", "tell", "notify")
PAGE = "petros:page"  # as_name of a write that comes from the fleet page


# ---------------------------------------------------------------- paths

def fleet_home():
    return os.environ.get("FLEET_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "fleet")


def sessions_dir():
    return os.environ.get("FLEET_SESSIONS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "sessions")


class FleetError(Exception):
    def __init__(self, msg, code=1):
        Exception.__init__(self, msg)
        self.code = code


# ---------------------------------------------------------------- store

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  session_id TEXT PRIMARY KEY, name TEXT NOT NULL, host TEXT, cwd TEXT, branch TEXT,
  pid INTEGER, proc_start TEXT, socket TEXT, respawn TEXT, joined_at REAL, left_at REAL, transcript_path TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, thread TEXT NOT NULL, kind TEXT NOT NULL,
  sender TEXT, sender_session TEXT, recipient TEXT, recipient_session TEXT, body TEXT,
  in_reply_to INTEGER, created_at REAL, delivered_at REAL, answered_at REAL,
  machine TEXT, remote_id INTEGER, delivery TEXT, nonce TEXT, scan_from INTEGER, confirmed_at REAL, wake TEXT);
CREATE INDEX IF NOT EXISTS messages_thread ON messages(thread);
CREATE TABLE IF NOT EXISTS todos (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, ref TEXT, notes TEXT,
  created_by TEXT, state TEXT NOT NULL DEFAULT 'open', claimed_by TEXT, claimed_session TEXT,
  reserved_for TEXT, created_at REAL, claimed_at REAL, done_at REAL, owner TEXT, after TEXT);
"""


def private_file(path):
    """When `path` exists and is readable by others, make it 0600."""
    try:
        if os.stat(path).st_mode & 0o077:
            os.chmod(path, 0o600)
    except OSError:
        pass


def private_home():
    """$FLEET_HOME, created 0700 (a looser existing one is tightened). The store holds what sessions said to
    each other and the page's token, so no other user of the machine may read it."""
    home = fleet_home()
    os.makedirs(home, mode=0o700, exist_ok=True)
    try:
        if os.stat(home).st_mode & 0o077:
            os.chmod(home, 0o700)
    except OSError:
        pass
    return home


_SCOPE = threading.local()


@contextlib.contextmanager
def db_scope():
    """Every store connection opened by this thread inside the block is closed at its end. A long-running server
    would otherwise hold each request's connections (a file and its WAL descriptors apiece) until the garbage
    collector found them, and run out of descriptors under load. The CLI needs none: its process ends."""
    outer = getattr(_SCOPE, "cons", None)
    _SCOPE.cons = []
    try:
        yield
    finally:
        for c in _SCOPE.cons:
            try:
                c.close()
            except sqlite3.Error:
                pass
        _SCOPE.cons = outer


def db():
    home = private_home()
    path = os.path.join(home, "fleet.db")
    if not os.path.exists(path):
        os.close(os.open(path, os.O_CREAT | os.O_WRONLY, 0o600))  # never created world-readable, even for a moment
    for suffix in ("", "-wal", "-shm"):
        private_file(path + suffix)
    con = sqlite3.connect(path, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    end = time.time() + 10
    while True:  # several processes opening a new store at once: switching to WAL can answer "locked" at once
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=10000")
            con.executescript(SCHEMA + hist.SCHEMA)
            break
        except sqlite3.OperationalError as e:
            if "lock" not in str(e) and "busy" not in str(e) or time.time() > end:
                raise
            time.sleep(0.05)
    for table, cols in (("messages", (("machine", "TEXT"), ("remote_id", "INTEGER"), ("delivery", "TEXT"),
                                      ("nonce", "TEXT"), ("scan_from", "INTEGER"), ("confirmed_at", "REAL"), ("wake", "TEXT"))),
                        ("members", (("transcript_path", "TEXT"),)),
                        ("todos", (("owner", "TEXT"), ("after", "TEXT"))),
                        ("conversations", (("unreadable", "INTEGER"),))):  # a store made by an older version
        have = {r["name"] for r in con.execute("PRAGMA table_info(%s)" % table)}
        for col, typ in cols:
            if col not in have:
                try:
                    con.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, typ))
                except sqlite3.OperationalError:
                    pass  # another process added it first
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS messages_remote ON messages(machine, remote_id)"
                " WHERE remote_id IS NOT NULL")
    for name in ("fleet.db-wal", "fleet.db-shm", "ui.json", "hooks.log"):
        private_file(os.path.join(home, name))
    if getattr(_SCOPE, "cons", None) is not None:
        _SCOPE.cons.append(con)
    return con


# ---------------------------------------------------------------- sessions
#
# What Claude Code documents is used wherever it documents something: `claude agents --json` for which sessions
# are alive (pid, sessionId, name, kind, state), CLAUDE_CODE_SESSION_ID and CLAUDE_CODE_MESSAGING_SOCKET for the
# session itself, `transcript_path` from hook input. The `~/.claude/sessions/<pid>.json` files are undocumented;
# they are read only as a fallback when `claude agents --json` cannot be run (their pid and start time), never
# for the socket path of a member (it is stored at join, from the environment variable) and never for a token.

_UNSET = object()


def claude_bin():
    return os.environ.get("FLEET_CLAUDE_BIN") or "claude"


def agents_list():
    """`claude agents --json` as a list of dicts, or None when it cannot be run or does not answer a list."""
    try:
        r = subprocess.run([claude_bin(), "agents", "--json"], capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if r.returncode != 0 or not isinstance(data, list):
        return None
    return [a for a in data if isinstance(a, dict)]


def session_files():
    out = []
    for path in glob.glob(os.path.join(sessions_dir(), "*.json")):
        try:
            with open(path) as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(info, dict) and info.get("pid"):
            out.append(info)
    return out


def pid_running(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (PermissionError, ValueError, TypeError):
        return True
    return True


def session_for_pid(pid, proc_start=None):
    """Fallback only: the live sessions-file record for a pid, or None."""
    if not pid_running(pid):
        return None
    for info in session_files():
        if info.get("pid") == pid and (proc_start is None or info.get("procStart") == proc_start):
            return info
    return None


def agent_for(agents, session_id):
    """The listed session with that id whose process is alive, or None."""
    for a in agents or ():
        if a.get("sessionId") == session_id and a.get("pid") and pid_running(a["pid"]):
            return a
    return None


def find_self():
    """This session: {pid, sessionId, cwd, name, messagingSocketPath, procStart?}. Its id and socket come from
    the environment Claude Code sets, the rest from `claude agents --json` (the sessions file only when that
    cannot find it)."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    sock = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET")
    agents = agents_list()
    hit = agent_for(agents, sid) if sid else None
    if hit:
        info = {"pid": hit["pid"], "sessionId": sid, "cwd": hit.get("cwd"), "name": hit.get("name"),
                "messagingSocketPath": sock}
        for f in session_files():  # the start time guards a legacy liveness check against a reused pid
            if f.get("pid") == hit["pid"]:
                info["procStart"] = f.get("procStart")
        return info
    hits = [i for i in session_files()
            if (sid and i.get("sessionId") == sid) or (sock and i.get("messagingSocketPath") == sock)]
    hits = [i for i in hits if pid_running(i["pid"])]
    if not hits:
        raise FleetError("fleet: cannot tell which Claude Code session this is "
                         "(no CLAUDE_CODE_SESSION_ID matching a live session in `claude agents --json`)")
    hits.sort(key=lambda i: i.get("updatedAt") or 0, reverse=True)
    info = dict(hits[0])
    info["messagingSocketPath"] = sock or info.get("messagingSocketPath")
    return info


def is_alive(member, agents=_UNSET):
    """Alive: `claude agents --json` lists the session with a running process. When that command cannot run,
    the pid and start time recorded at join are checked against the sessions file instead."""
    return member["left_at"] is None and session_running(member, agents)


def session_running(member, agents=_UNSET):
    """The session behind a member row is running, whether or not the member has left the fleet."""
    if agents is _UNSET:
        agents = agents_list()
    if agents is not None:
        return agent_for(agents, member["session_id"]) is not None
    return bool(member["pid"] and session_for_pid(member["pid"], member["proc_start"]))


# ---------------------------------------------------------------- machines

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]


class RemoteError(Exception):
    def __init__(self, msg, unreachable=False):
        Exception.__init__(self, msg)
        self.unreachable = unreachable


def machines_config():
    try:
        with open(os.path.join(fleet_home(), "machines.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def self_machine():
    data = machines_config()
    name = data.get("self")
    return name if isinstance(name, str) and name else socket.gethostname().split(".")[0]


def other_machines():
    """name -> {ssh, fleet, python} for every machine but this one. Empty = single-machine mode."""
    data = machines_config()
    me = self_machine()
    out = {}
    for name, m in data.items():
        if name == "self" or name == me or not isinstance(m, dict) or not m.get("ssh") or not m.get("fleet"):
            continue
        env = m.get("env") if isinstance(m.get("env"), dict) else {}
        out[name] = {"ssh": m["ssh"], "fleet": m["fleet"], "python": m.get("python") or "python3", "env": env}
    return out


def shell_word(w):
    """Quote for the remote shell, keeping a leading ~/ expandable."""
    if w.startswith("~/"):
        return "~/" + shlex.quote(w[2:])
    return shlex.quote(w)


def env_word(w):
    """Like shell_word, but a leading ~/ becomes "$HOME"/ (the shell does not expand ~ in an argument)."""
    if w.startswith("~/"):
        return '"$HOME"/' + shlex.quote(w[2:])
    return shlex.quote(w)


def remote_command(m, args):
    env = ["env"] + ["%s=%s" % (k, env_word(str(v))) for k, v in sorted((m.get("env") or {}).items())
                     if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k)]
    return " ".join((env if len(env) > 1 else []) + [shell_word(m["python"]), shell_word(m["fleet"])]
                    + [shlex.quote(a) for a in args])


def run_remote(machine, args, stdin=None, timeout=60):
    """Run `fleet <args>` on another machine over ssh; returns its stdout."""
    m = other_machines().get(machine)
    if not m:
        raise RemoteError("no machine named %r in machines.json" % machine)
    cmd = [os.environ.get("FLEET_SSH") or "ssh"] + SSH_OPTS + ["--", m["ssh"], remote_command(m, args)]
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RemoteError("timed out", unreachable=True)
    except (OSError, subprocess.SubprocessError) as e:
        raise RemoteError(str(e), unreachable=True)
    if r.returncode != 0:
        lines = (r.stderr or "").strip().splitlines()
        raise RemoteError(lines[-1] if lines else "exit %d" % r.returncode, unreachable=r.returncode == 255)
    return r.stdout


def parse_remote_json(out):
    """The JSON document at the end of a remote command's output. A login banner or a motd before it is skipped
    (the answer may span lines); anything else is a RemoteError, never a ValueError."""
    text = out or ""
    starts = [m.start() for m in re.finditer(r"(?m)^[\[{]", text)]
    dec = json.JSONDecoder()
    for strict in (True, False):
        for at in reversed(starts):
            try:
                val, end = dec.raw_decode(text[at:])
            except ValueError:
                continue
            if not strict or not text[at + end:].strip():
                return val
    raise RemoteError("answered something that is not JSON (%s)" % ((text.strip().splitlines() or ["nothing"])[-1][:80]))


def run_remote_json(machine, args, stdin=None, timeout=60, kind=None, keys=()):
    """run_remote, parsed. `kind` (list or dict) and `keys` check the shape: a wrong one is a RemoteError."""
    val = parse_remote_json(run_remote(machine, args, stdin=stdin, timeout=timeout))
    if kind is not None and not isinstance(val, kind) or any(k not in val for k in keys):
        raise RemoteError("answered JSON of an unexpected shape")
    return val


def fan_out(names, fn):
    """fn(machine) on every machine in parallel -> {machine: result or RemoteError}."""
    out = {}
    if not names:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(names)) as ex:
        futs = {n: ex.submit(fn, n) for n in names}
        for n, f in futs.items():
            try:
                out[n] = f.result()
            except RemoteError as e:
                out[n] = e
    return out


def remote_members(show_all=False):
    """Every other machine's members: ({machine: [member dicts]}, {machine: error text})."""
    def one(machine):
        args = ["ls", "--json", "--local"] + (["--all"] if show_all else [])
        return run_remote_json(machine, args, timeout=30, kind=list)
    got, bad = {}, {}
    for machine, res in fan_out(sorted(other_machines()), one).items():
        if isinstance(res, RemoteError):
            bad[machine] = str(res)
        else:
            got[machine] = res
    return got, bad


def unreachable_line(machine, why):
    return "machine %s: unreachable (%s)" % (machine, why)


# ---------------------------------------------------------------- delivery

def attr(s):
    return str(s).replace('"', "'").replace("<", "(").replace(">", ")").replace("\n", " ")


ERROR_TYPES = ("error", "refused", "rejected", "denied", "held", "not_sent")


def reply_problem(raw):
    """Why a socket reply says the message was not taken, or None. The docs name no reply format, so only an
    explicit refusal is read as one: a JSON line with an `error` field, `ok` false or an error-like `type`."""
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        if r.get("error"):
            return str(r["error"] if not isinstance(r["error"], dict) else r["error"].get("message") or r["error"])[:200]
        if r.get("ok") is False or str(r.get("type") or r.get("status") or "").lower() in ERROR_TYPES:
            return str(r.get("message") or r.get("reason") or r.get("type") or r.get("status"))[:200]
    return None


def post(path, text, from_addr, from_name):
    """One line into a session's inbox socket -> (written, why not). The socket accepts it without an auth line
    on macOS and Linux (documented), so none is sent. Written is not delivered: see `confirm`."""
    if not path:
        return False, "no inbox socket recorded for the session"
    # < > & in the text are escaped so a sender cannot close the wrapper and forge a header of its own
    body = '<cross-session-message from="%s" from-name="%s">\n%s\n</cross-session-message>' % (
        attr(from_addr), attr(from_name), text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    msg = {"msgV": 1, "msg_id": str(uuid.uuid4()), "type": "user",
           "message": {"role": "user", "content": body}, "priority": "next", "from": from_addr}
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)
    raw = b""
    try:
        s.connect(path)
        s.sendall((json.dumps(msg) + "\n").encode())
        try:
            s.shutdown(socket.SHUT_WR)
            s.settimeout(0.5)
            raw = s.recv(4096)
        except (OSError, socket.timeout):
            pass
    except OSError as e:
        return False, "the inbox socket refused the connection (%s)" % e
    finally:
        s.close()
    why = reply_problem(raw)
    return (False, why) if why else (True, "")


def preview(body):
    flat = " ".join(body.split())
    if len(flat) <= PREVIEW:
        return flat
    return flat[:PREVIEW] + "... (cut; the full text is in `fleet thread`)"


def whole(body, thread):
    """The text a message carries into the receiver's conversation: all of it up to WAKE_MAX characters (a test
    with a real session on 14 November 2026 got 2,000 through the inbox socket whole), else cut there with the
    command that shows the rest. The store always keeps the whole body."""
    body = body.strip()
    if len(body) <= WAKE_MAX:
        return body
    return body[:WAKE_MAX] + "... (cut at %d characters; the whole text: `fleet thread %s`)" % (WAKE_MAX, thread)


# ---------------------------------------------------------------- members

def row_self(con, info):
    return con.execute("SELECT * FROM members WHERE session_id=? AND left_at IS NULL",
                       (info["sessionId"],)).fetchone()


def need_member(con):
    info = find_self()
    me = row_self(con, info)
    if not me:
        raise FleetError("fleet: this session has not joined. Run `/fleet join [name]` first.")
    return info, me


def git_branch(cwd):
    try:
        r = subprocess.run(["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                           text=True, timeout=2)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def join(name=None, transcript=None):
    con = db()
    info = find_self()
    cwd = info.get("cwd") or os.getcwd()
    name = name or info.get("name") or os.path.basename(cwd.rstrip("/")) or "session"
    if name.strip().lower() == PETROS:
        raise FleetError("fleet: %r is reserved for the user, who has no session. Pick another name." % name)
    agents = agents_list()  # asked before the write lock is taken: it can be slow
    respawn = os.environ.get("FLEET_RESPAWN") or "cd %s && claude --resume %s -n %s" % (
        shlex.quote(cwd), info["sessionId"], shlex.quote(name))
    if not transcript:  # the recording hook noted it at SessionStart (hook input `transcript_path`)
        r = con.execute("SELECT transcript_path FROM conversations WHERE session_id=?", (info["sessionId"],)).fetchone()
        transcript = r[0] if r else None
    branch = git_branch(cwd)
    con.execute("BEGIN IMMEDIATE")  # the name check and the insert are one step: two joins cannot both win a name
    try:
        for m in con.execute("SELECT * FROM members WHERE name=? AND left_at IS NULL AND session_id!=?",
                             (name, info["sessionId"])).fetchall():
            if is_alive(m, agents):
                raise FleetError("fleet: the name %r is taken by a live member (session %s in %s)."
                                 % (name, m["session_id"], m["cwd"]))
            con.execute("UPDATE members SET left_at=? WHERE session_id=?", (time.time(), m["session_id"]))
        con.execute("INSERT OR REPLACE INTO members (session_id, name, host, cwd, branch, pid, proc_start, socket,"
                    " respawn, joined_at, left_at, transcript_path) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?)",
                    (info["sessionId"], name, socket.gethostname(), cwd, branch, info["pid"],
                     info.get("procStart"), info.get("messagingSocketPath"), respawn, time.time(), transcript))
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    print("joined the fleet as %s" % name)
    again = redeliver(con, name, info["sessionId"])
    if again:
        print("sent again %d message%s that reached no session" % (again, "" if again == 1 else "s"))


def leave(session_id=None):
    con = db()
    sid = session_id or find_self()["sessionId"]
    cur = con.execute("UPDATE members SET left_at=? WHERE session_id=? AND left_at IS NULL", (time.time(), sid))
    print("left the fleet" if cur.rowcount else "not in the fleet")


def forget(patterns, live=False):
    """Delete this machine's member rows whose name matches a glob in `patterns`. A live member is kept
    unless `live`. Messages stay; a forgotten session's history row just loses its fleet name."""
    import fnmatch
    con = db()
    agents = agents_list()
    rows = [m for m in con.execute("SELECT * FROM members ORDER BY joined_at").fetchall()
            if any(fnmatch.fnmatchcase(m["name"], p) for p in patterns)]
    if not rows:
        print("no member matches %s" % " ".join(patterns))
        return
    gone, kept = [], []
    for m in rows:
        if not live and member_status(m, agents) == "alive":
            kept.append(m["name"])
            continue
        con.execute("DELETE FROM members WHERE session_id=?", (m["session_id"],))
        gone.append(m["name"])
    plural = lambda n: "%d member%s" % (n, "" if n == 1 else "s")
    if gone:
        print("forgot %s: %s" % (plural(len(gone)), ", ".join(gone)))
    if kept:
        print("kept %s (add --live to forget %s too): %s"
              % ("1 live member" if len(kept) == 1 else "%d live members" % len(kept),
                 "it" if len(kept) == 1 else "them", ", ".join(kept)))


def member_status(m, agents=_UNSET):
    if m["left_at"] is not None:
        return "left"
    return "alive" if is_alive(m, agents) else "dead"


# A member's live state is worked out each time it is read, never stored, so it cannot go stale:
# - `activity`: the raw `status` that `claude agents --json` gives the session (busy, idle, waiting), else its
#   `state`; "unknown" when that command does not answer. A test on 14 November 2026 with a scratch background
#   session showed `status: waiting` (`state: blocked`) while a permission prompt was open, and `done`/`idle` after
#   a finished turn; a `blocked` entry with no pid is a stopped background job, never a live one.
# - `held`: the to-dos it holds; `unanswered`: asks and tells to it not yet answered or acknowledged.
# - `free`: only when every source answered, it is idle, and it holds nothing and owes nothing.
# - `as_of`: when this machine read it. The store is read in one read transaction, so the rows agree.

WAITING = "waiting"


def local_members(show_all=False):
    con = db()
    agents = agents_list()
    con.execute("BEGIN")
    try:
        members = con.execute("SELECT * FROM members ORDER BY joined_at").fetchall()
        held = con.execute("SELECT id, title, claimed_session FROM todos WHERE state='claimed'").fetchall()
        owed = con.execute("SELECT id, kind, sender, recipient_session, created_at FROM messages WHERE kind IN"
                           " ('ask','tell') AND answered_at IS NULL AND recipient_session IS NOT NULL ORDER BY id").fetchall()
    finally:
        con.execute("COMMIT")
    as_of = time.time()
    out = []
    for m in members:
        st = member_status(m, agents)
        if st == "left" and not show_all:
            continue
        sid = m["session_id"]
        entry = agent_for(agents, sid) if agents is not None else None
        activity = None
        if st == "alive":
            activity = "unknown" if not entry else str(entry.get("status") or entry.get("state") or "unknown")
        mine = [{"id": t["id"], "title": t["title"]} for t in held if t["claimed_session"] == sid]
        due = [{"id": x["id"], "kind": x["kind"], "sender": x["sender"], "created_at": x["created_at"]}
               for x in owed if x["recipient_session"] == sid]
        out.append({"name": m["name"], "session_id": sid, "host": m["host"], "cwd": m["cwd"],
                    "branch": m["branch"], "status": st, "respawn": m["respawn"], "joined_at": m["joined_at"],
                    "activity": activity, "agent_kind": entry.get("kind") if entry else None,
                    "held": mine, "unanswered": due,
                    "free": st == "alive" and activity == "idle" and not mine and not due, "as_of": as_of})
    return out


def state_words(m, now=None):
    """One member's live state in a few words, for `fleet ls --state`."""
    now = now or time.time()
    if m["status"] != "alive":
        words = [m["status"]]
    elif m.get("activity") is None:
        words = ["unknown (that machine's fleet does not report state)"]
    elif m["activity"] == WAITING:
        words = ["waiting (a prompt is open)"]
    else:
        words = [m["activity"]]
    if m.get("held"):
        words.append("holds " + ", ".join("#%d %s" % (t["id"], t["title"]) for t in m["held"]))
    if m.get("unanswered"):
        words.append("unanswered: " + ", ".join("%s %d from %s, %d min" % (u["kind"], u["id"], u["sender"],
                     max(0, int((now - (u["created_at"] or now)) / 60))) for u in m["unanswered"]))
    if m.get("free"):
        words.append("free")
    return "; ".join(words)


def all_members(show_all=False, local_only=False, always_machine=False):
    """Members of every machine: (rows, {machine: error}). Each row has `machine` when other machines are
    configured (or `always_machine`)."""
    out = local_members(show_all)
    others = {} if local_only else other_machines()
    bad = {}
    if others or always_machine:
        me = self_machine()
        for m in out:
            m["machine"] = me
    if others:
        got, bad = remote_members(show_all)
        for machine in sorted(got):
            for m in got[machine]:
                m["machine"] = machine
                out.append(m)
    return out, bad, bool(others)


def ls(as_json=False, show_all=False, local_only=False, state=False):
    out, bad, others = all_members(show_all, local_only)
    if as_json:
        print(json.dumps(out, indent=2))
        for machine in sorted(bad):
            print(unreachable_line(machine, bad[machine]), file=sys.stderr)
        return
    if not out:
        print("no members")
    if state:
        stamps = {}
        for m in out:
            stamps.setdefault(m.get("machine") or self_machine(), m.get("as_of"))
        for machine, t in sorted(stamps.items()):
            print("as of %s on %s" % (time.strftime("%H:%M:%S", time.localtime(t)) if t else "an unknown time", machine))
    for m in out:
        name = m["name"] if not others or m["machine"] == self_machine() else "%s@%s" % (m["name"], m["machine"])
        if state:
            print("%-20s %s" % (name, state_words(m)))
        else:
            print("%-20s %-6s %s  %s" % (name, m["status"], m["session_id"][:8], m["cwd"]))
    for machine in sorted(bad):
        print(unreachable_line(machine, bad[machine]) + ("; its members' state is unknown" if state else ""))


# ---------------------------------------------------------------- messages

def new_thread():
    # Never all digits: `fleet thread 12345678` reads a number as a message id.
    return "t" + uuid.uuid4().hex[:10]


def insert_message(con, thread, kind, me, rec, body, in_reply_to=None, machine=None, remote_id=None):
    cur = con.execute(
        "INSERT OR IGNORE INTO messages (thread,kind,sender,sender_session,recipient,recipient_session,body,"
        "in_reply_to,created_at,machine,remote_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (thread, kind, me["name"], me["session_id"], rec["name"], rec["session_id"], body, in_reply_to,
         time.time(), machine, remote_id))
    return cur.lastrowid if cur.rowcount else None


# A socket write is not a delivery: the envelope Claude Code reads (msgV, msg_id, priority, the
# cross-session-message wrapper) is not documented, so an update could stop delivery without any error. Every
# post carries a marker, `fleet-ref-<message id>-<nonce>`, and a message counts as delivered only once the
# marker shows in the target's transcript (`transcript_path`, documented hook input). `messages.delivery` is
# delivered (written, nothing to check it against), confirmed, unconfirmed (written, marker not seen yet: a
# detached `fleet _confirm` keeps looking, then falls back to a headless `claude -p` that sends through
# SendMessage, the documented path) or failed (then the user's inbox gets one line).

def env_float(name, default):
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def marker_for(mid, nonce):
    return "fleet-ref-%d-%s" % (mid, nonce)


def transcript_of(con, member):
    """The member's transcript file: recorded at join, else by the history table; None when unknown."""
    if member["transcript_path"]:
        return member["transcript_path"]
    r = con.execute("SELECT transcript_path FROM conversations WHERE session_id=?", (member["session_id"],)).fetchone()
    return r[0] if r and r[0] else None


def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def marker_seen(path, marks, start):
    """Whether any marker is in the transcript after byte `start`."""
    try:
        with open(path, "rb") as f:
            f.seek(start or 0)
            data = f.read(32 * 1024 * 1024)
    except OSError:
        return False
    return any(m.encode() in data for m in marks)


def wait_for_marker(path, marks, start, seconds, step=0.1):
    end = time.time() + seconds
    while True:
        if marker_seen(path, marks, start):
            return True
        if time.time() >= end:
            return False
        time.sleep(step)


def log_line(text):
    """One line appended to $FLEET_HOME/hooks.log (created 0600). Never raises."""
    try:
        path = os.path.join(private_home(), "hooks.log")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
        private_file(path)
    except OSError:
        pass


def delivery_log(msg):
    log_line("delivery: %s" % msg)


def member_socket(member):
    if member["socket"]:
        return member["socket"]
    info = session_for_pid(member["pid"], member["proc_start"]) if member["pid"] else None  # an old row
    return (info or {}).get("messagingSocketPath")


def deliver(con, mid, member, text, from_addr, from_name):
    """Post text to a member's session. Returns 'delivered', 'waiting' or 'failed'; the row's `delivery` says how
    sure the delivery is."""
    if member["left_at"] is not None or not is_alive(member):
        return "waiting"
    path = transcript_of(con, member)
    start = file_size(path) if path else None
    nonce = uuid.uuid4().hex[:8]
    mark = marker_for(mid, nonce)
    written, why = post(member_socket(member), "%s\n(delivery check: %s)" % (text, mark), from_addr, from_name)
    if not written:
        con.execute("UPDATE messages SET delivery='failed' WHERE id=?", (mid,))
        delivery_log("message %d to %s: not written: %s" % (mid, member["name"], why))
        print("fleet: message %d to %s was not accepted: %s" % (mid, member["name"], why), file=sys.stderr)
        return "failed"
    con.execute("UPDATE messages SET delivered_at=?, delivery='delivered', nonce=?, scan_from=?, wake=? WHERE id=?",
                (time.time(), nonce, start, text, mid))
    if path is None:
        return "delivered"
    if wait_for_marker(path, [mark], start, env_float("FLEET_CONFIRM_WAIT", 3.0)):
        con.execute("UPDATE messages SET delivery='confirmed', confirmed_at=? WHERE id=?", (time.time(), mid))
        return "delivered"
    con.execute("UPDATE messages SET delivery='unconfirmed' WHERE id=?", (mid,))
    start_follow_up(mid)
    return "delivered"


def delivery_of(con, mid):
    r = con.execute("SELECT delivery FROM messages WHERE id=?", (mid,)).fetchone()
    return r[0] if r else None


def delivery_note(delivery):
    return {"confirmed": " (confirmed in its transcript)",
            "unconfirmed": " (not seen in its transcript yet; still checking in the background)",
            "failed": ""}.get(delivery, "")


def start_follow_up(mid):
    """Detached, so the sender returns now: `fleet _confirm <id>` waits for the marker, then falls back."""
    if os.environ.get("FLEET_CONFIRM_DETACH") == "0":
        return
    try:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "_confirm", str(mid)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except OSError as e:
        delivery_log("message %d: could not start the follow-up: %s" % (mid, e))


def fallback_send(name, session_id, text):
    """The documented path: a headless `claude -p` asked to use SendMessage. -> (asked, why not). It runs through
    FLEET_CLAUDE_BIN with FLEET_NO_RECORD set, leaves no session behind and never bypasses permissions (a message
    from a bypassing sender is held by a session that prompts)."""
    prompt = ("Use your SendMessage tool to deliver the text between the lines of dashes, word for word, to the "
              "Claude Code session named %r (session id %s). If several sessions answer to that name, use the id. "
              "Do nothing else. Answer `sent` when SendMessage reports it delivered, else say why not.\n"
              "-----\n%s\n-----" % (name, session_id, text))
    cmd = [claude_bin(), "-p", "--model", os.environ.get("FLEET_FALLBACK_MODEL") or "haiku", "--no-session-persistence",
           "--strict-mcp-config", "--allowedTools", "SendMessage,ListAgents"]
    cmd += shlex.split(os.environ.get("FLEET_CLAUDE_ARGS") or "")
    env = dict(os.environ, FLEET_NO_RECORD="1")
    for k in ("FLEET_JOIN_NAME", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN"):
        env.pop(k, None)
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=180, env=env,
                           cwd=tempfile.gettempdir())
    except (OSError, subprocess.SubprocessError) as e:
        return False, "could not run %s: %s" % (cmd[0], e)
    if r.returncode != 0:
        return False, "claude -p failed (exit %d): %s" % (r.returncode, (r.stderr or r.stdout).strip()[:200])
    return True, ""


def notify_user(con, sender, body):
    """One line into the user's inbox from a name that is not a member (the fleet itself, the canary)."""
    return insert_message(con, new_thread(), "notify", {"name": sender, "session_id": None},
                          {"name": PETROS, "session_id": None}, body)


def follow_up(con, mid):
    """What `fleet _confirm <id>` does. -> the final delivery state: confirmed, confirmed-fallback (the direct post
    was not seen, the SendMessage fallback was), failed, or what it was when there is nothing to check."""
    r = con.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    if not r or r["delivery"] != "unconfirmed":
        return r["delivery"] if r else None
    member = con.execute("SELECT * FROM members WHERE session_id=?", (r["recipient_session"],)).fetchone()
    path = transcript_of(con, member) if member else None
    if not member or not path:
        return r["delivery"]
    marks = [marker_for(mid, r["nonce"])]
    if wait_for_marker(path, marks, r["scan_from"], env_float("FLEET_CONFIRM_WINDOW", 90.0), 0.5):
        con.execute("UPDATE messages SET delivery='confirmed', confirmed_at=? WHERE id=?", (time.time(), mid))
        return "confirmed"
    # A busy session takes a queued message when its turn ends, so a second copy sent now would arrive twice.
    # Keep looking while `claude agents --json` says it is busy; fall back only once it is idle and still silent.
    busy_end = time.time() + env_float("FLEET_BUSY_WINDOW", 300.0)
    while session_busy(member["session_id"]) and time.time() < busy_end:
        if wait_for_marker(path, marks, r["scan_from"], env_float("FLEET_BUSY_STEP", 2.0), 0.5):
            con.execute("UPDATE messages SET delivery='confirmed', confirmed_at=? WHERE id=?", (time.time(), mid))
            return "confirmed"
    if marker_seen(path, marks, r["scan_from"]):  # one last look before a second copy goes out
        con.execute("UPDATE messages SET delivery='confirmed', confirmed_at=? WHERE id=?", (time.time(), mid))
        return "confirmed"
    delivery_log("message %d to %s: marker not seen in %s; asking a headless claude to use SendMessage"
                 % (mid, member["name"], path))
    nonce = uuid.uuid4().hex[:8]
    marks.append(marker_for(mid, nonce))
    asked, why = fallback_send(member["name"], member["session_id"],
                               "%s\n(delivery check: %s)" % (r["wake"] or r["body"], marks[-1]))
    if asked and wait_for_marker(path, marks, r["scan_from"], env_float("FLEET_FALLBACK_WINDOW", 60.0), 0.5):
        con.execute("UPDATE messages SET delivery='confirmed', confirmed_at=? WHERE id=?", (time.time(), mid))
        delivery_log("message %d to %s: confirmed through the SendMessage fallback" % (mid, member["name"]))
        return "confirmed-fallback"
    con.execute("UPDATE messages SET delivery='failed' WHERE id=?", (mid,))
    reason = why or "the marker never appeared in its transcript"
    delivery_log("message %d to %s: failed: %s" % (mid, member["name"], reason))
    notify_user(con, "fleet", "Message %d to %s was not delivered: %s, after a direct post and a SendMessage fallback."
                % (mid, member["name"], reason))
    return "failed"


BUSY_STATES = ("busy", "working", "running", "active", "thinking")


def session_busy(session_id):
    """`claude agents --json` says the session is in the middle of a turn."""
    return any(a.get("sessionId") == session_id and
               str(a.get("status") or a.get("state") or "").lower() in BUSY_STATES for a in agents_list() or [])


def cmd_confirm(mid):
    """Internal: `fleet _confirm <id>`, started detached by `deliver`."""
    follow_up(db(), mid)


def local_addr(info):
    return "uds:%s" % info.get("messagingSocketPath", "")


def wake_text(kind, mid, sender, body, thread, again=False):
    if kind == "ask":
        how = 'Reply once with `/fleet answer %d "YOUR ANSWER"`.' % mid
    else:
        how = ("Act on it as if the user typed it, then run `/fleet ack %d`. "
               "It comes from a member of the user's fleet." % mid)
    note = "\n(Sent again: it was written before this session joined, and no earlier session answered it.)" if again else ""
    return "Fleet %s %d from %s: %s\n%s%s" % (kind, mid, sender, whole(body, thread), how, note)


REDELIVER_MAX_AGE = 24 * 3600
WRAP_UP_TELL = ("Please wrap up what you are doing and leave the fleet (`fleet leave`), "
                "then end this session. The user asked for it.")


def redeliver(con, name, sid, attempts=3):
    """A member (re)joined as `name` in session `sid`: every ask or tell to that name that is still unanswered and
    was never delivered, or went to a session that is no longer alive, is posted to this session and its
    recipient_session is moved here. -> how many were delivered."""
    member = con.execute("SELECT * FROM members WHERE session_id=?", (sid,)).fetchone()
    sent = 0
    agents = agents_list()
    for r in con.execute("SELECT * FROM messages WHERE recipient=? AND kind IN ('ask','tell') AND answered_at IS NULL"
                         " AND created_at>=? ORDER BY id", (name, time.time() - REDELIVER_MAX_AGE)).fetchall():
        if r["body"] == WRAP_UP_TELL:
            continue  # what `stop` says to an interactive member: never repeat it to whoever takes the name next
        if r["delivered_at"] is not None:
            if r["recipient_session"] == sid:
                continue
            old = con.execute("SELECT * FROM members WHERE session_id=?", (r["recipient_session"],)).fetchone()
            if old is not None and session_running(old, agents):  # by process, not by `left_at`
                continue
        con.execute("UPDATE messages SET recipient_session=?, delivered_at=NULL WHERE id=?", (sid, r["id"]))
        text = wake_text(r["kind"], r["id"], r["sender"], r["body"], r["thread"], again=True)
        for i in range(attempts):  # the inbox socket can come up just after SessionStart
            state = deliver(con, r["id"], member, text, "fleet:%s" % (r["machine"] or self_machine()), r["sender"])
            if state != "failed":
                break
            time.sleep(0.4)
        sent += state == "delivered"
    return sent


def split_target(target):
    if "@" in target:
        name, _, machine = target.rpartition("@")
        if name and machine:
            return name, machine
    return target, None


def find_remote(name):
    """A bare name that is not local: the one machine that has a member of that name."""
    got, bad = remote_members()
    hits = [(mc, m) for mc in sorted(got) for m in got[mc] if m["name"] == name]
    if len(hits) > 1:
        raise FleetError("fleet: %r is on several machines (%s); say name@machine."
                         % (name, ", ".join(mc for mc, _ in hits)))
    if not hits:
        hint = "".join("\n" + unreachable_line(mc, why) for mc, why in sorted(bad.items()))
        raise FleetError("fleet: no member named %r. `fleet ls` lists them.%s" % (name, hint))
    return hits[0][0]


def targets(con, me, target):
    """[('local', member row) | ('remote', machine, name)] and report lines for machines that did not answer."""
    notes = []
    if target == "*":
        agents = agents_list()
        out = [("local", m) for m in con.execute("SELECT * FROM members WHERE left_at IS NULL AND session_id!=?",
                                                 (me["session_id"],)) if is_alive(m, agents)]
        if other_machines():
            got, bad = remote_members()
            for machine in sorted(got):
                out += [("remote", machine, m["name"]) for m in got[machine] if m["status"] == "alive"]
            notes = [unreachable_line(mc, why) for mc, why in sorted(bad.items())]
        skipped = [t for t in out if is_job(target_name(t))]
        out = [t for t in out if not is_job(target_name(t))]
        if skipped:
            notes.append("skipped %d job%s (a broadcast never reaches a job; name it to reach it): %s"
                         % (len(skipped), "" if len(skipped) == 1 else "s", ", ".join(target_label(t) for t in skipped)))
        if not out:
            raise FleetError("fleet: no other live member to send to%s." % (" but jobs" if skipped else ""))
        return out, notes
    name, machine = split_target(target)
    if machine and machine != self_machine():
        if machine not in other_machines():
            raise FleetError("fleet: no machine named %r in machines.json." % machine)
        return [("remote", machine, name)], notes
    if name == me["name"]:
        raise FleetError("fleet: %r is this session." % target)
    m = con.execute("SELECT * FROM members WHERE name=? AND left_at IS NULL ORDER BY joined_at DESC",
                    (name,)).fetchone()
    if m:
        return [("local", m)], notes
    if machine or not other_machines():
        raise FleetError("fleet: no member named %r. `fleet ls` lists them." % target)
    return [("remote", find_remote(name), name)], notes


JOB_PREFIX = "job:"  # a member that is a job of a job runner: a broadcast (`*`) skips it, a tell by name reaches it


def is_job(name):
    return name.startswith(JOB_PREFIX)


def target_name(t):
    return t[1]["name"] if t[0] == "local" else t[2]


def target_label(t):
    return t[1]["name"] if t[0] == "local" else "%s@%s" % (t[2], t[1])


def send_remote(con, me, kind, thread, machine, name, body):
    shown = "%s@%s" % (name, machine)
    mid = insert_message(con, thread, kind, me, {"name": shown, "session_id": None}, body, machine=machine)
    payload = {"thread": thread, "kind": kind, "body": body, "target": name, "origin_id": mid,
               "sender": me["name"], "sender_session": me["session_id"], "sender_machine": self_machine()}
    try:
        res = run_remote_json(machine, ["_deliver"], json.dumps(payload), kind=dict, keys=("id", "state"))
    except RemoteError as e:
        state = "unreachable (%s; stored here, not delivered)" % e if e.unreachable else "failed (%s)" % e
        print("message %d to %s: %s" % (mid, shown, state))
        return
    con.execute("UPDATE messages SET remote_id=?, recipient_session=?, delivered_at=? WHERE id=?",
                (res["id"], res.get("session"), time.time() if res["state"] == "delivered" else None, mid))
    print("message %d to %s: %s%s" % (mid, shown, res["state"], " (dead; it will wait)" if res["state"] == "waiting"
                                       else delivery_note(res.get("delivery"))))


def member_or_none(con):
    try:
        return need_member(con)
    except FleetError:
        return None


def acting(con, as_name=None):
    """Who is sending: (sessions-file info, member row), or ({}, the user) when a session outside the fleet
    sends `--as petros` (or with FLEET_AS=petros). A member always speaks as itself."""
    if as_name == PAGE:  # the fleet page: the user at his own page, whatever session started the server
        return {}, {"name": PETROS, "session_id": None}
    as_name = as_name or os.environ.get("FLEET_AS")
    if as_name:
        if as_name.strip().lower() != PETROS:
            raise FleetError("fleet: --as takes only %r." % PETROS)
        mine = member_or_none(con)
        if mine:
            raise FleetError("fleet: this session is a member (%s) and speaks as itself; only a session outside "
                             "the fleet sends as %s." % (mine[1]["name"], PETROS))
        return {}, {"name": PETROS, "session_id": None}
    return need_member(con)


def is_petros(target):
    return split_target(target)[0].strip().lower() == PETROS


def send_petros(con, me, kind, target, body):
    """A message to the user is stored, never posted: it is his inbox (`fleet inbox`)."""
    if split_target(target)[1]:
        raise FleetError("fleet: %s's inbox is on the machine that sent the message; write just %r." % (PETROS, PETROS))
    if me["name"] == PETROS:
        raise FleetError("fleet: that is you.")
    thread = new_thread()
    mid = insert_message(con, thread, kind, me, {"name": PETROS, "session_id": None}, body)
    print("thread %s" % thread)
    print("message %d to %s: stored in his inbox" % (mid, PETROS))
    return thread


def send(kind, target, body, as_name=None):
    con = db()
    info, me = acting(con, as_name)
    if is_petros(target):
        return send_petros(con, me, kind, target, body)
    todo, notes = targets(con, me, target)
    thread = new_thread()
    print("thread %s" % thread)
    for n in notes:
        print(n)
    for t in todo:
        if t[0] == "remote":
            send_remote(con, me, kind, thread, t[1], t[2], body)
            continue
        m = t[1]
        mid = insert_message(con, thread, kind, me, m, body)
        state = deliver(con, mid, m, wake_text(kind, mid, me["name"], body, thread),
                        local_addr(info) if info else "fleet:%s" % PETROS, me["name"])
        print("message %d to %s: %s%s" % (mid, m["name"], state, " (dead; it will wait)" if state == "waiting"
                                       else delivery_note(delivery_of(con, mid))))
    return thread


def notify(body):
    """A member tells the user something: stored in his inbox."""
    con = db()
    info, me = need_member(con)
    mid = insert_message(con, new_thread(), "notify", me, {"name": PETROS, "session_id": None}, body)
    print("notice %d stored in %s's inbox" % (mid, PETROS))


def cmd_deliver():
    """Internal: `fleet _deliver`, run on the target's machine. A message as JSON on stdin is stored here,
    in the target's store, and posted to the target's socket. Prints {id, state, session} as JSON."""
    p = json.loads(sys.stdin.read())
    con = db()
    m = con.execute("SELECT * FROM members WHERE name=? AND left_at IS NULL ORDER BY joined_at DESC",
                    (p["target"],)).fetchone()
    if not m:
        raise FleetError("fleet: no member named %r on %s." % (p["target"], self_machine()))
    shown = "%s@%s" % (p["sender"], p["sender_machine"])
    sender = {"name": shown, "session_id": p["sender_session"]}
    mid = insert_message(con, p["thread"], p["kind"], sender, m, p["body"], machine=p["sender_machine"],
                         remote_id=p["origin_id"])
    if mid is None:  # the same message sent twice
        raise FleetError("fleet: message already stored.")
    state = deliver(con, mid, m, wake_text(p["kind"], mid, shown, p["body"], p["thread"]), "fleet:%s" % p["sender_machine"],
                    shown)
    print(json.dumps({"id": mid, "state": state, "session": m["session_id"], "delivery": delivery_of(con, mid)}))


def parse_ref(ref):
    """'12' or '12@machine' -> (12, machine or None)."""
    if str(ref).startswith("lungo:"):
        raise FleetError("fleet: %s is Lungo's; the fleet only shows it. Act on it in Lungo." % ref)
    num, _, machine = str(ref).partition("@")
    if not num.isdigit():
        raise FleetError("fleet: %r is not a message id (12, or 12@machine for another machine)." % ref)
    return int(num), (machine or None)


def petros_remote(ref, verb_args):
    """A petros action on an item that lives on another machine: run it there. -> True when it was forwarded."""
    mid, machine = parse_ref(ref)
    if not machine or machine == self_machine():
        return False
    if machine not in other_machines():
        raise FleetError("fleet: no machine named %r in machines.json." % machine)
    try:
        sys.stdout.write(run_remote(machine, [verb_args[0], str(mid)] + verb_args[1:] + ["--as", PETROS], timeout=60))
    except RemoteError as e:
        raise FleetError("fleet: %s %s: %s" % (machine, "unreachable" if e.unreachable else "failed", e))
    return True


NOUN = {"ask": "ask", "tell": "tell", "notify": "notice"}


def reply(kind, ref, body, as_name=None):
    """answer (to an ask) or ack (of a tell). As petros, answer any item of his inbox."""
    con = db()
    petros = bool(as_name or os.environ.get("FLEET_AS")) and kind == "answer"
    if petros and petros_remote(ref, ["answer", body]):
        return
    msg_id, where = parse_ref(ref)
    if where and not petros:
        raise FleetError("fleet: name@machine ids are only for the user's inbox (--as petros).")
    info, me = acting(con, as_name) if petros else need_member(con)
    orig = con.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    if petros:
        if not orig or orig["recipient"] != PETROS or orig["kind"] not in INBOX_KINDS:
            raise FleetError("fleet: message %s is not in %s's inbox." % (msg_id, PETROS))
    else:
        want = "ask" if kind == "answer" else "tell"
        if not orig or orig["kind"] != want:
            raise FleetError("fleet: message %s is not an %s." % (msg_id, want))
        if orig["recipient_session"] != me["session_id"]:
            raise FleetError("fleet: message %s was not sent to this session." % msg_id)
    already = FleetError("fleet: message %s is already %s." % (msg_id, "answered" if kind == "answer" else "acknowledged"))
    if orig["answered_at"] is not None:
        raise already
    rec = {"name": orig["sender"], "session_id": orig["sender_session"]}
    con.execute("BEGIN IMMEDIATE")  # claim and store as one step: of two answers at once exactly one is stored
    try:
        claimed = con.execute("UPDATE messages SET answered_at=? WHERE id=? AND answered_at IS NULL",
                              (time.time(), msg_id)).rowcount
        rid = insert_message(con, orig["thread"], kind, me, rec, body, in_reply_to=msg_id,
                             machine=orig["machine"]) if claimed else None
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    if not claimed:
        raise already
    print("%s %d stored" % (kind, rid))
    if orig["machine"]:  # the asker is on another machine: the answer goes back there
        payload = {"thread": orig["thread"], "kind": kind, "body": body, "origin_id": orig["remote_id"],
                   "answer_id": rid, "sender": me["name"], "sender_machine": self_machine()}
        try:
            res = run_remote_json(orig["machine"], ["_answer"], json.dumps(payload), kind=dict, keys=("id", "state"))
        except RemoteError as e:
            print("asker: %s (the answer is stored here; `fleet wait` on %s fetches it)" % (
                "unreachable" if e.unreachable else "failed: %s" % e, orig["machine"]))
            return
        con.execute("UPDATE messages SET remote_id=? WHERE id=?", (res["id"], rid))
        print("asker: %s" % res["state"])
        return
    asker = con.execute("SELECT * FROM members WHERE session_id=?", (orig["sender_session"],)).fetchone()
    if kind == "answer" and asker:
        text = "Fleet answer %d to your %s %d from %s: %s\nThe whole thread: `fleet thread %s`." % (
            rid, NOUN.get(orig["kind"], "ask"), msg_id, me["name"], whole(body, orig["thread"]), orig["thread"])
        print("asker: %s" % deliver(con, rid, asker, text, local_addr(info) if info else "fleet:%s" % PETROS, me["name"]))


def dismiss(ref, as_name=None):
    """The user clears an inbox item. An ask gets an answer saying so, so its asker stops waiting."""
    con = db()
    acting(con, as_name or PETROS)
    if petros_remote(ref, ["dismiss"]):
        return
    msg_id = parse_ref(ref)[0]
    orig = con.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    if not orig or orig["recipient"] != PETROS or orig["kind"] not in INBOX_KINDS:
        raise FleetError("fleet: message %s is not in %s's inbox." % (msg_id, PETROS))
    if orig["answered_at"] is not None:
        raise FleetError("fleet: message %s is already cleared." % msg_id)
    if orig["kind"] == "ask":
        return reply("answer", str(msg_id), "(%s dismissed this without answering.)" % PETROS, PETROS)
    con.execute("UPDATE messages SET answered_at=? WHERE id=?", (time.time(), msg_id))
    print("dismissed %d" % msg_id)


def inbox_local(show_all=False, limit=200):
    con = db()
    me = self_machine()
    rows = con.execute("SELECT * FROM messages WHERE recipient=? AND kind IN ('ask','tell','notify')%s"
                       " ORDER BY id DESC LIMIT ?" % ("" if show_all else " AND answered_at IS NULL"),
                       (PETROS, limit)).fetchall()
    out = []
    for r in rows:
        rep = con.execute("SELECT body FROM messages WHERE in_reply_to=? AND kind='answer' ORDER BY id LIMIT 1",
                          (r["id"],)).fetchone()
        out.append({"id": r["id"], "machine": me, "thread": r["thread"], "kind": r["kind"], "sender": r["sender"],
                    "body": r["body"], "created_at": r["created_at"], "answered_at": r["answered_at"],
                    "reply": rep["body"] if rep else None})
    return out


# ---------------------------------------------------------------- Lungo: what a job runner needs from the user
#
# Lungo, the user's job runner, keeps its own list of what waits on him. The fleet reads it when the inbox is read
# (`fleet inbox`, the page's For you) and never stores it: there is one source of truth, and each item is shown
# with the time Lungo wrote it. The command that prints Lungo's brief is configured per machine in
# $FLEET_HOME/lungo.json, {"command": ["ssh", "<host>", "<path>/@lungo status --short --json"], "ttl": 60}, so no
# host is named here. Without the file, nothing is read. A read that fails, or a brief of another shape, is shown
# as "Lungo unreachable", never as nothing to do. Only the asking machine reads it (a fan-out asks `--local`).

LUNGO_SCHEMA = "lungo.brief/1"
LUNGO_TTL = 60.0
LUNGO_ERROR_TTL = 10.0
_LUNGO = {"at": 0.0, "val": None, "key": None}
_LUNGO_LOCK = threading.Lock()


def lungo_config():
    """lungo.json as a dict, None when there is none, or {"error": ...} when it is not usable."""
    path = os.path.join(fleet_home(), "lungo.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            conf = json.load(f)
    except (OSError, ValueError) as e:
        return {"error": "cannot read %s (%s)" % (path, e)}
    cmd = conf.get("command") if isinstance(conf, dict) else None
    if not (isinstance(cmd, list) and cmd and all(isinstance(w, str) for w in cmd)):
        return {"error": "%s needs \"command\" as a list of words" % path}
    return conf


def iso_epoch(s):
    """'2026-11-14T15:41:50+01:00' -> seconds, or None."""
    if not isinstance(s, str) or not s:
        return None
    try:
        import datetime
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def lungo_items(doc):
    """The needs-you rows of a Lungo brief -> (items, count). The brief lists its rows group by group, needs-you
    first, and never cuts those (Lungo's SPEC, "The brief says where each plan is"); each such row has `attention`.
    Anything else raises ValueError, so a changed brief is reported, never misread."""
    if not isinstance(doc, dict) or doc.get("ok") is not True or not isinstance(doc.get("data"), dict):
        raise ValueError("it did not answer ok (%s)" % str((doc or {}).get("error") if isinstance(doc, dict) else doc)[:120])
    data = doc["data"]
    if data.get("schema") != LUNGO_SCHEMA:
        raise ValueError("its brief has schema %r, not %s" % (data.get("schema"), LUNGO_SCHEMA))
    n = (data.get("counts") or {}).get("needs_petros")
    jobs = data.get("jobs")
    if not isinstance(n, int) or not isinstance(jobs, list) or len(jobs) < n:
        raise ValueError("its brief has no needs_petros count or fewer rows than it counts")
    items = []
    for row in jobs[:n]:
        if not isinstance(row, dict) or not row.get("attention") or not row.get("name"):
            raise ValueError("a needs-you row of its brief has no attention or name")
        machine = str(row.get("machine") or "")
        text = row.get("step") or row.get("question") or row.get("line") or row.get("say") or row["name"]
        items.append({"id": None, "ref": "lungo:%s/%s" % (machine, row["name"]), "machine": machine,
                      "thread": None, "kind": "lungo", "sender": "Lungo", "title": row.get("say") or row["name"],
                      "job": row["name"], "attention": row["attention"], "lungo_kind": row.get("kind"),
                      "body": str(text), "created_at": iso_epoch(row.get("asked") or row.get("ended")),
                      "answered_at": None, "reply": None})
    return items, n


def lungo_read(conf):
    now = time.time()
    try:
        r = subprocess.run(conf["command"], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=float(conf.get("timeout") or 30))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "it did not answer in time", "read_at": now}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)[:160], "read_at": now}
    try:
        doc = parse_remote_json(r.stdout)
        items, n = lungo_items(doc)
    except (RemoteError, ValueError) as e:
        why = str(e) if r.returncode == 0 else "exit %d: %s" % (r.returncode, ((r.stderr or r.stdout).strip().splitlines()
                                                                                 or [str(e)])[-1][:160])
        return {"ok": False, "error": why, "read_at": now}
    return {"ok": True, "items": items, "count": n, "as_of": doc["data"].get("as_of"), "read_at": now}


def lungo_needs():
    """What Lungo says waits on the user, read live and kept in this process for `ttl` seconds (10 after a failure)
    -> None when lungo.json does not exist, else {ok, items, count, as_of, read_at} or {ok: False, error, read_at}."""
    conf = lungo_config()
    if conf is None:
        return None
    if conf.get("error"):
        return {"ok": False, "error": conf["error"], "read_at": time.time()}
    key = json.dumps(conf, sort_keys=True)
    with _LUNGO_LOCK:
        hit = _LUNGO["val"]
        ttl = env_float("FLEET_LUNGO_TTL", float(conf.get("ttl") or LUNGO_TTL))
        if hit and _LUNGO["key"] == key and time.time() - _LUNGO["at"] < (ttl if hit["ok"] else min(ttl, LUNGO_ERROR_TTL)):
            return hit
        val = lungo_read(conf)
        _LUNGO.update(at=time.time(), val=val, key=key)
        return val


def lungo_line(lz):
    """One line about Lungo for the inbox: how many items and as of when, or why they are not shown."""
    if not lz["ok"]:
        return "Lungo: unreachable (%s); what it needs from you is not shown" % lz["error"]
    when = time.strftime("%H:%M", time.localtime(iso_epoch(lz.get("as_of")) or lz["read_at"]))
    return "Lungo, as of %s: %d need%s you" % (when, lz["count"], "s" if lz["count"] == 1 else "")


def inbox_all(show_all=False, local_only=False):
    """The user's inbox on every machine, newest first, with what Lungo needs from him:
    (items, {machine: error}, Lungo's answer or None)."""
    items, bad = inbox_local(show_all), {}
    me = self_machine()
    lz = None
    if not local_only:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            lungo_future = ex.submit(lungo_needs)  # read beside the other machines, not after them
            if other_machines():
                def one(machine):
                    return run_remote_json(machine, ["inbox", "--json", "--local"] + (["--all"] if show_all else []),
                                           timeout=30, kind=list)
                for machine, res in fan_out(sorted(other_machines()), one).items():
                    if isinstance(res, RemoteError):
                        bad[machine] = str(res)
                    else:
                        items += res
            lz = lungo_future.result()
    for i in items:
        i["ref"] = str(i["id"]) if i["machine"] == me else "%s@%s" % (i["id"], i["machine"])
    if lz and lz["ok"]:
        items += [dict(i) for i in lz["items"]]
    items.sort(key=lambda i: -(i["created_at"] or 0))
    return items, bad, lz


def inbox(as_json=False, show_all=False, local_only=False):
    items, bad, lz = inbox_all(show_all, local_only)
    if as_json:
        print(json.dumps(items, indent=2))
        for machine in sorted(bad):
            print(unreachable_line(machine, bad[machine]), file=sys.stderr)
        if lz and not lz["ok"]:
            print(lungo_line(lz), file=sys.stderr)
        return
    fleet_items = [i for i in items if i["kind"] != "lungo"]
    if not fleet_items:
        print("nothing for %s in the fleet" % PETROS if lz else "nothing for %s" % PETROS)
    now = time.time()
    for i in fleet_items:
        state = "" if i["answered_at"] is None else " (answered)" if i["reply"] else " (cleared)"
        print("[%s] %s from %s, %d min ago%s: %s" % (i["ref"], i["kind"], i["sender"],
              max(0, int((now - (i["created_at"] or now)) / 60)), state, preview(i["body"])))
    if lz:
        print(lungo_line(lz))
        for i in items:
            if i["kind"] == "lungo":
                age = "" if i["created_at"] is None else ", %s ago" % ago_words(now - i["created_at"])
                print("[%s] %s%s: %s: %s" % (i["ref"], i["lungo_kind"] or i["attention"], age, i["title"], preview(i["body"])))
    for machine in sorted(bad):
        print(unreachable_line(machine, bad[machine]))


def ago_words(s):
    s = max(0, int(s))
    if s < 3600:
        return "%d min" % (s // 60)
    if s < 2 * 86400:
        return "%d h" % (s // 3600)
    return "%d days" % (s // 86400)


def cmd_answer():
    """Internal: `fleet _answer`, run on the asker's machine: store an answer or ack to one of this store's
    asks or tells (JSON on stdin) and wake the asker. Prints {id, state}."""
    p = json.loads(sys.stdin.read())
    con = db()
    orig = con.execute("SELECT * FROM messages WHERE id=? AND thread=? AND kind IN ('ask','tell')",
                       (p["origin_id"], p["thread"])).fetchone()
    if not orig:
        raise FleetError("fleet: no such message here.")
    shown = "%s@%s" % (p["sender"], p["sender_machine"])
    rid = store_remote_reply(con, orig, p["kind"], shown, p["sender_machine"], p["answer_id"], p["body"])
    state = "stored"
    asker = con.execute("SELECT * FROM members WHERE session_id=?", (orig["sender_session"],)).fetchone()
    if rid and p["kind"] == "answer" and asker:
        text = "Fleet answer %d to your ask %d from %s: %s\nThe whole thread: `fleet thread %s`." % (
            rid, orig["id"], shown, whole(p["body"], orig["thread"]), orig["thread"])
        state = deliver(con, rid, asker, text, "fleet:%s" % p["sender_machine"], shown)
    print(json.dumps({"id": rid, "state": state}))


def store_remote_reply(con, orig, kind, shown, machine, remote_id, body):
    """File a reply from another machine under the message it answers; None when it is already filed."""
    con.execute("BEGIN IMMEDIATE")
    try:
        rid = insert_message(con, orig["thread"], kind, {"name": shown, "session_id": None},
                             {"name": orig["sender"], "session_id": orig["sender_session"]}, body,
                             in_reply_to=orig["id"], machine=machine, remote_id=remote_id)
        if rid:
            con.execute("UPDATE messages SET answered_at=? WHERE id=?", (time.time(), orig["id"]))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return rid


def cmd_thread(th):
    """Internal: `fleet _thread <thread>`: this store's rows of a thread, as JSON."""
    print(json.dumps([dict(r) for r in thread_rows(db(), th)]))


def pull_thread(con, th):
    """Fetch replies that are stored on another machine (the push back failed or has not happened) for
    the asks and tells this store sent there. Unreachable machines are skipped."""
    rows = con.execute("SELECT * FROM messages WHERE thread=? AND kind IN ('ask','tell') AND machine IS NOT NULL"
                       " AND answered_at IS NULL AND remote_id IS NOT NULL AND recipient_session IS NOT NULL"
                       " AND sender_session IN (SELECT session_id FROM members)", (th,)).fetchall()
    for machine in sorted({r["machine"] for r in rows}):
        try:
            theirs = run_remote_json(machine, ["_thread", th], timeout=30, kind=list)
        except RemoteError:
            continue
        for orig in (r for r in rows if r["machine"] == machine):
            for t in theirs:
                if t["kind"] in ("answer", "ack") and t["in_reply_to"] == orig["remote_id"]:
                    store_remote_reply(con, orig, t["kind"], "%s@%s" % (t["sender"], machine), machine,
                                       t["id"], t["body"])


def resolve_thread(con, ident):
    if ident.isdigit():
        r = con.execute("SELECT thread FROM messages WHERE id=?", (int(ident),)).fetchone()
        if not r:
            raise FleetError("fleet: no message %s." % ident)
        return r["thread"]
    if not con.execute("SELECT 1 FROM messages WHERE thread=?", (ident,)).fetchone():
        raise FleetError("fleet: no thread %s." % ident)
    return ident


def thread_rows(con, thread):
    return con.execute("SELECT * FROM messages WHERE thread=? ORDER BY id", (thread,)).fetchall()


def show_thread(rows):
    for r in rows:
        extra = " (reply to %d)" % r["in_reply_to"] if r["in_reply_to"] else ""
        print("[%d] %s %s -> %s%s\n%s\n" % (r["id"], r["kind"], r["sender"], r["recipient"], extra, r["body"]))


def thread(ident, as_json=False):
    con = db()
    th = resolve_thread(con, ident)
    if other_machines():
        pull_thread(con, th)
    rows = thread_rows(con, th)
    if as_json:
        print(json.dumps([dict(r) for r in rows], indent=2))
    else:
        show_thread(rows)


def pending(rows):
    return [r for r in rows if r["kind"] in ("ask", "tell") and r["answered_at"] is None]


def wait(ident, timeout, interval=0.3):
    con = db()
    th = resolve_thread(con, ident)
    deadline = time.time() + timeout
    cross = bool(other_machines())
    next_pull = 0
    while True:
        if cross and time.time() >= next_pull and pending(thread_rows(con, th)):
            pull_thread(con, th)
            next_pull = time.time() + 2
        rows = thread_rows(con, th)
        left = pending(rows)
        if not left or time.time() >= deadline:
            break
        time.sleep(interval)
    show_thread([r for r in rows if r["kind"] in ("answer", "ack")])
    if left:
        print("timed out; no answer from: %s" % ", ".join(r["recipient"] for r in left))
        return 3
    print("all answered")
    return 0


# ---------------------------------------------------------------- spawn

def spawn_settings(name):
    return json.dumps({"env": {"FLEET_JOIN_NAME": name, "FLEET_HOME": fleet_home()},
                       "crossSessionInbound": "accept"}, separators=(",", ":"))


def spawn_on(machine, name, cwd, prompt, as_json=False):
    args = ["spawn", name, cwd, prompt] + (["--json"] if as_json else [])
    try:
        sys.stdout.write(run_remote(machine, args, timeout=180))
    except RemoteError as e:
        raise FleetError("fleet: spawn on %s %s: %s" % (machine, "unreachable" if e.unreachable else "failed", e))


def find_started(name, since_ms, wait=None):
    """The background session `name` that started after `since_ms`, found in `claude agents --json` (it can take
    a moment to be listed). -> its entry, or None."""
    end = time.time() + (env_float("FLEET_FIND_WAIT", 10.0) if wait is None else wait)
    while True:
        hits = [a for a in agents_list() or []
                if a.get("name") == name and a.get("kind") in ("bg", "background") and (a.get("startedAt") or 0) >= since_ms]
        if hits:
            return max(hits, key=lambda a: a.get("startedAt") or 0)
        if time.time() >= end:
            return None
        time.sleep(0.3)


def start_background(args, cwd, name, prompt=None):
    """`claude <args> [prompt]` in cwd, started as the background session `name`; -> the id `claude agents --json`
    lists it under. FLEET_CLAUDE_ARGS adds arguments."""
    cmd = [claude_bin()] + args + shlex.split(os.environ.get("FLEET_CLAUDE_ARGS") or "")
    if prompt:
        cmd.append(prompt)
    since = int(time.time() * 1000) - 2000
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise FleetError("fleet: could not run %s: %s" % (cmd[0], e))
    text = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        if "trust" in text.lower():
            raise FleetError("fleet: Claude Code does not trust %s, and --bg refuses an untrusted folder.\n"
                             "Fix: run `claude` once in that folder and accept the trust prompt, then try again.\n%s"
                             % (cwd, text))
        raise FleetError("fleet: claude --bg failed (exit %d): %s" % (r.returncode, text))
    entry = find_started(name, since)
    if not entry:
        raise FleetError("fleet: claude --bg started %r but `claude agents --json` does not list it (output: %s)."
                         % (name, text[:200] or "none"))
    return entry.get("id") or (entry.get("sessionId") or "")[:8]


def spawn(name, cwd, prompt, as_json=False, on=None, extra=()):
    """Start a background session that joins the fleet as `name` before it reads the prompt."""
    if name.strip().lower() == PETROS:
        raise FleetError("fleet: %r is reserved for the user. Pick another name." % name)
    if on and on != self_machine():
        return spawn_on(on, name, cwd, prompt, as_json)
    con = db()
    for m in con.execute("SELECT * FROM members WHERE name=? AND left_at IS NULL", (name,)):
        if is_alive(m):
            raise FleetError("fleet: the name %r is taken by a live member (session %s in %s)."
                             % (name, m["session_id"], m["cwd"]))
    cwd = os.path.abspath(os.path.expanduser(cwd))
    if not os.path.isdir(cwd):
        raise FleetError("fleet: %s is not a folder." % cwd)
    sid = start_background(["--bg", "-n", name, "--settings", spawn_settings(name)] + list(extra), cwd, name, prompt)
    out = {"name": name, "id": sid, "cwd": cwd, "attach": "claude attach %s" % name}
    if as_json:
        print(json.dumps(out, indent=2))
    else:
        print("started %s (id %s) in %s\nattach: %s" % (name, sid, cwd, out["attach"]))
    return out


# ---------------------------------------------------------------- control: stop, respawn, attach

def bg_agents():
    """`claude agents --json`: the background sessions the daemon runs. Raises FleetError when it cannot."""
    try:
        r = subprocess.run([claude_bin(), "agents", "--json"], capture_output=True, text=True, timeout=20)
        data = json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        raise FleetError("fleet: cannot list background sessions with `claude agents --json` (%s)." % e)
    if r.returncode != 0 or not isinstance(data, list):
        raise FleetError("fleet: `claude agents --json` failed: %s" % ((r.stderr or r.stdout or "").strip()[:200]))
    return [a for a in data if isinstance(a, dict)]


def bg_entry(member):
    """The background-session record of a member (matched by session id), or None for an interactive one."""
    for a in bg_agents():
        if a.get("sessionId") == member["session_id"] and a.get("kind") in ("bg", "background"):
            return a
    return None


def member_by_name(con, name):
    """The member to act on: a live row of that name first, else the latest one."""
    m = con.execute("SELECT * FROM members WHERE name=? ORDER BY (left_at IS NULL) DESC, joined_at DESC",
                    (name,)).fetchone()
    if not m:
        raise FleetError("fleet: no member named %r. `fleet ls --all` lists them." % name)
    return m


def respawn_command(m):
    return m["respawn"] or "cd %s && claude --resume %s -n %s" % (shlex.quote(m["cwd"] or "."), m["session_id"],
                                                                   shlex.quote(m["name"]))


def claude_respawn(m, name):
    """`claude respawn <id>` (documented) for a member that was a background session -> its id, or None when claude
    has no such job. The id is the first eight characters of the session id. A respawned session keeps its name and
    its settings, so it rejoins the fleet under the same name through the SessionStart hook."""
    since = int(time.time() * 1000) - 2000
    try:
        r = subprocess.run([claude_bin(), "respawn", m["session_id"][:8]], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    entry = find_started(name, since)
    return (entry.get("id") or (entry.get("sessionId") or "")[:8]) if entry else None


def control_local(verb, name):
    """stop | respawn | attach on this machine's member `name` -> a dict (see each verb)."""
    con = db()
    m = member_by_name(con, name)
    status = member_status(m)
    if verb == "respawn":
        if status == "alive":
            raise FleetError("fleet: %s is alive (session %s). `fleet stop %s` first if you mean to restart it."
                             % (name, m["session_id"][:8], name))
        cwd = m["cwd"]
        sid = claude_respawn(m, name)  # documented: keeps the session's name, settings (FLEET_JOIN_NAME) and conversation
        if not sid:  # not a background session of the daemon's (it ran in a terminal), or its record is gone
            if not cwd or not os.path.isdir(cwd):
                raise FleetError("fleet: the folder of %s (%s) is gone; cannot start it there." % (name, cwd))
            sid = start_background(["--bg", "--resume", m["session_id"], "-n", name, "--settings", spawn_settings(name)],
                                   cwd, name)
        return {"action": "respawned", "name": name, "id": sid, "cwd": cwd, "attach": "claude attach %s" % name}
    if status != "alive":
        if verb == "stop":
            raise FleetError("fleet: %s is %s, not running. `fleet respawn %s` starts it again." % (name, status, name))
        return {"kind": status, "command": respawn_command(m),
                "note": "%s is %s. `fleet respawn %s` starts it again in the background; to resume it by hand:"
                        % (name, status, name)}
    entry = bg_entry(m)
    if verb == "stop":
        if not entry:
            return {"action": "interactive", "name": name}
        r = subprocess.run([claude_bin(), "stop", entry["id"]], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise FleetError("fleet: claude stop %s failed: %s" % (entry["id"], (r.stderr or r.stdout).strip()))
        return {"action": "stopped", "name": name, "id": entry["id"]}
    if entry:
        return {"kind": "background", "command": "claude attach %s" % entry["id"], "note": None}
    return {"kind": "interactive", "command": respawn_command(m),
            "note": "%s lives in a terminal session, so it cannot be attached. To resume its conversation instead:" % name}


def cmd_control(verb, name):
    """Internal: `fleet _control <verb> <name>`, run on the member's machine. Prints the result as JSON."""
    print(json.dumps(control_local(verb, name)))


def locate(con, name, machine):
    """Which machine holds the member: None for this one, else its name."""
    if machine and machine != self_machine():
        if machine not in other_machines():
            raise FleetError("fleet: no machine named %r in machines.json." % machine)
        return machine
    if machine or con.execute("SELECT 1 FROM members WHERE name=?", (name,)).fetchone() or not other_machines():
        return None
    got, bad = remote_members(True)
    hits = [mc for mc in sorted(got) if any(m["name"] == name for m in got[mc])]
    if len(hits) > 1:
        raise FleetError("fleet: %r is on several machines (%s); say name@machine." % (name, ", ".join(hits)))
    if not hits:
        hint = "".join("\n" + unreachable_line(mc, why) for mc, why in sorted(bad.items()))
        raise FleetError("fleet: no member named %r. `fleet ls --all` lists them.%s" % (name, hint))
    return hits[0]


def control(verb, target):
    """Run stop | respawn | attach on `target` (name, or name@machine) wherever it lives; the dict has `machine`
    (None for this machine). Attach commands for another machine are wrapped in ssh -t."""
    con = db()
    name, machine = split_target(target)
    where = locate(con, name, machine)
    if where is None:
        res = control_local(verb, name)
    else:
        try:
            res = run_remote_json(where, ["_control", verb, name], timeout=180, kind=dict)
        except RemoteError as e:
            raise FleetError("fleet: %s %s: %s" % (where, "unreachable" if e.unreachable else "failed", e))
        if res.get("command"):
            res["command"] = "ssh -t %s %s" % (shlex.quote(other_machines()[where]["ssh"]), shlex.quote(res["command"]))
    res["machine"] = where
    return res


def stop(target, as_name=None):
    res = control("stop", target)
    name = split_target(target)[0]
    if res["action"] == "stopped":
        print("stopped %s (background session %s). Its conversation is kept; `fleet respawn %s` starts it again."
              % (name, res["id"], name))
        return res
    print("%s is an interactive session in a terminal; it is never killed from here. Asking it to wrap up and leave:"
          % name)
    res["thread"] = send("tell", target, WRAP_UP_TELL, as_name)
    return res


def respawn(target):
    res = control("respawn", target)
    print("started %s again in the background (id %s) in %s\nattach: claude attach %s"
          % (split_target(target)[0], res["id"], res["cwd"], split_target(target)[0]))
    return res


def attach(target):
    res = control("attach", target)
    if res.get("note"):
        print(res["note"])
    print(res["command"])
    return res


# ---------------------------------------------------------------- backlog

def todo_row(con, tid):
    r = con.execute("SELECT * FROM todos WHERE id=?", (tid,)).fetchone()
    if not r:
        raise FleetError("fleet: no to-do %s. `fleet todo ls --all` lists them." % tid)
    return r


def caller_name(con):
    try:
        return need_member(con)[1]["name"]
    except FleetError:
        return None


# A to-do's order: `owner` names the member it is meant for (name, name@machine, or petros), `after` the to-dos it
# waits on, stored as "3,4". Both change only inside one BEGIN IMMEDIATE that refuses an unknown id, a to-do
# waiting on itself and a loop, so the stored order is always a valid one. Whether a to-do is ready (every to-do it
# waits on is done) and whether its owner is gone are worked out on read, never stored.

def after_ids(text):
    """'3, 4' or '#3 #4' -> [3, 4]; '' -> []. An id on another machine (12@bee) is refused: order is per store."""
    out = []
    for part in re.split(r"[\s,]+", (text or "").strip()):
        part = part.lstrip("#")
        if not part:
            continue
        if "@" in part:
            raise FleetError("fleet: %r is a to-do on another machine; a to-do can wait only on to-dos of its own "
                             "machine." % part)
        if not part.isdigit():
            raise FleetError("fleet: %r is not a to-do id." % part)
        if int(part) not in out:
            out.append(int(part))
    return out


def stored_after(r):
    return [int(x) for x in (r["after"] or "").split(",") if x]


def check_order(con, tid, after):
    """Inside the caller's transaction: every id exists, none is `tid` itself, and no loop forms."""
    edges = {r["id"]: stored_after(r) for r in con.execute("SELECT id, after FROM todos")}
    for a in after:
        if a == tid:
            raise FleetError("fleet: to-do %d cannot wait on itself." % tid)
        if a not in edges:
            raise FleetError("fleet: no to-do %d. `fleet todo ls --all` lists them." % a)
    edges[tid] = after
    seen, stack = set(), list(after)
    while stack:
        n = stack.pop()
        if n == tid:
            raise FleetError("fleet: to-do %d cannot wait on %s: that would make a loop."
                             % (tid, ", ".join("#%d" % a for a in after)))
        if n not in seen:
            seen.add(n)
            stack.extend(edges.get(n, []))


def owner_name(owner):
    owner = (owner or "").strip()
    if owner and not re.match(r"^[^\s@]+(@[^\s@]+)?$", owner):
        raise FleetError("fleet: %r is not a member name (name, or name@machine)." % owner)
    return owner or None


def waits_on(con, r):
    """The to-dos `r` waits on that are not done yet."""
    ids = stored_after(r)
    if not ids:
        return []
    done = {x["id"] for x in con.execute("SELECT id FROM todos WHERE state='done' AND id IN (%s)"
                                        % ",".join("?" * len(ids)), ids)}
    return [i for i in ids if i not in done]


def in_write(con, fn):
    """fn() inside BEGIN IMMEDIATE: all of it is stored, or none of it."""
    con.execute("BEGIN IMMEDIATE")
    try:
        res = fn()
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return res


def todo_add(title, ref=None, notes=None, by=None, owner=None, after=None):
    con = db()
    who = by or caller_name(con) or "user"
    owner, ids = owner_name(owner), after_ids(after)

    def write():
        cur = con.execute("INSERT INTO todos (title,ref,notes,created_by,created_at,owner,after) VALUES (?,?,?,?,?,?,?)",
                          (title, ref, notes, who, time.time(), owner, ",".join(map(str, ids)) or None))
        check_order(con, cur.lastrowid, ids)
        return cur.lastrowid
    tid = in_write(con, write)
    print("todo %d added" % tid)
    return tid


def todo_set(tid, owner=None, after=None):
    """Change a to-do's owner or what it waits on ("" clears either). A done to-do keeps its order."""
    if owner is None and after is None:
        raise FleetError("fleet: say --owner NAME or --after IDS (an empty value clears it).")
    con = db()
    new_owner = owner_name(owner) if owner is not None else None
    ids = after_ids(after) if after is not None else None

    def write():
        r = todo_row(con, tid)
        if r["state"] == "done":
            raise FleetError("fleet: to-do %d is done; its order no longer changes." % tid)
        if owner is not None:
            if r["state"] == "claimed" and new_owner and r["claimed_by"] != new_owner:
                raise FleetError("fleet: to-do %d is claimed by %s; it must be released before it can be for %s."
                                 % (tid, r["claimed_by"], new_owner))
            con.execute("UPDATE todos SET owner=? WHERE id=?", (new_owner, tid))
        if ids is not None:
            check_order(con, tid, ids)
            con.execute("UPDATE todos SET after=? WHERE id=?", (",".join(map(str, ids)) or None, tid))
    in_write(con, write)
    r = todo_row(con, tid)
    print("todo %d: %s" % (tid, order_words(con, r) or "no owner, waits on nothing"))


def order_words(con, r):
    """'for X; waits on #3' or 'for X; ready' for a to-do with an order, '' without."""
    parts = []
    if r["owner"]:
        parts.append("for %s" % r["owner"])
    if r["after"] and r["state"] != "done":
        w = waits_on(con, r)
        parts.append("waits on %s" % ", ".join("#%d" % i for i in w) if w else "ready")
    return "; ".join(parts)


def owner_gone(owner, live_names):
    """An owner on this machine with no live member of that name. None when this machine cannot tell (an owner on
    another machine, the user, or no answer about who is alive)."""
    if not owner or "@" in owner or owner == PETROS or live_names is None:
        return None
    return owner not in live_names


def todo_rows(con, show_all=False, live_names=None):
    """The backlog with its order worked out: `after` as a list, `waits_on` (not done yet), `ready`, `owner_gone`.
    One read transaction, so a to-do and the ones it waits on are read at the same moment."""
    con.execute("BEGIN")
    try:
        rows = con.execute("SELECT * FROM todos ORDER BY id").fetchall()
    finally:
        con.execute("COMMIT")
    done = {r["id"] for r in rows if r["state"] == "done"}
    out = []
    for r in rows:
        if not show_all and r["state"] == "done":
            continue
        d = dict(r)
        d["after"] = stored_after(r)
        d["waits_on"] = [i for i in d["after"] if i not in done] if r["state"] != "done" else []
        d["ready"] = r["state"] == "open" and not d["waits_on"]
        d["owner_gone"] = owner_gone(r["owner"], live_names)
        out.append(d)
    return out


def live_member_names(con, agents=_UNSET):
    """Names of this machine's live members, or None when `claude agents --json` cannot say."""
    if agents is _UNSET:
        agents = agents_list()
    if agents is None:
        return None
    return {m["name"] for m in con.execute("SELECT * FROM members WHERE left_at IS NULL") if is_alive(m, agents)}


def todo_ls(as_json=False, show_all=False):
    con = db()
    rows = todo_rows(con, show_all, live_member_names(con))
    if as_json:
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("no to-dos")
    for r in rows:
        who = r["claimed_by"] or ("reserved for %s" % r["reserved_for"] if r["reserved_for"] else "")
        order = []
        if r["owner"]:
            order.append("for %s%s" % (r["owner"], " (gone)" if r["owner_gone"] else ""))
        if r["waits_on"]:
            order.append("waits on %s" % ", ".join("#%d" % i for i in r["waits_on"]))
        elif r["after"] and r["state"] == "open":
            order.append("ready")
        print("%-4d %-8s %s%s%s%s" % (r["id"], r["state"], r["title"], "  [%s]" % who if who else "",
                                      "  {%s}" % "; ".join(order) if order else "",
                                      "  (%s)" % r["ref"] if r["ref"] else ""))


def todo_claim(tid):
    con = db()
    info, me = need_member(con)
    todo_row(con, tid)

    def write():  # the order is checked and the claim stored in one step: no to-do it waits on can change between
        r = todo_row(con, tid)
        if r["state"] == "open" and r["owner"] and r["owner"] != me["name"]:
            raise FleetError("fleet: to-do %d is for %s." % (tid, r["owner"]))
        w = waits_on(con, r) if r["state"] == "open" else []
        if w:
            raise FleetError("fleet: to-do %d waits on %s, not done yet." % (tid, ", ".join("#%d" % i for i in w)))
        return con.execute(
            "UPDATE todos SET state='claimed', claimed_by=?, claimed_session=?, claimed_at=?"
            " WHERE id=? AND state='open' AND (reserved_for IS NULL OR reserved_for=?)",
            (me["name"], me["session_id"], time.time(), tid, me["name"])).rowcount
    if in_write(con, write) != 1:
        r = todo_row(con, tid)
        if r["state"] == "open" and r["reserved_for"]:
            raise FleetError("fleet: to-do %d is reserved for %s." % (tid, r["reserved_for"]))
        raise FleetError("fleet: to-do %d is %s%s." % (tid, r["state"], " by %s" % r["claimed_by"] if r["claimed_by"] else ""))
    r = todo_row(con, tid)
    print("claimed todo %d: %s" % (tid, r["title"]))
    for k in ("ref", "notes"):
        if r[k]:
            print("%s: %s" % (k, r[k]))


def todo_holder_guard(con, tid, verb):
    info, me = need_member(con)
    r = todo_row(con, tid)
    if r["state"] != "claimed" or r["claimed_session"] != me["session_id"]:
        raise FleetError("fleet: to-do %d is %s%s; only the member holding it can %s it."
                         % (tid, r["state"], " by %s" % r["claimed_by"] if r["claimed_by"] else "", verb))


def todo_done(tid):
    con = db()
    todo_holder_guard(con, tid, "finish")
    con.execute("UPDATE todos SET state='done', done_at=? WHERE id=?", (time.time(), tid))
    print("todo %d done" % tid)


def todo_release(tid):
    con = db()
    todo_holder_guard(con, tid, "release")
    con.execute("UPDATE todos SET state='open', claimed_by=NULL, claimed_session=NULL, claimed_at=NULL,"
                " reserved_for=NULL WHERE id=?", (tid,))
    print("todo %d released" % tid)


def todo_prompt(r):
    lines = ["/fleet todo claim %d" % r["id"], "",
             "Work on to-do %d: %s" % (r["id"], r["title"])]
    if r["ref"]:
        lines.append("Reference: %s" % r["ref"])
    if r["notes"]:
        lines.append("Notes: %s" % r["notes"])
    lines.append("When it is finished run `fleet todo done %d`; if you cannot do it run `fleet todo release %d` "
                 "and say why." % (r["id"], r["id"]))
    return "\n".join(lines)


def todo_spawn_on(con, r, machine, name, cwd):
    """The to-do is copied into the other machine's backlog, where the new session claims it; here it is
    reserved for that member so nobody else takes it."""
    try:
        out = run_remote(machine, ["todo", "add", r["title"]] + (["--ref", r["ref"]] if r["ref"] else [])
                         + (["--notes", r["notes"]] if r["notes"] else []), timeout=30)
        rid = int(re.search(r"todo (\d+) added", out).group(1))
        run_remote(machine, ["todo", "spawn", str(rid), "--name", name] + (["--cwd", cwd] if cwd else []),
                   timeout=180)
    except (RemoteError, AttributeError) as e:
        raise FleetError("fleet: todo spawn on %s failed: %s" % (machine, e))
    con.execute("UPDATE todos SET reserved_for=? WHERE id=?", ("%s@%s" % (name, machine), r["id"]))
    print("started %s on %s for to-do %d (its copy there is to-do %d)" % (name, machine, r["id"], rid))


def todo_spawn(tid, name=None, cwd=None, on=None):
    con = db()
    r = todo_row(con, tid)
    if r["owner"]:  # a to-do meant for a member starts as that member
        o_name, _, o_machine = r["owner"].partition("@")
        if name and name != o_name or on and o_machine and on != o_machine:
            raise FleetError("fleet: to-do %d is for %s; spawn it as that member, or change its owner first."
                             % (tid, r["owner"]))
        name, on = o_name, on or o_machine or None
    name = name or "todo-%d" % tid

    def reserve():  # the order is checked and the reservation stored in one step
        w = waits_on(con, todo_row(con, tid))
        if w:
            raise FleetError("fleet: to-do %d waits on %s, not done yet." % (tid, ", ".join("#%d" % i for i in w)))
        return con.execute("UPDATE todos SET reserved_for=? WHERE id=? AND state='open' AND reserved_for IS NULL",
                           (name, tid)).rowcount
    reserved = in_write(con, reserve)
    r = todo_row(con, tid)
    if reserved != 1:
        raise FleetError("fleet: to-do %d is %s." % (tid, "reserved for %s" % r["reserved_for"]
                                                       if r["state"] == "open" else r["state"]))
    if on and on != self_machine():
        try:
            return todo_spawn_on(con, r, on, name, cwd)
        except FleetError:
            con.execute("UPDATE todos SET reserved_for=NULL WHERE id=? AND state='open'", (tid,))
            raise
    try:
        spawn(name, cwd or os.getcwd(), todo_prompt(r))
    except FleetError:
        con.execute("UPDATE todos SET reserved_for=NULL WHERE id=? AND state='open'", (tid,))
        raise


# ---------------------------------------------------------------- hooks

def hook_input():
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        data = {}
    sid = data.get("session_id")
    if sid and not os.environ.get("CLAUDE_CODE_SESSION_ID"):
        os.environ["CLAUDE_CODE_SESSION_ID"] = sid
    return data


def hook_join():
    name = os.environ.get("FLEET_JOIN_NAME")
    if not name:
        return 0
    data = hook_input()
    err = None
    for _ in range(10):  # the session can show in `claude agents --json` just after SessionStart
        try:
            join(name, data.get("transcript_path"))
            return 0
        except FleetError as e:
            err = e
            time.sleep(0.3)
    print(err, file=sys.stderr)
    return 0


def hook_leave():
    data = hook_input()
    try:
        leave(data.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID"))
    except (FleetError, sqlite3.Error) as e:
        print(e, file=sys.stderr)
    return 0


# ---------------------------------------------------------------- session history

def history_ago(t):
    if not t:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def history_guard(fn, *a):
    try:
        return fn(*a)
    except hist.HistoryError as e:
        raise FleetError(str(e))


def fleet_names(con):
    """session id -> the name that session has (or last had) in the fleet."""
    out = {}
    for m in con.execute("SELECT session_id, name FROM members ORDER BY joined_at"):
        out[m["session_id"]] = m["name"]
    return out


def hview(con, r, names=None):
    return hist.view(r, (names if names is not None else fleet_names(con)).get(r["session_id"], ""))


def history_ls(folder=None, as_json=False):
    con = db()
    rs = hist.rows(con, folder)
    names = fleet_names(con)
    bad = hist.unreadable_count(con)
    if bad:
        print("warning: %d transcript%s could not be read: has the transcript format changed? (the reason is in %s)"
              % (bad, "" if bad == 1 else "s", os.path.join(fleet_home(), "hooks.log")), file=sys.stderr)
    if as_json:
        print(json.dumps([hview(con, r, names) for r in rs], indent=2))
        return
    if not rs:
        print("no sessions in the history" + (" under %s." % folder if folder else "."))
        return
    for r in rs:
        v = hview(con, r, names)
        print("%s  %s  %-28s  %s" % (v["id"][:8], history_ago(v["last_seen"]), (v["name"] or "(unnamed) " + hist.clip(v["about"], 30))[:40], v["folder"]))


def history_show(ident, as_json=False):
    con = db()
    r = history_guard(hist.find, con, ident)
    v = hview(con, r)
    if as_json:
        print(json.dumps(v, indent=2))
        return
    print("id:          %s\nname:        %s\nfolder:      %s\nstarted:     %s\nlast seen:   %s\nended:       %s"
          % (v["id"], v["name"] or "(unnamed)", v["folder"], history_ago(v["started"]), history_ago(v["last_seen"]),
             (history_ago(v["ended"]) + " (" + v["end_reason"] + ")") if v["ended"] else "not recorded"))
    print("transcript:  %s\nopened with: %s\ndescription: %s\nresume:      %s"
          % (v["transcript"], v["about"] or "-", v["description"] or "none yet (fleet history describe)", v["resume"]))


def history_rename(ident, name):
    r = history_guard(hist.rename, db(), ident, name)
    print("%s is now %s" % (r["session_id"][:8], hist.display_name(r) or "(unnamed)"))


def history_delete(ident):
    r = history_guard(hist.delete, db(), ident)
    print("removed %s from the history (the transcript is untouched)" % r["session_id"][:8])


def history_resume(ident):
    print(hist.resume_command(history_guard(hist.find, db(), ident)))


def history_ask(ident, question):
    print(history_guard(hist.ask, db(), ident, question))


def history_describe(limit, folder=None):
    con = db()
    n = len(hist.pending(con, folder=folder))
    if not n:
        print("every session that can be described has a description.")
        return
    res = history_guard(hist.describe, con, limit, None, lambda m: print("failed " + m, file=sys.stderr), folder)
    print("described %d, failed %d, %d still waiting" % (res["described"], res["failed"], res["left"]))


def history_search(query, as_json=False):
    res = history_guard(hist.search, db(), query)
    if as_json:
        print(json.dumps(res, indent=2))
        return
    print("%d of %d sessions have a description" % (res["described"], res["total"]))
    for h in res["hits"]:
        print("%s  %s  %s\n    %s" % (h["id"][:8], history_ago(h["last_seen"]), h["name"] or h["folder"], h["why"]))
    if not res["hits"]:
        print("no match")


def history_import(path, descriptions=None):
    con = db()
    before = hist.counts(con)
    res = history_guard(hist.import_store, con, os.path.expanduser(path), descriptions and os.path.expanduser(descriptions))
    after = hist.counts(con)
    print("read %(read)d, added %(added)d, kept %(kept)d, descriptions filled %(described)d" % res)
    print("sessions %d -> %d, described %d -> %d" % (before["total"], after["total"], before["described"], after["described"]))


def hook_record():
    """SessionStart, Stop and SessionEnd: note the session in the history. It must never fail a session, so
    whatever goes wrong is logged under FLEET_HOME and the exit code is 0."""
    try:
        if os.environ.get("FLEET_NO_RECORD"):
            return 0
        hist.record(db(), hook_input())
    except BaseException as e:  # noqa: B902 - a recording problem may cost a row, never a session
        log_line("hook-record: %s: %s" % (type(e).__name__, e))
    return 0


# ---------------------------------------------------------------- canary

CANARY_PROMPT = "Fleet canary session. Reply with the single word ready, then wait. Do nothing else."
CANARY_TELL = "Fleet canary ping. Reply with the single word pong. Do not run any command."


def canary_root():
    return os.environ.get("FLEET_CANARY_DIR") or os.path.join(os.path.expanduser("~"), "projects", ".fleet-canary")


def canary_steps(run, name):
    """The canary, step by step; each step appends to run["steps"]. Raises FleetError with the one-line reason."""
    def step(what):
        run["steps"].append(what)
    root = canary_root()
    os.makedirs(root, exist_ok=True)
    folder = tempfile.mkdtemp(prefix="run-", dir=root)
    run["folder"] = folder
    step("started in %s" % folder)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            out = spawn(name, folder, CANARY_PROMPT, False, None, ["--model", os.environ.get("FLEET_CANARY_MODEL") or "haiku"])
    except FleetError as e:
        raise FleetError("could not start the scratch session: %s" % str(e).replace("\n", " "))
    run["id"] = out["id"]
    step("started background session %s (id %s)" % (name, out["id"]))
    con = db()
    end = time.time() + env_float("FLEET_CANARY_JOIN_WAIT", 60.0)
    member = None
    while time.time() < end and not (member and is_alive(member)):
        member = con.execute("SELECT * FROM members WHERE name=? AND left_at IS NULL", (name,)).fetchone()
        if not (member and is_alive(member)):
            time.sleep(0.5)
    if not (member and is_alive(member)):
        raise FleetError("the scratch session did not join the fleet in time (is the fleet plugin enabled for new sessions?)")
    run["session_id"] = member["session_id"]
    step("joined as %s" % name)
    if not transcript_of(con, member):
        raise FleetError("no transcript path is known for the scratch session, so delivery cannot be confirmed")
    t0 = time.time()
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        send("tell", name, CANARY_TELL, PAGE)
    row = con.execute("SELECT * FROM messages WHERE recipient=? ORDER BY id DESC", (name,)).fetchone()
    if not row:
        raise FleetError("the canary message was not stored: %s" % buf.getvalue().strip())
    run["message"] = row["id"]
    state = row["delivery"]
    if state == "unconfirmed":
        state = follow_up(con, row["id"])  # the direct post did not show up: the SendMessage fallback, inline
    run["delivery"] = state
    run["seconds"] = round(time.time() - t0, 1)
    step("posted message %d, delivery %s in %.1fs" % (row["id"], state, run["seconds"]))
    if state == "confirmed":
        return
    if state == "confirmed-fallback":
        raise FleetError("the direct socket post was not seen in the target's transcript; only the SendMessage "
                         "fallback delivered (the envelope may have changed)")
    raise FleetError("the message was not delivered: %s" % (state or "no delivery recorded"))


def listed(name, session_id):
    """True while `claude agents --json` still lists a session by that name or id. None when it cannot say."""
    agents = agents_list()
    if agents is None:
        return None
    return any(a.get("name") == name or (session_id and a.get("sessionId") == session_id) for a in agents)


def canary_cleanup(run):
    """Stop and remove the scratch session, leave no trace of it: its members row, history row, transcript and
    folder. Works when the run broke early: a session that was started but never reported its id is found by
    name in `claude agents --json`. The history row goes last, once the session has ended, because the
    SessionEnd hook of a stopping session writes it again."""
    notes = []
    name, sid, agent_sid = run.get("name"), run.get("session_id"), None
    if not run.get("id") and name:
        for a in agents_list() or []:
            if a.get("name") == name and a.get("kind") in ("bg", "background") and a.get("id"):
                run["id"] = a["id"]
                agent_sid = a.get("sessionId")
                break
    if run.get("id"):
        for verb in (["stop"], ["rm"]):
            try:
                r = subprocess.run([claude_bin()] + verb + [run["id"]], capture_output=True, text=True, timeout=60)
                if r.returncode != 0:
                    notes.append("claude %s %s failed: %s" % (verb[0], run["id"], (r.stderr or r.stdout).strip()[:120]))
            except (OSError, subprocess.SubprocessError) as e:
                notes.append("claude %s %s: %s" % (verb[0], run["id"], e))
    con = db()
    if not sid and name:
        r = con.execute("SELECT session_id FROM members WHERE name=?", (name,)).fetchone()
        sid = r[0] if r else agent_sid
    if run.get("id") or sid:
        end = time.time() + env_float("FLEET_CANARY_END_WAIT", 20.0)
        while listed(name, sid):
            if time.time() >= end:
                notes.append("the scratch session %s is still listed by `claude agents --json`" % name)
                break
            time.sleep(0.3)
    if name:
        con.execute("DELETE FROM members WHERE name=?", (name,))
    if sid:
        con.execute("DELETE FROM members WHERE session_id=?", (sid,))
        r = con.execute("SELECT transcript_path FROM conversations WHERE session_id=?", (sid,)).fetchone()
        path = r[0] if r else None
        if path and os.path.basename(path) == sid + ".jsonl":  # its own transcript, by exact name
            for p in (path, path[:-len(".jsonl")]):
                try:
                    shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)
                except OSError:
                    pass
            if "-fleet-canary-run-" in os.path.basename(os.path.dirname(path)):
                try:
                    os.rmdir(os.path.dirname(path))  # the project folder Claude Code made for the scratch folder
                except OSError:
                    pass
        con.execute("DELETE FROM conversations WHERE session_id=?", (sid,))
    folder = run.get("folder")
    if folder and os.path.dirname(os.path.abspath(folder)) == os.path.abspath(canary_root()):
        shutil.rmtree(folder, ignore_errors=True)
    return notes


def canary(as_json=False):
    """`fleet canary`: prove delivery end to end with a scratch background session of its own. Exit 0 when a
    message posted through the normal path is confirmed in the session's transcript; else 1 with one line of
    reason, and the user's inbox gets that line too."""
    name = "fleet-canary-%s" % uuid.uuid4().hex[:6]
    run = {"name": name, "steps": []}
    os.environ["FLEET_CONFIRM_DETACH"] = "0"  # the follow-up runs here, so its result is the canary's
    reason = None
    try:
        canary_steps(run, name)
    except FleetError as e:
        reason = " ".join(str(e).split())
    except Exception as e:  # noqa: BLE001 - whatever breaks, the canary must say so in one line
        reason = "%s: %s" % (type(e).__name__, " ".join(str(e).split()))
    finally:
        notes = canary_cleanup(run)
    if notes and not reason:
        reason = "the scratch session was not cleaned up: " + "; ".join(notes)
    res = {"ok": reason is None, "reason": reason or "", "name": name, "id": run.get("id"),
           "message": run.get("message"), "delivery": run.get("delivery"), "seconds": run.get("seconds"),
           "steps": run["steps"]}
    if reason:
        try:
            notify_user(db(), "fleet-canary", "fleet canary failed: %s" % reason)
        except sqlite3.Error:
            pass
    if as_json:
        print(json.dumps(res, indent=2))
    elif reason:
        print("fleet canary FAILED: %s" % reason, file=sys.stderr)
    else:
        print("fleet canary ok: message %d delivered and confirmed in the target's transcript in %.1fs"
              % (run["message"], run["seconds"]))
    return 0 if res["ok"] else 1


# ---------------------------------------------------------------- the page

UI_PORT = 8797
UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
UI_TTL = 3.0
THREADS_SHOWN = 30
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


def recent_threads(limit):
    """This store's last `limit` threads (by newest message), each with its messages."""
    con = db()
    ids = [r["thread"] for r in con.execute(
        "SELECT thread FROM messages GROUP BY thread ORDER BY MAX(id) DESC LIMIT ?", (limit,)).fetchall()]
    return [{"thread": th, "messages": [dict(r) for r in thread_rows(con, th)]} for th in ids]


def cmd_threads(limit):
    """Internal: `fleet _threads [N]`: this store's recent threads as JSON."""
    print(json.dumps(recent_threads(limit)))


def merge_threads(stores, limit):
    """stores: {machine: [thread dicts of that machine's store]}. A message sent across machines is stored on
    both; it is shown once, answered if either copy is. -> newest-first [{thread, updated, open, messages}]."""
    merged = {}
    for machine in sorted(stores):
        for t in stores[machine]:
            seen = merged.setdefault(t["thread"], {"keys": {}, "messages": []})
            for m in t["messages"]:
                own = (machine, m["id"])
                twin = (m["machine"], m["remote_id"]) if m["machine"] and m["remote_id"] else None
                kept = seen["keys"].get(own) or (seen["keys"].get(twin) if twin else None)
                if kept is not None:
                    kept["answered_at"] = kept["answered_at"] or m["answered_at"]
                    continue
                m = dict(m, store=machine)
                seen["messages"].append(m)
                seen["keys"][own] = m
                if twin:
                    seen["keys"][twin] = m
    out = []
    for th, v in merged.items():
        msgs = sorted(v["messages"], key=lambda m: (m["created_at"] or 0, m["id"]))
        out.append({"thread": th, "updated": msgs[-1]["created_at"], "messages": msgs,
                    "open": sum(1 for m in msgs if m["kind"] in ("ask", "tell") and m["answered_at"] is None)})
    out.sort(key=lambda t: -(t["updated"] or 0))
    return out[:limit]


def ui_threads():
    me = self_machine()
    stores = {me: recent_threads(THREADS_SHOWN)}
    bad = {}

    def one(machine):
        return run_remote_json(machine, ["_threads", str(THREADS_SHOWN)], timeout=30, kind=list)
    for machine, res in fan_out(sorted(other_machines()), one).items():
        if isinstance(res, RemoteError):
            bad[machine] = str(res)
        else:
            stores[machine] = res
    return {"threads": merge_threads(stores, THREADS_SHOWN), "notices": notices(bad)}


def notices(bad):
    return [{"machine": m, "text": unreachable_line(m, bad[m])} for m in sorted(bad)]


def ui_members():
    rows, bad, _ = all_members(True, always_machine=True)
    return {"members": rows, "notices": notices(bad), "machine": self_machine(), "home": os.path.expanduser("~")}


def ui_todos():
    me = self_machine()
    con = db()
    rows = [dict(r, machine=me) for r in todo_rows(con, True, live_member_names(con))]
    bad = {}

    def one(machine):
        return run_remote_json(machine, ["todo", "ls", "--json", "--all"], timeout=30, kind=list)
    for machine, res in fan_out(sorted(other_machines()), one).items():
        if isinstance(res, RemoteError):
            bad[machine] = str(res)
        else:
            rows += [dict(r, machine=machine) for r in res]
    return {"todos": rows, "notices": notices(bad), "machine": me}


class Cache:
    """One answer per endpoint for UI_TTL seconds, so open pages never stack ssh calls."""

    def __init__(self, ttl=UI_TTL):
        self.ttl, self.lock, self.items = ttl, threading.Lock(), {}

    def get(self, key, fn):
        with self.lock:
            hit = self.items.get(key)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
            val = fn()
            self.items[key] = (time.time(), val)
            return val


def ui_settings(port=None, host=None):
    try:
        with open(os.path.join(fleet_home(), "ui.json")) as f:
            conf = json.load(f)
    except (OSError, ValueError):
        conf = {}
    conf = conf if isinstance(conf, dict) else {}
    return (port if port is not None else int(conf.get("port") or UI_PORT),
            host or conf.get("host") or "127.0.0.1")


LOOPBACK = ("127.0.0.1", "::1", "localhost")
POST_MAX = 65536
COOKIE = "fleet_ui"


def ui_conf():
    try:
        with open(os.path.join(fleet_home(), "ui.json")) as f:
            conf = json.load(f)
    except (OSError, ValueError):
        return {}
    return conf if isinstance(conf, dict) else {}


def shared_token():
    """The owner's one password for all their own services: the first line of ~/.config/shared-token
    (FLEET_SHARED_TOKEN_FILE moves it), or "" when there is none."""
    path = os.path.expanduser(os.environ.get("FLEET_SHARED_TOKEN_FILE") or "~/.config/shared-token")
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def ui_token():
    """The page's secret: `token` in $FLEET_HOME/ui.json when set, else the shared password (see
    shared_token), else one made on first use with secrets.token_urlsafe and written 0600 into ui.json,
    keeping its other keys (port, host, hosts)."""
    conf = ui_conf()
    tok = conf.get("token")
    if isinstance(tok, str) and len(tok) >= 20:
        return tok
    shared = shared_token()
    if shared:
        return shared
    conf["token"] = secrets.token_urlsafe(32)
    path = os.path.join(private_home(), "ui.json")
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(conf, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return conf["token"]


def sign_in_page(wrong):
    """The page's own sign-in form, shown at / until the browser holds the cookie. It posts the password
    to /login, which sets the same cookie the `fleet ui url` link does."""
    note = '<p class="bad">That password is not right.</p>' if wrong else ""
    return (SIGN_IN_HTML % note).encode()


SIGN_IN_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Fleet: sign in</title>
<style>
:root{--bg:#eef0f4;--card:#fff;--text:#1a1d2d;--dim:#5d6275;--line:#d5d8e0;--accent:#0c8299;--bad:#c2333a}
@media (prefers-color-scheme: dark){:root{--bg:#14161d;--card:#1f222c;--text:#e8eaf0;--dim:#a2a7b8;--line:#343846;--accent:#3cc3da;--bad:#ff8087}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
form{width:100%%;max-width:360px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px;
box-shadow:0 12px 32px rgba(0,0,0,.12)}h1{margin:0 0 4px;font-size:22px}p{margin:0 0 18px;color:var(--dim)}
label{display:block;font-weight:600;margin-bottom:6px}input{width:100%%;font:inherit;padding:10px 12px;border-radius:9px;
border:1px solid var(--line);background:var(--bg);color:var(--text)}input:focus{outline:none;border-color:var(--accent);
box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 30%%,transparent)}button{margin-top:16px;width:100%%;font:inherit;
font-weight:650;padding:10px;border:0;border-radius:9px;background:var(--accent);color:#fff;cursor:pointer}
.bad{color:var(--bad);font-weight:600;margin:12px 0 0}
</style></head><body>
<form method="post" action="/login"><h1>Fleet</h1><p>Sign in once in this browser; it stays signed in for a year.</p>
<label for="pw">Password</label><input id="pw" name="password" type="password" autocomplete="current-password" autofocus required>
%s<button type="submit">Sign in</button></form></body></html>"""


def cookie_value(header, name=COOKIE):
    for part in (header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name:
            return v
    return ""


def request_token_ok(headers, token):
    """True when the request carries the page's token as a cookie or as `Authorization: Bearer`."""
    given = cookie_value(headers.get("Cookie"))
    auth = headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        given = auth[7:].strip()
    return bool(given) and hmac.compare_digest(given.encode(), token.encode())


def ui_url(port=None, host=None):
    """The link that opens the page signed in: /login?t=<token> sets the cookie and redirects to /. The https
    name is the first non-loopback entry of `hosts` in ui.json (a proxy's name); without one, the loopback
    address of the server."""
    tok = ui_token()
    conf = ui_conf()
    proxied = [h for h in (conf.get("hosts") or []) if isinstance(h, str) and h not in LOOPBACK]
    if proxied:
        return "https://%s/login?t=%s" % (proxied[0], tok)
    port, host = ui_settings(port, host)
    host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    return "http://%s:%d/login?t=%s" % ("[%s]" % host if ":" in host else host, port, tok)


def ui_hosts():
    """Host names the history API answers to: loopback names, plus any `hosts` in ui.json (a name a local reverse
    proxy forwards under)."""
    try:
        with open(os.path.join(fleet_home(), "ui.json")) as f:
            extra = json.load(f).get("hosts") or []
    except (OSError, ValueError, AttributeError):
        extra = []
    return set(LOOPBACK) | {h for h in extra if isinstance(h, str)}


def host_name(header):
    h = (header or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else ""
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def host_refusal(headers):
    """Why a request is refused for its Host (DNS rebinding makes a hostile page reach loopback under its own
    name), or None. Applies to every request, static files included."""
    host = headers.get("Host") or ""
    if host_name(host) not in ui_hosts():
        return "unknown Host %r; add it to \"hosts\" in ui.json if a proxy forwards under it" % host
    return None


def history_refusal(bound, headers, post):
    """Why the history API refuses this request, or None. History shows what people typed and its POSTs change
    the store, so: the server must listen on loopback; the Host must be a name of this machine (DNS rebinding
    makes a hostile page reach loopback under its own name); a POST must come from this page (Origin equal to
    Host, Sec-Fetch-Site not cross-site) and be JSON, which a cross-origin form cannot send."""
    if bound not in ("127.0.0.1", "::1"):
        return "history is served only when fleet ui listens on loopback (it listens on %s)" % bound
    host = headers.get("Host") or ""
    why = host_refusal(headers)
    if why:
        return why
    if post:
        origin = headers.get("Origin") or ""
        if urlparse(origin).netloc != host or urlparse(origin).scheme not in ("http", "https"):
            return "a write must come from the fleet page itself (Origin %r)" % origin
        if headers.get("Sec-Fetch-Site") not in (None, "same-origin"):
            return "a write must come from the fleet page itself (Sec-Fetch-Site %s)" % headers.get("Sec-Fetch-Site")
        if not (headers.get("Content-Type") or "").lower().startswith("application/json"):
            return "a write must be application/json"
    return None


def ui_history():
    con = db()
    names = fleet_names(con)
    counts = dict(hist.counts(con), unreadable=hist.unreadable_count(con))
    return {"rows": [hview(con, r, names) for r in hist.rows(con)], "counts": counts,
            "home": os.path.expanduser("~")}


def ui_history_write(path, body):
    """The page's writes. -> (status, json). A model call (ask, search) can take a while."""
    con = db()
    try:
        if path == "/api/history/rename":
            return 200, hview(con, hist.rename(con, body.get("id"), body.get("name")))
        if path == "/api/history/delete":
            return 200, {"deleted": hist.delete(con, body.get("id"))["session_id"]}
        if path == "/api/history/ask":
            return 200, {"answer": hist.ask(con, body.get("id"), body.get("question"))}
        if path == "/api/history/search":
            return 200, hist.search(con, body.get("query"))
    except hist.HistoryError as e:
        return (404 if "no session" in str(e) else 400), {"error": str(e)}
    return 404, {"error": "not found"}


def ui_inbox():
    items, bad, lz = inbox_all(True)
    lungo = None
    if lz:
        lungo = {"ok": lz["ok"], "line": lungo_line(lz), "count": lz.get("count"), "as_of": lz.get("as_of"),
                 "read_at": lz["read_at"], "error": lz.get("error")}
    return {"items": items, "open": sum(1 for i in items if i["answered_at"] is None), "notices": notices(bad),
            "machine": self_machine(), "lungo": lungo}


# ---------------------------------------------------------------- launch profiles (fleet_profiles.py)

PROFILE_TOOLS = prof.ToolCache(claude_bin)


def profile_config():
    return prof.Config(prof.settings(fleet_home()))


def profile_usage():
    """[(folder, sessions, last seen)]: the folders the profile view lists, from the history and from Claude
    Code's transcript folders, since the history holds only what its hook has recorded."""
    con = db()
    recorded = [(r[0], r[1], r[2]) for r in con.execute(
        "SELECT cwd, COUNT(*), MAX(COALESCE(last_seen_at, started_at)) FROM conversations GROUP BY cwd")]
    return prof.merge_usage(recorded, prof.transcript_usage())


NOT_CONFIGURED = "fleet: profiles are not set up: write %s with at least \"roots\" (see fleet_profiles.py)."


def ui_profiles(refresh=False):
    return prof.read_config(profile_config(), PROFILE_TOOLS, profile_usage(), refresh)


def ui_profiles_write(path, body):
    """The profile view's writes. -> (status, json)."""
    cfg = profile_config()
    try:
        if not cfg.configured:
            raise prof.ProfileError(409, NOT_CONFIGURED % os.path.join(fleet_home(), "profiles.json"))
        if path == "/api/profiles/folder":
            profile = body.get("profile")
            if profile is not None and not isinstance(profile, str):
                raise prof.ProfileError(400, "profile must be a name or null")
            return 200, prof.set_folder_profile(cfg, profile_usage(), body.get("folder"), profile)
        if path == "/api/profiles/save":
            return 200, prof.save_profile(cfg, PROFILE_TOOLS, body)
    except prof.ProfileError as e:
        return e.status, {"error": str(e)}
    return 404, {"error": "not found"}


def profile_cmd(cmd, folder=None, name=None, as_json=False):
    """`fleet profile ls|show|set`."""
    cfg = profile_config()
    if not cfg.configured:
        raise FleetError(NOT_CONFIGURED % os.path.join(fleet_home(), "profiles.json"))
    label = lambda s: (s["profile"] or "custom file") if s["kind"] in ("here", "inherited") else (  # noqa: E731
        "custom file" if s["kind"] == "custom" else "none (the launcher's defaults)")
    where = lambda s: {"here": "set here", "inherited": "from %s" % s["from"], "none": "",  # noqa: E731
                       "custom": "hand-written"}[s["kind"]]
    if cmd == "ls":
        folders = prof.scan_folders(profile_usage())
        if as_json:
            print(json.dumps({"folders": folders, "profiles": prof.read_profiles(cfg)}, indent=2))
            return
        for f in folders:
            print("%-50s %-14s %s" % (f["display"], label(f["source"]), where(f["source"])))
        return
    path = os.path.abspath(os.path.expanduser(folder or "."))
    if cmd == "show":
        src = prof.resolve_source(path)
        p = next((x for x in prof.read_profiles(cfg) if x["name"] == src["profile"]), None)
        if as_json:
            print(json.dumps({"folder": path, "source": src, "profile": p}, indent=2))
            return
        print("%s runs %s%s" % (prof.tilde(path), label(src), (", " + where(src)) if where(src) else ""))
        if src["content"]:
            print(src["content"].rstrip())
        if p:
            print("kept in %s" % p["repo"])
            for d in p["pluginDirs"]:
                print("  plugin dir  %s" % d)
            for d in p["denied"]:
                print("  denied      %s" % d)
            for d in p["disabledPlugins"]:
                print("  plugin off  %s" % d)
        return
    if cmd == "set":
        try:
            res = prof.set_folder_profile(cfg, None, path, None if name == "inherit" else name, any_folder=True)
        except prof.ProfileError as e:
            raise FleetError("fleet: %s" % e)
        src = res["source"]
        print("%s now runs %s%s" % (prof.tilde(path), label(src), (", " + where(src)) if where(src) else ""))


OUT_LOCK = threading.Lock()


def captured(fn, *a, **k):
    """fn's result and what it printed. The CLI verbs print; the page wants the text."""
    with OUT_LOCK:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = fn(*a, **k)
    return res, buf.getvalue().strip()


def text_field(body, key, required=True, limit=20000):
    v = body.get(key)
    if v is None or v == "":
        if required:
            raise FleetError("fleet: %s is required." % key)
        return None
    if not isinstance(v, str) or len(v) > limit:
        raise FleetError("fleet: %s must be text of at most %d characters." % (key, limit))
    return v.strip() if required else v


def ui_page_write(path, body):
    """The page's writes outside the history. They act as the user. -> (status, json); FleetError is a 400."""
    try:
        if path == "/api/todos/add":
            tid, out = captured(todo_add, text_field(body, "title", limit=500), text_field(body, "ref", False, 500),
                                text_field(body, "notes", False), PETROS)
            return 200, {"id": tid, "output": out}
        if path == "/api/tell":
            kind = body.get("kind")
            if kind not in ("tell", "ask"):
                raise FleetError("fleet: kind is tell or ask.")
            th, out = captured(send, kind, text_field(body, "target", limit=200), text_field(body, "text"), PAGE)
            return 200, {"thread": th, "output": out}
        if path == "/api/inbox/answer":
            _, out = captured(reply, "answer", text_field(body, "ref", limit=40), text_field(body, "text"), PAGE)
            return 200, {"output": out}
        if path == "/api/inbox/dismiss":
            _, out = captured(dismiss, text_field(body, "ref", limit=40), PAGE)
            return 200, {"output": out}
        # stop and respawn call `claude` and wait for it, so they run outside `captured`: its lock is process-wide,
        # and holding it that long would stall every other write from the page (an answer, a tell, a to-do).
        if path == "/api/members/stop":
            tgt = text_field(body, "target", limit=200)
            res = control("stop", tgt)
            if res["action"] != "stopped":
                res["thread"], _ = captured(send, "tell", tgt, WRAP_UP_TELL, PAGE)
            return 200, res
        if path == "/api/members/respawn":
            return 200, control("respawn", text_field(body, "target", limit=200))
        if path == "/api/members/attach":
            return 200, control("attach", text_field(body, "target", limit=200))
    except FleetError as e:
        return 400, {"error": str(e).splitlines()[0] if str(e) else "failed"}
    return 404, {"error": "not found"}


PROFILE_WRITES = ("/api/profiles/folder", "/api/profiles/save")
PAGE_WRITES = ("/api/todos/add", "/api/tell", "/api/inbox/answer", "/api/inbox/dismiss", "/api/members/stop",
               "/api/members/respawn", "/api/members/attach")


def make_ui_handler(cache, token):
    api = {"/api/members": ui_members, "/api/todos": ui_todos, "/api/threads": ui_threads}
    writes = ("/api/history/rename", "/api/history/delete", "/api/history/ask", "/api/history/search") + PAGE_WRITES \
        + PROFILE_WRITES
    guarded = ("/api/history", "/api/inbox", "/api/profiles")  # served only on loopback, like the writes

    class Handler(BaseHTTPRequestHandler):
        server_version = "fleet-ui"
        timeout = 30  # a client that connects and says nothing must not hold a thread and a socket forever

        def log_message(self, *a):
            pass

        def send_body(self, code, ctype, data, extra=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in extra:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, code, data):
            self.send_body(code, "application/json", json.dumps(data).encode())

        def refuse(self, post, strict=True):
            """403 for a request the page must not answer (Host, and for history and writes the loopback and
            Origin rules); 401 without the token. True when it answered."""
            why = history_refusal(self.server.server_address[0], self.headers, post) if strict \
                else host_refusal(self.headers)
            if why:
                self.send_json(403, {"error": why})
                return True
            if not request_token_ok(self.headers, token):
                if urlparse(self.path).path == "/":
                    self.send_body(401, "text/html; charset=utf-8", sign_in_page(False))
                    return True
                self.send_json(401, {"error": "not signed in: run `fleet ui url` on the machine that serves "
                                              "this page and open the link it prints"})
                return True
            return False

        def login(self, given=None):
            why = host_refusal(self.headers)
            if why:
                return self.send_json(403, {"error": why})
            form = given is not None
            if not form:
                given = (parse_qs(urlparse(self.path).query).get("t") or [""])[0]
            if not given or not hmac.compare_digest(given.encode(), token.encode()):
                if form:
                    time.sleep(1)  # a password typed from memory is short: make guessing slow
                    return self.send_body(401, "text/html; charset=utf-8", sign_in_page(True))
                return self.send_json(401, {"error": "wrong or missing token: run `fleet ui url` for a fresh link"})
            cookie = "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000" % (COOKIE, token)
            if (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower() == "https":
                cookie += "; Secure"  # only ever added, never trusted to loosen anything
            self.send_body(303, "text/plain", b"signed in", [("Location", "/"), ("Set-Cookie", cookie)])

        def do_POST(self):
            with db_scope():
                self.handle_post()

        def handle_post(self):
            path = urlparse(self.path).path
            if path == "/login":
                n = int(self.headers.get("Content-Length") or 0)
                fields = parse_qs(self.rfile.read(min(n, 4096)).decode("utf-8", "replace"))
                return self.login((fields.get("password") or [""])[0])
            if path not in writes:
                return self.send_json(404, {"error": "not found"})
            if self.refuse(True):
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n > POST_MAX:
                    raise ValueError("too large")
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("not an object")
            except ValueError as e:
                return self.send_json(400, {"error": "bad request: %s" % e})
            try:
                if path in PAGE_WRITES:
                    code, data = ui_page_write(path, body)
                    cache.items.clear()
                elif path in PROFILE_WRITES:
                    code, data = ui_profiles_write(path, body)
                else:
                    code, data = ui_history_write(path, body)
            except Exception as e:
                code, data = 500, {"error": str(e)}
            self.send_json(code, data)

        def do_GET(self):
            with db_scope():
                self.handle_get()

        def handle_get(self):
            path = urlparse(self.path).path
            if path == "/login":
                return self.login()
            if self.refuse(False, strict=path in guarded):
                return
            if path in guarded:
                try:
                    if path == "/api/profiles":
                        refresh = (parse_qs(urlparse(self.path).query).get("refresh") or [""])[0] == "1"
                        return self.send_json(200, ui_profiles(refresh))
                    data = ui_history() if path == "/api/history" else cache.get(path, ui_inbox)
                    return self.send_json(200, data)
                except Exception as e:
                    return self.send_json(500, {"error": str(e)})
            if path in api:
                try:
                    data = cache.get(path, api[path])
                except Exception as e:  # a broken store is shown, never fatal
                    return self.send_json(500, {"error": str(e)})
                return self.send_json(200, data)
            if path.startswith("/api/"):
                return self.send_json(404, {"error": "not found"})
            name = "index.html" if path == "/" else path.lstrip("/")
            full = os.path.realpath(os.path.join(UI_DIR, name))
            ext = os.path.splitext(full)[1]
            if os.path.dirname(full) != os.path.realpath(UI_DIR) or ext not in TYPES or not os.path.isfile(full):
                return self.send_body(404, "text/plain", b"not found")
            with open(full, "rb") as f:
                self.send_body(200, TYPES[ext], f.read())

        do_HEAD = do_GET

    return Handler


def make_ui_server(port=None, host=None, ttl=UI_TTL):
    port, host = ui_settings(port, host)
    token = ui_token()
    srv = ThreadingHTTPServer((host, port), make_ui_handler(Cache(ttl), token))
    srv.daemon_threads = True
    srv.fleet_token = token
    return srv


def ui(port=None, host=None):
    try:
        srv = make_ui_server(port, host)
    except OSError as e:
        raise FleetError("fleet: cannot listen on %s:%s (%s)." % (host or ui_settings()[1], port or ui_settings()[0], e))
    print("fleet ui on http://%s:%d/ (sign in with the link `fleet ui url` prints)" % srv.server_address[:2], flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_statusline(session_id):
    """`fleet statusline <session id>`: one JSON object for a status line, read-only and fast.
    {} when there is no store. Keys: members (live members here), name (this session's fleet name, or
    null), inbox (tells and asks to it not yet answered), knock (the newest of those arrived in the last
    two minutes), knock_from (its sender), waiting (its own asks not yet answered), todos (to-dos it holds),
    open_todos (unclaimed to-dos here), for_petros (unanswered items in the user's inbox on this machine)."""
    path = os.path.join(fleet_home(), "fleet.db")
    if not os.path.exists(path):
        print("{}")
        return
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=1)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=500")
        out = statusline_object(con, session_id)
    except sqlite3.Error:  # a locked, old or damaged store: a status line shows nothing rather than an error
        print("{}")
        return
    print(json.dumps(out))


def statusline_object(con, session_id):

    def alive(pid):
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, TypeError, ValueError):
            return False

    rows = con.execute("SELECT session_id, name, pid FROM members WHERE left_at IS NULL").fetchall()
    live = [r for r in rows if alive(r["pid"])]
    me = next((r for r in live if r["session_id"] == session_id), None)
    out = {"members": len(live), "name": me["name"] if me else None,
           "open_todos": con.execute("SELECT count(*) FROM todos WHERE state='open'").fetchone()[0],
           "for_petros": con.execute("SELECT count(*) FROM messages WHERE recipient=? AND kind IN "
                                     "('ask','tell','notify') AND answered_at IS NULL", (PETROS,)).fetchone()[0]}
    if me:
        inbox = con.execute("SELECT sender, created_at FROM messages WHERE recipient_session=? AND kind IN "
                            "('ask','tell') AND answered_at IS NULL ORDER BY created_at DESC",
                            (session_id,)).fetchall()
        out["inbox"] = len(inbox)
        out["knock"] = bool(inbox) and time.time() - (inbox[0]["created_at"] or 0) < 120
        out["knock_from"] = inbox[0]["sender"] if inbox else None
        out["waiting"] = con.execute("SELECT count(DISTINCT thread) FROM messages WHERE sender_session=? "
                                     "AND kind='ask' AND answered_at IS NULL", (session_id,)).fetchone()[0]
        out["todos"] = con.execute("SELECT count(*) FROM todos WHERE state='claimed' AND claimed_session=?",
                                   (session_id,)).fetchone()[0]
    return out


# ---------------------------------------------------------------- cli

def main(argv=None):
    os.umask(0o077)  # anything this command creates is private to the user
    p = argparse.ArgumentParser(prog="fleet", description="Claude Code sessions that talk to each other.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("join", help="register this session"); s.add_argument("name", nargs="?")
    sub.add_parser("leave", help="leave the fleet")
    s = sub.add_parser("forget", help="delete this machine's members whose name matches a glob (live ones only with --live)")
    s.add_argument("patterns", nargs="+"); s.add_argument("--live", action="store_true")
    s = sub.add_parser("ls", help="list members"); s.add_argument("--json", action="store_true"); s.add_argument("--all", action="store_true")
    s.add_argument("--state", action="store_true", help="what each member is doing now, read live, with the time read")
    s.add_argument("--local", action="store_true", help="this machine only")
    as_help = "send as the user (only a session outside the fleet; also FLEET_AS=petros)"
    for k in ("tell", "ask"):
        s = sub.add_parser(k, help="%s a member, or * for all" % k)
        s.add_argument("target"); s.add_argument("text", nargs="+"); s.add_argument("--as", dest="as_name", help=as_help)
    s = sub.add_parser("notify", help="tell the user something (blocked, done, needs a decision)")
    s.add_argument("text", nargs="+")
    s = sub.add_parser("answer", help="answer an ask (as petros: any item of his inbox)")
    s.add_argument("msg_id"); s.add_argument("text", nargs="+"); s.add_argument("--as", dest="as_name", help=as_help)
    s = sub.add_parser("dismiss", help="clear an item of the user's inbox"); s.add_argument("msg_id")
    s.add_argument("--as", dest="as_name", help=as_help)
    s = sub.add_parser("inbox", help="the user's inbox, every machine")
    s.add_argument("--json", action="store_true"); s.add_argument("--all", action="store_true")
    s.add_argument("--local", action="store_true", help="this machine only")
    s = sub.add_parser("stop", help="stop a background member; ask an interactive one to leave")
    s.add_argument("target"); s.add_argument("--as", dest="as_name", help=as_help)
    sub.add_parser("respawn", help="start a dead or left member again in the background").add_argument("target")
    sub.add_parser("attach", help="print the command that steps into a member").add_argument("target")
    s = sub.add_parser("_control"); s.add_argument("verb"); s.add_argument("name")
    sub.add_parser("_confirm").add_argument("mid", type=int)
    s = sub.add_parser("canary", help="prove delivery end to end with a scratch session (for a daily schedule)")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("ack", help="acknowledge a tell"); s.add_argument("msg_id"); s.add_argument("text", nargs="*")
    s = sub.add_parser("wait", help="block until a thread is answered")
    s.add_argument("thread"); s.add_argument("--timeout", type=float, default=300)
    s = sub.add_parser("thread", help="show a thread"); s.add_argument("id"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("spawn", help="start a background session that joins as <name>")
    s.add_argument("name"); s.add_argument("cwd"); s.add_argument("prompt", nargs="+"); s.add_argument("--json", action="store_true")
    s.add_argument("--on", metavar="MACHINE", help="start it on another machine")
    t = sub.add_parser("todo", help="the backlog").add_subparsers(dest="todo_cmd", required=True)
    s = t.add_parser("add"); s.add_argument("title"); s.add_argument("--ref"); s.add_argument("--notes")
    s.add_argument("--owner", help="the member it is meant for (name, name@machine, or petros)")
    s.add_argument("--after", help="the to-dos it waits on, e.g. 3,4")
    s = t.add_parser("set", help="change a to-do's owner or what it waits on (an empty value clears it)")
    s.add_argument("id", type=int); s.add_argument("--owner"); s.add_argument("--after")
    s = t.add_parser("ls"); s.add_argument("--json", action="store_true"); s.add_argument("--all", action="store_true")
    for k in ("claim", "done", "release"):
        s = t.add_parser(k); s.add_argument("id", type=int)
    s = t.add_parser("spawn"); s.add_argument("id", type=int); s.add_argument("--name"); s.add_argument("--cwd")
    s.add_argument("--on", metavar="MACHINE", help="start it on another machine")
    s = sub.add_parser("ui", help="serve the fleet page, or print its sign-in link"); s.add_argument("--port", type=int)
    s.add_argument("--host"); s.add_argument("what", nargs="?", choices=["url"], help="`url`: print the sign-in link")
    sub.add_parser("_threads").add_argument("limit", type=int, nargs="?", default=30)
    sub.add_parser("_deliver"); sub.add_parser("_answer"); sub.add_parser("_thread").add_argument("thread")
    sub.add_parser("statusline", help="one JSON line for a status line").add_argument("session_id")
    sub.add_parser("hook-join"); sub.add_parser("hook-leave"); sub.add_parser("hook-record")
    h = sub.add_parser("history", help="every session this machine has run").add_subparsers(dest="history_cmd", required=True)
    s = h.add_parser("ls", help="list sessions, newest first")
    s.add_argument("--folder"); s.add_argument("--json", action="store_true")
    s = h.add_parser("show"); s.add_argument("id"); s.add_argument("--json", action="store_true")
    s = h.add_parser("rename"); s.add_argument("id"); s.add_argument("name", nargs="*")
    h.add_parser("delete", help="remove the row (never the transcript)").add_argument("id")
    h.add_parser("resume", help="print the command that resumes it").add_argument("id")
    s = h.add_parser("ask", help="answer a question from one transcript"); s.add_argument("id"); s.add_argument("question", nargs="+")
    s = h.add_parser("describe", help="describe sessions that have no description (headless calls)")
    s.add_argument("--limit", type=int, default=hist.DESCRIBE_LIMIT); s.add_argument("--folder", help="only sessions under this folder")
    s = h.add_parser("search", help="find a session by meaning"); s.add_argument("query", nargs="+"); s.add_argument("--json", action="store_true")
    s = h.add_parser("import", help="copy conversations from another store"); s.add_argument("path")
    s.add_argument("--descriptions", help="a store with a digests table, when it is not the same file")
    pr = sub.add_parser("profile", help="which tools a folder's new sessions get").add_subparsers(dest="profile_cmd", required=True)
    pr.add_parser("ls", help="every folder sessions ran in, with its profile").add_argument("--json", action="store_true")
    s = pr.add_parser("show", help="a folder's profile and what it keeps"); s.add_argument("folder", nargs="?"); s.add_argument("--json", action="store_true")
    s = pr.add_parser("set", help="set a folder's profile, or inherit"); s.add_argument("folder"); s.add_argument("name")
    a = p.parse_args(argv)
    try:
        if a.cmd == "join": join(a.name)
        elif a.cmd == "leave": leave()
        elif a.cmd == "forget": forget(a.patterns, a.live)
        elif a.cmd == "ls": ls(a.json, a.all, a.local, a.state)
        elif a.cmd == "statusline": cmd_statusline(a.session_id)
        elif a.cmd in ("tell", "ask"): send(a.cmd, a.target, " ".join(a.text), a.as_name)
        elif a.cmd == "notify": notify(" ".join(a.text))
        elif a.cmd == "answer": reply("answer", a.msg_id, " ".join(a.text), a.as_name)
        elif a.cmd == "dismiss": dismiss(a.msg_id, a.as_name)
        elif a.cmd == "inbox": inbox(a.json, a.all, a.local)
        elif a.cmd == "stop": stop(a.target, a.as_name)
        elif a.cmd == "respawn": respawn(a.target)
        elif a.cmd == "attach": attach(a.target)
        elif a.cmd == "_control": cmd_control(a.verb, a.name)
        elif a.cmd == "_confirm": cmd_confirm(a.mid)
        elif a.cmd == "canary": return canary(a.json)
        elif a.cmd == "ack": reply("ack", a.msg_id, " ".join(a.text) or "ok")
        elif a.cmd == "wait": return wait(a.thread, a.timeout)
        elif a.cmd == "thread": thread(a.id, a.json)
        elif a.cmd == "spawn": spawn(a.name, a.cwd, " ".join(a.prompt), a.json, a.on)
        elif a.cmd == "todo":
            if a.todo_cmd == "add": todo_add(a.title, a.ref, a.notes, owner=a.owner, after=a.after)
            elif a.todo_cmd == "set": todo_set(a.id, a.owner, a.after)
            elif a.todo_cmd == "ls": todo_ls(a.json, a.all)
            elif a.todo_cmd == "claim": todo_claim(a.id)
            elif a.todo_cmd == "done": todo_done(a.id)
            elif a.todo_cmd == "release": todo_release(a.id)
            elif a.todo_cmd == "spawn": todo_spawn(a.id, a.name, a.cwd, a.on)
        elif a.cmd == "ui":
            if a.what == "url": print(ui_url(a.port, a.host))
            else: ui(a.port, a.host)
        elif a.cmd == "_threads": cmd_threads(a.limit)
        elif a.cmd == "_deliver": cmd_deliver()
        elif a.cmd == "_answer": cmd_answer()
        elif a.cmd == "_thread": cmd_thread(a.thread)
        elif a.cmd == "hook-join": return hook_join()
        elif a.cmd == "hook-leave": return hook_leave()
        elif a.cmd == "hook-record": return hook_record()
        elif a.cmd == "history":
            c = a.history_cmd
            if c == "ls": history_ls(a.folder, a.json)
            elif c == "show": history_show(a.id, a.json)
            elif c == "rename": history_rename(a.id, " ".join(a.name))
            elif c == "delete": history_delete(a.id)
            elif c == "resume": history_resume(a.id)
            elif c == "ask": history_ask(a.id, " ".join(a.question))
            elif c == "describe": history_describe(a.limit, a.folder)
            elif c == "search": history_search(" ".join(a.query), a.json)
            elif c == "import": history_import(a.path, a.descriptions)
        elif a.cmd == "profile":
            profile_cmd(a.profile_cmd, getattr(a, "folder", None), getattr(a, "name", None), getattr(a, "json", False))
    except FleetError as e:
        print(e, file=sys.stderr)
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
