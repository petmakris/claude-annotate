"""The session index: the hub's store (`$FLEET_HOME/index/hub.db` on the hub).

One row per session id, durable facts only. `owner` and `epoch` change only through `take`, a compare-and-set on
`(sid, epoch)`. Journal entries from every machine are applied per sid in `seq` order, deduped on `(machine, seq)`
by one high mark per machine, and dropped when their writer is not the owner or their epoch is not current. A
Claude Voice handover is one transaction (`chain`). Nothing here orders by wall clock: `at` and `updated` are for
display only. Contract: `fleet/docs/session-index.md`, sections 2 to 11 and 15.

Stdlib only, Python 3.9+, no fleet imports. Every write runs inside one `BEGIN IMMEDIATE` transaction.
"""
import json
import os
import re
import sqlite3
import time

import fleet_work

SCHEMA_VERSION = 1
STALE_AFTER = 60
HUB_DOWN = "ownership cannot change while the hub is down"
NAME_RANK = ("manual", "custom", "topic", "job", "ai", "agent", "fleet", "registry", "prompt")
BACKUP_KEEP = 20

SID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]{0,127}$")
OWNER_RE = re.compile(r"^(phone:prod|phone:dev:[a-z0-9]+|[a-z0-9][a-z0-9-]{0,62})$")
KINDS = ("chat", "job", "worker", "voice")
EVENTS = ("start", "prompt", "stop", "end", "observe", "describe")
WHERE = ("tmux", "window", "bg", "phone", "none")

# text fields of a row and their limits (section 2.1)
LIMITS = {"name": 200, "first_prompt": 300, "last_prompt": 200, "last_answer": 200, "description": 2000,
          "rc_name": 200, "end_reason": 64, "account": 64, "cwd": 4096}
FIELDS = ("sid", "conversation", "name", "name_source", "kind", "env", "machine", "cwd", "account", "owner",
          "owner_since", "epoch", "continues", "superseded_by", "first_prompt", "last_prompt", "last_answer", "topic",
          "rc_name", "started", "updated", "ended", "end_reason", "description", "work")
JOURNAL_FIELDS = ("name", "name_source", "kind", "cwd", "account", "first_prompt", "last_prompt", "last_answer",
                  "topic", "rc_name", "description", "end_reason", "work", "observed")
OBSERVED_KEYS = ("live", "state", "where", "tmux", "pid", "observed_at")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  sid TEXT PRIMARY KEY, conversation TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', name_source TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL, env TEXT NOT NULL, machine TEXT NOT NULL, cwd TEXT, account TEXT,
  owner TEXT NOT NULL, owner_since REAL NOT NULL, epoch INTEGER NOT NULL,
  continues TEXT, superseded_by TEXT, first_prompt TEXT, last_prompt TEXT, last_answer TEXT, topic TEXT,
  rc_name TEXT, started REAL NOT NULL, updated REAL NOT NULL, ended REAL, end_reason TEXT, description TEXT,
  work INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS sessions_conversation ON sessions(conversation);
CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner);
CREATE TABLE IF NOT EXISTS journal_high (machine TEXT PRIMARY KEY, seq INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS journal_observed (sid TEXT PRIMARY KEY, writer TEXT NOT NULL, observed TEXT NOT NULL);
"""


class Refused(Exception):
    """A refused take, chain or other hub call: `.code` (section 4.2 or 8) and `.line` (the one line)."""

    def __init__(self, code, line):
        Exception.__init__(self, line)
        self.code = code
        self.line = line

    def reply(self):
        return {"ok": False, "code": self.code, "error": self.line}


# ---------------------------------------------------------------- paths and connection

def hub_db_path(fleet_home):
    return os.path.join(fleet_home, "index", "hub.db")


def backup_dir():
    return os.environ.get("FLEET_BACKUP_DIR") or os.path.join(os.path.expanduser("~"), ".local", "state", "fleet",
                                                              "index-backups")


def _private_dir(d):
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        if os.stat(d).st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        pass


def _private_file(path):
    try:
        if os.stat(path).st_mode & 0o077:
            os.chmod(path, 0o600)
    except OSError:
        pass


def connect(path):
    """The hub's store, made 0600 in a 0700 folder. Autocommit: every write opens its own transaction."""
    _private_dir(os.path.dirname(path) or ".")
    if not os.path.exists(path):
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    con = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    for suffix in ("", "-wal", "-shm"):
        _private_file(path + suffix)
    return con


def _db_file(con):
    for row in con.execute("PRAGMA database_list"):
        if row[1] == "main":
            return row[2] or None
    return None


def _log(con, text):
    """One line in `$FLEET_HOME/hooks.log` of the store's own FLEET_HOME. Never raises."""
    try:
        db = _db_file(con)
        if not db:
            return
        path = os.path.join(os.path.dirname(os.path.dirname(db)), "hooks.log")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s index: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


# ---------------------------------------------------------------- callbacks

_ON_CHANGE = []
_BEFORE_READ = []


def on_change(fn):
    """fn(con, sids) after each committed change (the registry shim)."""
    if fn not in _ON_CHANGE:
        _ON_CHANGE.append(fn)


def before_read(fn):
    """fn(con) before a list or show reads rows (the shim reads Claude Voice's patches in)."""
    if fn not in _BEFORE_READ:
        _BEFORE_READ.append(fn)


def run_before_read(con):
    for fn in list(_BEFORE_READ):
        try:
            fn(con)
        except Exception as e:  # noqa: B902 - a callback may cost a refresh, never a read
            _log(con, "before_read %s: %s: %s" % (getattr(fn, "__name__", fn), type(e).__name__, e))


def _changed(con, sids):
    sids = [s for s in dict.fromkeys(sids) if s]
    if not sids:
        return
    for fn in list(_ON_CHANGE):
        try:
            fn(con, sids)
        except Exception as e:  # noqa: B902 - the index is written; a callback failure is logged
            _log(con, "on_change %s: %s: %s" % (getattr(fn, "__name__", fn), type(e).__name__, e))


class _Tx:
    """`with _Tx(con):` one BEGIN IMMEDIATE transaction, rolled back on any exception."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, kind, value, tb):
        if kind is None:
            self.con.execute("COMMIT")
        else:
            self.con.execute("ROLLBACK")
        return False


# ---------------------------------------------------------------- rows

def cut(text, n):
    """The registry's cut: runs of white space become one space, a longer text is cut to n-1 plus an ellipsis."""
    if text is None:
        return None
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _row_dict(r):
    if r is None:
        return None
    d = {k: r[k] for k in FIELDS}
    d["topic"] = json.loads(d["topic"]) if d["topic"] else None
    d["work"] = bool(d["work"])
    return d


def get_row(con, sid):
    return _row_dict(con.execute("SELECT * FROM sessions WHERE sid=?", (sid,)).fetchone())


def _write_row(con, row):
    vals = dict(row)
    vals["topic"] = json.dumps(vals["topic"], sort_keys=True) if vals.get("topic") else None
    vals["work"] = 1 if vals.get("work") else 0
    con.execute("INSERT OR REPLACE INTO sessions(%s) VALUES (%s)" % (",".join(FIELDS), ",".join("?" * len(FIELDS))),
                [vals.get(k) for k in FIELDS])


def _put(con, row):
    """Tests only: write a whole row as it is, in its own transaction, with no checks and no callbacks."""
    with _Tx(con):
        _write_row(con, row)


def head_of(con, sid):
    """The chain's head: superseded_by followed to the end."""
    seen = set()
    cur = sid
    while cur and cur not in seen:
        seen.add(cur)
        r = con.execute("SELECT superseded_by FROM sessions WHERE sid=?", (cur,)).fetchone()
        if r is None or not r[0]:
            return cur
        cur = r[0]
    return cur


def chain_of(con, sid):
    """The sids of sid's conversation, oldest first."""
    r = con.execute("SELECT conversation FROM sessions WHERE sid=?", (sid,)).fetchone()
    if r is None:
        return [sid]
    out, cur = [], r[0]
    while cur and cur not in out:
        row = con.execute("SELECT superseded_by FROM sessions WHERE sid=?", (cur,)).fetchone()
        if row is None:
            break
        out.append(cur)
        cur = row[0]
    return out or [sid]


def env_of(writer):
    """`dev:<sandbox>` for a row a sandbox's Claude Voice server makes, else `prod` (section 3)."""
    return "dev:" + writer[len("phone:dev:"):] if writer.startswith("phone:dev:") else "prod"


def _observed_of(con, sid, now):
    r = con.execute("SELECT writer, observed FROM journal_observed WHERE sid=?", (sid,)).fetchone()
    base = {"live": None, "state": None, "where": None, "tmux": None, "pid": None, "observed_at": None,
            "stale": False, "source": "none"}
    if r is None:
        return base
    try:
        obs = json.loads(r["observed"])
    except ValueError:
        return base
    for k in OBSERVED_KEYS:
        if k in obs:
            base[k] = obs[k]
    base["source"] = "journal"
    at = base["observed_at"]
    base["stale"] = not r["writer"].startswith("phone:") and (at is None or now - at > STALE_AFTER)
    return base


def listed(con, row, now=None):
    """A row as lists show it: durable fields, `observed` (journal source; a surface may replace it with newer
    values read from the machine), `key`, `head` and `chain`."""
    now = time.time() if now is None else now
    out = dict(row)
    out["observed"] = _observed_of(con, row["sid"], now)
    out["key"] = "%s:%s" % (row["machine"], row["sid"])
    out["head"] = not row["superseded_by"]
    out["chain"] = chain_of(con, row["sid"]) if out["head"] else []
    return out


def list_rows(con, *, env="prod", chains="heads", kinds=None, machine=None, owner=None, q=None, limit=300,
              now=None):
    """Rows newest `updated` first. Dev rows only with env `all` or `dev:<sandbox>`; heads only unless chains is
    `all`. Live rows always come, whatever the limit."""
    where, args = [], []
    if env == "prod" or not env:
        where.append("env='prod'")
    elif env != "all":
        where.append("env=?")
        args.append(env)
    if chains != "all":
        where.append("superseded_by IS NULL")
    if kinds:
        kinds = [k for k in kinds if k in KINDS]
        where.append("kind IN (%s)" % ",".join("?" * len(kinds)) if kinds else "0")
        args += kinds
    if machine:
        where.append("machine=?")
        args.append(machine)
    if owner:
        where.append("owner=?")
        args.append(owner)
    sql = "SELECT * FROM sessions" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY updated DESC, sid"
    rows = [_row_dict(r) for r in con.execute(sql, args)]
    if q:
        words = [w.lower() for w in str(q).split()]

        def hit(r):
            text = " ".join(str(r.get(k) or "") for k in ("name", "last_prompt", "last_answer", "cwd")).lower()
            return all(w in text for w in words)
        rows = [r for r in rows if hit(r)]
    out = [listed(con, r, now) for r in rows]
    if limit is not None and len(out) > limit:
        out = out[:limit] + [r for r in out[limit:] if r["observed"].get("live")]
    return out


def high_seq(con, machine):
    r = con.execute("SELECT seq FROM journal_high WHERE machine=?", (machine,)).fetchone()
    return int(r[0]) if r else 0


def _set_high(con, machine, seq):
    con.execute("INSERT INTO journal_high(machine, seq) VALUES (?, ?) ON CONFLICT(machine) DO UPDATE SET seq=excluded.seq",
                (machine, seq))


# ---------------------------------------------------------------- backups

def backup(con, *, label, keep=BACKUP_KEEP, directory=None):
    """Copy the store with SQLite's backup call to `hub-<UTC time>-<label>.db`; keep the `keep` newest by name."""
    d = directory or backup_dir()
    _private_dir(d)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", label or "manual").strip("-") or "manual"
    path = os.path.join(d, "hub-%s-%s.db" % (stamp, safe))
    n = 2
    while os.path.exists(path):
        path = os.path.join(d, "hub-%s-%s-%d.db" % (stamp, safe, n))
        n += 1
    os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))
    dest = sqlite3.connect(path)
    try:
        con.backup(dest)
    finally:
        dest.close()
    _private_file(path)
    def order(f):  # by the time in the name; within one second, by the file's own time
        try:
            return f[4:20], os.stat(os.path.join(d, f)).st_mtime_ns
        except OSError:
            return f[4:20], 0
    names = sorted((f for f in os.listdir(d) if f.startswith("hub-") and f.endswith(".db")), key=order)
    for old in names[:-keep] if keep and len(names) > keep else []:
        try:
            os.unlink(os.path.join(d, old))
        except OSError:
            pass
    return path


