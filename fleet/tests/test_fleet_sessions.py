"""`fleet sessions`: every session of every machine, the plan that lands in one, and the page's Sessions API.

Three machines: `here` (the hub, a Mac-like screen), `bee` (reachable) and `cee` (in machines.json, never
answers). The hub holds the real session index; a seeded session is in its machine's history and, through a journal
batch, in the index. Each machine's tmux server and process tree are files in its FLEET_HOME read by a fake `tmux`
and `ps`; each machine's work.json calls a folder under WORK work; the env checkout is a fake one that only has to
be there for the picker's command.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

import pytest

import schema_check
from fleet_testkit import cache_row, fleet, world  # noqa: F401

import fleet_index_cli as cli  # noqa: E402
import fleet_index_store as store  # noqa: E402
import fleet_sessions_api as sapi  # noqa: E402
import fleet_work  # noqa: E402

fs = fleet.fs
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs",
                           "session-index.schema.json")

FAKE_TMUX = '''#!/bin/sh
if [ -f "$FLEET_HOME/tmux.txt" ]; then cat "$FLEET_HOME/tmux.txt"; else echo "no server running" >&2; exit 1; fi
'''
FAKE_PS = '''#!/bin/sh
cat "$FLEET_HOME/ps.txt" 2>/dev/null
'''
LOGGER = '''#!%s
import json, os, sys
open(os.environ["FAKE_WINDOW_LOG"], "a").write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + "\\n")
print("ok")
'''
TIMEOUT_LINE = "ssh: connect to host %s port 22: Operation timed out"
# A headless `claude -p` that says which machine ran it (its FLEET_HOME's folder), and `agents` as the shared stub
# does it, so the list still sees the fake sessions.
MODEL = '''#!%s
import json, os, sys
a = sys.argv[1:]
if a[:1] == ["agents"]:
    os.execv(os.path.join(os.environ["STUB_DIR"], "claude"), ["claude"] + a)
where = "bee" if "/h-bee/" in os.environ["FLEET_HOME"] else "here"
prompt = sys.stdin.read()
if "They are looking for" in prompt:
    print('[{"n": 1, "why": "it planned the export"}]')
elif "Question:" in prompt:
    print("ANSWER of %%s: %%s" %% (where, prompt.split("Question: ")[1].splitlines()[0]))
else:
    print("Described on %%s, from its own transcript." %% where)
'''


def sid(n):
    return str(uuid.UUID(int=n, version=4))


def script(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)
    return path


class Three:
    def __init__(self, world, here_conf=None):
        self.w, b = world, world.base
        self.bee = world.host("bee")
        conf = {"hub": "here", "screen": "macos", "cee": {"ssh": "cee", "fleet": "/x/fleet.py"}}
        conf.update(here_conf or {})
        world.link(self.bee, extra=conf)
        bee_file = os.path.join(self.bee.home, "machines.json")
        with open(bee_file) as f:
            theirs = json.load(f)
        theirs["hub"] = conf["hub"]
        with open(bee_file, "w") as f:
            json.dump(theirs, f)
        self.env = os.path.join(b, "env")
        script(os.path.join(self.env, "libexec", "claude", "_session", "_core.py"), "")
        self.work = "/home/u/work"  # outside /tmp, which the kind rules call a job folder
        self.window_log = os.path.join(b, "windows.jsonl")
        for host in (world.here, self.bee):
            with open(os.path.join(host.home, "work.json"), "w") as f:
                json.dump({"accounts": ["me", "other"], "profile_paths": [self.work],
                           "own_profiles": os.path.join(b, "profiles")}, f)
        for k, v in {"FLEET_ENV_DIR": self.env, "FLEET_BACKUP_DIR": os.path.join(b, "backups"),
                     "CLAUDE_SESSIONS_DIR": os.path.join(b, "registry"),  # the registry shim writes here only
                     "FLEET_TMUX": script(os.path.join(b, "tools", "tmux"), FAKE_TMUX),
                     "FLEET_PS": script(os.path.join(b, "tools", "ps"), FAKE_PS),
                     "FAKE_WINDOW_LOG": self.window_log}.items():
            world.mp.setenv(k, v)
        store._ON_CHANGE.clear()
        store._BEFORE_READ.clear()
        cli._HUBS.clear()
        sapi._ATTEMPTS.clear()
        self.T = float(int(time.time()))
        self.seqs = {}

    def hub_db(self, host=None):
        return store.connect(os.path.join((host or self.w.here).home, "index", "hub.db"))

    def index(self, machine, s, fields, ago=0, event="start", writer=None, epoch=1, hub=None):
        """One journal entry of `machine`, applied to the hub's index `ago` seconds ago."""
        self.seqs[machine] = self.seqs.get(machine, 0) + 1
        con = self.hub_db(hub)
        hub_name = hub.name if hub else "here"
        reply = store.apply_batch(con, {"machine": machine, "entries": [{
            "v": 1, "machine": machine, "seq": self.seqs[machine], "as": writer or machine, "sid": s,
            "epoch_seen": epoch, "event": event, "at": self.T - ago, "fields": fields}]},
            hub=hub_name, machines={"here", "bee", "cee"}, now=self.T - ago)
        con.close()
        assert reply["results"][0]["outcome"] == "applied", reply

    def take(self, s, to, expect=1):
        con = self.hub_db()
        store.take(con, s, to, expect, "here" if to.startswith("phone:") else to, hub="here",
                   machines={"here", "bee", "cee"})
        con.close()

    def row(self, s):
        con = self.hub_db()
        r = store.get_row(con, s)
        con.close()
        return r

    def seed(self, host, s, cwd, ago, name=None, ai=None, prompt="", transcript="", ended=None, kind=None,
             index=True, hub=None):
        machine = "here" if host is self.w.here else host.name
        # the machine's own cache of the index: what its journal left, its work rows whole
        cache_row(host.home, s, cwd, self.T - 3600 - ago, self.T - ago, machine=machine, name=name or ai or "",
                  name_source="custom" if name else "ai" if ai else "", first_prompt=prompt, ended=ended,
                  end_reason="exit" if ended else None, kind=kind or fs.kind_of(name or ai, cwd),
                  work=cwd.startswith(self.work) or "/.claude-work/" in transcript)
        if not index:
            return
        label = name or ai
        fields = {"cwd": cwd, "first_prompt": prompt, "kind": kind or fs.kind_of(label, cwd),
                  "work": cwd.startswith(self.work) or "/.claude-work/" in transcript}
        if label:
            fields.update(name=label, name_source="custom" if name else "ai")
        if fields["work"]:
            fields = fleet_work.mask_fields(fields)
        self.index(machine, s, fields, ago, hub=hub)
        if ended:
            self.index(machine, s, {"work": fields["work"], "end_reason": "exit"}, ago, event="end", hub=hub)

    def live(self, host, name, s, cwd):
        """A running interactive session with session id `s`."""
        ses = host.session(name, cwd=cwd)
        ses.sid = s
        ses.info["sessionId"] = s
        ses.write_info()
        return ses

    def tmux(self, host, ses, tmux_name, pane=70001):
        """`ses` runs in a pane of tmux session `tmux_name`, under a shell: its pid -> 70002 (the shell) -> pane."""
        with open(os.path.join(host.home, "tmux.txt"), "a") as f:
            f.write("%d %s\n" % (pane, tmux_name))
        with open(os.path.join(host.home, "ps.txt"), "a") as f:
            f.write("%d %d\n%d %d\n" % (ses.pid, pane + 1, pane + 1, pane))

    def agents(self, host, entries):
        os.makedirs(host.home, exist_ok=True)
        with open(os.path.join(host.home, "agents.json"), "w") as f:
            json.dump(entries, f)

    def status(self, name, status):
        with open(os.path.join(self.w.stub_dir, "status.json"), "w") as f:
            json.dump({name: {"status": status}}, f)

    def cli(self, *argv):
        self.w.here_env()
        self.w.mp.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        self.w.capsys.readouterr()
        code = fleet.main(list(argv))
        out = self.w.capsys.readouterr()
        return code, out.out, out.err

    def env_json(self, *argv):
        code, out, err = self.cli("sessions", "--json", *argv)
        assert code == 0, err
        return json.loads(out)

    def plan(self, key):
        code, out, err = self.cli("sessions", "open", key, "--json")
        assert code == 0, err
        return json.loads(out)


