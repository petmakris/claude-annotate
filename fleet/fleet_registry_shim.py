"""The registry shim: the old registry files, written on the hub as a view of the session index (phase 1).

Contract: fleet/docs/session-index.md, section 12. Until phase 3, Claude Voice in Production and old machines read
`~/.local/state/claude-sessions/<sid>.json` (`$CLAUDE_SESSIONS_DIR`). On the hub this module writes those files
from the index after every change, and reads Claude Voice's own patches back into the index when a file changes.

One writer per field of a file:

- On a `phone:*` row, `topic`, `last_prompt`, `last_answer`, `updated` and `live` are Claude Voice's. The shim never
  writes them into a file that exists. When the file's size or change time differs from what the shim last saw, it
  reads the file and journals those values into the index as the row's owner (`ingest_phone_rows`).
- Every other field, and every field of any other row, is the shim's. It merges into the file: it starts from the
  file's content and writes only a field whose index value differs from what it last wrote (`shim-state.json`).
- `owner`, `owner_since`, `epoch`, `machine` and `cwd` always follow the index. A file that disagrees on one of
  them is written again at once.

No timer: `after_change` runs as the store's `on_change` callback, `ingest_phone_rows` as its `before_read` callback.
A file is never deleted. Stdlib only, Python 3.9+. The store, the journal and the hub's name are read through the
contract's public functions (`fleet_index_store`, `fleet_index_journal`), imported when first needed.
"""
import contextlib
import datetime
import fcntl
import json
import os
import socket
import threading
import time

VERSION = 1
LINE_MAX = 200
NAME_MAX = 60
# The fields of a registry file, in the order env writes them.
FIELDS = ("version", "sid", "name", "machine", "account", "cwd", "last_prompt", "last_answer", "updated", "live",
          "owner", "owner_since", "epoch", "kind", "topic")
# Claude Voice writes these into the file of a session a phone owns.
VOICE_FIELDS = ("topic", "last_prompt", "last_answer", "updated", "live")
# Of those, the ones the index keeps (`live` is an observed fact, `updated` the hub's own clock).
VOICE_INDEX_FIELDS = ("topic", "last_prompt", "last_answer")
# The index always wins on these: a file that disagrees is written again.
INDEX_WINS = ("owner", "owner_since", "epoch", "machine", "cwd")
# A registry `name` follows the index only for these sources; for the others the file keeps its own name.
FILE_NAME_SOURCES = ("manual", "custom", "registry", "prompt")

_lock = threading.RLock()
_depth = threading.local()
_busy = threading.local()


# ---------------------------------------------------------------- where things are

