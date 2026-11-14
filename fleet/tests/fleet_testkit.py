"""Fixtures for the fleet tests: a fake sessions dir and fake inbox sockets.

Each fake session is a real sleeping process (so its pid is alive and distinct), a
<pid>.json in $FLEET_SESSIONS_DIR (which the fake `claude agents --json` below lists, as the real command
lists live sessions), and a listener thread on a unix socket that records every line posted to it. A session
made with transcript=True also appends what it receives to a transcript file, the way Claude Code does, unless
`writes` is turned off: that is what delivery confirmation reads.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

import stat

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import fleet  # noqa: E402


class FakeSession:
    def __init__(self, base, name, cwd="/work/x", pid=None, home=None, transcript=False):
        self.name = name
        self.home = home or os.path.join(base, "home")
        self.sid = "sid-%s-%s" % (name, os.urandom(3).hex())
        self.proc = None
        if pid is None:
            self.proc = subprocess.Popen(["sleep", "300"])
            pid = self.proc.pid
        self.pid = pid
        self.sock_path = os.path.join(base, "s", "%s.sock" % name)
        self.lines = []
        self.writes = True
        self.reply = b""  # what the socket answers before it closes
        self.transcript = None
        if transcript:
            os.makedirs(os.path.join(base, "t"), exist_ok=True)
            self.transcript = os.path.join(base, "t", "%s.jsonl" % self.sid)
            open(self.transcript, "w").close()
        self.info = {"pid": pid, "sessionId": self.sid, "cwd": cwd, "procStart": "start-%s" % name,
                     "name": name, "messagingSocketPath": self.sock_path, "updatedAt": 1}
        self.dir = os.path.join(base, "sessions")
        self.write_info()
        self.srv = socket.socket(socket.AF_UNIX)
        self.srv.bind(self.sock_path)
        self.srv.listen(8)
        self.srv.settimeout(0.2)
        self.stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def write_info(self):
        with open(os.path.join(self.dir, "%d.json" % self.pid), "w") as f:
            json.dump(self.info, f)

    def _serve(self):
        while not self.stop:
            try:
                c, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            data = b""
            c.settimeout(2)
            try:
                while True:
                    chunk = c.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            except (OSError, socket.timeout):
                pass
            if self.reply:
                try:
                    c.sendall(self.reply)
                except OSError:
                    pass
            c.close()
            for ln in data.decode().splitlines():
                rec = json.loads(ln)
                self.lines.append(rec)
                if self.transcript and self.writes and rec.get("type") == "user":
                    self.append_transcript(rec["message"]["content"])

    def append_transcript(self, text):
        with open(self.transcript, "a") as f:
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}) + "\n")

    def record_start(self):
        """What the recording hook does at SessionStart: note the session and its transcript path."""
        old = os.environ.get("FLEET_HOME")
        os.environ["FLEET_HOME"] = self.home
        try:
            fleet.hist.record(fleet.db(), {"hook_event_name": "SessionStart", "session_id": self.sid,
                                           "cwd": self.info["cwd"], "transcript_path": self.transcript})
        finally:
            if old is None:
                os.environ.pop("FLEET_HOME", None)
            else:
                os.environ["FLEET_HOME"] = old

    def messages(self):
        return [ln for ln in self.lines if ln.get("type") == "user"]

    def auths(self):
        return [ln for ln in self.lines if ln.get("type") == "auth"]

    def env(self, monkeypatch):
        monkeypatch.setenv("FLEET_HOME", self.home)
        monkeypatch.setenv("FLEET_SESSIONS_DIR", self.dir)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", self.sid)
        monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", self.sock_path)

    def die(self):
        """The process exits; its sessions file goes with it."""
        self.proc.kill()
        self.proc.wait()
        os.unlink(os.path.join(self.dir, "%d.json" % self.pid))

    def close(self):
        self.stop = True
        self.srv.close()
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()


# One fake `claude` for every test: `agents --json` lists the fake sessions of $FLEET_SESSIONS_DIR (live pids
# only, minus those named in STUB_HIDE) plus the entries in $STUB_DIR/agents.json and every session a `--bg`
# call started (named by its -n, id $STUB_BG_ID); `stop` and `rm` answer; `-p` is the headless fallback (it
# appends the delivery marker it is asked to deliver to the file in STUB_TRANSCRIPT when that is set, and
# fails when STUB_HEADLESS_FAIL is); anything else is a `--bg` start (STUB_OUT gets the arguments, STUB_FAIL
# makes it fail). Every call but `agents` is logged to $STUB_DIR/calls.jsonl.
CLAUDE_STUB = """#!%s
import glob, json, os, re, sys, time
a = sys.argv[1:]
d = os.environ.get("STUB_DIR") or ""


