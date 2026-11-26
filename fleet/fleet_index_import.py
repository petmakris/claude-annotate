"""The importer: every registry file and every machine's `conversations` into the session index, once (phase 1).

Contract: fleet/docs/session-index.md (rows section 2, modules section 15) and the committee's rulings, D.

    fleet session import [--dry-run] [--machine M]... [--backup-dir D] [--json]

It runs on the hub. For each machine of machines.json (or each `--machine`) it reads that machine's dump: on the hub
in process, elsewhere over ssh as `<python> <fleet folder>/fleet_index_import.py _import-dump`. A dump holds the
machine's registry files and its `conversations` rows; a work session's dump row is masked on its own machine, so
no prompt, folder, account or prompt-derived name leaves it.

The rows of every machine are merged per sid: the registry copy with the highest epoch wins (on a tie, the hub's
copy, then the newest), and each machine's history fills what the registry lacks. A row then meets the index:

- no row there: `new`;
- the import's epoch is higher: the import's row wins, `updated`, and the conflict is logged;
- the index's epoch is higher, or the same epoch with another owner: the index's row stays, `conflict-kept`, logged;
- the same epoch and owner: only empty fields are filled, `updated`, else `same`.

So a second import changes nothing. `--dry-run` prints the same report and writes nothing. Before its first write
the real import makes a tarball of the hub's registry folder and a copy of every imported machine's `fleet.db`
(SQLite's backup call), and prints their paths; the store backs up `hub.db` too. Nothing is ever deleted. Conflicts
are logged to `$FLEET_HOME/hooks.log` on the hub.

Stdlib only, Python 3.9+. The store and the work rule come from the contract's modules (`fleet_index_store`,
`fleet_work`), imported when first needed.
"""
import argparse
import datetime
import json
import os
import re
import shlex
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

SID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]{0,127}$")
OWNER_RE = re.compile(r"^(phone:prod|phone:dev:[a-z0-9]+|[a-z0-9][a-z0-9-]{0,62})$")
NAME_RANK = ("manual", "custom", "topic", "job", "ai", "agent", "fleet", "registry", "prompt")
PROMPT_NAME_SOURCES = ("ai", "registry", "prompt")
# Fields a same-epoch import may fill when the index has them empty.
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
DUMP_TIMEOUT = 120
COPY_TIMEOUT = 600


class ImportError_(Exception):
    """An import that must not go on: one line, exit 1."""


# ---------------------------------------------------------------- where things are, as the registry wrote them