def fleet_home():
    return os.environ.get("FLEET_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "fleet")


def registry_dir():
    """$CLAUDE_SESSIONS_DIR, else ~/.local/state/claude-sessions (env's `_core.registry_dir`)."""
    return os.environ.get("CLAUDE_SESSIONS_DIR") or os.path.join(os.path.expanduser("~"), ".local", "state",
                                                                 "claude-sessions")


def index_dir(home=None):
    return os.path.join(home or fleet_home(), "index")


def state_path(home=None):
    return os.path.join(index_dir(home), "shim-state.json")


def record_path(sid):
    return os.path.join(registry_dir(), sid + ".json")


def machines_config(home=None):
    try:
        with open(os.path.join(home or fleet_home(), "machines.json")) as f:
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


# ---------------------------------------------------------------- text and time, as the registry writes them

def cut(text, n):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def iso(t):
    """Epoch seconds as ISO 8601 with the local offset, to the second (env's `_core.iso`)."""
    if t is None:
        return ""
    return datetime.datetime.fromtimestamp(float(t)).astimezone().isoformat(timespec="seconds")


def parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- the state: what the shim last wrote and saw

@contextlib.contextmanager
def locked(home=None):
    """One writer of files and state at a time, across processes (flock) and threads (an RLock). Re-entrant."""
    with _lock:
        depth = getattr(_depth, "n", 0)
        fh = None
        if depth == 0:
            os.makedirs(index_dir(home), mode=0o700, exist_ok=True)
            fh = open(os.path.join(index_dir(home), "shim.lock"), "a")
            fcntl.flock(fh, fcntl.LOCK_EX)
        _depth.n = depth + 1
        try:
            yield
        finally:
            _depth.n = depth
            if fh is not None:
                fcntl.flock(fh, fcntl.LOCK_UN)
                fh.close()


def load_state(home=None):
    try:
        with open(state_path(home)) as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        data = {"v": 1, "files": {}}
    return data


def save_state(state, home=None):
    os.makedirs(index_dir(home), mode=0o700, exist_ok=True)
    path = state_path(home)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def file_stamp(path):
    """(size, change time in ns) of a file, or None when it is missing."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def read_file(path):
    try:
        with open(path) as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def write_file(path, rec):
    """Atomically, by rename (temp file and os.replace), as env writes it, so a half file never shows."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(rec, f, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- an index row as a registry record

def holds_file(row):
    """Whether the registry would hold this row: chat or job, prod, not work, named, a chain head."""
    return bool(row) and row.get("kind") in ("chat", "job") and row.get("env") == "prod" and not row.get("work") \
        and bool(row.get("name")) and not row.get("superseded_by")


def is_phone(row):
    return str((row or {}).get("owner") or "").startswith("phone:")


def index_values(row):
    """Each registry field as the index gives it. `name` is None when the index leaves the file's name alone."""
    name = row.get("name") if row.get("name_source") in FILE_NAME_SOURCES else None
    topic = row.get("topic")
    return {
        "version": VERSION,
        "sid": row["sid"],
        "name": cut(name, NAME_MAX) if name and row.get("name_source") == "prompt" else name,
        "machine": row.get("machine") or "",
        "account": row.get("account") or "",
        "cwd": row.get("cwd") or "",
        "last_prompt": cut(row.get("last_prompt"), LINE_MAX),
        "last_answer": cut(row.get("last_answer"), LINE_MAX),
        "updated": iso(row.get("updated")),
        "live": row.get("ended") is None,
        "owner": row.get("owner"),
        "owner_since": iso(row.get("owner_since")),
        "epoch": row.get("epoch"),
        "kind": row.get("kind") if row.get("kind") in ("chat", "job") else "chat",
        "topic": dict(topic) if isinstance(topic, dict) else None,
    }


def registry_record(row, existing=None, written=None):
    """The file for `row`. `existing` is the file's content (None for a new file), `written` what the shim last
    wrote into it (field -> value). Merges: a field is written only when its index value differs from what the
    shim last wrote (or, never written, from the file), and never a Claude Voice field of a phone row's file."""
    want = index_values(row)
    if existing is None:
        rec = {}
        for f in FIELDS:
            rec[f] = want[f]
        if rec["name"] is None:
            rec["name"] = cut(row.get("first_prompt") or row.get("name"), NAME_MAX)
        return rec
    written = written or {}
    phone = is_phone(row)
    rec = dict(existing)
    for f in FIELDS:
        v = want[f]
        if f == "name" and v is None:
            continue
        if phone and f in VOICE_FIELDS:
            continue
        if f in INDEX_WINS or f in ("version", "sid"):
            if existing.get(f) != v:
                rec[f] = v
            continue
        last = written[f] if f in written else existing.get(f)
        if last != v:
            rec[f] = v
    return rec


# ---------------------------------------------------------------- the store, the journal (contract modules)

def _store():
    import fleet_index_store
    return fleet_index_store


def _journal():
    import fleet_index_journal
    return fleet_index_journal


def journal_phone_patch(con, row, fields, observed=None, home=None):
    """Claude Voice's patch into the index: one journal entry written as the row's owner from the hub machine,
    at the row's epoch, flushed in process (contract sections 5.3 and 12.3). The store merges it and runs its
    change callbacks. Returns the journal reply, or None when the entry was dropped."""
    home = home or fleet_home()
    hub = hub_name(home)
    machines = machine_names(home)
    fields = dict(fields)
    if observed:
        fields["observed"] = observed
    event = "stop" if ("last_prompt" in fields or "last_answer" in fields) else "observe"
    if event == "observe" and "observed" not in fields:
        fields["observed"] = {"observed_at": time.time()}
    journal = _journal()
    journal.append(home, hub, row["sid"], event, fields, as_owner=row["owner"], epoch_seen=row["epoch"])
    store = _store()
    return journal.flush(home, hub, lambda batch: store.apply_batch(con, batch, hub=hub, machines=machines))


# ---------------------------------------------------------------- the callbacks

def _ingest_one(con, row, rec, home):
    """Takes Claude Voice's fields of a phone row's file into the index. True when anything was taken."""
    fields = {}
    for f in VOICE_INDEX_FIELDS:
        if f not in rec:
            continue
        v = rec.get(f)
        if f == "topic":
            v = v if isinstance(v, dict) and v.get("host") and v.get("id") else None
            v = {"host": str(v["host"]), "id": str(v["id"])} if v else None
        else:
            v = cut(v, LINE_MAX) if isinstance(v, str) else None
        if v != row.get(f):
            fields[f] = v
    observed = None
    if isinstance(rec.get("live"), bool):
        observed = {"live": rec["live"], "state": "running" if rec["live"] else "idle", "where": "phone",
                    "observed_at": time.time()}
    if not fields:
        return False
    journal_phone_patch(con, row, fields, observed=observed, home=home)
    return True


def _write_one(con, sid, state, home):
    store = _store()
    row = store.get_row(con, sid)
    if not holds_file(row):
        return False
    path = record_path(sid)
    entry = state["files"].get(sid) or {}
    existing = read_file(path)
    stamp = file_stamp(path)
    if existing is not None and is_phone(row) and stamp != entry.get("stamp"):
        entry["stamp"] = stamp
        state["files"][sid] = entry
        if _ingest_one(con, row, existing, home):
            row = store.get_row(con, sid) or row
    rec = registry_record(row, existing, entry.get("fields"))
    if rec == existing:
        return False
    write_file(path, rec)
    written = dict(entry.get("fields") or {})
    for f in FIELDS:
        if existing is None or rec.get(f) != existing.get(f):
            written[f] = rec.get(f)
    state["files"][sid] = {"fields": written, "stamp": file_stamp(path)}
    return True


def after_change(con, sids):
    """The store's `on_change` callback: writes the registry file of every changed sid that the registry would hold,
    merging into it. Never raises: a problem is logged to hooks.log and the next change catches up."""
    home = fleet_home()
    busy = getattr(_busy, "sids", None)
    if busy is None:
        busy = _busy.sids = set()
    todo = [s for s in dict.fromkeys(sids or ()) if s and s not in busy]
    if not todo:
        return
    try:
        with locked(home):
            state = load_state(home)
            for sid in todo:
                busy.add(sid)
                try:
                    _write_one(con, sid, state, home)
                finally:
                    busy.discard(sid)
            save_state(state, home)
    except Exception as e:  # a callback never breaks the change that ran it
        log(home, "registry shim: %s: %s" % (type(e).__name__, e))


def ingest_phone_rows(con):
    """The store's `before_read` callback: every registry file whose size or change time differs from what the shim
    last saw is read; a phone row's Claude Voice fields go into the index. A file that disagrees with the index on
    owner, epoch, machine or folder is written again. Returns how many rows took a patch."""
    home = fleet_home()
    taken = 0
    try:
        names = os.listdir(registry_dir())
    except OSError:
        return 0
    try:
        with locked(home):
            state = load_state(home)
            store = _store()
            changed = []
            for n in names:
                if not n.endswith(".json"):
                    continue
                sid = n[:-5]
                path = os.path.join(registry_dir(), n)
                entry = state["files"].get(sid) or {}
                stamp = file_stamp(path)
                if stamp is None or stamp == entry.get("stamp"):
                    continue
                entry["stamp"] = stamp
                state["files"][sid] = entry
                row = store.get_row(con, sid)
                rec = read_file(path)
                if not holds_file(row) or rec is None or not is_phone(row):
                    continue  # env's own writes on the hub go through its dual write, never read back here
                _busy.sids = getattr(_busy, "sids", None) or set()
                _busy.sids.add(sid)
                try:
                    if _ingest_one(con, row, rec, home):
                        taken += 1
                finally:
                    _busy.sids.discard(sid)
                changed.append(sid)
            for sid in changed:
                _write_one(con, sid, state, home)
            save_state(state, home)
    except Exception as e:
        log(home, "registry shim: %s: %s" % (type(e).__name__, e))
    return taken


def seed(records, home=None):
    """Seeds shim-state with each imported file's own values, so an import writes no file: the shim later writes a
    field only when the index's value moves away from what the file held. A file already tracked is left as it is."""
    home = home or fleet_home()
    with locked(home):
        state = load_state(home)
        for rec in records or ():
            sid = rec.get("sid") if isinstance(rec, dict) else None
            if not sid or sid in state["files"]:
                continue  # a file the shim already tracks keeps its stamp, so a patch since then is still read in
            state["files"][sid] = {"fields": {f: rec[f] for f in FIELDS if f in rec},
                                   "stamp": file_stamp(record_path(sid))}
        save_state(state, home)


def register(store=None):
    """Registers the two callbacks with the store (the hub's `open_hub` may call this)."""
    store = store or _store()
    store.on_change(after_change)
    store.before_read(ingest_phone_rows)


def log(home, line):
    try:
        os.makedirs(home, exist_ok=True)
        fd = os.open(os.path.join(home, "hooks.log"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%dT%H:%M:%S"), line))
    except OSError:
        pass