def load(name):
    try:
        return json.load(open(os.path.join(d, name)))
    except (OSError, ValueError):
        return []


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


if a[:1] == ["agents"]:
    if os.environ.get("STUB_AGENTS_BROKEN"):
        print("not json")
        sys.exit(0)
    hide = [x for x in (os.environ.get("STUB_HIDE") or "").split(",") if x]
    stopped = load("stopped.json")  # names of sessions that `stop` ended
    out = []
    for p in glob.glob(os.path.join(os.environ.get("FLEET_SESSIONS_DIR", "-"), "*.json")):
        try:
            i = json.load(open(p))
        except ValueError:
            continue
        if i.get("pid") and alive(i["pid"]) and i.get("name") not in hide + stopped:
            out.append({"pid": i["pid"], "sessionId": i["sessionId"], "cwd": i.get("cwd"), "name": i.get("name"),
                        "kind": "interactive", "status": "idle", "startedAt": 1})
    print(json.dumps(out + load("agents.json") + [e for e in load("started.json") if e["name"] not in stopped]))
    sys.exit(0)
if d:
    with open(os.path.join(d, "calls.jsonl"), "a") as f:
        f.write(json.dumps({"argv": a, "cwd": os.getcwd(), "no_record": os.environ.get("FLEET_NO_RECORD"),
                            "session_env": os.environ.get("CLAUDE_CODE_SESSION_ID")}) + "\\n")
if a[:1] == ["stop"]:
    started = load("started.json")
    json.dump(load("stopped.json") + [e["name"] for e in started if e["id"] == a[1]], open(os.path.join(d, "stopped.json"), "w"))
    print("stopped " + a[1])
elif a[:1] == ["respawn"]:
    started = load("started.json")
    hit = [e for e in started if e["id"] == a[1]]
    if not hit:
        sys.stderr.write("No job matching " + repr(a[1]) + "\\n")
        sys.exit(1)
    json.dump([n for n in load("stopped.json") if n != hit[0]["name"]], open(os.path.join(d, "stopped.json"), "w"))
    hit[0]["startedAt"] = int(time.time() * 1000)
    json.dump(started, open(os.path.join(d, "started.json"), "w"))
    print("respawned " + a[1])
elif a[:1] == ["rm"]:
    json.dump([e for e in load("started.json") if e["id"] != a[1]], open(os.path.join(d, "started.json"), "w"))
    print("removed " + a[1])
elif "-p" in a:
    text = sys.stdin.read()
    if d:
        open(os.path.join(d, "headless.txt"), "a").write(text + "\\n=====\\n")
    if os.environ.get("STUB_HEADLESS_FAIL"):
        sys.stderr.write("headless failed\\n")
        sys.exit(1)
    if os.environ.get("STUB_TRANSCRIPT"):
        for m in re.findall(r"fleet-ref-[0-9]+-[0-9a-f]+", text):
            with open(os.environ["STUB_TRANSCRIPT"], "a") as f:
                f.write(json.dumps({"type": "user", "message": {"role": "user", "content": m}}) + "\\n")
    print("sent")
