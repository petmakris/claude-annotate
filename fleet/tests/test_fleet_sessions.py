"""`fleet sessions`: every session of every machine, the plan that lands in one, and the page's Sessions API.

Three machines: `here` (the hub, a Mac-like screen), `bee` (reachable) and `cee` (in machines.json, never
answers). Each machine's tmux server and process tree are files in its FLEET_HOME read by a fake `tmux` and `ps`;
the env checkout is a fake one whose `_core.py` work rule calls a folder under $FAKE_WORK_DIR work, and whose
registry (`_session/list --json`) prints $FAKE_REGISTRY.
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

from fleet_testkit import fleet, world  # noqa: F401

fs = fleet.fs

FAKE_CORE = '''import os
def profile_paths():
    return [os.environ["FAKE_WORK_DIR"]]
def listed_accounts():
    return ["me", "other"]
def is_work_folder(folder, paths=None):
    return any(folder == p or folder.startswith(p + "/") for p in paths)
'''
FAKE_LIST = '''#!/bin/sh
cat "$FAKE_REGISTRY" 2>/dev/null || echo "[]"
'''
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
        self.env = os.path.join(b, "env")
        script(os.path.join(self.env, "libexec", "claude", "_session", "_core.py"), FAKE_CORE)
        script(os.path.join(self.env, "libexec", "claude", "_session", "list"), FAKE_LIST)
        self.work = "/home/u/work"  # outside /tmp, which the kind rules call a job folder
        self.registry = os.path.join(b, "registry.json")
        self.window_log = os.path.join(b, "windows.jsonl")
        for k, v in {"FLEET_ENV_DIR": self.env, "FAKE_WORK_DIR": self.work, "FAKE_REGISTRY": self.registry,
                     "FLEET_TMUX": script(os.path.join(b, "tools", "tmux"), FAKE_TMUX),
                     "FLEET_PS": script(os.path.join(b, "tools", "ps"), FAKE_PS),
                     "FAKE_WINDOW_LOG": self.window_log}.items():
            world.mp.setenv(k, v)
        fleet._WORK.update(key=None, fn=None)
        self.T = float(int(time.time()))

    def seed(self, host, s, cwd, ago, name=None, ai=None, prompt="", transcript="", ended=None):
        self.w.mp.setenv("FLEET_HOME", host.home)
        con = fleet.db()
        con.execute("INSERT INTO conversations(session_id, cwd, transcript_path, started_at, last_seen_at, ended_at,"
                    " end_reason, name_custom, name_ai, first_prompt, origin) VALUES (?,?,?,?,?,?,?,?,?,?,'hook')",
                    (s, cwd, transcript, self.T - 3600 - ago, self.T - ago, ended, "exit" if ended else None,
                     name, ai, prompt))
        con.close()
        self.w.here_env()

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

    def reg(self, records):
        with open(self.registry, "w") as f:
            json.dump(records, f)

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


def listing(t):
    """here: voice (live in tmux, a member), an unnamed chat of yesterday, an unnamed chat of 20 days ago, a job;
    bee: notes (live in a window), a work-rule chat; cee: one row in the cache of its last answer."""
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
    t.reg([{"sid": V, "owner": "here"}])
    cached = {"key": "cee:" + C, "id": C, "machine": "cee", "name": "gym notes", "named": True, "folder": "/home/u/c",
              "about": "x", "kind": "chat", "where": "tmux", "tmux": "gym-notes", "state": "idle", "pid": 300,
              "member": False, "held": [], "unanswered": [], "free": False, "started": t.T - 9000,
              "last_seen": t.T - 8000, "ended": None, "end_reason": "", "live_on": ["cee"], "copies": [],
              "stale": False, "as_of": t.T - 7200, "masked": False, "registry": None}
    fleet.remember_rows("cee", t.T - 7200, [cached])
    return v


def test_the_list_holds_every_machine_with_exact_rows(three):
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
                     "free": True, "started": t.T - 3660, "last_seen": t.T - 60, "ended": None, "end_reason": "",
                     "live_on": ["here"], "copies": [], "stale": False, "masked": False, "registry": "here"}
    notes = rows[W]
    assert (notes["machine"], notes["where"], notes["tmux"], notes["state"], notes["member"], notes["live_on"]) == \
        ("bee", "window", None, "idle", False, ["bee"])
    secret = rows[S]  # a work-rule row through another machine: no folder, no prompt, no name taken from it
    assert (secret["masked"], secret["folder"], secret["about"], secret["name"], secret["named"], secret["kind"],
            secret["last_seen"]) == (True, "", "", "", False, "chat", t.T - 300)
    assert (rows[U]["name"], rows[U]["named"], rows[U]["about"]) == ("", False, "Fix the feed")
    assert (rows[C]["stale"], rows[C]["as_of"]) == (True, t.T - 7200)
    assert env["hub"] == "here"
    assert env["machines"]["cee"] == {"reachable": False, "stale": True, "as_of": t.T - 7200,
                                      "reason": TIMEOUT_LINE % "cee", "fleet": None, "screen": "hyprland",
                                      "unreadable": None, "tmux_server": None}
    bee = dict(env["machines"]["bee"])
    assert bee.pop("as_of") >= t.T
    assert bee == {"reachable": True, "stale": False, "reason": "", "fleet": True, "screen": "none",
                   "unreadable": 0, "tmux_server": False}
    here = env["machines"]["here"]
    assert (here["screen"], here["tmux_server"], here["stale"]) == ("macos", True, False)
    assert set(env) == {"machines", "hub", "as_of", "rows"}
    assert [r["id"] for r in env["rows"]] == [V, W, S, C, U]  # newest last_seen first

    every = {r["id"]: r for r in t.env_json("--kind", "all")["rows"]}
    assert every[JOB]["kind"] == "job" and OLD in every
    assert {r["id"] for r in t.env_json("--named")["rows"]} == {V, W, S, C}  # named on its own machine, or live
    assert {r["id"] for r in t.env_json("--machine", "bee")["rows"]} == {W, S}


def test_the_own_machine_lists_its_work_rows_in_full(three):
    t = three
    listing(t)
    t.w.mp.setenv("FLEET_HOME", t.bee.home)
    t.w.mp.setenv("FLEET_SESSIONS_DIR", t.bee.sessions_dir)
    t.w.capsys.readouterr()
    assert fleet.main(["sessions", "--local", "--json"]) == 0
    rows = {r["id"]: r for r in json.loads(t.w.capsys.readouterr().out)["rows"]}
    assert (rows[S]["masked"], rows[S]["folder"], rows[S]["about"], rows[S]["name"]) == \
        (False, os.path.join(t.work, "a"), "the secret prompt", "Secret plan")


def test_a_work_account_transcript_is_masked_whatever_its_folder(three):
    t = three
    tr = os.path.join(os.path.expanduser("~"), ".claude-work", "projects", "x", S + ".jsonl")
    t.seed(t.bee, S, "/home/u/projects/plain", 300, name="standup", prompt="what did we ship", transcript=tr)
    row = {r["id"]: r for r in t.env_json()["rows"]}[S]
    assert (row["masked"], row["folder"], row["about"], row["name"]) == (True, "", "", "standup")


def test_the_last_answer_is_served_stale_with_this_runs_reason(three):
    t = three
    listing(t)
    first = t.env_json()
    with open(fleet.seen_path("bee")) as f:
        saved = json.load(f)
    assert set(saved) == {"as_of", "rows"}  # rows and when; nothing about reachability
    assert {r["id"] for r in saved["rows"]} == {W, S}
    with open(os.path.join(t.w.base, "hosts.json")) as f:
        hosts = json.load(f)
    del hosts["bee"]
    with open(os.path.join(t.w.base, "hosts.json"), "w") as f:
        json.dump(hosts, f)
    asks = len([x for x in t.w.ssh_log() if x[0] == "bee"])
    env = t.env_json()
    assert len([x for x in t.w.ssh_log() if x[0] == "bee"]) == asks + 1  # asked again: no memo of the failure
    m = env["machines"]["bee"]
    assert (m["reachable"], m["stale"], m["reason"], m["as_of"]) == \
        (False, True, TIMEOUT_LINE % "bee", first["machines"]["bee"]["as_of"])
    rows = {r["id"]: r for r in env["rows"]}
    assert (rows[W]["stale"], rows[W]["as_of"], rows[W]["masked"]) == (True, m["as_of"], False)
    assert rows[S]["masked"] and rows[S]["about"] == ""  # the cache holds only what bee sent: masked


def test_a_machine_whose_fleet_is_older_answers_but_has_no_sessions_verb(three, tmp_path):
    t = three
    old = script(os.path.join(str(tmp_path), "old_fleet.py"),
                 "import sys\nsys.stderr.write(\"fleet: error: argument cmd: invalid choice: 'sessions'\\n\")\nsys.exit(2)\n")
    conf_path = os.path.join(t.w.here.home, "machines.json")
    with open(conf_path) as f:
        conf = json.load(f)
    conf["bee"]["fleet"] = old
    with open(conf_path, "w") as f:
        json.dump(conf, f)
    m = t.env_json()["machines"]["bee"]
    assert (m["reachable"], m["fleet"], m["stale"], m["reason"]) == \
        (True, False, True, "fleet: error: argument cmd: invalid choice: 'sessions'")


def plans_world(t):
    w = t.w
    listing(t)
    t.seed(w.here, sid(20), str(w.base), 7200, name="lungo plan review", ended=t.T - 7200)
    t.seed(w.here, sid(21), str(w.base), 7300, name="voice", ended=t.T - 7300)
    helper = t.live(w.here, "helper", sid(22), str(w.base))
    t.seed(w.here, sid(22), str(w.base), 10, name="helper")
    assert w.member(helper, "helper")[0] == 0
    t.seed(w.here, sid(23), "/no/such/folder", 9000, name="gone away", ended=t.T - 9000)
    t.seed(w.here, sid(24), str(w.base), 9100, name="moved", ended=t.T - 9100)
    t.live(t.bee, "moved-copy", sid(24), "/home/u/b")
    t.seed(w.here, sid(25), str(w.base), 9200, name="phone talk")
    t.agents(t.bee, [{"id": "bg123456", "sessionId": sid(26), "name": "admin", "cwd": "/home/u/l",
                      "kind": "background", "state": "blocked", "startedAt": 1000}])
    t.reg([{"sid": V, "owner": "here"}, {"sid": sid(24), "owner": "here"}, {"sid": sid(25), "owner": "phone:prod"}])
    w.here_env()


def test_every_plan_kind(three):
    t = three
    plans_world(t)
    base = str(t.w.base)
    p = t.plan("here:" + sid(20))
    assert p == {"kind": "resume", "key": "here:" + sid(20), "id": sid(20), "machine": "here",
                 "name": "lungo plan review", "tmux": "lungo-plan-review", "folder": base, "pid": None, "state": "",
                 "member": False, "message": "", "force": False, "run_on_owner": False}
    p = t.plan("here:" + sid(21))  # "voice" is taken by another conversation's tmux session
    assert (p["kind"], p["tmux"]) == ("resume", "voice-" + sid(21)[:8])
    p = t.plan("here:" + V)
    assert (p["kind"], p["machine"], p["tmux"], p["folder"], p["member"]) == \
        ("attach-tmux", "here", "voice", "/home/u/projects/a", True)
    p = t.plan("bee:" + sid(26))
    assert (p["kind"], p["machine"], p["id"], p["state"]) == ("attach-bg", "bee", sid(26), "blocked")
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
    p = t.plan("here:" + sid(24))  # the registry says here; it runs in a window on bee
    assert (p["kind"], p["machine"], p["message"]) == (
        "refuse-live-elsewhere", "bee", "moved is live on bee in a window, not in tmux: it is not resumed on here")
    p = t.plan("here:" + sid(25))
    assert (p["kind"], p["message"]) == ("refuse-registry", "phone talk is on the phone now: take it back with @claude -r first")
    p = t.plan("bee:" + S)  # a work-rule row of bee, planned on here: bee works it out itself, and no folder leaks
    assert (p["kind"], p["machine"], p["folder"], p["tmux"], p["run_on_owner"], p["message"]) == \
        ("refuse-no-folder", "bee", "", "", True, "bee: the folder of this session is gone; it is not created again")
    assert {k for k in fs.PLAN_KINDS} == {"attach-tmux", "attach-bg", "resume", "wrap-up-then-resume", "blocked-window",
                                          "refuse-offline", "refuse-no-folder", "refuse-live-elsewhere", "refuse-registry"}


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


def test_the_registry_owner_wins_over_the_newest_copy():
    a = {"id": V, "machine": "a", "live_on": [], "stale": False, "last_seen": 100, "started": 0}
    b = dict(a, machine="b", last_seen=200)
    assert fs.merge({"a": [a], "b": [b]})[0]["machine"] == "b"
    got = fs.merge({"a": [a], "b": [b]}, {V: {"sid": V, "owner": "a"}})[0]
    assert (got["machine"], got["copies"], got["registry"]) == ("a", ["b"], "a")
    phone = fs.merge({"a": [a], "b": [b]}, {V: {"sid": V, "owner": "phone:prod"}}, hub_main="a")[0]
    assert (phone["machine"], phone["registry"]) == ("a", "phone:prod")


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


def test_a_machine_off_the_hub_asks_the_hub_and_keeps_its_own_rows_in_full(world):
    t = Three(world, here_conf={"hub": "bee"})
    with open(os.path.join(t.bee.home, "machines.json")) as f:
        conf = json.load(f)
    conf["hub"] = "bee"
    with open(os.path.join(t.bee.home, "machines.json"), "w") as f:
        json.dump(conf, f)
    t.seed(world.here, S, os.path.join(t.work, "a"), 300, name="standup", prompt="the secret prompt")
    env = t.env_json()
    assert any(h == "bee" and " sessions --json" in cmd for h, cmd in world.ssh_log())
    row = {r["id"]: r for r in env["rows"]}[S]
    assert (row["machine"], row["masked"], row["about"]) == ("here", False, "the secret prompt")
    with open(os.path.join(world.base, "hosts.json")) as f:
        hosts = json.load(f)
    del hosts["bee"]
    with open(os.path.join(world.base, "hosts.json"), "w") as f:
        json.dump(hosts, f)
    env = t.env_json()
    assert env["note"] == "the hub bee did not answer (%s); this machine asked the others itself" % (TIMEOUT_LINE % "bee")
    assert S in {r["id"] for r in env["rows"]}
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
    line = "%s pick --open here:%s" % (os.path.join(t.env, "bin", "@claude"), V)
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
    line = "%s pick --open here:%s" % (os.path.join(t.env, "bin", "@claude"), V)
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
    assert t.env_json("--machine", "here")["machines"]["here"]["tmux_server"] is True


def test_claude_is_found_in_the_installers_folder_without_a_login_path(monkeypatch, tmp_path):
    home = str(tmp_path)
    b = script(os.path.join(home, ".local", "bin", "claude"), "#!/bin/sh\n")
    monkeypatch.delenv("FLEET_CLAUDE_BIN", raising=False)
    monkeypatch.setenv("HOME", home)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert fleet.claude_bin() == b
    monkeypatch.setenv("FLEET_CLAUDE_BIN", "/x/claude")
    assert fleet.claude_bin() == "/x/claude"


def test_history_ls_into_a_closed_pipe_ends_quietly(tmp_path):
    home = str(tmp_path)
    env = dict(os.environ, FLEET_HOME=home, FLEET_NO_UPDATE="1")
    env.pop("FLEET_CLAUDE_BIN", None)
    old = os.environ.get("FLEET_HOME")
    os.environ["FLEET_HOME"] = home
    try:
        con = fleet.db()
        con.executemany("INSERT INTO conversations(session_id, cwd, first_prompt, last_seen_at) VALUES (?,?,?,?)",
                        [(sid(1000 + i), "/home/u/p", "prompt %d " % i + "x" * 200, i) for i in range(3000)])
        con.close()
    finally:
        if old is None:
            os.environ.pop("FLEET_HOME")
        else:
            os.environ["FLEET_HOME"] = old
    p = subprocess.Popen([sys.executable, fleet.__file__, "history", "ls", "--json"], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env)
    p.stdout.read(10)
    p.stdout.close()
    err = p.stderr.read().decode()
    assert (p.wait(30), err) == (0, "")


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
    yield call
    srv.shutdown()
    srv.server_close()


def test_the_sessions_api_lists_and_is_guarded(three, page):
    listing(three)
    code, data = page("GET", "/api/sessions")
    assert code == 200 and set(data) == {"machines", "hub", "as_of", "rows"}
    assert {r["id"] for r in data["rows"]} >= {V, W, S, C}
    assert not any(k.startswith("_") for r in data["rows"] for k in r)
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


def test_the_page_opens_a_window_through_the_internal_verb_only(three, page):
    listing(three)
    script(os.path.join(three.w.base, "bin", "open"), LOGGER % sys.executable)
    three.w.mp.setenv("SHELL", "/bin/zsh")
    code, data = page("POST", "/api/sessions/open", {"key": "bee:" + W, "target": "here", "command": "touch /tmp/x"})
    assert code == 200, data
    line = "%s pick --open bee:%s" % (os.path.join(three.env, "bin", "@claude"), W)
    assert window_log(three) == [["open", "-na", "Ghostty", "--args", "-e", "/bin/zsh", "-lic", line]]
    assert data == {"opened": "here", "screen": "macos", "command": line, "copy": "@claude pick --open bee:" + W}


def test_the_page_renames_in_the_owners_history(three, page):
    listing(three)
    assert page("POST", "/api/sessions/rename", {"key": "bee:" + W, "name": "field notes"})[0] == 200
    con = three.bee.db()
    assert con.execute("SELECT name_custom FROM conversations WHERE session_id=?", (W,)).fetchone()[0] == "field notes"
    code, data = page("GET", "/api/sessions?fresh=1")
    assert {r["id"]: r["name"] for r in data["rows"]}[W] == "field notes"


def test_the_page_stops_a_member_with_the_wrap_up_tell(three, page):
    listing(three)
    code, data = page("POST", "/api/sessions/stop", {"key": "here:" + V})
    assert code == 200, data
    assert data["action"] == "interactive" and data["thread"]
    con = three.w.here.db()
    assert con.execute("SELECT body FROM messages WHERE thread=?", (data["thread"],)).fetchone()[0] == fleet.WRAP_UP_TELL