V, U, OLD, JOB, W, S, C = (sid(i) for i in range(1, 8))


@pytest.fixture
def three(world):
    t = Three(world)
    yield t
    world.here_env()
    for con in cli._HUBS.values():
        con.close()
    cli._HUBS.clear()
    store._ON_CHANGE.clear()
    store._BEFORE_READ.clear()


def listing(t):
    """here: voice (live in tmux, a member), an unnamed chat of yesterday, an unnamed chat of 20 days ago, a job;
    bee: notes (live in a window), a work-rule chat; cee (never answers): one session the index holds."""
    w = t.w
    v = t.live(w.here, "voice", V, "/home/u/projects/a")
    t.seed(w.here, V, "/home/u/projects/a", 60, name="voice", prompt="Plan the voice work")
    t.tmux(w.here, v, "voice")
    assert w.member(v, "voice")[0] == 0
    t.seed(w.here, U, "/home/u/projects/blog", 86400, prompt="Fix the feed")
    t.seed(w.here, OLD, "/home/u/projects/blog", 20 * 86400, prompt="An old question", ended=t.T - 20 * 86400)
    t.seed(w.here, JOB, "/home/u/tmp/job-1", 30, name="job one", prompt="Do the job")
    t.live(t.bee, "notes", W, "/home/u/b")
    t.seed(t.bee, W, "/home/u/b", 120, name="notes", prompt="Take notes")
    t.seed(t.bee, S, os.path.join(t.work, "a"), 300, ai="Secret plan", prompt="the secret prompt")
    t.index("cee", C, {"name": "gym notes", "name_source": "custom", "kind": "chat", "cwd": "/home/u/c",
                       "first_prompt": "x", "work": False}, 8000)
    w.here_env()
    return v


def api(t, query=None, **kw):
    t.w.here_env()
    return sapi.envelope(query, **kw)


def test_one_sid_is_one_row_on_the_sessions_endpoint(three):
    """Two machines hold a transcript of one session: the endpoint gives one row, the index's."""
    t = three
    t.seed(t.w.here, W, "/home/u/b", 500, name="notes", prompt="Take notes", index=False)
    listing(t)
    rows = [r for r in api(t, {"env": "all", "chains": "all", "kind": "all"})["rows"] if r["sid"] == W]
    assert [(r["key"], r["machine"], r["owner"], r["name"]) for r in rows] == [("bee:" + W, "bee", "bee", "notes")]
    picked = [r for r in t.env_json("--kind", "all")["rows"] if r["id"] == W]
    assert [(r["key"], r["name"], r["registry"], r["copies"]) for r in picked] == [("bee:" + W, "notes", "bee", [])]


def test_the_endpoint_gives_the_contracts_reply_with_what_each_session_does_now(three):
    t = three
    v = listing(t)
    reply = api(t)
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)
    assert schema_check.errors(schema, reply, "sessions_reply") == []
    assert (reply["index"], reply["hub"]) == ("up", "here")
    rows = {r["sid"]: r for r in reply["rows"]}
    o = rows[V]["observed"]
    assert (o["live"], o["state"], o["where"], o["tmux"], o["pid"], o["stale"], o["source"]) == \
        (True, "idle", "tmux", "voice", v.pid, False, "machine")
    assert o["observed_at"] >= t.T
    assert (rows[W]["observed"]["live"], rows[W]["observed"]["where"]) == (True, "window")
    assert (rows[U]["observed"]["live"], rows[U]["observed"]["state"]) == (False, "ended")
    assert (rows[C]["observed"]["live"], rows[C]["observed"]["source"], rows[C]["observed"]["stale"]) == \
        (None, "none", True)
    assert (rows[S]["work"], rows[S]["cwd"], rows[S]["first_prompt"], rows[S]["name"]) == (True, None, None, "")
    cee = reply["machines"]["cee"]
    assert cee == {"reachable": False, "as_of": None, "stale": True, "reason": TIMEOUT_LINE % "cee"}
    assert [r["sid"] for r in reply["rows"]] == [r["sid"] for r in sorted(reply["rows"], key=lambda r: -r["updated"])]


