"""Shared helpers for the session index's tests. Other test files import them and never edit them.

`index_env` points FLEET_HOME, FLEET_BACKUP_DIR and HOME at a temp folder, so no test touches a real store,
backup folder or env checkout. `Store` is a hub store on machines `main` (the hub), `mac` and `lat`. `Cluster`
builds machines with their own FLEET_HOME and a fake `ssh` (fleet_testkit's), so a command runs "on" a machine
as a subprocess, the way it runs for real.
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import fleet_index_store as store  # noqa: E402
import fleet_work  # noqa: E402
from fleet_testkit import FAKE_SSH  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "session_index")
CLI = os.path.join(ROOT, "fleet_index_cli.py")
HOOK = os.path.join(ROOT, "fleet_index_hook.py")
MACHINES = {"main", "mac", "lat", "self"}
SID = "0a1b2c3d-0000-4000-8000-0000000000%02d"


def sid(n):
    return SID % n


def fixture(*parts):
    with open(os.path.join(FIX, *parts)) as f:
        return json.load(f)


@pytest.fixture
def index_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("FLEET_HOME", str(tmp_path / "fleet"))
    monkeypatch.setenv("FLEET_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("FLEET_INDEX_FOREGROUND", "1")
    for k in ("CLAUDE_DETACH_NAME", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CONFIG_DIR", "FLEET_RC_NAME", "FLEET_NO_RECORD"):
        monkeypatch.delenv(k, raising=False)
    store._ON_CHANGE.clear()
    store._BEFORE_READ.clear()
    import fleet_index_cli
    fleet_index_cli._HUBS.clear()
    yield tmp_path
    for con in fleet_index_cli._HUBS.values():
        con.close()
    fleet_index_cli._HUBS.clear()


class Store:
    """A hub store on `main` with a seq counter per machine."""

    def __init__(self, path):
        self.con = store.connect(path)
        self.seqs = {}
        self.hub = "main"
        self.machines = set(MACHINES)

    def entry(self, machine, sid_, event, fields=None, *, epoch_seen=1, writer=None, seq=None):
        if seq is None:
            seq = self.seqs.get(machine, 0) + 1
        self.seqs[machine] = max(self.seqs.get(machine, 0), seq)
        return {"v": 1, "machine": machine, "seq": seq, "as": writer or machine, "sid": sid_,
                "epoch_seen": epoch_seen, "event": event, "at": 1795600000.0 + seq, "fields": dict(fields or {})}

    def apply(self, machine, *entries):
        return store.apply_batch(self.con, {"machine": machine, "entries": list(entries)}, hub=self.hub,
                                 machines=self.machines)

    def start(self, machine, sid_, fields=None, writer=None):
        f = {"name": "a chat", "name_source": "custom", "kind": "chat", "cwd": "/home/me/app", "work": False}
        f.update(fields or {})
        if f.get("work"):
            f = fleet_work.mask_fields(f)
        reply = self.apply(machine, self.entry(machine, sid_, "start", f, writer=writer))
        assert reply["results"][-1]["outcome"] == "applied", reply
        return store.get_row(self.con, sid_)

    def take(self, sid_, to, expect, by=None):
        return store.take(self.con, sid_, to, expect, by or to, hub=self.hub, machines=self.machines)

    def row(self, sid_):
        return store.get_row(self.con, sid_)


@pytest.fixture
def hub(index_env):
    s = Store(str(index_env / "fleet" / "index" / "hub.db"))
    yield s
    s.con.close()


class Machine:
    def __init__(self, cluster, name):
        self.cluster, self.name = cluster, name
        self.home = str(cluster.base / ("m-" + name))
        os.makedirs(self.home, exist_ok=True)

    def env(self, **extra):
        env = dict(os.environ, FLEET_HOME=self.home, FLEET_INDEX_FOREGROUND="1")
        env.pop("FLEET_NO_RECORD", None)
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def cli(self, *args, stdin=None, **extra):
        return subprocess.run([sys.executable, CLI] + list(args), input=stdin, capture_output=True, text=True,
                              env=self.env(**extra), timeout=60)

    def hook(self, payload, **extra):
        return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), capture_output=True, text=True,
                              env=self.env(**extra), timeout=60)

    def file(self, *parts):
        return os.path.join(self.home, *parts)

    def journal(self):
        try:
            with open(self.file("index", "journal.jsonl")) as f:
                return [json.loads(ln) for ln in f if ln.strip()]
        except OSError:
            return []

    def state(self):
        with open(self.file("index", "journal.state.json")) as f:
            return json.load(f)

    def cache(self, sid_):
        try:
            with open(self.file("index", "cache", sid_ + ".json")) as f:
                return json.load(f)
        except OSError:
            return None

    def hub_row(self, sid_):
        con = store.connect(self.file("index", "hub.db"))
        try:
            return store.get_row(con, sid_)
        finally:
            con.close()


class Cluster:
    """Machines with their own FLEET_HOME, one of them the hub, joined by a fake ssh. `down(name)` makes a machine
    unreachable and `up(name)` brings it back."""

    def __init__(self, base, monkeypatch, names, hub):
        self.base, self.mp = base, monkeypatch
        self.machines = {n: Machine(self, n) for n in names}
        os.makedirs(str(base / "bin"), exist_ok=True)
        ssh = str(base / "bin" / "ssh")
        with open(ssh, "w") as f:
            f.write(FAKE_SSH % sys.executable)
        os.chmod(ssh, 0o755)
        monkeypatch.setenv("PATH", str(base / "bin") + os.pathsep + os.environ["PATH"])
        monkeypatch.setenv("FAKE_SSH_BASE", str(base))
        fleet_py = os.path.join(ROOT, "fleet.py")
        for m in self.machines.values():
            conf = {"self": m.name, "hub": hub}
            for o in self.machines.values():
                if o is not m:
                    conf[o.name] = {"ssh": o.name, "fleet": fleet_py, "python": sys.executable}
            with open(m.file("machines.json"), "w") as f:
                json.dump(conf, f)
        self.reachable = set(names)
        self._hosts()

    def _hosts(self):
        with open(str(self.base / "hosts.json"), "w") as f:
            json.dump({n: {"home": m.home, "sessions": os.path.join(m.home, "sessions")}
                       for n, m in self.machines.items() if n in self.reachable}, f)

    def down(self, name):
        self.reachable.discard(name)
        self._hosts()

    def up(self, name):
        self.reachable.add(name)
        self._hosts()

    def __getitem__(self, name):
        return self.machines[name]


@pytest.fixture
def cluster(index_env, monkeypatch):
    return Cluster(index_env, monkeypatch, ["main", "mac", "lat"], hub="main")


def transcript(path, prompts, answers=(), title=None):
    """A small transcript: prompts and answers in turn, then a custom title when given."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for i, p in enumerate(prompts):
            f.write(json.dumps({"type": "user", "message": {"role": "user", "content": p},
                                "timestamp": "2026-11-25T10:%02d:00Z" % i}) + "\n")
            if i < len(answers):
                f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": answers[i]}]}, "timestamp": "2026-11-25T10:%02d:30Z" % i}) + "\n")
        if title:
            f.write(json.dumps({"type": "custom-title", "customTitle": title, "sessionId": "x"}) + "\n")
    return path