def _backup_quiet(con, label):
    try:
        return backup(con, label=label)
    except (OSError, sqlite3.Error) as e:
        _log(con, "backup %s failed: %s" % (label, e))
        return None


# ---------------------------------------------------------------- take (section 4)

def _owner_ok(owner, machines):
    if not isinstance(owner, str) or not OWNER_RE.match(owner):
        return False
    return owner.startswith("phone:") or owner in machines


def take(con, sid, to, expect_epoch, by, *, hub, machines, cwd=None, release=None, now=None):
    """Move a session to `to`, compare-and-set on (sid, epoch). Raises Refused; returns the take_reply."""
    now = time.time() if now is None else now
    machines = set(machines or ()) | {hub}
    if not isinstance(sid, str) or not SID_RE.match(sid):
        raise Refused("bad-request", "%r is not a session id" % (sid,))
    if not _owner_ok(to, machines):
        raise Refused("bad-request", "%r is not an owner: a machine of machines.json, phone:prod or "
                                     "phone:dev:<sandbox>" % (to,))
    by = by or hub
    if not _owner_ok(by, machines):
        raise Refused("bad-request", "%r is not a machine or a Claude Voice server" % (by,))
    if isinstance(expect_epoch, bool) or not isinstance(expect_epoch, int) or expect_epoch < 1:
        raise Refused("bad-request", "expect_epoch must be a whole number, 1 or more")
    with _Tx(con):
        row = get_row(con, sid)
        if row is None:
            raise Refused("no-session", "session %s is not in the index" % sid)
        if row["superseded_by"]:
            raise Refused("superseded", "session %s was continued as %s; take %s instead"
                          % (sid, head_of(con, sid), head_of(con, sid)))
        if row["kind"] in ("job", "worker"):
            raise Refused("job", "session %s is a %s: it can be read, never taken" % (sid, row["kind"]))
        if row["work"]:
            raise Refused("work", "session %s is a work session: it never leaves its machine" % sid)
        dev_line = ("a Claude Voice sandbox takes only the sessions it made, and never gives one to phone:prod")
        for who in (by, to):
            if who.startswith("phone:dev:") and row["env"] != env_of(who):
                raise Refused("dev-refused", dev_line)
        if to == "phone:prod" and row["env"].startswith("dev:"):
            raise Refused("dev-refused", dev_line)
        if row["owner"] == to:
            return {"ok": True, "sid": sid, "owner": to, "epoch": row["epoch"], "owner_since": row["owner_since"],
                    "previous_owner": row["owner"], "conversation": row["conversation"]}
        if row["epoch"] != expect_epoch:
            raise Refused("stale-epoch", "session %s moved meanwhile (epoch %d, expected %d); read it again"
                          % (sid, row["epoch"], expect_epoch))
        new = dict(row)
        new["owner"] = to
        new["owner_since"] = now
        new["epoch"] = row["epoch"] + 1
        new["machine"] = hub if to.startswith("phone:") else to
        if cwd:
            new["cwd"] = None if row["work"] else cut(cwd, LIMITS["cwd"])
        new["updated"] = now
        _write_row(con, new)
    _log(con, "take %s %s -> %s epoch %d by %s release %s" % (sid, row["owner"], to, new["epoch"], by, release or "-"))
    _backup_quiet(con, "%s-e%d" % (sid[:8], new["epoch"]))
    _changed(con, [sid])
    return {"ok": True, "sid": sid, "owner": to, "epoch": new["epoch"], "owner_since": now,
            "previous_owner": row["owner"], "conversation": row["conversation"]}