def test_a_machine_that_stops_answering_keeps_its_last_values_which_turn_stale(three):
    t = three
    listing(t)
    first = {r["sid"]: r for r in api(t)["rows"]}[W]["observed"]
    path = sapi._observed_path("bee")
    with open(path) as f:
        kept = json.load(f)
    kept["as_of"] = t.T - 61
    with open(path, "w") as f:
        json.dump(kept, f)
    with open(os.path.join(t.w.base, "hosts.json")) as f:
        hosts = json.load(f)
    del hosts["bee"]
    with open(os.path.join(t.w.base, "hosts.json"), "w") as f:
        json.dump(hosts, f)
    reply = api(t)
    o = {r["sid"]: r for r in reply["rows"]}[W]["observed"]
    assert (o["live"], o["pid"], o["observed_at"], o["stale"]) == (True, first["pid"], t.T - 61, True)
    assert (reply["machines"]["bee"]["reachable"], reply["machines"]["bee"]["reason"]) == \
        (False, TIMEOUT_LINE % "bee")


def test_the_server_answers_from_its_last_list_and_refreshes_behind_it(monkeypatch):
    calls = []

    def fake(query=None, *, fresh=False):
        calls.append(fresh)
        return {"n": len(calls)}
    monkeypatch.setattr(sapi, "envelope", fake)
    feed = sapi.IndexFeed(ttl=0)
    assert feed.get()["n"] == 1
    assert feed.get()["n"] == 1  # the last list at once; the next one is being read behind it
    end = time.time() + 5
    while len(calls) < 2 or feed.busy:
        assert time.time() < end
        time.sleep(0.01)
    assert feed.get()["n"] == 2
    assert feed.get(fresh=True)["n"] >= 3 and calls[-1] is True


def test_a_voice_chain_shows_as_one_row_its_head(three):
    t = three
    old, new = sid(40), sid(41)
    t.index("here", old, {"name": "kitchen plans", "name_source": "topic", "kind": "voice",
                          "topic": {"host": "prod", "id": "kitchen"}, "work": False}, 900, writer="phone:prod")
    con = t.hub_db()
    store.chain(con, old, new, "phone:prod", 1, {"name": "kitchen plans", "name_source": "topic", "kind": "voice",
                                                   "topic": {"host": "prod", "id": "kitchen"}}, hub="here")
    con.close()
    got = [(r["sid"], r["head"], r["chain"], r["conversation"]) for r in api(t)["rows"]]
    assert got == [(new, True, [old, new], old)]
    assert [r["id"] for r in t.env_json()["rows"]] == [new]
    every = api(t, {"chains": "all"})
    assert sorted(r["sid"] for r in every["rows"]) == sorted([old, new]) and every["counts"]["superseded"] == 0
    assert api(t)["counts"] == {"rows": 1, "hidden_dev": 0, "superseded": 1}


def test_dev_rows_are_hidden_unless_asked_for(three):
    t = three
    t.index("here", sid(42), {"name": "sandbox topic", "name_source": "topic", "kind": "voice", "work": False},
            writer="phone:dev:box1")
    assert api(t)["rows"] == [] and api(t)["counts"]["hidden_dev"] == 1
    assert [r["sid"] for r in api(t, {"env": "dev:box1"})["rows"]] == [sid(42)]
    assert [r["sid"] for r in api(t, {"env": "all"})["rows"]] == [sid(42)]


def test_the_picker_reads_the_index_in_its_own_row_shape(three):
    t = three
    v = listing(t)
    conf_path = os.path.join(t.w.here.home, "machines.json")
    with open(conf_path) as f:
        conf = json.load(f)
    conf["cee"]["screen"] = "hyprland"  # the hub's machines.json says which screen another machine has
    with open(conf_path, "w") as f:
        json.dump(conf, f)
    env = t.env_json()
    rows = {r["id"]: r for r in env["rows"]}
    assert set(rows) == {V, U, W, S, C}  # the 20-day-old unnamed chat and the job are out of the default view
    voice = dict(rows[V])
    assert voice.pop("as_of") >= t.T
    assert voice == {"key": "here:" + V, "id": V, "machine": "here", "name": "voice", "named": True,
                     "folder": "/home/u/projects/a", "about": "Plan the voice work", "kind": "chat", "where": "tmux",
                     "tmux": "voice", "state": "idle", "pid": v.pid, "member": True, "held": [], "unanswered": [],
                     "free": True, "started": t.T - 60, "last_seen": t.T - 60, "ended": None, "end_reason": "",
                     "live_on": ["here"], "copies": [], "stale": False, "masked": False, "registry": "here"}
    notes = rows[W]
    assert (notes["machine"], notes["where"], notes["tmux"], notes["state"], notes["member"], notes["live_on"]) == \
        ("bee", "window", None, "idle", False, ["bee"])
    secret = rows[S]  # a work-rule row through another machine: no folder, no prompt, no name taken from it
    assert (secret["masked"], secret["folder"], secret["about"], secret["name"], secret["named"]) == \
        (True, "", "", "", False)
    assert (rows[U]["name"], rows[U]["named"], rows[U]["about"]) == ("", False, "Fix the feed")
    assert (rows[C]["stale"], rows[C]["where"], rows[C]["state"]) == (True, "none", "")
    assert (env["machines"]["cee"]["reachable"], env["machines"]["cee"]["screen"],
            env["machines"]["here"]["screen"]) == (False, "hyprland", "macos")
    assert set(env) == {"machines", "hub", "as_of", "rows"}
    assert [r["id"] for r in env["rows"]] == [V, W, S, C, U]  # newest change first
    every = {r["id"]: r for r in t.env_json("--kind", "all")["rows"]}
    assert every[JOB]["kind"] == "job" and OLD in every
    assert {r["id"] for r in t.env_json("--machine", "bee")["rows"]} == {W, S}


