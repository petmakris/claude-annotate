"""The importer (fleet_index_import.py): backups before the first write, a dry run that writes nothing, the higher
epoch winning and logged, masking on the machine, and a second import changing nothing.

The store, the journal and the work rule are the hub job's modules (contract section 15). Until they exist, this
file supplies stand-ins that follow the contract's signatures, written as files on a path after the fleet folder,
so the real modules win once they are there. The other two test files of this job import `IndexWorld` from here.
"""
import glob
import json
import os
import sqlite3
import sys
import textwrap
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FLEET = os.path.dirname(HERE)
sys.path.insert(0, FLEET)
sys.path.insert(0, HERE)

import fleet_testkit  # noqa: E402

# ---------------------------------------------------------------- stand-ins for the hub job's modules

STANDIN_STORE = '''
"""Stand-in for fleet_index_store (contract section 15), for the importer's tests only."""
import json, os, shutil, sqlite3, time

COLS = ("sid", "conversation", "name", "name_source", "kind", "env", "machine", "cwd", "account", "owner",
        "owner_since", "epoch", "continues", "superseded_by", "first_prompt", "last_prompt", "last_answer", "topic",
        "rc_name", "started", "updated", "ended", "end_reason", "description", "work")
FILLABLE = ("name", "cwd", "account", "first_prompt", "last_prompt", "last_answer", "topic", "description")
_on_change, _before_read = [], []

def hub_db_path(fleet_home):
    return os.path.join(fleet_home, "index", "hub.db")

def connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS sessions (%s)" % ", ".join(
        c + (" PRIMARY KEY" if c == "sid" else "") for c in COLS))
    con.execute("CREATE TABLE IF NOT EXISTS journal_high (machine PRIMARY KEY, seq)")
    return con

def on_change(fn):
    _on_change.append(fn)

def before_read(fn):
    _before_read.append(fn)

def get_row(con, sid):
    r = con.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["topic"] = json.loads(d["topic"]) if d["topic"] else None
    d["work"] = bool(d["work"])
    return d

def _put(con, row):
    vals = [json.dumps(row.get(c)) if c == "topic" and row.get(c) is not None else row.get(c) for c in COLS]
    con.execute("INSERT OR REPLACE INTO sessions VALUES (%s)" % ",".join("?" * len(COLS)), vals)

def _changed(con, sids):
    for fn in list(_on_change):
        fn(con, sids)

def list_rows(con, **kw):
    for fn in list(_before_read):
        fn(con)
    return [get_row(con, r[0]) for r in con.execute("SELECT sid FROM sessions ORDER BY updated DESC")]

def import_row(con, row, *, origin):
    ex = get_row(con, row["sid"])
    if ex is None:
        _put(con, row)
        return "new"
    if row["epoch"] > ex["epoch"]:
        new = dict(row)
        for k in ("conversation", "continues", "superseded_by"):
            new[k] = ex[k]
        _put(con, new)
        return "updated"
    if row["epoch"] < ex["epoch"] or row["owner"] != ex["owner"]:
        return "conflict-kept"
    new = dict(ex)
    for f in FILLABLE:
        if ex.get(f) in (None, "") and row.get(f) not in (None, ""):
            new[f] = row[f]
            if f == "name":
                new["name_source"] = row["name_source"]
    if new == ex:
        return "same"
    _put(con, new)
    return "updated"

def apply_batch(con, batch, *, hub, machines, now=None):
    now = time.time() if now is None else now
    m = batch["machine"]
    r = con.execute("SELECT seq FROM journal_high WHERE machine=?", (m,)).fetchone()
    high = r[0] if r else 0
    results, changed, rows = [], [], {}
    for e in sorted(batch["entries"], key=lambda e: e["seq"]):
        if e["seq"] <= high:
            results.append({"seq": e["seq"], "outcome": "duplicate"})
            continue
        high = e["seq"]
        row = get_row(con, e["sid"])
        if row is None:
            outcome = "invalid"
        elif row["owner"] != e["as"]:
            outcome = "not-owner"
        elif row["epoch"] != e["epoch_seen"]:
            outcome = "stale-epoch"
        else:
            for k, v in e["fields"].items():
                if k != "observed":
                    row[k] = v
            row["updated"] = now
            if e["event"] in ("start", "prompt", "stop"):
                row["ended"], row["end_reason"] = None, None
            _put(con, row)
            changed.append(e["sid"])
            outcome = "applied"
        results.append({"seq": e["seq"], "outcome": outcome})
        row = get_row(con, e["sid"])
        if row:
            rows[e["sid"]] = {"owner": row["owner"], "epoch": row["epoch"], "conversation": row["conversation"],
                              "head": row["sid"], "work": row["work"]}
    con.execute("INSERT OR REPLACE INTO journal_high VALUES (?, ?)", (m, high))
    if changed:
        _changed(con, changed)
    return {"high_seq": high, "results": results, "rows": rows}

def rename(con, sid, name, *, now=None):
    row = get_row(con, sid)
    row["name"], row["name_source"], row["updated"] = name, "manual" if name else "", time.time()
    _put(con, row)
    _changed(con, [sid])
    return row

def take(con, sid, to, expect_epoch, by, *, hub, machines, cwd=None, release=None, now=None):
    row = get_row(con, sid)
    assert row["epoch"] == expect_epoch
    prev = row["owner"]
    row["owner"], row["epoch"], row["owner_since"] = to, row["epoch"] + 1, time.time() if now is None else now
    row["machine"] = hub if to.startswith("phone:") else to
    _put(con, row)
    _changed(con, [sid])
    return {"ok": True, "sid": sid, "owner": to, "epoch": row["epoch"], "previous_owner": prev}

def backup(con, *, label, keep=20, directory=None):
    d = directory or os.environ.get("FLEET_BACKUP_DIR") or os.path.expanduser("~/.local/state/fleet/index-backups")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, "hub-%s-%s-e0.db" % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), label))
    out = sqlite3.connect(dest)
    con.backup(out)
    out.close()
    return dest
'''