# ---------------------------------------------------------------- the journal (section 5)

def _text_ok(v, n, nullable=True):
    return (v is None and nullable) or (isinstance(v, str) and len(v) <= n)


def _time_ok(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0


def fields_problem(fields):
    """Why a journal entry's fields break the schema (`journal_fields`), or None."""
    if not isinstance(fields, dict):
        return "fields is not an object"
    for k, v in fields.items():
        if k not in JOURNAL_FIELDS:
            return "fields may not carry %s" % k
        if k in LIMITS and k != "name" and not _text_ok(v, LIMITS[k]):
            return "%s is not text of at most %d characters" % (k, LIMITS[k])
    if "name" in fields and not _text_ok(fields["name"], 200, nullable=False):
        return "name is not text of at most 200 characters"
    if "name_source" in fields and fields["name_source"] not in NAME_RANK + ("",):
        return "name_source %r is unknown" % (fields["name_source"],)
    if "kind" in fields and fields["kind"] not in KINDS:
        return "kind %r is unknown" % (fields["kind"],)
    if "work" in fields and not isinstance(fields["work"], bool):
        return "work is not true or false"
    t = fields.get("topic")
    if t is not None and not (isinstance(t, dict) and set(t) == {"host", "id"} and isinstance(t["id"], str)
                              and isinstance(t["host"], str) and re.match(r"^(prod|dev:[a-z0-9]+)$", t["host"])):
        return "topic is not {host, id}"
    obs = fields.get("observed")
    if obs is not None:
        if not isinstance(obs, dict) or not obs or "observed_at" not in obs or set(obs) - set(OBSERVED_KEYS):
            return "observed is not an object with observed_at and only live, state, where, tmux, pid"
        if not _time_ok(obs["observed_at"]):
            return "observed_at is not a time"
        if obs.get("live") is not None and not isinstance(obs["live"], bool):
            return "observed.live is not true or false"
        if obs.get("where") is not None and obs["where"] not in WHERE:
            return "observed.where is unknown"
        if not _text_ok(obs.get("state"), 64) or not _text_ok(obs.get("tmux"), 200):
            return "observed text too long"
        pid = obs.get("pid")
        if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid < 1):
            return "observed.pid is not a process id"
    return None  # a work entry's forbidden fields are the hub's own check (work-refused)