def test_a_machines_own_facts_hold_its_work_rows_in_full(three):
    t = three
    listing(t)
    t.w.mp.setenv("FLEET_HOME", t.bee.home)
    t.w.mp.setenv("FLEET_SESSIONS_DIR", t.bee.sessions_dir)
    t.w.capsys.readouterr()
    assert fleet.main(["sessions", "--local", "--json"]) == 0
    rows = {r["id"]: r for r in json.loads(t.w.capsys.readouterr().out)["rows"]}
    assert (rows[S]["masked"], rows[S]["folder"], rows[S]["about"], rows[S]["name"]) == \
        (False, os.path.join(t.work, "a"), "the secret prompt", "Secret plan")


def test_observe_never_names_a_work_sessions_tmux(three):
    t = three
    s = t.live(t.w.here, "client", sid(43), os.path.join(t.work, "a"))
    t.tmux(t.w.here, s, "client-secret")
    t.w.here_env()
    reply = sapi.observe_local()
    with open(SCHEMA_PATH) as f:
        assert schema_check.errors(json.load(f), reply, "observe_reply") == []
    assert reply["rows"][sid(43)] == {"live": True, "state": "idle", "where": "tmux", "tmux": None, "pid": s.pid}


def test_a_work_account_transcript_is_masked_on_its_own_machine_whatever_its_folder(three):
    t = three
    tr = os.path.join(os.path.expanduser("~"), ".claude-work", "projects", "x", S + ".jsonl")
    t.seed(t.bee, S, "/home/u/projects/plain", 300, name="standup", prompt="what did we ship", transcript=tr,
           index=False)
    t.w.mp.setenv("FLEET_HOME", t.bee.home)
    rows = fs.build_rows("bee", fleet.own_index_rows(), [], [], {}, {}, is_work=fleet.work_rule())
    row = fs.mask(rows[0])
    assert (row["masked"], row["folder"], row["about"], row["name"]) == (True, "", "", "standup")


def plans_world(t):
    w = t.w
    listing(t)
    base = str(w.base)
    t.seed(w.here, sid(20), base, 7200, name="lungo plan review", kind="chat", ended=t.T - 7200)
    t.seed(w.here, sid(21), base, 7300, name="voice", kind="chat", ended=t.T - 7300)
    helper = t.live(w.here, "helper", sid(22), base)
    t.seed(w.here, sid(22), base, 10, name="helper", kind="chat")
    assert w.member(helper, "helper")[0] == 0
    t.seed(w.here, sid(23), "/no/such/folder", 9000, name="gone away", kind="chat", ended=t.T - 9000)
    t.seed(w.here, sid(24), base, 9100, name="moved", kind="chat", ended=t.T - 9100)
    t.live(t.bee, "moved-copy", sid(24), "/home/u/b")
    t.seed(w.here, sid(25), base, 9200, name="phone talk", kind="chat")
    t.take(sid(25), "phone:prod")
    t.agents(t.bee, [{"id": "bg123456", "sessionId": sid(26), "name": "admin", "cwd": "/home/u/l",
                      "kind": "background", "state": "blocked", "startedAt": 1000}])
    w.here_env()


def test_every_plan_kind(three):
    t = three
    plans_world(t)
    base = str(t.w.base)
    p = t.plan("here:" + sid(20))
    assert p == {"kind": "resume", "key": "here:" + sid(20), "id": sid(20), "machine": "here",
                 "name": "lungo plan review", "tmux": "lungo-plan-review", "folder": base, "pid": None, "state": "",
                 "member": False, "message": "", "force": False, "run_on_owner": False, "head": sid(20),
                 "take": None}
    p = t.plan("here:" + sid(21))  # "voice" is taken by another conversation's tmux session
    assert (p["kind"], p["tmux"]) == ("resume", "voice-" + sid(21)[:8])
    p = t.plan("here:" + V)
    assert (p["kind"], p["machine"], p["tmux"], p["folder"], p["member"]) == \
        ("attach-tmux", "here", "voice", "/home/u/projects/a", True)
    p = t.plan("bee:" + sid(26))  # a session the index does not hold yet: what its machine says
    assert (p["kind"], p["machine"], p["id"], p["state"], p["take"]) == ("attach-bg", "bee", sid(26), "blocked", None)
    p = t.plan("here:" + sid(22))
    assert (p["kind"], p["name"], p["tmux"], p["member"], p["message"]) == ("wrap-up-then-resume", "helper", "helper", True,
        "helper is a fleet member in a window: it is told to wrap up and leave, then resumed in tmux once its process is gone")
    p = t.plan("bee:" + W)
    assert (p["kind"], p["force"], p["machine"], p["message"]) == (
        "blocked-window", True, "bee",
        "open in a window on bee, status idle, pid %d: it is not a fleet member, so it cannot be told to leave" % p["pid"])
    p = t.plan("cee:" + C)
    assert (p["kind"], p["machine"]) == ("refuse-offline", "cee")
    assert p["message"].startswith("cee: not answering (%s); last answer at " % (TIMEOUT_LINE % "cee"))
    p = t.plan("here:" + sid(23))
    assert (p["kind"], p["message"]) == ("refuse-no-folder", "here: the folder /no/such/folder is gone; it is not created again")
    p = t.plan("here:" + sid(24))  # the index says here owns it; it runs in a window on bee
    assert (p["kind"], p["machine"], p["message"]) == (
        "refuse-live-elsewhere", "bee", "moved is live on bee in a window, not in tmux: it is not resumed on here")
    p = t.plan("bee:" + S)  # a work-rule row of bee, planned on here: bee works it out itself, and no folder leaks
    assert (p["kind"], p["machine"], p["folder"], p["tmux"], p["run_on_owner"], p["take"], p["message"]) == \
        ("refuse-no-folder", "bee", "", "", True, None,
         "bee: the folder of this session is gone; it is not created again")
    assert {k for k in fs.PLAN_KINDS} == {"attach-tmux", "attach-bg", "resume", "take-then-resume",
                                          "wrap-up-then-resume", "blocked-window", "refuse-offline",
                                          "refuse-no-folder", "refuse-live-elsewhere"}