STANDIN_JOURNAL = '''
"""Stand-in for fleet_index_journal (contract section 15), for the importer's tests only."""
import json, os, time

class HubDown(Exception):
    pass

def index_dir(fleet_home):
    return os.path.join(fleet_home, "index")

def _state(h):
    try:
        return json.load(open(os.path.join(index_dir(h), "journal.state.json")))
    except (OSError, ValueError):
        return {"next_seq": 1, "acked_seq": 0}

def _save(h, st):
    json.dump(st, open(os.path.join(index_dir(h), "journal.state.json"), "w"))

def append(fleet_home, machine, sid, event, fields, *, as_owner=None, epoch_seen=None, at=None):
    os.makedirs(index_dir(fleet_home), exist_ok=True)
    st = _state(fleet_home)
    e = {"v": 1, "machine": machine, "seq": st["next_seq"], "as": as_owner or machine, "sid": sid,
         "epoch_seen": epoch_seen if epoch_seen is not None else 0, "event": event,
         "at": time.time() if at is None else at, "fields": fields}
    with open(os.path.join(index_dir(fleet_home), "journal.jsonl"), "a") as f:
        f.write(json.dumps(e) + "\\n")
    st["next_seq"] += 1
    _save(fleet_home, st)
    return e

def pending(fleet_home):
    st = _state(fleet_home)
    try:
        lines = open(os.path.join(index_dir(fleet_home), "journal.jsonl")).read().splitlines()
    except OSError:
        return []
    return [e for e in map(json.loads, lines) if e["seq"] > st["acked_seq"]]

def flush(fleet_home, machine, send):
    entries = pending(fleet_home)
    if not entries:
        return None
    reply = send({"machine": machine, "entries": entries})
    st = _state(fleet_home)
    st["acked_seq"] = reply["high_seq"]
    _save(fleet_home, st)
    return reply
'''