def entry_problem(entry, batch_machine, hub, machines):
    """Why an entry is invalid (schema, unknown machine, a phone writer off the hub), or None."""
    if not isinstance(entry, dict):
        return "an entry is not an object"
    need = ("v", "machine", "seq", "as", "sid", "epoch_seen", "event", "at", "fields")
    missing = [k for k in need if k not in entry]
    if missing:
        return "the entry has no %s" % ", ".join(missing)
    extra = set(entry) - set(need)
    if extra:
        return "the entry may not carry %s" % ", ".join(sorted(extra))
    if entry["v"] != 1:
        return "v is not 1"
    if entry["machine"] != batch_machine:
        return "the entry's machine is not the batch's"
    if entry["machine"] not in machines:
        return "machine %r is not in machines.json" % (entry["machine"],)
    if not isinstance(entry["sid"], str) or not SID_RE.match(entry["sid"]):
        return "sid is not a session id"
    if entry["event"] not in EVENTS:
        return "event %r is unknown" % (entry["event"],)
    e = entry["epoch_seen"]
    if isinstance(e, bool) or not isinstance(e, int) or e < 0:
        return "epoch_seen is not a whole number"
    if not _time_ok(entry["at"]):
        return "at is not a time"
    w = entry["as"]
    if not isinstance(w, str) or not OWNER_RE.match(w):
        return "as is not an owner"
    if w.startswith("phone:"):
        if entry["machine"] != hub:
            return "only the hub machine writes as %s" % w
    elif w != entry["machine"]:
        return "as must be the writing machine"
    return fields_problem(entry["fields"])


def _merge_name(row, fields):
    if "name" not in fields:
        return
    name, src = cut(fields["name"], LIMITS["name"]) or "", fields.get("name_source") or "prompt"
    if not name:
        return
    if src not in NAME_RANK:
        return
    cur = row.get("name_source") or ""
    if not row.get("name") or cur not in NAME_RANK or NAME_RANK.index(src) <= NAME_RANK.index(cur):
        row["name"], row["name_source"] = name, src


def _merge_fields(row, fields, event, writer, now):
    _merge_name(row, fields)
    if "kind" in fields and fields["kind"] == "voice" and writer.startswith("phone:"):
        row["kind"] = "voice"
    for k in ("cwd", "account", "last_prompt", "last_answer", "rc_name", "description"):
        if k in fields:
            row[k] = cut(fields[k], LIMITS[k]) if fields[k] is not None else None
    if fields.get("first_prompt") and not row.get("first_prompt"):
        row["first_prompt"] = cut(fields["first_prompt"], LIMITS["first_prompt"])
    if "topic" in fields:
        row["topic"] = fields["topic"]
    if event in ("start", "prompt", "stop"):
        row["ended"], row["end_reason"] = None, None
    elif event == "end":
        row["ended"] = now
        row["end_reason"] = cut(fields.get("end_reason"), LIMITS["end_reason"]) or "other"
    row["updated"] = now


def _new_row(entry, now):
    f = entry["fields"]
    kind = f.get("kind") if f.get("kind") in KINDS else "chat"
    if kind == "voice" and not entry["as"].startswith("phone:"):
        kind = "chat"
    return {"sid": entry["sid"], "conversation": entry["sid"], "name": "", "name_source": "", "kind": kind,
            "env": env_of(entry["as"]), "machine": entry["machine"], "cwd": None, "account": None,
            "owner": entry["as"], "owner_since": now, "epoch": 1, "continues": None, "superseded_by": None,
            "first_prompt": None, "last_prompt": None, "last_answer": None, "topic": None, "rc_name": None,
            "started": now, "updated": now, "ended": None, "end_reason": None, "description": None,
            "work": bool(f.get("work"))}


def _keep_observed(con, sid, writer, obs):
    con.execute("INSERT INTO journal_observed(sid, writer, observed) VALUES (?,?,?) ON CONFLICT(sid) DO UPDATE SET "
                "writer=excluded.writer, observed=excluded.observed", (sid, writer, json.dumps(obs, sort_keys=True)))


def _apply_one(con, entry, now):
    """The outcome of one valid entry (steps 3 to 7) and whether the row changed."""
    sid, f = entry["sid"], entry["fields"]
    row = get_row(con, sid)
    work = bool(f.get("work")) or bool(row and row["work"])
    if work:
        why = fleet_work.work_refusal(f)
        if why:
            return "work-refused", why, False
    if row is None:
        if entry["epoch_seen"] not in (0, 1):
            return "stale-epoch", "no row, and the entry saw epoch %d" % entry["epoch_seen"], False
        row = _new_row(entry, now)
        _merge_fields(row, f, entry["event"], entry["as"], now)
        _write_row(con, row)
        if f.get("observed"):
            _keep_observed(con, sid, entry["as"], f["observed"])
        return "applied", "", True
    if row["owner"] != entry["as"]:
        return "not-owner", "the owner is %s, not %s" % (row["owner"], entry["as"]), False
    if row["epoch"] != entry["epoch_seen"]:
        return "stale-epoch", "epoch %d, the entry saw %d" % (row["epoch"], entry["epoch_seen"]), False
    if row["work"] and "name" in f and f.get("name_source") in fleet_work.PROMPT_NAME_SOURCES:
        return "work-refused", "a work row never holds a name taken from a prompt", False
    _merge_fields(row, f, entry["event"], entry["as"], now)
    _write_row(con, row)
    if f.get("observed"):
        _keep_observed(con, sid, entry["as"], f["observed"])
    return "applied", "", True


