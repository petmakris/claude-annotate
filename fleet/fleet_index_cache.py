"""The cache: one file per session on every machine (`$FLEET_HOME/index/cache/<sid>.json`), holding the row as
this machine last knew it. The status line reads only `.owner` of it; the owner guard falls back to it when the hub
does not answer. On the writing machine a work row's file may hold the whole row: it never leaves, and `dump`
masks it before it does. Contract: `fleet/docs/session-index.md`, section 14. Stdlib only, no fleet imports.
"""
import json
import os
import re
import time

import fleet_work

SID_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]{0,127}$")
ROW_KEYS = ("sid", "conversation", "owner", "epoch", "owner_since", "name", "name_source", "kind", "env", "machine",
            "work", "superseded_by", "cwd", "account", "continues", "first_prompt", "last_prompt", "last_answer",
            "topic", "rc_name", "started", "updated", "ended", "end_reason", "description")
REQUIRED = ("sid", "conversation", "owner", "epoch", "owner_since", "name", "name_source", "kind", "env", "machine",
            "work", "superseded_by")


def _index_dir(fleet_home):
    d = os.path.join(fleet_home, "index")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def cache_dir(fleet_home):
    d = os.path.join(_index_dir(fleet_home), "cache")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _path(fleet_home, sid):
    if not isinstance(sid, str) or not SID_RE.match(sid):
        raise ValueError("%r is not a session id" % (sid,))
    return os.path.join(cache_dir(fleet_home), sid + ".json")


def read(fleet_home, sid):
    try:
        with open(_path(fleet_home, sid)) as f:
            row = json.load(f)
    except (OSError, ValueError):
        return None
    return row if isinstance(row, dict) and row.get("sid") == sid else None


def _atomic(path, data):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def write(fleet_home, row, *, source):
    """Write one row (the keys of `cache_row`), plus `cached_at` and `source` (`hub` or `local`)."""
    out = {"v": 1}
    for k in ROW_KEYS:
        if k in row:
            out[k] = row[k]
    out.setdefault("conversation", out.get("sid"))
    out.setdefault("name", "")
    out.setdefault("name_source", "")
    out.setdefault("kind", "chat")
    out.setdefault("env", "prod")
    out.setdefault("work", False)
    out.setdefault("superseded_by", None)
    out.setdefault("owner_since", out.get("started") or time.time())
    missing = [k for k in REQUIRED if out.get(k) is None and k != "superseded_by"]
    if missing:
        raise ValueError("a cache row needs %s" % ", ".join(missing))
    out["cached_at"] = time.time()
    out["source"] = source
    _atomic(_path(fleet_home, out["sid"]), out)
    return out


def write_truth(fleet_home, rows):
    """The truth from the hub: the `rows` of a journal reply ({sid: {owner, epoch, conversation, head, work}}),
    or whole rows (a list, from a take, `_cache-put` or a rebuild). Descriptive fields this machine holds stay."""
    if isinstance(rows, dict):
        for sid, t in rows.items():
            if not isinstance(t, dict) or not SID_RE.match(str(sid)):
                continue
            cur = read(fleet_home, sid) or {"sid": sid, "machine": t.get("owner") if not str(t.get("owner", "")).startswith("phone:") else "self"}
            cur = dict(cur)
            changed_owner = cur.get("owner") != t.get("owner") or cur.get("epoch") != t.get("epoch")
            cur.update(owner=t["owner"], epoch=t["epoch"], conversation=t.get("conversation") or sid,
                       work=bool(t.get("work", cur.get("work", False))))
            if changed_owner:
                cur["owner_since"] = cur.get("owner_since") or time.time()
            head = t.get("head") or sid
            if head != sid:
                cur["superseded_by"] = cur.get("superseded_by") or head
            else:
                cur["superseded_by"] = None
            write(fleet_home, cur, source="hub")
        return
    for row in rows or ():
        if isinstance(row, dict) and SID_RE.match(str(row.get("sid") or "")):
            cur = read(fleet_home, row["sid"]) or {}
            merged = dict(cur)
            merged.update({k: v for k, v in row.items() if k in ROW_KEYS})
            if cur.get("work") and not row.get("work"):
                merged["work"] = True
            write(fleet_home, merged, source="hub")


def all_rows(fleet_home):
    out = []
    d = cache_dir(fleet_home)
    for name in sorted(os.listdir(d)):
        if name.endswith(".json"):
            row = read(fleet_home, name[:-5])
            if row:
                out.append(row)
    return out


def masked(row):
    """A cache row as it may leave its machine: a work row loses its words."""
    if not row.get("work"):
        return dict(row)
    out = dict(row)
    for k in fleet_work.FORBIDDEN:
        if k in out:
            out[k] = None
    if out.get("name_source") not in fleet_work.NAME_SOURCES_NOT_FROM_PROMPT:
        out["name"], out["name_source"] = "", ""
    return out


def acked_seq(fleet_home):
    try:
        with open(os.path.join(fleet_home, "index", "journal.state.json")) as f:
            return int(json.load(f).get("acked_seq") or 0)
    except (OSError, ValueError, AttributeError, TypeError):
        return 0


def dump(fleet_home):
    """{"rows": every cache row, work rows masked, "acked_seq": n}: what a rebuild reads from this machine."""
    return {"rows": [masked(r) for r in all_rows(fleet_home)], "acked_seq": acked_seq(fleet_home)}