STANDIN_WORK = '''
"""Stand-in for fleet_work (contract sections 7 and 15), for the importer's tests only."""
import json, os

FORBIDDEN = ("first_prompt", "last_prompt", "last_answer", "cwd", "account", "description", "rc_name")
PROMPT_NAME_SOURCES = ("ai", "registry", "prompt")

class Rules:
    def __init__(self, accounts, profile_paths, own_profiles, home, fail_closed=False):
        self.accounts, self.profile_paths, self.own_profiles = accounts, profile_paths, own_profiles
        self.home, self.fail_closed = home, fail_closed

def load_rules(fleet_home=None, home=None):
    home = home or os.path.expanduser("~")
    fleet_home = fleet_home or os.environ.get("FLEET_HOME")
    try:
        d = json.load(open(os.path.join(fleet_home, "work.json")))
        return Rules(d.get("accounts") or [], [os.path.normpath(p) for p in d.get("profile_paths") or []],
                     d.get("own_profiles"), home)
    except (OSError, ValueError, TypeError):
        return Rules([], [], None, home, fail_closed=os.path.isdir(os.path.join(home, "projects", "env")))

def account_of(config_dir, rules):
    config = os.path.normpath(config_dir)
    if config == os.path.join(rules.home, ".claude"):
        return rules.accounts[0] if rules.accounts else None
    base = os.path.basename(config)
    if base.startswith(".claude-") and base[8:] in rules.accounts[1:]:
        return base[8:]
    return None

def is_work(folder, transcript, rules):
    if rules.fail_closed:
        return True
    if transcript:
        parts = os.path.normpath(transcript).split(os.sep)
        if "projects" in parts:
            config = os.sep.join(parts[: parts.index("projects")])
            if account_of(config, rules) is None:
                return True
    if folder:
        f = os.path.normpath(folder)
        return any(f == p or f.startswith(p + os.sep) for p in rules.profile_paths)
    return False

def mask_fields(fields):
    out = {k: v for k, v in fields.items() if k not in FORBIDDEN}
    if out.get("name_source") in PROMPT_NAME_SOURCES:
        out.pop("name", None)
        out.pop("name_source", None)
    if isinstance(out.get("observed"), dict):
        out["observed"] = {k: v for k, v in out["observed"].items() if k != "tmux"}
    return out

def work_refusal(fields):
    for k in FORBIDDEN:
        if k in fields:
            return "a work entry carries " + k
    return None
'''

STANDINS = {"fleet_index_store": STANDIN_STORE, "fleet_index_journal": STANDIN_JOURNAL, "fleet_work": STANDIN_WORK}


def standin_dir(base):
    """Writes the stand-ins the fleet folder lacks into `base`; returns it (put after the fleet folder on paths)."""
    os.makedirs(base, exist_ok=True)
    for mod, src in STANDINS.items():
        if not os.path.isfile(os.path.join(FLEET, mod + ".py")):
            with open(os.path.join(base, mod + ".py"), "w") as f:
                f.write(textwrap.dedent(src))
    return base


# ---------------------------------------------------------------- a world of machines