def test_a_phone_owned_session_plans_a_take_then_a_resume(three):
    t = three
    plans_world(t)
    p = t.plan("here:" + sid(25))
    assert p == {"kind": "take-then-resume", "key": "here:" + sid(25), "id": sid(25), "machine": "here",
                 "name": "phone talk", "tmux": "phone-talk", "folder": str(t.w.base), "pid": None, "state": "",
                 "member": False, "message": "phone talk is on the phone: it is taken to here first, then resumed there",
                 "force": False, "run_on_owner": False, "head": sid(25),
                 "take": {"sid": sid(25), "to": "here", "expect_epoch": 2}}
    code, out, err = t.cli("sessions", "open", "here:" + sid(25), "--to", "bee", "--json")
    assert code == 0, err
    p = json.loads(out)
    assert (p["kind"], p["machine"], p["take"]) == \
        ("take-then-resume", "bee", {"sid": sid(25), "to": "bee", "expect_epoch": 2})


def test_a_session_owned_by_a_machine_where_it_is_not_live_is_taken_to_the_asked_one(three):
    t = three
    plans_world(t)
    code, out, err = t.cli("sessions", "open", "here:" + sid(20), "--to", "bee", "--json")
    assert code == 0, err
    p = json.loads(out)
    assert (p["kind"], p["machine"], p["take"], p["message"]) == (
        "take-then-resume", "bee", {"sid": sid(20), "to": "bee", "expect_epoch": 1},
        "lungo plan review is on here: it is taken to bee first, then resumed there")
    code, out, _ = t.cli("sessions", "open", "cee:" + C, "--to", "here", "--json")
    assert json.loads(out)["kind"] == "refuse-offline"  # its owner does not answer: it may be running there


def test_continue_on_the_phone_plans_a_take_to_the_phone(three):
    t = three
    plans_world(t)
    code, out, err = t.cli("sessions", "open", "here:" + sid(20), "--to", "phone:prod", "--json")
    assert code == 0, err
    p = json.loads(out)
    assert (p["kind"], p["machine"], p["tmux"], p["take"]) == (
        "take-then-resume", "phone:prod", "", {"sid": sid(20), "to": "phone:prod", "expect_epoch": 1})
    code, _, err = t.cli("sessions", "open", "here:" + sid(20), "--to", "phone:everyone", "--json")
    assert (code, err.strip()) == (1, "fleet: --to takes a machine of machines.json or phone:<host>, not "
                                      "'phone:everyone'.")


def test_a_superseded_sid_plans_the_chain_head(three):
    t = three
    base = str(t.w.base)
    old, new = sid(44), sid(45)
    t.seed(t.w.here, old, base, 900, name="kitchen plans")
    con = t.hub_db()
    store.chain(con, old, new, "here", 1, {"name": "kitchen plans", "name_source": "topic"}, hub="here")
    con.close()
    p = t.plan("here:" + old)
    assert (p["kind"], p["id"], p["head"], p["key"], p["folder"], p["take"]) == \
        ("resume", new, new, "here:" + new, base, None)


def test_a_busy_window_is_never_offered_a_force_stop(three):
    t = three
    listing(t)
    t.status("notes", "busy")
    p = t.plan("bee:" + W)
    assert (p["kind"], p["force"], p["state"]) == ("blocked-window", False, "busy")
    assert p["message"].endswith("; it is never stopped while it works")


def test_a_key_that_is_not_one_is_refused(three):
    code, _, err = three.cli("sessions", "open", "here:not-hex!", "--json")
    assert (code, err.strip()) == (1, "fleet: 'here:not-hex!' is not a session key (machine:id).")
    code, _, err = three.cli("sessions", "open", "nowhere:" + V, "--json")
    assert (code, err.strip()) == (1, "fleet: no machine named 'nowhere' in machines.json.")


def test_the_pane_walk_and_the_kind_rules():
    panes = fs.parse_panes("500 voice\n600 other\nnot a line\n")
    parents = fs.parse_parents(" 900 800\n 800 500\n 700 1\n")
    assert fs.pane_of(900, panes, parents) == "voice"
    assert fs.pane_of(700, panes, parents) is None
    assert fs.pane_of(600, panes, parents) == "other"
    assert fs.pane_of(901, panes, {901: 902, 902: 901}) is None  # a loop ends
    assert [fs.kind_of(n, f) for n, f in [
        ("job:x", "/home/u/p"), ("dashboard-worker-3", "/"), ("Claude voice session handover", "/home/u/p"),
        ("", "/home/u/tmp/a"), ("", "/tmp/a"), ("", "/home/u/.local/state/lungo/x"),
        ("", "/home/u/projects/lomem-checkouts/a/b"), ("", "/home/u/p/.scratch/x"), ("", "/home/u/tmp"),
        ("", "/home/u/tmpx/a")]] == [
        "worker", "worker", "chat", "job", "job", "job", "job", "job", "job", "chat"]
    assert fs.kind_of("bot-1", "/srv/x", {"worker_prefixes": ["bot-"]}) == "worker"
    assert fs.kind_of("", "/srv/x/y", {"job_folders": ["/srv/x/*"]}) == "job"
    assert fs.slug("Claude voice session handover.v2", V) == "Claude-voice-session-handover-v2"
    assert fs.slug("", V) == V[:8] and len(fs.slug("x" * 80, V)) == 40


def test_off_the_hub_the_hubs_list_is_shown_and_a_down_hub_says_so_with_the_last_one(world):
    t = Three(world, here_conf={"hub": "bee"})
    t.index("bee", W, {"name": "notes", "name_source": "custom", "kind": "chat", "cwd": "/home/u/b",
                       "work": False}, 100, hub=t.bee)
    t.index("here", U, {"name": "stale name", "name_source": "custom", "kind": "chat", "cwd": "/home/u/p",
                        "work": False}, 200, hub=t.bee)
    sapi._cache().write(fleet.fleet_home(), dict(store.get_row(t.hub_db(t.bee), U), name="my own name"),
                        source="local")
    env = api(t)
    assert (env["index"], env["hub"], sorted(r["sid"] for r in env["rows"])) == ("up", "bee", sorted([U, W]))
    assert any(h == "bee" and " session list --json" in cmd for h, cmd in world.ssh_log())
    with open(os.path.join(world.base, "hosts.json")) as f:
        hosts = json.load(f)
    del hosts["bee"]
    with open(os.path.join(world.base, "hosts.json"), "w") as f:
        json.dump(hosts, f)
    env = api(t)
    assert (env["index"], env["reason"]) == ("down", "the hub bee did not answer (%s)" % (TIMEOUT_LINE % "bee"))
    assert {r["sid"]: r["name"] for r in env["rows"]} == {W: "notes", U: "my own name"}
    picked = t.env_json()
    assert picked["note"] == env["reason"] and {r["id"] for r in picked["rows"]} == {W, U}
    world.here_env()