def truth_of(con, sid):
    row = get_row(con, sid)
    if row is None:
        return None
    return {"owner": row["owner"], "epoch": row["epoch"], "conversation": row["conversation"],
            "head": head_of(con, sid), "work": row["work"]}


def apply_batch(con, batch, *, hub, machines, now=None):
    """Apply a journal batch in one transaction, entries in seq order; returns the journal_reply."""
    now = time.time() if now is None else now
    machines = set(machines or ()) | {hub}
    m = batch.get("machine") if isinstance(batch, dict) else None
    entries = batch.get("entries") if isinstance(batch, dict) else None
    if not isinstance(m, str) or not isinstance(entries, list):
        raise Refused("bad-request", "a batch is {machine, entries}")
    good = [e for e in entries if isinstance(e, dict) and isinstance(e.get("seq"), int)
            and not isinstance(e.get("seq"), bool) and e["seq"] >= 1]
    good.sort(key=lambda e: e["seq"])
    results, changed, sids, dropped = [], [], [], []
    with _Tx(con):
        high = high_seq(con, m)
        for e in good:
            seq = e["seq"]
            if isinstance(e.get("sid"), str):
                sids.append(e["sid"])
            if seq <= high:
                results.append({"seq": seq, "outcome": "duplicate"})
                continue
            high = seq
            why = entry_problem(e, m, hub, machines)
            if why:
                outcome, ok = "invalid", False
            else:
                outcome, why, ok = _apply_one(con, e, now)
            res = {"seq": seq, "outcome": outcome}
            if why:
                res["reason"] = why
            results.append(res)
            if ok:
                changed.append(e["sid"])
            elif outcome != "duplicate":
                dropped.append("%s seq %d sid %s: %s (%s)" % (m, seq, e.get("sid"), outcome, why))
        if m in machines and high > high_seq(con, m):
            _set_high(con, m, high)
        rows = {}
        for sid in dict.fromkeys(sids):
            if isinstance(sid, str):
                t = truth_of(con, sid)
                if t:
                    rows[sid] = t
    for line in dropped:
        _log(con, "dropped " + line)
    _changed(con, changed)
    return {"high_seq": high_seq(con, m), "results": results, "rows": rows}


# ---------------------------------------------------------------- the legacy note (section 12.3)

def apply_legacy_note(con, note, *, machines, now=None):
    """A registry note that reached the hub through env's `note --apply`. No epoch, never replayed."""
    now = time.time() if now is None else now
    if not isinstance(note, dict):
        return None
    sid, m = note.get("sid"), note.get("machine")
    if not isinstance(sid, str) or not SID_RE.match(sid) or m not in set(machines or ()):
        return None
    with _Tx(con):
        row = get_row(con, sid)
        if row is None:
            kind = note.get("kind") if note.get("kind") in ("chat", "job") else "chat"
            row = _new_row({"sid": sid, "as": m, "machine": m, "fields": {"kind": kind}}, now)
        elif row["owner"] != m:
            return None
        for k in ("last_prompt", "last_answer"):
            if note.get(k) is not None:
                row[k] = cut(note[k], LIMITS[k])
        for k in ("cwd", "account"):
            if note.get(k) and not row.get(k):
                row[k] = cut(note[k], LIMITS[k])
        if note.get("name") and not row["name"]:
            src = note.get("name_source") if note.get("name_source") in ("custom", "prompt") else "prompt"
            row["name"], row["name_source"] = cut(note["name"], LIMITS["name"]), src
        row["updated"] = now
        _write_row(con, row)
        if "live" in note:
            _keep_observed(con, sid, m, {"live": bool(note["live"]), "observed_at": now})
    _changed(con, [sid])
    return get_row(con, sid)


# ---------------------------------------------------------------- chains (section 8)

CHAIN_FIELDS = ("name", "name_source", "kind", "topic", "rc_name", "last_prompt", "last_answer", "first_prompt",
                "description")