else:
    if os.environ.get("STUB_OUT"):
        with open(os.environ["STUB_OUT"], "w") as f:
            f.write("\\n".join(a) + "\\n" + (os.getcwd() + "\\n" if os.environ.get("STUB_PWD") else ""))
    if os.environ.get("STUB_FAIL"):
        sys.stderr.write(os.environ["STUB_FAIL"] + "\\n")
        sys.exit(1)
    bid = os.environ.get("STUB_BG_ID") or "ab12cd34"
    if os.environ.get("STUB_START_UNLISTED") != "1" and d:
        name = a[a.index("-n") + 1] if "-n" in a else ""
        started = load("started.json")
        started.append({"id": bid, "sessionId": bid + "-0000-4000-8000-000000000000", "name": name, "cwd": os.getcwd(),
                        "kind": "background", "state": "working", "startedAt": int(time.time() * 1000)})
        json.dump(started, open(os.path.join(d, "started.json"), "w"))
    print("started in the background: " + (os.environ.get("STUB_PRINT_ID") or bid))
"""


def install_claude_stub(world, bg_id="ab12cd34"):
    """Put the fake `claude` in place as FLEET_CLAUDE_BIN; -> the folder STUB_DIR points at."""
    d = os.path.join(world.base, "claude-stub")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "claude")
    with open(path, "w") as f:
        f.write(CLAUDE_STUB % sys.executable)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    world.mp.setenv("FLEET_CLAUDE_BIN", path)
    world.mp.setenv("STUB_DIR", d)
    world.mp.setenv("STUB_BG_ID", bg_id)
    for k in ("STUB_OUT", "STUB_FAIL", "STUB_HIDE", "STUB_AGENTS_BROKEN", "STUB_TRANSCRIPT", "STUB_HEADLESS_FAIL",
              "STUB_START_UNLISTED", "STUB_PWD", "STUB_PRINT_ID", "FLEET_CLAUDE_ARGS"):
        world.mp.delenv(k, raising=False)
    return d


FAKE_SSH = """#!%s
import json, os, subprocess, sys
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "-o":
        i += 2
    elif args[i] == "--":
        i += 1
        break
    else:
        break
host, cmd = args[i], " ".join(args[i + 1:])
base = os.environ["FAKE_SSH_BASE"]
with open(os.path.join(base, "ssh.log"), "a") as f:
    f.write(json.dumps([host, cmd]) + "\\n")
hosts = json.load(open(os.path.join(base, "hosts.json")))
if host not in hosts:
    sys.stderr.write("ssh: connect to host %%s port 22: Operation timed out\\n" %% host)
    sys.exit(255)