def fleet_home_dir():
    return os.environ.get("FLEET_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "fleet")


def registry_dir():
    """The old registry folder this import reads: $CLAUDE_SESSIONS_DIR, else ~/.local/state/claude-sessions."""
    return os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.join(os.path.expanduser("~"), ".local", "state",
                                                                 "claude-sessions")


def machines_config(home=None):
    try:
        with open(os.path.join(home or fleet_home_dir(), "machines.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def self_name(home=None):
    name = machines_config(home).get("self")
    return name if isinstance(name, str) and name else socket.gethostname().split(".")[0]


def hub_name(home=None):
    """The `hub` of machines.json, else this machine (contract section 1)."""
    hub = machines_config(home).get("hub")
    return hub if isinstance(hub, str) and hub else self_name(home)


def machine_names(home=None):
    data = machines_config(home)
    names = {k for k, v in data.items() if k not in ("self", "hub") and isinstance(v, dict)}
    names.add(self_name(home))
    return names


def parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def read_file(path):
    try:
        with open(path) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def log(home, line):
    try:
        os.makedirs(home, exist_ok=True)
        fd = os.open(os.path.join(home, "hooks.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), line))
    except OSError:
        pass


# ---------------------------------------------------------------- the contract's modules

def _store():
    import fleet_index_store
    return fleet_index_store


def _work():
    import fleet_work
    return fleet_work


def cut(text, n):
    if not text:
        return text
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- one machine's dump (runs on that machine)

def _conversations(home):
    path = os.path.join(home, "fleet.db")
    if not os.path.isfile(path):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
        con.row_factory = sqlite3.Row
        have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "conversations" not in have:
            return []
        rows = [dict(r) for r in con.execute("SELECT * FROM conversations")]
        con.close()
        return rows
    except sqlite3.Error as e:
        raise ImportError_("cannot read %s (%s)" % (path, e))


def _config_dir(transcript):
    """The Claude config folder a transcript is under (`<config>/projects/<key>/<sid>.jsonl`), or None."""
    if not transcript:
        return None
    key_dir = os.path.dirname(transcript)
    projects = os.path.dirname(key_dir)
    return os.path.dirname(projects) if os.path.basename(projects) == "projects" else None


def _best_name(c):
    for col, src in (("manual_name", "manual"), ("name_custom", "custom"), ("name_ai", "ai"), ("name_agent", "agent")):
        if c.get(col):
            return cut(c[col], 200), src
    return "", ""


def dump_local(fleet_home=None):
    """This machine's registry files and `conversations` rows, work rows masked here (contract section 7.2).
    -> {"v", "machine", "as_of", "registry": [records], "conversations": [rows], "masked", "skipped"}."""
    home = fleet_home or fleet_home_dir()
    work = _work()
    rules = work.load_rules(home)
    masked = skipped = 0
    registry = []
    try:
        names = sorted(os.listdir(registry_dir()))
    except OSError:
        names = []
    for n in names:
        if not n.endswith(".json"):
            continue
        rec = read_file(os.path.join(registry_dir(), n))
        if rec is None or not SID_RE.match(str(rec.get("sid") or "")) or rec.get("sid") != n[:-5]:
            skipped += 1
            continue
        try:
            is_work = work.is_work(rec.get("cwd") or None, None, rules)
        except Exception:
            is_work = True
        if is_work:
            masked += 1
            rec = {k: v for k, v in rec.items()
                   if k not in ("name", "cwd", "account", "last_prompt", "last_answer")}
            rec["work"] = True
        registry.append(rec)
    conversations = []
    for c in _conversations(home):
        sid = str(c.get("session_id") or "")
        if not SID_RE.match(sid):
            skipped += 1
            continue
        transcript = c.get("transcript_path") or None
        try:
            is_work = work.is_work(c.get("cwd") or None, transcript, rules)
        except Exception:
            is_work = True
        account = None
        config = _config_dir(transcript)
        if config:
            try:
                account = work.account_of(config, rules)
            except Exception:
                account = None
        name, source = _best_name(c)
        fields = {"cwd": c.get("cwd") or None, "account": account,
                  "first_prompt": cut(c.get("first_prompt"), 300) or None,
                  "description": cut(c.get("description"), 2000) or None}
        if name:
            fields["name"], fields["name_source"] = name, source
        if is_work:
            masked += 1
            fields = work.mask_fields(dict(fields, work=True))
            fields.pop("observed", None)
        row = {"sid": sid, "started": _num(c.get("started_at")), "updated": _num(c.get("last_seen_at")),
               "ended": _num(c.get("ended_at")), "end_reason": cut(c.get("end_reason"), 64) or None,
               "work": bool(is_work)}
        row.update(fields)
        conversations.append(row)
    return {"v": 1, "machine": self_name(home), "as_of": time.time(), "registry": registry,
            "conversations": conversations, "masked": masked, "skipped": skipped}


def db_copy(fleet_home, dest):
    """A copy of this machine's fleet.db at `dest`, made with SQLite's backup call. False when there is none."""
    path = os.path.join(fleet_home or fleet_home_dir(), "fleet.db")
    if not os.path.isfile(path):
        return False
    src = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(dest, 0o600)
    return True


# ---------------------------------------------------------------- reaching the other machines

def other_machines(home=None):
    """name -> {ssh, fleet, python, env} for every machine of machines.json but this one."""
    data = machines_config(home)
    me = self_name(home)
    out = {}
    for name, m in data.items():
        if name in ("self", "hub") or name == me or not isinstance(m, dict) or not m.get("ssh") or not m.get("fleet"):
            continue
        out[name] = {"ssh": m["ssh"], "fleet": m["fleet"], "python": m.get("python") or "python3",
                     "env": m.get("env") if isinstance(m.get("env"), dict) else {}}
    return out


def _word(w):
    return "~/" + shlex.quote(w[2:]) if w.startswith("~/") else shlex.quote(w)


def _env_word(w):
    return '"$HOME"/' + shlex.quote(w[2:]) if w.startswith("~/") else shlex.quote(w)


def remote_command(m, args):
    """`<python> <folder of the fleet path>/fleet_index_import.py <args>`, with the machine's env first."""
    env = ["%s=%s" % (k, _env_word(str(v))) for k, v in sorted((m.get("env") or {}).items())
           if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k)]
    script = os.path.join(os.path.dirname(m["fleet"]), "fleet_index_import.py")
    return " ".join((["env"] + env if env else []) + [_word(m["python"]), _word(script)]
                    + [shlex.quote(a) for a in args])


def run_remote(machine, args, timeout, home=None):
    """Runs this module on another machine over ssh; returns its stdout as bytes. Raises ImportError_ with the
    reason (unreachable, timed out, the remote's last stderr line)."""
    m = other_machines(home).get(machine)
    if not m:
        raise ImportError_("no machine named %r in machines.json" % machine)
    cmd = [os.environ.get("FLEET_SSH") or "ssh"] + SSH_OPTS + ["--", m["ssh"], remote_command(m, args)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ImportError_("timed out after %d s" % timeout)
    except (OSError, subprocess.SubprocessError) as e:
        raise ImportError_(str(e))
    if r.returncode != 0:
        lines = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ImportError_(lines[-1] if lines else "exit %d" % r.returncode)
    return r.stdout


def _parse_json_tail(text):
    starts = [m.start() for m in re.finditer(r"(?m)^\{", text)]
    dec = json.JSONDecoder()
    for at in reversed(starts):
        try:
            val, end = dec.raw_decode(text[at:])
        except ValueError:
            continue
        if not text[at + end:].strip():
            return val
    raise ImportError_("answered something that is not JSON")


def fetch_dumps(machines, home=None):
    """{machine: dump} and {machine: reason} for each machine name; the hub's own is read in process."""
    me = self_name(home)
    dumps, errors = {}, {}
    for m in machines:
        try:
            if m == me:
                d = dump_local(home)
            else:
                d = _parse_json_tail(run_remote(m, ["_import-dump"], DUMP_TIMEOUT, home).decode("utf-8", "replace"))
                if not isinstance(d, dict) or not isinstance(d.get("registry"), list) \
                        or not isinstance(d.get("conversations"), list):
                    raise ImportError_("answered a dump of an unexpected shape")
            dumps[m] = d
        except ImportError_ as e:
            errors[m] = str(e)
    return dumps, errors


# ---------------------------------------------------------------- the backups (before the first write)

def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_backup_dir():
    base = os.environ.get("FLEET_IMPORT_BACKUP_DIR") or os.path.join(os.path.expanduser("~"), ".local", "state",
                                                                     "fleet", "import-backups")
    return os.path.join(base, _stamp())


def backup_sources(machines, out_dir, home=None):
    """A tarball of the hub's registry folder and a copy of each machine's fleet.db, under `out_dir` (made 0700).
    -> {"registry_tar": path, "fleet_dbs": {machine: path or None when it has none}, "errors": {machine: reason}}.
    The tarball failing raises ImportError_: nothing may be written without it."""
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    me = self_name(home)
    tar_path = os.path.join(out_dir, "claude-sessions-%s.tar.gz" % me)
    reg = registry_dir()
    try:
        with tarfile.open(tar_path, "w:gz") as tar:
            if os.path.isdir(reg):
                tar.add(reg, arcname="claude-sessions")
        os.chmod(tar_path, 0o600)
    except (OSError, tarfile.TarError) as e:
        raise ImportError_("cannot make the registry tarball %s (%s)" % (tar_path, e))
    out = {"registry_tar": tar_path, "fleet_dbs": {}, "errors": {}}
    for m in machines:
        dest = os.path.join(out_dir, "fleet-%s.db" % m)
        try:
            if m == me:
                out["fleet_dbs"][m] = dest if db_copy(home, dest) else None
            else:
                data = run_remote(m, ["_db-copy"], COPY_TIMEOUT, home)
                if not data:
                    out["fleet_dbs"][m] = None
                    continue
                if not data.startswith(b"SQLite format 3\x00"):
                    raise ImportError_("sent something that is not a SQLite file")
                fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                chk = sqlite3.connect(dest)
                try:
                    ok = chk.execute("PRAGMA quick_check").fetchone()[0]
                finally:
                    chk.close()
                if ok != "ok":
                    raise ImportError_("the copy fails SQLite's check (%s)" % ok)
                out["fleet_dbs"][m] = dest
        except (ImportError_, OSError, sqlite3.Error) as e:
            out["errors"][m] = str(e)
    return out


# ---------------------------------------------------------------- merging the dumps into rows

def _valid_name(name, machines):
    return isinstance(name, str) and name in machines


def build_rows(dumps, *, hub, machines, rules=None):
    """The merged row of every sid in the dumps. -> (rows {sid: (row, origin)}, conflicts, invalid)."""
    import fleet_sessions
    by_sid = {}
    for m in sorted(dumps):
        for rec in dumps[m].get("registry") or ():
            by_sid.setdefault(rec.get("sid"), {"reg": [], "conv": []})["reg"].append((m, rec))
        for c in dumps[m].get("conversations") or ():
            by_sid.setdefault(c.get("sid"), {"reg": [], "conv": []})["conv"].append((m, c))
    rows, conflicts, invalid = {}, [], []
    for sid in sorted(s for s in by_sid if isinstance(s, str)):
        if not SID_RE.match(sid):
            invalid.append({"sid": sid, "machine": None, "why": "not a session id"})
            continue
        regs = [(m, r) for m, r in by_sid[sid]["reg"] if isinstance(r.get("epoch"), int) and r["epoch"] >= 1]
        bad = [(m, r) for m, r in by_sid[sid]["reg"] if (m, r) not in regs]
        for m, r in bad:
            invalid.append({"sid": sid, "machine": m, "why": "registry file without an epoch"})
        good = []
        for m, r in regs:
            owner = r.get("owner")
            if not isinstance(owner, str) or not OWNER_RE.match(owner) or \
                    (not owner.startswith("phone:") and owner not in machines):
                invalid.append({"sid": sid, "machine": m, "why": "owner %r is not a machine or a phone" % owner})
                continue
            good.append((m, r))
        convs = by_sid[sid]["conv"]
        if not good and not convs:
            continue
        reg = origin = None
        if good:
            good.sort(key=lambda mr: (-mr[1]["epoch"], mr[0] != hub, -(parse_iso(mr[1].get("updated")) or 0)))
            origin, reg = good[0]
            for m, r in good[1:]:
                if r["epoch"] != reg["epoch"] or r.get("owner") != reg.get("owner"):
                    conflicts.append({"sid": sid, "where": "copies",
                                      "kept": {"machine": origin, "owner": reg.get("owner"), "epoch": reg["epoch"]},
                                      "lost": {"machine": m, "owner": r.get("owner"), "epoch": r["epoch"]},
                                      "why": "the registry copy with the higher epoch wins" if r["epoch"] != reg["epoch"]
                                      else "same epoch, other owner: the hub's copy wins"})
        if reg is not None:
            owner, epoch = reg["owner"], reg["epoch"]
            machine = reg.get("machine") if _valid_name(reg.get("machine"), machines) else None
            machine = machine or (hub if owner.startswith("phone:") else owner)
        else:
            convs_sorted = sorted(convs, key=lambda mc: -(mc[1].get("updated") or 0))
            origin = convs_sorted[0][0]
            owner, epoch, machine = origin, 1, origin
        here = [c for m, c in convs if m == machine] or [c for m, c in convs]
        conv = max(here, key=lambda c: c.get("updated") or 0) if here else {}
        work = bool((reg or {}).get("work")) or any(c.get("work") for m, c in convs)
        names = []
        if reg is not None and reg.get("name"):
            names.append((cut(reg["name"], 200), "registry"))
        for c in here:
            if c.get("name") and c.get("name_source") in NAME_RANK:
                names.append((c["name"], c["name_source"]))
        first_prompt = next((c.get("first_prompt") for c in here if c.get("first_prompt")), None)
        if first_prompt:
            names.append((cut(first_prompt, 60), "prompt"))
        names.sort(key=lambda ns: NAME_RANK.index(ns[1]))
        name, name_source = names[0] if names else ("", "")
        starts = [c.get("started") for m, c in convs if c.get("started")]
        reg_updated = parse_iso((reg or {}).get("updated"))
        ups = [u for u in [reg_updated] + [c.get("updated") for m, c in convs] if u]
        started = min(starts) if starts else (parse_iso((reg or {}).get("owner_since")) or reg_updated
                                              or time.time())
        updated = max(ups) if ups else started
        owner_since = parse_iso((reg or {}).get("owner_since")) or started
        cwd = (reg or {}).get("cwd") or conv.get("cwd") or None
        if reg is not None:
            kind = reg.get("kind") if reg.get("kind") in ("chat", "job") else "chat"
            ended = None if reg.get("live") is True else (conv.get("ended") or updated)
            end_reason = None if ended is None else (conv.get("end_reason") or "other")
        else:
            kind = fleet_sessions.kind_of(name, cwd, rules)
            ended = conv.get("ended")
            end_reason = (conv.get("end_reason") or "other") if ended else None
        topic = (reg or {}).get("topic")
        topic = {"host": topic["host"], "id": str(topic["id"])[:200]} \
            if isinstance(topic, dict) and re.match(r"^(prod|dev:[a-z0-9]+)$", str(topic.get("host") or "")) \
            and topic.get("id") else None
        row = {
            "sid": sid, "conversation": sid, "name": name, "name_source": name_source, "kind": kind,
            "env": "dev:" + owner[len("phone:dev:"):] if owner.startswith("phone:dev:") else "prod",
            "machine": machine, "cwd": cwd, "account": (reg or {}).get("account") or conv.get("account") or None,
            "owner": owner, "owner_since": owner_since, "epoch": epoch, "continues": None, "superseded_by": None,
            "first_prompt": first_prompt, "last_prompt": cut((reg or {}).get("last_prompt"), 200) or None,
            "last_answer": cut((reg or {}).get("last_answer"), 200) or None, "topic": topic, "rc_name": None,
            "started": started, "updated": updated, "ended": ended, "end_reason": end_reason,
            "description": conv.get("description") or None, "work": work,
        }
        if work:
            for f in ("first_prompt", "last_prompt", "last_answer", "cwd", "account", "description", "rc_name"):
                row[f] = None
            if row["name_source"] in PROMPT_NAME_SOURCES:
                row["name"], row["name_source"] = "", ""
        rows[sid] = (row, origin)
    return rows, conflicts, invalid


def classify(existing, row, origin=None):
    """What importing `row` does to the index's `existing` row: (outcome, conflict or None). The rule the store's
    `import_row` follows (contract section 15): the higher epoch wins; at the same epoch and owner the index keeps
    its values and only empty fields are filled (`merge_same_epoch`)."""
    if existing is None:
        return "new", None
    if row["epoch"] > existing["epoch"]:
        return "updated", "the import's epoch %d is higher than the index's %d" % (row["epoch"], existing["epoch"])
    if row["epoch"] < existing["epoch"]:
        return "conflict-kept", "the index's epoch %d is higher than the import's %d" % (existing["epoch"],
                                                                                        row["epoch"])
    if row["owner"] != existing["owner"]:
        return "conflict-kept", "same epoch %d, other owner: the index's %s stays" % (row["epoch"], existing["owner"])
    if _store().merge_same_epoch(existing, row, origin=origin) != existing:
        return "updated", None
    return "same", None


# ---------------------------------------------------------------- the report, the plan and the import

def _report(dumps, errors, rows, conflicts, invalid, outcomes):
    machines = {}
    for m in sorted(set(dumps) | set(errors)):
        if m in errors:
            machines[m] = {"reachable": False, "reason": errors[m]}
            continue
        d = dumps[m]
        machines[m] = {"reachable": True, "registry": len(d.get("registry") or ()),
                       "conversations": len(d.get("conversations") or ()), "masked": d.get("masked", 0),
                       "rows": 0, "new": 0, "same": 0, "updated": 0, "conflict-kept": 0, "conflicts": 0,
                       "invalid": 0}
    for sid, (row, origin) in rows.items():
        e = machines.get(origin)
        if e and e.get("reachable"):
            e["rows"] += 1
            e[outcomes[sid]] += 1
    for c in conflicts:
        m = c.get("lost", {}).get("machine") if c.get("where") == "copies" else c.get("origin")
        if m in machines and machines[m].get("reachable"):
            machines[m]["conflicts"] += 1
    for i in invalid:
        if i.get("machine") in machines and machines[i["machine"]].get("reachable"):
            machines[i["machine"]]["invalid"] += 1
    totals = {k: sum(1 for o in outcomes.values() if o == k) for k in ("new", "same", "updated", "conflict-kept")}
    totals.update(rows=len(rows), conflicts=len(conflicts), invalid=len(invalid))
    return {"v": 1, "machines": machines, "totals": totals, "conflicts": conflicts, "invalid": invalid}


def _context(home=None):
    return hub_name(home), machine_names(home), _sessions_rules(home)


def _sessions_rules(home=None):
    try:
        with open(os.path.join(home or fleet_home_dir(), "sessions.json")) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _merge(dumps, home=None):
    hub, machines, rules = _context(home)
    return build_rows(dumps, hub=hub, machines=machines, rules=rules)


def plan(con, dumps, errors=None, home=None):
    """The dry-run report: per machine its rows, new, same, updated, kept on conflict, conflicts and invalid ones,
    and every conflict. Reads the index through `con` and writes nothing."""
    store = _store()
    rows, conflicts, invalid = _merge(dumps, home)
    outcomes = {}
    for sid, (row, origin) in rows.items():
        outcome, why = classify(store.get_row(con, sid), row, origin)
        outcomes[sid] = outcome
        if why:
            conflicts.append({"sid": sid, "where": "index", "origin": origin, "outcome": outcome, "why": why})
    return _report(dumps, errors or {}, rows, conflicts, invalid, outcomes)


def apply(con, dumps, errors=None, home=None):
    """Imports the merged rows through the store's `import_row`; logs each conflict to hooks.log. -> the report."""
    home = home or fleet_home_dir()
    store = _store()
    rows, conflicts, invalid = _merge(dumps, home)
    outcomes = {}
    for c in conflicts:
        log(home, "import: %s: registry copies disagree: kept %s, lost %s (%s)"
                 % (c["sid"], json.dumps(c["kept"]), json.dumps(c["lost"]), c["why"]))
    for sid, (row, origin) in rows.items():
        planned, why = classify(store.get_row(con, sid), row, origin)
        # A row the index already holds as the import would leave it is not written again: a second import
        # changes nothing, whatever the store does with an equal row.
        outcome = "same" if planned == "same" else store.import_row(con, row, origin=origin)
        outcomes[sid] = outcome
        if why:
            conflicts.append({"sid": sid, "where": "index", "origin": origin, "outcome": outcome, "why": why})
            log(home, "import: %s from %s: %s (%s)" % (sid, origin, outcome, why))
    for i in invalid:
        log(home, "import: %s from %s: skipped, %s" % (i["sid"], i["machine"], i["why"]))
    return _report(dumps, errors or {}, rows, conflicts, invalid, outcomes)


def _dry_connection(home):
    """A throwaway copy of hub.db (or an empty one) in a temp folder, so a dry run reads the index and writes
    nothing of the fleet's. -> (connection, temp folder)."""
    store = _store()
    tmp = tempfile.mkdtemp(prefix="fleet-import-dry-")
    path = os.path.join(tmp, "hub.db")
    real = store.hub_db_path(home)
    if os.path.isfile(real):
        src = sqlite3.connect("file:%s?mode=ro" % real, uri=True, timeout=30)
        dst = sqlite3.connect(path)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    return store.connect(path), tmp


def _print_report(rep, backups, dry, out):
    if backups:
        out.write("backup: registry tarball %s\n" % backups["registry_tar"])
        for m, p in sorted(backups["fleet_dbs"].items()):
            out.write("backup: fleet.db of %s %s\n" % (m, p or "(none on that machine)"))
        if backups.get("hub_db"):
            out.write("backup: hub.db %s\n" % backups["hub_db"])
    out.write("%s\n" % ("dry run: nothing written" if dry else "imported"))
    for m, e in rep["machines"].items():
        if not e.get("reachable"):
            out.write("  %s: not imported, %s\n" % (m, e.get("reason")))
            continue
        out.write("  %s: %d rows (%d new, %d same, %d updated, %d kept on conflict), %d conflicts, %d invalid; "
                  "read %d registry files, %d conversations, %d masked\n"
                  % (m, e["rows"], e["new"], e["same"], e["updated"], e["conflict-kept"], e["conflicts"],
                     e["invalid"], e["registry"], e["conversations"], e["masked"]))
    for c in rep["conflicts"]:
        out.write("  conflict %s: %s\n" % (c["sid"], c["why"]))
    for i in rep["invalid"]:
        out.write("  invalid %s from %s: %s\n" % (i["sid"], i["machine"], i["why"]))


def run_import(machines=None, dry_run=False, backup_dir=None, home=None):
    """The whole import on the hub. -> (report, backups or None). Raises ImportError_ when it must stop."""
    home = home or fleet_home_dir()
    me = self_name(home)
    hub = hub_name(home)
    if me != hub:
        raise ImportError_("the import runs on the hub (%s); this is %s" % (hub, me))
    names = list(dict.fromkeys(machines or ([me] + sorted(other_machines(home)))))
    dumps, errors = fetch_dumps(names, home)
    store = _store()
    if dry_run:
        con, tmp = _dry_connection(home)
        try:
            return plan(con, dumps, errors, home), None
        finally:
            con.close()
            for n in os.listdir(tmp):
                os.unlink(os.path.join(tmp, n))
            os.rmdir(tmp)
    backups = backup_sources(sorted(dumps), backup_dir or default_backup_dir(), home)
    for m, why in backups["errors"].items():  # no copy of its fleet.db: that machine is not imported
        errors[m] = "no copy of its fleet.db (%s)" % why
        dumps.pop(m, None)
    con = store.connect(store.hub_db_path(home))
    try:
        backups["hub_db"] = store.backup(con, label="import")
        return apply(con, dumps, errors, home), backups
    finally:
        con.close()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["_import-dump"]:
        json.dump(dump_local(), sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0
    if argv[:1] == ["_db-copy"]:
        tmp = tempfile.mkdtemp(prefix="fleet-db-copy-")
        dest = os.path.join(tmp, "fleet.db")
        try:
            if db_copy(None, dest):
                with open(dest, "rb") as f:
                    sys.stdout.buffer.write(f.read())
        finally:
            for n in os.listdir(tmp):
                os.unlink(os.path.join(tmp, n))
            os.rmdir(tmp)
        return 0
    if argv[:1] == ["import"]:
        argv = argv[1:]
    p = argparse.ArgumentParser(prog="fleet session import",
                                description="Import every registry file and every machine's history into the index.")
    p.add_argument("--dry-run", action="store_true", help="print the report and write nothing")
    p.add_argument("--machine", action="append", default=[], help="import only this machine (repeatable)")
    p.add_argument("--backup-dir", help="where the tarball and the fleet.db copies go")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    a = p.parse_args(argv)
    try:
        rep, backups = run_import(a.machine or None, a.dry_run, a.backup_dir)
    except ImportError_ as e:
        sys.stderr.write("fleet session import: %s\n" % e)
        return 1
    if a.json:
        json.dump(dict(rep, dry_run=a.dry_run, backups=backups), sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    else:
        _print_report(rep, backups, a.dry_run, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