def chain(con, old_sid, new_sid, by, expect_epoch, fields, *, hub, now=None):
    """A Claude Voice handover, one transaction: the old row is superseded, the new one continues it."""
    now = time.time() if now is None else now
    fields = fields or {}
    if not all(isinstance(s, str) and SID_RE.match(s) for s in (old_sid, new_sid)) or old_sid == new_sid:
        raise Refused("bad-request", "a chain needs two different session ids")
    if not isinstance(by, str) or not OWNER_RE.match(by):
        raise Refused("bad-request", "%r is not an owner" % (by,))
    bad = fields_problem(fields) or next(("fields may not carry %s" % k for k in fields if k not in CHAIN_FIELDS), None)
    if bad:
        raise Refused("bad-request", bad)
    with _Tx(con):
        old = get_row(con, old_sid)
        if old is None:
            raise Refused("no-session", "session %s is not in the index" % old_sid)
        if old["superseded_by"]:
            raise Refused("superseded", "session %s was continued as %s; take %s instead"
                          % (old_sid, head_of(con, old_sid), head_of(con, old_sid)))
        if old["owner"] != by:
            raise Refused("not-owner", "session %s is owned by %s, not %s" % (old_sid, old["owner"], by))
        if old["epoch"] != expect_epoch:
            raise Refused("stale-epoch", "session %s moved meanwhile (epoch %d, expected %s); read it again"
                          % (old_sid, old["epoch"], expect_epoch))
        cur = get_row(con, new_sid)
        if cur is not None and not (cur["owner"] == by and cur["epoch"] == 1 and not cur["continues"]
                                    and not cur["superseded_by"]):
            raise Refused("exists", "session %s is already in the index" % new_sid)
        old["superseded_by"], old["ended"], old["end_reason"], old["updated"] = new_sid, now, "handover", now
        _write_row(con, old)
        new = cur or _new_row({"sid": new_sid, "as": by, "machine": old["machine"], "fields": {}}, now)
        new.update(continues=old_sid, conversation=old["conversation"], owner=by, epoch=1, env=old["env"],
                   machine=old["machine"], cwd=old["cwd"], work=old["work"], updated=now, ended=None,
                   end_reason=None)
        if cur is None:
            new["owner_since"] = now
        if fields.get("kind") in KINDS and (fields["kind"] != "voice" or by.startswith("phone:")):
            new["kind"] = fields["kind"]
        _merge_name(new, fields)
        for k in ("topic", "rc_name", "last_prompt", "last_answer", "first_prompt", "description"):
            if k in fields:
                new[k] = cut(fields[k], LIMITS[k]) if k in LIMITS and fields[k] is not None else fields[k]
        _write_row(con, new)
    _backup_quiet(con, "%s-e1" % new_sid[:8])
    _changed(con, [old_sid, new_sid])
    return {"ok": True, "old": get_row(con, old_sid), "new": get_row(con, new_sid)}


# ---------------------------------------------------------------- rename, delete, end-host

def rename(con, sid, name, *, now=None):
    """`name_source = manual`. An empty name clears the name; the next journal name fills it again."""
    now = time.time() if now is None else now
    name = cut(name or "", LIMITS["name"]) or ""
    with _Tx(con):
        row = get_row(con, sid)
        if row is None:
            raise Refused("no-session", "session %s is not in the index" % sid)
        row["name"], row["name_source"] = (name, "manual") if name else ("", "")
        row["updated"] = now
        _write_row(con, row)
    _changed(con, [sid])
    return get_row(con, sid)


def delete_conversation(con, sid):
    """Remove every row of an ended session's conversation; refuses one that has not ended."""
    with _Tx(con):
        row = get_row(con, sid)
        if row is None:
            raise Refused("no-session", "session %s is not in the index" % sid)
        rows = [_row_dict(r) for r in con.execute("SELECT * FROM sessions WHERE conversation=?",
                                                  (row["conversation"],))]
        open_ = [r["sid"] for r in rows if r["ended"] is None]
        if open_:
            raise Refused("not-ended", "session %s has not ended; stop it first" % open_[0])
        sids = [r["sid"] for r in rows]
        con.executemany("DELETE FROM sessions WHERE sid=?", [(s,) for s in sids])
        con.executemany("DELETE FROM journal_observed WHERE sid=?", [(s,) for s in sids])
    _changed(con, sids)
    return sids


def end_host(con, owner, *, now=None):
    """End every open row a Claude Voice sandbox server holds (`end_reason = sandbox-down`)."""
    now = time.time() if now is None else now
    if not isinstance(owner, str) or not owner.startswith("phone:dev:") or not OWNER_RE.match(owner):
        raise Refused("bad-request", "end-host ends only a Claude Voice sandbox's rows (phone:dev:<sandbox>)")
    with _Tx(con):
        sids = [r[0] for r in con.execute("SELECT sid FROM sessions WHERE owner=? AND ended IS NULL", (owner,))]
        con.executemany("UPDATE sessions SET ended=?, end_reason='sandbox-down', updated=? WHERE sid=?",
                        [(now, now, s) for s in sids])
    _changed(con, sids)
    return sids


# ---------------------------------------------------------------- import and rebuild (section 11)