env = dict(os.environ, FLEET_HOME=hosts[host]["home"], FLEET_SESSIONS_DIR=hosts[host]["sessions"])
env.pop("CLAUDE_CODE_SESSION_ID", None)
env.pop("CLAUDE_CODE_MESSAGING_SOCKET", None)
sys.exit(subprocess.run(["sh", "-c", cmd], env=env).returncode)
"""


class Host:
    """One machine of a fake cluster: its own FLEET_HOME and sessions dir. `world.host(name)` makes one;
    the World itself is the host `here`."""

    def __init__(self, world, name, base, home=None):
        self.world, self.name, self.base = world, name, base
        self.home = home or os.path.join(base, "home")
        self.sessions_dir = os.path.join(base, "sessions")

    def session(self, name, **kw):
        s = FakeSession(self.base, name, home=self.home, **kw)
        self.world.sessions.append(s)
        return s

    def db(self):
        import sqlite3
        con = sqlite3.connect(os.path.join(self.home, "fleet.db"))
        con.row_factory = sqlite3.Row
        return con


class World:
    def __init__(self, base, monkeypatch, capsys):
        self.base, self.mp, self.capsys = base, monkeypatch, capsys
        os.makedirs(os.path.join(base, "sessions"))
        os.makedirs(os.path.join(base, "s"))
        monkeypatch.setenv("FLEET_HOME", os.path.join(base, "home"))
        monkeypatch.setenv("FLEET_SHARED_TOKEN_FILE", os.path.join(base, "shared-token"))  # never the owner's
        monkeypatch.setenv("FLEET_SESSIONS_DIR", os.path.join(base, "sessions"))
        monkeypatch.setenv("FLEET_USER_SETTINGS", os.path.join(base, "settings.json"))
        monkeypatch.delenv("FLEET_JOIN_NAME", raising=False)
        monkeypatch.delenv("FLEET_RESPAWN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_MESSAGING_SOCKET", raising=False)
        self.sessions = []
        self.here = Host(self, "here", base)
        monkeypatch.setenv("FLEET_CONFIRM_DETACH", "0")  # a test runs the follow-up itself (`_confirm`)
        monkeypatch.setenv("FLEET_CONFIRM_WAIT", "0.3")
        monkeypatch.setenv("FLEET_FIND_WAIT", "1")
        self.stub_dir = install_claude_stub(self)

    def session(self, name, **kw):
        return self.here.session(name, **kw)

    def host(self, name):
        base = os.path.join(self.base, "h-" + name)
        os.makedirs(os.path.join(base, "sessions"))
        os.makedirs(os.path.join(base, "s"))
        return Host(self, name, base)

    def link(self, *hosts, extra=None, python=None, only=None):
        """Put a fake `ssh` on PATH and write machines.json on `here` and every host. Host names are the ssh
        hosts. `extra` adds entries (e.g. an unreachable one) to `here`'s file; `only` limits who lists whom."""
        every = (self.here,) + hosts
        os.makedirs(os.path.join(self.base, "bin"), exist_ok=True)
        path = os.path.join(self.base, "bin", "ssh")
        with open(path, "w") as f:
            f.write(FAKE_SSH % sys.executable)
        os.chmod(path, 0o755)
        self.mp.setenv("PATH", os.path.join(self.base, "bin") + os.pathsep + os.environ["PATH"])
        self.mp.setenv("FAKE_SSH_BASE", self.base)
        with open(os.path.join(self.base, "hosts.json"), "w") as f:
            json.dump({h.name: {"home": h.home, "sessions": h.sessions_dir} for h in every}, f)
        for h in every:
            conf = {"self": h.name}
            for o in every:
                if o is not h and (only is None or o.name in only.get(h.name, [])):
                    conf[o.name] = {"ssh": o.name, "fleet": fleet.__file__, "python": python or sys.executable}
            if h is self.here:
                conf.update(extra or {})
            os.makedirs(h.home, exist_ok=True)
            with open(os.path.join(h.home, "machines.json"), "w") as f:
                json.dump(conf, f)

    def here_env(self):
        """Point the process back at `here` (a `run` as another machine's session moved it)."""
        self.mp.setenv("FLEET_HOME", self.here.home)
        self.mp.setenv("FLEET_SESSIONS_DIR", self.here.sessions_dir)

    def ssh_log(self):
        try:
            return [json.loads(ln) for ln in open(os.path.join(self.base, "ssh.log"))]
        except OSError:
            return []

    def run(self, who, *argv):
        """Run `fleet <argv>` as the session `who`; returns (code, stdout, stderr)."""
        who.env(self.mp)
        self.capsys.readouterr()
        code = fleet.main(list(argv))
        out = self.capsys.readouterr()
        return code, out.out, out.err

    def member(self, who, *argv):
        return self.run(who, "join", *argv)

    def close(self):
        for s in self.sessions:
            s.close()


@pytest.fixture
def world(monkeypatch, capsys):
    base = tempfile.mkdtemp(prefix="fl", dir="/tmp")  # short: unix socket paths are limited to ~100 bytes
    w = World(base, monkeypatch, capsys)
    yield w
    w.close()
    import shutil
    shutil.rmtree(base, ignore_errors=True)


def wait_for(cond, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False