class IndexWorld:
    """Machines with their own FLEET_HOME and registry folder, joined by the fleet's fake ssh. The test process is
    the hub. `machine.registry` is its registry folder, `machine.home` its FLEET_HOME."""

    class Machine:
        def __init__(self, base, name):
            self.name = name
            self.base = os.path.join(base, "m-" + name)
            self.home = os.path.join(self.base, "fleet")
            self.registry = os.path.join(self.base, "claude-sessions")
            self.work = os.path.join(self.base, "work")
            for d in (self.home, self.registry, self.work, os.path.join(self.base, "sessions")):
                os.makedirs(d, exist_ok=True)
            with open(os.path.join(self.home, "work.json"), "w") as f:
                json.dump({"accounts": ["me", "second"], "profile_paths": [self.work],
                           "own_profiles": os.path.join(self.base, "profiles")}, f)

        def put_record(self, rec):
            """A registry file as env writes it."""
            with open(os.path.join(self.registry, rec["sid"] + ".json"), "w") as f:
                json.dump(rec, f, ensure_ascii=False)
                f.write("\n")

        def history(self, *rows):
            """Rows of this machine's `conversations` (fleet_history's table)."""
            import fleet_history
            con = sqlite3.connect(os.path.join(self.home, "fleet.db"))
            con.executescript(fleet_history.SCHEMA)
            for r in rows:
                cols = ", ".join(r)
                con.execute("INSERT OR REPLACE INTO conversations (%s) VALUES (%s)" % (cols, ",".join("?" * len(r))),
                            list(r.values()))
            con.commit()
            con.close()

    def __init__(self, base, monkeypatch, names=("main", "mac", "lat"), hub="main", unreachable=()):
        self.base, self.mp = base, monkeypatch
        self.machines = {n: self.Machine(base, n) for n in names}
        self.hub = self.machines[hub]
        sdir = standin_dir(os.path.join(base, "standins"))
        if sdir not in sys.path:
            sys.path.append(sdir)
        monkeypatch.setenv("PYTHONPATH", os.pathsep.join([FLEET, sdir]))
        monkeypatch.setenv("FLEET_HOME", self.hub.home)
        monkeypatch.setenv("CLAUDE_SESSIONS_DIR", self.hub.registry)
        monkeypatch.setenv("FLEET_BACKUP_DIR", os.path.join(base, "index-backups"))
        monkeypatch.setenv("FLEET_IMPORT_BACKUP_DIR", os.path.join(base, "import-backups"))
        monkeypatch.setenv("FLEET_INDEX_FOREGROUND", "1")
        monkeypatch.setenv("TZ", "UTC")
        time.tzset()
        bindir = os.path.join(base, "bin")
        os.makedirs(bindir, exist_ok=True)
        with open(os.path.join(bindir, "ssh"), "w") as f:
            f.write(fleet_testkit.FAKE_SSH % sys.executable)
        os.chmod(os.path.join(bindir, "ssh"), 0o755)
        monkeypatch.setenv("PATH", bindir + os.pathsep + os.environ["PATH"])
        monkeypatch.setenv("FAKE_SSH_BASE", base)
        with open(os.path.join(base, "hosts.json"), "w") as f:
            json.dump({m.name: {"home": m.home, "sessions": os.path.join(m.base, "sessions")}
                       for m in self.machines.values() if m.name not in unreachable}, f)
        fleet_py = os.path.join(FLEET, "fleet.py")
        for m in self.machines.values():
            conf = {"self": m.name, "hub": hub}
            for o in self.machines.values():
                if o is not m:
                    conf[o.name] = {"ssh": o.name, "fleet": fleet_py, "python": sys.executable,
                                    "env": {"CLAUDE_SESSIONS_DIR": o.registry}}
            with open(os.path.join(m.home, "machines.json"), "w") as f:
                json.dump(conf, f)

    def __getitem__(self, name):
        return self.machines[name]

    def con(self):
        import fleet_index_store
        return fleet_index_store.connect(fleet_index_store.hub_db_path(self.hub.home))

    def rows(self):
        """Every row of the index, by sid."""
        import fleet_index_store
        path = fleet_index_store.hub_db_path(self.hub.home)
        if not os.path.isfile(path):
            return {}
        con = self.con()
        try:
            sids = [r[0] for r in con.execute("SELECT sid FROM sessions")]
            return {s: fleet_index_store.get_row(con, s) for s in sids}
        finally:
            con.close()

    def snapshot(self):
        """Every file under the world but the stand-ins and the fake ssh's log: path -> (bytes, mtime_ns)."""
        out = {}
        for p in glob.glob(os.path.join(self.base, "**"), recursive=True):
            if os.path.isfile(p) and "/standins/" not in p and not p.endswith("ssh.log") and "__pycache__" not in p:
                with open(p, "rb") as f:
                    out[os.path.relpath(p, self.base)] = (f.read(), os.stat(p).st_mtime_ns)
        return out


@pytest.fixture
def iw(tmp_path, monkeypatch):
    w = IndexWorld(str(tmp_path), monkeypatch)
    yield w
    monkeypatch.undo()
    time.tzset()


def record(sid, owner="main", epoch=1, name="fix the build", machine=None, updated="2026-11-20T10:00:00+00:00",
           **kw):
    rec = {"version": 1, "sid": sid, "name": name, "machine": machine or (owner if ":" not in owner else "main"),
           "account": "me", "cwd": "/home/me/projects/app", "last_prompt": "run the tests",
           "last_answer": "All green.", "updated": updated, "live": False, "owner": owner,
           "owner_since": "2026-11-20T09:00:00+00:00", "epoch": epoch, "kind": "chat", "topic": None}
    rec.update(kw)
    return rec