def _normal_row(row, now):
    """A whole row from an imported or cached one: missing fields take their defaults, a work row is masked."""
    out = {k: row.get(k) for k in FIELDS}
    out["conversation"] = out["conversation"] or out["sid"]
    out["name"] = cut(out["name"] or "", LIMITS["name"]) or ""
    out["name_source"] = out["name_source"] if out["name_source"] in NAME_RANK else ("prompt" if out["name"] else "")
    out["kind"] = out["kind"] if out["kind"] in KINDS else "chat"
    out["env"] = out["env"] or "prod"
    out["epoch"] = int(out["epoch"] or 1)
    out["owner_since"] = out["owner_since"] or now
    out["started"] = out["started"] or out["owner_since"]
    out["updated"] = out["updated"] or out["owner_since"]
    out["work"] = bool(out["work"])
    for k, n in LIMITS.items():
        if k != "name" and out.get(k) is not None:
            out[k] = cut(out[k], n)
    if out["work"]:
        for k in fleet_work.FORBIDDEN:
            out[k] = None
        if out["name_source"] in fleet_work.PROMPT_NAME_SOURCES:
            out["name"], out["name_source"] = "", ""
    return out


def import_row(con, row, *, origin):
    """Put an imported row in: "new", "same", "updated" or "conflict-kept". The higher epoch wins."""
    now = time.time()
    new = _normal_row(row, now)
    if not SID_RE.match(new["sid"] or "") or not OWNER_RE.match(new["owner"] or ""):
        raise Refused("bad-request", "an imported row needs a session id and an owner")
    with _Tx(con):
        cur = get_row(con, new["sid"])
        if cur is None:
            _write_row(con, new)
            outcome = "new"
        elif new["epoch"] > cur["epoch"]:
            _write_row(con, new)
            outcome = "updated"
        elif new["epoch"] < cur["epoch"]:
            outcome = "conflict-kept"
        else:
            filled = dict(cur)
            for k in FIELDS:
                if filled.get(k) in (None, "") and new.get(k) not in (None, "") and k not in ("owner", "epoch"):
                    filled[k] = new[k]
            if filled != cur:
                _write_row(con, filled)
                outcome = "updated"
            elif {k: new[k] for k in ("owner", "machine")} != {k: cur[k] for k in ("owner", "machine")}:
                outcome = "conflict-kept"
            else:
                outcome = "same"
    if outcome == "conflict-kept":
        _log(con, "import from %s: %s kept the hub's row (epoch %d)" % (origin, new["sid"], cur["epoch"]))
    return outcome  # no change callbacks: an import writes no registry file (the importer seeds the shim's state)


def rebuild(con, dumps, *, now=None, dry_run=False):
    """Make the index again from every machine's cache dump: per sid the row with the highest epoch (on a tie, the
    one its owner's machine holds); each machine's high mark becomes at least the acked_seq it reports."""
    now = time.time() if now is None else now
    best, report = {}, {"machines": {}, "rows": 0, "written": 0, "conflicts": 0, "backup": None}
    for m in sorted(dumps):
        d = dumps[m] or {}
        rows = [r for r in d.get("rows") or [] if isinstance(r, dict) and SID_RE.match(str(r.get("sid") or ""))]
        rep = {"rows": len(rows), "conflicts": 0, "acked_seq": int(d.get("acked_seq") or 0)}
        report["machines"][m] = rep
        for r in rows:
            key = (int(r.get("epoch") or 1), 1 if r.get("owner") == m else 0)
            have = best.get(r["sid"])
            if have is not None:
                rep["conflicts"] += 1
                report["conflicts"] += 1
            if have is None or key > have[0]:
                best[r["sid"]] = (key, m, r)
    report["rows"] = len(best)
    if dry_run:
        for sid, (_, m, r) in best.items():
            cur = get_row(con, sid)
            if cur is None or int(r.get("epoch") or 1) >= cur["epoch"]:
                report["written"] += 1
        return report
    report["backup"] = _backup_quiet(con, "rebuild")
    written = []
    with _Tx(con):
        for sid, (_, m, r) in best.items():
            cur = get_row(con, sid)
            new = _normal_row(r, now)
            if cur is None or new["epoch"] > cur["epoch"] or (new["epoch"] == cur["epoch"] and new != cur
                                                                and cur["owner"] == new["owner"]):
                if cur is not None and new["epoch"] == cur["epoch"]:
                    new = dict(cur, **{k: v for k, v in new.items() if v not in (None, "")})
                _write_row(con, new)
                written.append(sid)
        for m, d in dumps.items():
            acked = int((d or {}).get("acked_seq") or 0)
            if acked > high_seq(con, m):
                _set_high(con, m, acked)
    report["written"] = len(written)
    _changed(con, written)
    return report