# ---------------------------------------------------------------- internal verbs

def test_force_stop_ends_only_an_idle_window_that_is_no_member(three):
    t = three
    w = t.w
    loose = t.live(w.here, "loose", sid(30), "/home/u/x")
    v = listing(t)
    t.status("loose", "busy")
    assert t.cli("_force-stop", "here:" + sid(30))[2].strip() == \
        "fleet: here:%s is busy, not idle; it is never stopped while it works." % sid(30)
    assert t.cli("_force-stop", "here:" + V)[2].strip() == \
        "fleet: here:%s is a fleet member: it is told to wrap up (`fleet stop`), never killed." % V
    t.status("voice", "idle")
    assert v.proc.poll() is None
    t.status("loose", "idle")
    code, out, err = t.cli("_force-stop", "here:" + sid(30))
    assert code == 0, err
    assert json.loads(out) == {"stopped": loose.pid, "key": "here:" + sid(30), "id": sid(30)}
    assert loose.proc.wait(5) == -15
    assert t.cli("_force-stop", "bee:" + W)[2].strip() == \
        "fleet: bee:%s is a session of bee, not of this machine (here)." % W


def test_force_stop_refuses_a_session_in_tmux(three):
    t = three
    s = t.live(t.w.here, "boxed", sid(31), "/home/u/x")
    t.tmux(t.w.here, s, "boxed")
    assert t.cli("_force-stop", "here:" + sid(31))[2].strip() == "fleet: here:%s runs in tmux; attach to it instead." % sid(31)
    assert s.proc.poll() is None


def window_log(t):
    try:
        return [json.loads(x) for x in open(t.window_log)]
    except OSError:
        return []


def test_open_window_on_a_mac_runs_ghostty_with_the_picker_in_a_login_shell(three):
    t = three
    script(os.path.join(t.w.base, "bin", "open"), LOGGER % sys.executable)
    t.w.mp.setenv("SHELL", "/bin/zsh")
    code, out, err = t.cli("_open-window", "here:" + V)
    assert code == 0, err
    line = "%s --open here:%s" % (os.path.join(t.env, "libexec", "claude", "pick"), V)
    assert window_log(t) == [["open", "-na", "Ghostty", "--args", "-e", "/bin/zsh", "-lic", line]]
    assert json.loads(out) == {"opened": "here", "screen": "macos", "command": line}


def test_open_window_on_hyprland_uses_the_live_instance(three, tmp_path):
    t = three
    conf_path = os.path.join(t.w.here.home, "machines.json")
    with open(conf_path) as f:
        conf = json.load(f)
    conf["screen"] = "hyprland"
    with open(conf_path, "w") as f:
        json.dump(conf, f)
    run = str(tmp_path)
    os.makedirs(os.path.join(run, "hypr", "abc_123"))
    open(os.path.join(run, "hypr", "abc_123", ".socket.sock"), "w").close()
    t.w.mp.setenv("XDG_RUNTIME_DIR", run)
    t.w.mp.setenv("SHELL", "/bin/bash")
    script(os.path.join(t.w.base, "bin", "hyprctl"), LOGGER % sys.executable)
    code, _, err = t.cli("_open-window", "here:" + V)
    assert code == 0, err
    line = "%s --open here:%s" % (os.path.join(t.env, "libexec", "claude", "pick"), V)
    assert window_log(t) == [["hyprctl", "--instance", "abc_123", "dispatch", "exec",
                              "ghostty -e /bin/bash -lic '%s'" % line]]


def test_a_machine_without_a_screen_opens_no_window(three):
    t = three
    conf_path = os.path.join(t.w.here.home, "machines.json")
    with open(conf_path) as f:
        conf = json.load(f)
    del conf["screen"]
    with open(conf_path, "w") as f:
        json.dump(conf, f)
    assert t.cli("_open-window", "here:" + V)[2].strip() == "fleet: here has no screen to open a window on."


# ---------------------------------------------------------------- fixes

def test_the_hubs_machines_json_names_the_screen_of_a_machine_that_answers(three):
    t = three
    conf_path = os.path.join(t.w.here.home, "machines.json")
    with open(conf_path) as f:
        conf = json.load(f)
    conf["bee"]["screen"] = "hyprland"
    with open(conf_path, "w") as f:
        json.dump(conf, f)
    assert t.env_json()["machines"]["bee"]["screen"] == "hyprland"  # bee's own answer says none