SID_A = "aaaaaaaa-1111-4111-8111-000000000001"
SID_B = "bbbbbbbb-2222-4222-8222-000000000002"
SID_C = "cccccccc-3333-4333-8333-000000000003"
SID_W = "dddddddd-4444-4444-8444-000000000004"


def run(argv):
    import fleet_index_import
    return fleet_index_import.main(argv)


def seed_world(iw):
    iw["main"].put_record(record(SID_A, owner="main", epoch=2))
    iw["mac"].put_record(record(SID_A, owner="mac", epoch=3, machine="mac", updated="2026-11-21T10:00:00+00:00"))
    iw["main"].put_record(record(SID_B, owner="phone:prod", epoch=2, topic={"host": "prod", "id": "kitchen"}))
    iw["lat"].history({"session_id": SID_C, "cwd": "/home/me/projects/notes", "started_at": 1795000000.0,
                       "last_seen_at": 1795000500.0, "name_custom": "notes cleanup", "first_prompt": "tidy notes"})
    iw["mac"].history({"session_id": SID_W, "cwd": os.path.join(iw["mac"].work, "repo"),
                       "transcript_path": "/home/me/.claude/projects/x/%s.jsonl" % SID_W,
                       "started_at": 1795000000.0, "last_seen_at": 1795000600.0,
                       "name_ai": "secret client migration", "first_prompt": "SECRET-PROMPT-BYTES",
                       "description": "SECRET-DESCRIPTION"})


# ---------------------------------------------------------------- the guard tests

