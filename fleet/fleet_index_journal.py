"""The writer's journal: what this machine's sessions did, in order, until the hub has it.

`$FLEET_HOME/index/journal.jsonl` holds one entry per line, appended under `journal.lock` and flushed to disk
before anything is sent; `journal.state.json` holds `next_seq` and `acked_seq`. A flush sends every entry above
`acked_seq` in one batch. When the hub does not answer, the entries stay and nothing fails; the next append or the
next session start sends them. No timer, no poller. Contract: `fleet/docs/session-index.md`, section 5.3.
Stdlib only, no fleet imports.
"""
import fcntl
import json
import os
import time

import fleet_index_cache as cache

COMPACT_AT = 1_000_000


class HubDown(Exception):
    pass


def index_dir(fleet_home):
    d = os.path.join(fleet_home, "index")
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        if os.stat(d).st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _p(fleet_home, name):
    return os.path.join(index_dir(fleet_home), name)


class _Lock:
    def __init__(self, fleet_home, name="journal.lock", block=True):
        self.path, self.block, self.fd = _p(fleet_home, name), block, None

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | (0 if self.block else fcntl.LOCK_NB))
        except OSError:
            os.close(self.fd)
            self.fd = None
            return False
        return True

    def __exit__(self, *a):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
        return False


def _entries(fleet_home):
    out = []
    try:
        with open(_p(fleet_home, "journal.jsonl")) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and isinstance(e.get("seq"), int):
                    out.append(e)
    except OSError:
        pass
    return out


def _read_state(fleet_home):
    try:
        with open(_p(fleet_home, "journal.state.json")) as f:
            st = json.load(f)
        if isinstance(st.get("next_seq"), int) and isinstance(st.get("acked_seq"), int):
            return st
    except (OSError, ValueError, AttributeError):
        pass
    return None


def _write_state(fleet_home, st):
    path = _p(fleet_home, "journal.state.json")
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"next_seq": st["next_seq"], "acked_seq": st["acked_seq"]}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _state(fleet_home):
    """The state; when it is lost, one made from the journal and a marker that makes the next flush ask the hub
    for its high mark and renumber the unsent entries above it."""
    st = _read_state(fleet_home)
    if st is not None:
        return st
    es = _entries(fleet_home)
    st = {"next_seq": (max(e["seq"] for e in es) + 1) if es else 1, "acked_seq": 0}
    if es:
        open(_p(fleet_home, "journal.renumber"), "a").close()
    _write_state(fleet_home, st)
    return st


def _epoch_seen(fleet_home, sid, event):
    row = cache.read(fleet_home, sid)
    if row and isinstance(row.get("epoch"), int):
        return row["epoch"]
    return 1 if event == "start" else 0


def _env_of(writer):
    return "dev:" + writer[len("phone:dev:"):] if writer.startswith("phone:dev:") else "prod"


def _cache_local(fleet_home, machine, writer, entry):
    """Keep this machine's cache current from its own entry: a session it starts gets a `local` row with itself as
    owner at epoch 1; a row it knows keeps its owner and epoch and takes the entry's descriptive fields."""
    f = entry["fields"]
    row = cache.read(fleet_home, entry["sid"])
    desc = {k: f[k] for k in ("name", "name_source", "cwd", "account", "first_prompt", "last_prompt", "last_answer",
                              "topic", "rc_name", "description", "end_reason") if k in f}
    if row is None:
        if entry["event"] != "start" or entry["epoch_seen"] != 1:
            return
        row = {"sid": entry["sid"], "conversation": entry["sid"], "owner": writer, "epoch": 1,
               "owner_since": entry["at"], "name": "", "name_source": "", "kind": f.get("kind") or "chat",
               "env": _env_of(writer), "machine": machine, "work": bool(f.get("work")), "superseded_by": None,
               "started": entry["at"]}
        row.update(desc)
        cache.write(fleet_home, row, source="local")
        return
    row = dict(row)
    if "name" in desc and row.get("name_source") == "manual":
        desc.pop("name")
        desc.pop("name_source", None)
    row.update(desc)
    cache.write(fleet_home, row, source=row.get("source") or "hub")


def append(fleet_home, machine, sid, event, fields, *, as_owner=None, epoch_seen=None, at=None):
    """Append one entry, flushed to disk before anything is sent. Returns the entry."""
    writer = as_owner or machine
    with _Lock(fleet_home):
        st = _state(fleet_home)
        entry = {"v": 1, "machine": machine, "seq": st["next_seq"], "as": writer, "sid": sid,
                 "epoch_seen": _epoch_seen(fleet_home, sid, event) if epoch_seen is None else int(epoch_seen),
                 "event": event, "at": time.time() if at is None else at, "fields": dict(fields or {})}
        path = _p(fleet_home, "journal.jsonl")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        st["next_seq"] += 1
        _write_state(fleet_home, st)
        try:
            _cache_local(fleet_home, machine, writer, entry)
        except (OSError, ValueError):
            pass
    return entry


def pending(fleet_home):
    st = _read_state(fleet_home) or {"acked_seq": 0}
    return [e for e in _entries(fleet_home) if e["seq"] > st["acked_seq"]]


def _renumber(fleet_home, machine, send):
    """The state was lost: ask the hub for this machine's high mark (an empty batch) and number every entry in
    the journal above it."""
    reply = send({"machine": machine, "entries": []})
    high = int(reply.get("high_seq") or 0)
    es = _entries(fleet_home)
    for i, e in enumerate(es):
        e["seq"] = high + 1 + i
    _rewrite(fleet_home, es)
    _write_state(fleet_home, {"next_seq": high + 1 + len(es), "acked_seq": high})
    try:
        os.unlink(_p(fleet_home, "journal.renumber"))
    except OSError:
        pass


def _rewrite(fleet_home, entries):
    path = _p(fleet_home, "journal.jsonl")
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def flush(fleet_home, machine, send):
    """Send every unsent entry in one batch; `send(batch)` returns the journal_reply or raises HubDown. Returns the
    last reply, or None when nothing was sent or the hub did not answer (the entries stay)."""
    last = None
    with _Lock(fleet_home, "flush.lock"):
        for _ in range(5):
            try:
                with _Lock(fleet_home):
                    if os.path.exists(_p(fleet_home, "journal.renumber")) or _read_state(fleet_home) is None:
                        _state(fleet_home)
                        if os.path.exists(_p(fleet_home, "journal.renumber")):
                            _renumber(fleet_home, machine, send)
                    todo = pending(fleet_home)
                if not todo:
                    break
                reply = send({"machine": machine, "entries": todo})
            except HubDown:
                return last
            with _Lock(fleet_home):
                st = _state(fleet_home)
                st["acked_seq"] = max(st["acked_seq"], min(int(reply.get("high_seq") or 0), todo[-1]["seq"]))
                if st["acked_seq"] >= st["next_seq"]:
                    st["next_seq"] = st["acked_seq"] + 1
                _write_state(fleet_home, st)
                try:
                    cache.write_truth(fleet_home, reply.get("rows") or {})
                except (OSError, ValueError):
                    pass
            last = reply
        compact(fleet_home)
    return last


def compact(fleet_home, max_bytes=COMPACT_AT):
    """Past `max_bytes`, rewrite the journal without the acknowledged entries."""
    try:
        if os.path.getsize(_p(fleet_home, "journal.jsonl")) <= max_bytes:
            return
    except OSError:
        return
    with _Lock(fleet_home):
        st = _read_state(fleet_home)
        if st is None:
            return
        _rewrite(fleet_home, [e for e in _entries(fleet_home) if e["seq"] > st["acked_seq"]])