def test_tmux_is_found_where_homebrew_puts_it_without_a_login_path(monkeypatch, tmp_path):
    monkeypatch.delenv("FLEET_TMUX", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    brew = os.path.join(str(tmp_path), "opt", "homebrew", "bin", "tmux")
    script(brew, "#!/bin/sh\n")
    monkeypatch.setattr(fleet, "TMUX_PLACES", (brew, "/nowhere/tmux"))
    assert fleet.tmux_bin() == brew


def test_a_tmux_server_with_no_session_still_counts_as_running(three):
    t = three
    t.w.mp.setenv("FLEET_TMUX", script(os.path.join(t.w.base, "tools", "tmux-empty"),
                                       '#!/bin/sh\ncase "$3" in ls) exit 0;; *) exit 1;; esac\n'))
    assert t.env_json("--local")["machines"]["here"]["tmux_server"] is True


def test_claude_is_found_in_the_installers_folder_without_a_login_path(monkeypatch, tmp_path):
    home = str(tmp_path)
    b = script(os.path.join(home, ".local", "bin", "claude"), "#!/bin/sh\n")
    monkeypatch.delenv("FLEET_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert fleet.claude_bin() == b
    monkeypatch.setenv("FLEET_CLAUDE_BIN", "/x/claude")
    assert fleet.claude_bin() == "/x/claude"


def test_history_and_sessions_into_a_closed_pipe_end_quietly(tmp_path):
    home = str(tmp_path)
    env = dict(os.environ, FLEET_HOME=home, FLEET_NO_UPDATE="1")
    env.pop("FLEET_CLAUDE_BIN", None)
    old = os.environ.get("FLEET_HOME")
    os.environ["FLEET_HOME"] = home
    try:  # 3000 sessions of this machine in the index and in its cache
        me = fleet.self_machine()
        con = store.connect(store.hub_db_path(home))
        reply = store.apply_batch(con, {"machine": me, "entries": [
            {"v": 1, "machine": me, "seq": i + 1, "as": me, "sid": sid(1000 + i), "epoch_seen": 1, "event": "start",
             "at": 1000.0 + i, "fields": {"cwd": "/home/u/p", "first_prompt": "prompt %d " % i + "x" * 200,
                                          "kind": "chat", "work": False}} for i in range(3000)]},
            hub=me, machines={me})
        con.close()
        assert {r["outcome"] for r in reply["results"]} == {"applied"}
        for i in range(3000):
            cache_row(home, sid(1000 + i), "/home/u/p", i, i, first_prompt="prompt %d " % i + "x" * 200)
    finally:
        if old is None:
            os.environ.pop("FLEET_HOME")
        else:
            os.environ["FLEET_HOME"] = old
    env["FLEET_ENV_DIR"] = ""
    for argv in (["history", "ls", "--json"], ["sessions", "--local", "--json", "--kind", "all", "--limit", "3000"],
                 ["sessions", "--local", "--kind", "all", "--limit", "3000"]):
        p = subprocess.Popen([sys.executable, fleet.__file__] + argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        p.stdout.read(10)
        p.stdout.close()
        err = p.stderr.read().decode()
        assert (argv, p.wait(30), err) == (argv, 0, "")


# ---------------------------------------------------------------- the page

@pytest.fixture
def page(three):
    srv = fleet.make_ui_server(port=0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = "127.0.0.1:%d" % srv.server_address[1]

    def call(method, path, body=None, headers=None):
        three.w.here_env()
        h = {"Host": host, "Authorization": "Bearer " + srv.fleet_token}
        if method == "POST":
            h.update({"Origin": "http://" + host, "Content-Type": "application/json"})
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        req = urllib.request.Request("http://" + host + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=30)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    call.token = srv.fleet_token
    yield call
    srv.shutdown()
    srv.server_close()


def test_the_sessions_api_lists_and_is_guarded(three, page):
    listing(three)
    code, data = page("GET", "/api/sessions")
    assert code == 200 and set(data) == {"v", "index", "hub", "as_of", "machines", "counts", "rows"}
    assert {r["sid"] for r in data["rows"]} >= {V, W, S, C}
    assert not any(k.startswith("_") for r in data["rows"] for k in r)
    assert [r["sid"] for r in page("GET", "/api/sessions?kind=job")[1]["rows"]] == [JOB]
    assert page("GET", "/api/sessions?env=prodd") == (400, {"error": "env takes prod, all or dev:<sandbox>"})
    assert page("GET", "/api/sessions", headers={"Host": "evil.example"})[0] == 403
    assert page("GET", "/api/sessions", headers={"Authorization": None})[0] == 401
    body = {"key": "here:" + V, "target": "copy"}
    assert page("POST", "/api/sessions/open", body, {"Origin": "http://evil.example"})[0] == 403
    assert page("POST", "/api/sessions/open", body, {"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert page("POST", "/api/sessions/open", body, {"Content-Type": "text/plain"})[0] == 403
    assert page("POST", "/api/sessions/open", body) == (200, {"copy": "@claude pick --open here:" + V})
    assert page("POST", "/api/sessions/open", {"key": "here:" + V, "target": "bee"}) == \
        (400, {"error": "fleet: bee has no screen to open a window on; copy the line instead."})
    assert page("POST", "/api/sessions/open", {"key": "here:x; rm -rf /", "target": "copy"}) == \
        (400, {"error": "fleet: 'here:x; rm -rf /' is not a session key (machine:id)."})
    assert page("POST", "/api/sessions/open", {"key": "here:" + sid(99), "target": "copy"}) == \
        (400, {"error": "fleet: no session here:%s in the list." % sid(99)})
    assert page("POST", "/api/sessions/stop", {"key": "bee:" + W}) == (400, {"error": (
        "fleet: notes is not a fleet member, so it cannot be told to wrap up; an idle one in a window can be stopped "
        "with force.")})


def test_the_service_routes_take_a_bearer_token_and_never_the_cookie(three, page):
    listing(three)
    assert page("GET", "/api/session/owner?sid=" + V) == \
        (200, {"sid": V, "owner": "here", "epoch": 1, "head": V, "source": "hub", "stale": False})
    code, _ = page("GET", "/api/session/owner?sid=" + V,
                   headers={"Authorization": None, "Cookie": "fleet_ui=" + page.token})
    assert code == 401
    code, data = page("POST", "/api/session/take", {"sid": U, "to": "phone:prod", "expect_epoch": 1, "by": "here"})
    assert (code, data["owner"], data["epoch"]) == (200, "phone:prod", 2)
    code, data = page("POST", "/api/session/take", {"sid": U, "to": "here", "expect_epoch": 1})
    assert (code, data["code"]) == (409, "stale-epoch")


def test_the_cli_serves_the_session_verb_and_the_token(three):
    t = three
    listing(t)
    code, out, err = t.cli("session", "show", W, "--json")
    assert (code, json.loads(out)["key"]) == (0, "bee:" + W)
    code, out, _ = t.cli("ui", "token")
    got = json.loads(out)
    assert set(got) == {"url", "token"} and got["url"].startswith("http://127.0.0.1:") and got["token"]


def test_the_page_opens_a_window_through_the_internal_verb_only(three, page):
    listing(three)
    script(os.path.join(three.w.base, "bin", "open"), LOGGER % sys.executable)
    three.w.mp.setenv("SHELL", "/bin/zsh")
    code, data = page("POST", "/api/sessions/open", {"key": "bee:" + W, "target": "here", "command": "touch /tmp/x"})
    assert code == 200, data
    line = "%s --open bee:%s" % (os.path.join(three.env, "libexec", "claude", "pick"), W)
    assert window_log(three) == [["open", "-na", "Ghostty", "--args", "-e", "/bin/zsh", "-lic", line]]
    assert data == {"opened": "here", "screen": "macos", "command": line, "copy": "@claude pick --open bee:" + W}


def test_history_actions_work_on_index_rows(three, page):
    """Rename, describe, ask, search and delete on a row whose transcript is on another machine: the index changes
    on the hub, and the work that reads the transcript runs on the row's own machine."""
    t = three
    t.w.mp.setenv("FLEET_DESCRIBE_PAUSE", "0")
    t.w.mp.setenv("FLEET_NO_RECORD", "1")
    tr = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects", "-home-u-b", W + ".jsonl")  # Claude Code's place
    os.makedirs(os.path.dirname(tr))
    with open(tr, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "Plan the export"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "The export runs nightly."}]}}) + "\n")
    os.utime(tr, (t.T - 3600, t.T - 3600))
    script(os.path.join(t.w.base, "model"), MODEL % sys.executable)
    t.w.mp.setenv("FLEET_CLAUDE_BIN", os.path.join(t.w.base, "model"))
    t.seed(t.bee, W, "/home/u/b", 120, name="notes", prompt="Plan the export", transcript=tr, ended=t.T - 120)
    key = "bee:" + W
    os.makedirs(os.path.join(t.bee.home, "index"), exist_ok=True)
    with open(os.path.join(t.bee.home, "index", "journal.state.json"), "w") as f:
        json.dump({"next_seq": 100, "acked_seq": 99}, f)

    code, data = page("POST", "/api/sessions/rename", {"key": key, "name": "field  notes"})
    assert code == 200, data
    row = t.row(W)
    assert (row["name"], row["name_source"]) == ("field notes", "manual")
    last = json.loads(open(tr).read().splitlines()[-1])  # bee wrote Claude Code's title: one name
    assert last == {"type": "custom-title", "customTitle": "field notes", "sessionId": W}
    assert {r["sid"]: r["name"] for r in page("GET", "/api/sessions?fresh=1")[1]["rows"]}[W] == "field notes"

    code, data = page("POST", "/api/sessions/ask", {"key": key, "question": "when does it run?"})
    assert (code, data) == (200, {"answer": "ANSWER of bee: when does it run?"})

    code, data = page("POST", "/api/sessions/describe", {"key": key})
    assert code == 200, data
    assert t.row(W)["description"] == "Described on bee, from its own transcript."

    t.w.here_env()
    code, data = page("POST", "/api/sessions/search", {"query": "the export"})
    assert (code, data) == (200, {"hits": [{"key": key, "why": "it planned the export"}], "described": 1, "total": 1})

    code, data = page("POST", "/api/sessions/delete", {"key": key})
    assert code == 200, data
    assert t.row(W) is None and os.path.exists(tr)


def test_the_page_refuses_to_describe_a_session_its_machine_does_not_own(three, page):
    plans_world(three)
    assert page("POST", "/api/sessions/describe", {"key": "here:" + sid(25)}) == (400, {"error": (
        "fleet: phone:prod owns this session, not here: take it there first, then describe it.")})


def test_the_page_refuses_to_delete_a_running_session_and_to_ask_about_a_work_session_elsewhere(three, page):
    listing(three)
    assert page("POST", "/api/sessions/delete", {"key": "bee:" + W}) == \
        (400, {"error": "session %s has not ended; stop it first" % W})
    assert three.row(W)["name"] == "notes"
    assert page("POST", "/api/sessions/ask", {"key": "bee:" + S, "question": "what was said?"}) == \
        (400, {"error": "fleet: %s is a work session: it is read only on bee." % S[:8]})


def test_the_page_stops_a_member_with_the_wrap_up_tell(three, page):
    listing(three)
    code, data = page("POST", "/api/sessions/stop", {"key": "here:" + V})
    assert code == 200, data
    assert data["action"] == "interactive" and data["thread"]
    con = three.w.here.db()
    assert con.execute("SELECT body FROM messages WHERE thread=?", (data["thread"],)).fetchone()[0] == fleet.WRAP_UP_TELL


# ---------------------------------------------------------------- one sid, three surfaces

def test_one_sid_reads_the_same_through_the_endpoint_the_cli_list_and_the_pick_plan(three, page):
    """The page's GET /api/sessions, `fleet session list --json` and `fleet sessions open --json` (the pick plan)
    all read the one index: a session shows the same name, owner and state through each."""
    t = three
    listing(t)
    t.take(U, "phone:prod")  # U moves to the phone: epoch 2, its plan must take it back first
    code, api_reply = page("GET", "/api/sessions")
    assert code == 200
    code, out, err = t.cli("session", "list", "--json")
    assert code == 0, err
    cli_reply = json.loads(out)
    seen = {}
    for s in (V, W, U):
        a = next(r for r in api_reply["rows"] if r["sid"] == s)
        c = next(r for r in cli_reply["rows"] if r["sid"] == s)
        p = t.plan(a["key"])
        assert (a["name"], a["owner"], a["epoch"], a["observed"]["state"]) == \
            (c["name"], c["owner"], c["epoch"], c["observed"]["state"])
        assert (p["id"], p["head"], p["name"], p["state"] or None) == (s, s, a["name"], a["observed"]["state"])
        seen[s] = (a["name"], a["owner"], a["observed"]["state"], p["kind"], p["machine"], p["take"])
    assert seen == {
        V: ("voice", "here", "idle", "attach-tmux", "here", None),
        W: ("notes", "bee", "idle", "blocked-window", "bee", None),
        U: ("", "phone:prod", None, "take-then-resume", "here", {"sid": U, "to": "here", "expect_epoch": 2}),
    }