def test_importing_twice_changes_nothing(iw, capsys, monkeypatch):
    seed_world(iw)
    assert run(["import", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["totals"]["new"] == 4
    rows = iw.rows()
    files = {p: open(p, "rb").read() for p in glob.glob(os.path.join(iw.hub.registry, "*.json"))}
    state = open(os.path.join(iw.hub.home, "index", "shim-state.json")).read()

    import fleet_index_store
    calls = []
    real = fleet_index_store.import_row
    monkeypatch.setattr(fleet_index_store, "import_row", lambda con, row, **kw: calls.append(row) or real(con, row, **kw))
    assert run(["import", "--json"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert calls == []  # the index is not written at all
    assert second["totals"] == {"new": 0, "same": 4, "updated": 0, "conflict-kept": 0, "rows": 4,
                                "conflicts": 1, "invalid": 0}
    assert iw.rows() == rows
    assert {p: open(p, "rb").read() for p in glob.glob(os.path.join(iw.hub.registry, "*.json"))} == files
    assert open(os.path.join(iw.hub.home, "index", "shim-state.json")).read() == state


def test_a_higher_epoch_wins_and_is_logged(iw, capsys):
    seed_world(iw)
    assert run(["import", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    row = iw.rows()[SID_A]
    assert (row["owner"], row["epoch"], row["machine"]) == ("mac", 3, "mac")
    assert rep["conflicts"] == [{"sid": SID_A, "where": "copies",
                                 "kept": {"machine": "mac", "owner": "mac", "epoch": 3},
                                 "lost": {"machine": "main", "owner": "main", "epoch": 2},
                                 "why": "the registry copy with the higher epoch wins"}]
    assert rep["machines"]["main"]["conflicts"] == 1
    log = open(os.path.join(iw.hub.home, "hooks.log")).read()
    assert ('import: %s: registry copies disagree: kept {"machine": "mac", "owner": "mac", "epoch": 3}, '
            'lost {"machine": "main", "owner": "main", "epoch": 2} (the registry copy with the higher epoch wins)'
            % SID_A) in log

    # Against the index: a newer import replaces a row at a lower epoch, an older one leaves a higher epoch alone.
    import fleet_index_store
    if not hasattr(fleet_index_store, "_put"):
        pytest.skip("the real store has no test writer; the copies case above ran")
    con = iw.con()
    fleet_index_store._put(con, dict(iw.rows()[SID_B], epoch=1, owner="main", machine="main"))
    fleet_index_store._put(con, dict(iw.rows()[SID_C], epoch=5))
    con.close()
    assert run(["import", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    rows = iw.rows()
    assert (rows[SID_B]["owner"], rows[SID_B]["epoch"]) == ("phone:prod", 2)
    assert rows[SID_C]["epoch"] == 5
    index = sorted((c["sid"], c["outcome"], c["why"]) for c in rep["conflicts"] if c["where"] == "index")
    assert index == sorted([(SID_B, "updated", "the import's epoch 2 is higher than the index's 1"),
                            (SID_C, "conflict-kept", "the index's epoch 5 is higher than the import's 1")])
    log = open(os.path.join(iw.hub.home, "hooks.log")).read()
    assert "import: %s from main: updated (the import's epoch 2 is higher than the index's 1)" % SID_B in log
    assert "import: %s from lat: conflict-kept (the index's epoch 5 is higher than the import's 1)" % SID_C in log


def test_the_dry_run_writes_nothing(iw, capsys):
    seed_world(iw)
    before = iw.snapshot()
    assert run(["import", "--dry-run", "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["dry_run"] is True and rep["backups"] is None
    assert rep["totals"]["new"] == 4 and rep["totals"]["conflicts"] == 1
    assert {m: (e["rows"], e["new"], e["conflicts"]) for m, e in rep["machines"].items()} == \
        {"lat": (1, 1, 0), "mac": (2, 2, 0), "main": (1, 1, 1)}
    assert iw.snapshot() == before
    assert not os.path.exists(os.path.join(iw.base, "import-backups"))
    assert not os.path.exists(os.path.join(iw.hub.home, "index"))


def test_the_backups_exist_before_the_first_write(iw, capsys, monkeypatch):
    import fleet_index_import
    import fleet_index_store
    seed_world(iw)
    bdir = os.path.join(iw.base, "bk")
    seen = []

    def expect_backups(what):
        tar = os.path.join(bdir, "claude-sessions-main.tar.gz")
        dbs = [os.path.join(bdir, "fleet-%s.db" % m) for m in ("lat", "mac")]
        seen.append((what, os.path.isfile(tar), all(os.path.isfile(p) for p in dbs)))

    real_connect = fleet_index_store.connect
    real_seed = fleet_index_import.shim.seed

    def connect(path):
        expect_backups("connect")
        return real_connect(path)

    def seed(records, home=None):
        expect_backups("seed")
        return real_seed(records, home)

    monkeypatch.setattr(fleet_index_store, "connect", connect)
    monkeypatch.setattr(fleet_index_import.shim, "seed", seed)
    assert run(["import", "--backup-dir", bdir]) == 0
    out = capsys.readouterr().out
    assert seen == [("connect", True, True), ("seed", True, True)]
    assert "backup: registry tarball %s/claude-sessions-main.tar.gz\n" % bdir in out
    assert "backup: fleet.db of lat %s/fleet-lat.db\n" % bdir in out
    assert "backup: fleet.db of mac %s/fleet-mac.db\n" % bdir in out
    assert "backup: fleet.db of main (none on that machine)\n" in out
    import tarfile
    with tarfile.open(os.path.join(bdir, "claude-sessions-main.tar.gz")) as tar:
        assert sorted(tar.getnames()) == ["claude-sessions", "claude-sessions/%s.json" % SID_A,
                                          "claude-sessions/%s.json" % SID_B]
    con = sqlite3.connect(os.path.join(bdir, "fleet-lat.db"))
    assert con.execute("SELECT session_id FROM conversations").fetchall() == [(SID_C,)]
    con.close()


# ---------------------------------------------------------------- more of the importer

def test_a_work_session_is_masked_on_its_own_machine(iw, capsys):
    seed_world(iw)
    assert run(["import"]) == 0
    capsys.readouterr()
    row = iw.rows()[SID_W]
    assert row["work"] is True
    assert (row["cwd"], row["first_prompt"], row["description"], row["account"], row["name"]) == \
        (None, None, None, None, "")
    secrets = (b"SECRET-PROMPT-BYTES", b"SECRET-DESCRIPTION", b"secret client migration",
               iw["mac"].work.encode())
    import fleet_index_store
    blob = open(fleet_index_store.hub_db_path(iw.hub.home), "rb").read()
    for s in secrets:
        assert s not in blob
    # The dump that leaves the machine already holds none of it.
    import subprocess
    out = subprocess.run(["ssh", "mac", "env CLAUDE_SESSIONS_DIR=%s %s %s/fleet_index_import.py _import-dump"
                          % (iw["mac"].registry, sys.executable, FLEET)], capture_output=True).stdout
    assert out and not any(s in out for s in secrets)


def test_rows_are_built_from_the_registry_and_the_history(iw, capsys):
    seed_world(iw)
    assert run(["import"]) == 0
    capsys.readouterr()
    rows = iw.rows()
    b = rows[SID_B]
    assert (b["owner"], b["machine"], b["env"], b["topic"], b["name_source"], b["kind"]) == \
        ("phone:prod", "main", "prod", {"host": "prod", "id": "kitchen"}, "registry", "chat")
    c = rows[SID_C]
    assert (c["owner"], c["epoch"], c["machine"], c["name"], c["name_source"], c["first_prompt"], c["started"],
            c["updated"], c["conversation"]) == \
        ("lat", 1, "lat", "notes cleanup", "custom", "tidy notes", 1795000000.0, 1795000500.0, SID_C)


def test_an_unreachable_machine_is_reported_and_the_others_import(tmp_path, monkeypatch, capsys):
    w = IndexWorld(str(tmp_path), monkeypatch, unreachable=("lat",))
    try:
        seed_world(w)
        assert run(["import", "--json"]) == 0
        rep = json.loads(capsys.readouterr().out)
        assert rep["machines"]["lat"]["reachable"] is False
        assert "timed out" in rep["machines"]["lat"]["reason"]
        assert sorted(w.rows()) == sorted([SID_A, SID_B, SID_W])
    finally:
        monkeypatch.undo()
        time.tzset()


def test_the_import_runs_only_on_the_hub(iw, capsys, monkeypatch):
    monkeypatch.setenv("FLEET_HOME", iw["mac"].home)
    assert run(["import"]) == 1
    assert capsys.readouterr().err == "fleet session import: the import runs on the hub (main); this is mac\n"


def test_plan_and_apply_agree_on_every_row(iw):
    import fleet_index_import
    seed_world(iw)
    dumps, errors = fleet_index_import.fetch_dumps(["main", "mac", "lat"])
    con = iw.con()
    try:
        planned = fleet_index_import.plan(con, dumps, errors)
        applied = fleet_index_import.apply(con, dumps, errors)
    finally:
        con.close()
    assert planned["totals"] == applied["totals"]
    assert planned["machines"] == applied["machines"]


def _hub_work_row(iw, sid):
    """The row the hub holds when the session's machine journaled it while its rule failed closed."""
    import fleet_index_store
    con = iw.con()
    try:
        fleet_index_store.import_row(con, dict(record(sid, owner="main", epoch=1), machine="main", work=True,
                                               name="", conversation=sid), origin="main")
    finally:
        con.close()


def test_the_rows_own_machine_clears_a_work_flag_its_failed_closed_rule_set(iw, capsys):
    _hub_work_row(iw, SID_A)
    assert iw.rows()[SID_A]["work"] is True
    iw["main"].put_record(record(SID_A, owner="main", epoch=1))
    assert run(["import", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["machines"]["main"]["updated"] == 1
    row = iw.rows()[SID_A]
    assert (row["work"], row["name"], row["cwd"], row["last_prompt"], row["account"]) == \
        (False, "fix the build", "/home/me/projects/app", "run the tests", "me")


def test_an_import_from_another_machine_never_fills_a_work_rows_words(iw, capsys):
    _hub_work_row(iw, SID_A)
    iw["mac"].put_record(record(SID_A, owner="main", epoch=1, machine="main"))
    assert run(["import", "--json"]) == 0
    capsys.readouterr()
    row = iw.rows()[SID_A]
    assert (row["work"], row["name"], row["cwd"], row["last_prompt"], row["account"]) == (True, "", None, None, None)
    import fleet_index_store
    blob = open(fleet_index_store.hub_db_path(iw.hub.home), "rb").read()
    assert b"run the tests" not in blob and b"/home/me/projects/app" not in blob
