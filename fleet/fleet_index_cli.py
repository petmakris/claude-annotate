"""`fleet session <verb>`: the session index's CLI and the hub client.

On the hub every call runs in process on `$FLEET_HOME/index/hub.db`; on any other machine it runs on the hub over
ssh as `fleet_index_cli.py _hub OP` (JSON on stdin), with `BatchMode=yes` and `ConnectTimeout=3`. When the hub does
not answer, a take fails with exactly one line (`HUB_DOWN`) and exit 3; journal entries stay in this machine's
journal until the next write or session start sends them. Contract: `fleet/docs/session-index.md`, section 13.

Stdlib only, Python 3.9+. This module and `fleet_sessions_api` are the only ones that import `fleet`, and only
inside functions.
"""
import argparse
import datetime
import json
import os
import posixpath
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import fleet_index_cache as cache  # noqa: E402
import fleet_index_journal as journal  # noqa: E402
import fleet_index_parse as parse  # noqa: E402
import fleet_index_store as store  # noqa: E402
import fleet_work  # noqa: E402

HubDown = journal.HubDown
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=3"]
TAKE_TIMEOUT = 30
OWNER_TIMEOUT = 2.0


class Unreachable(Exception):
    pass


# ---------------------------------------------------------------- machines

def _home(fleet_home=None):
    return fleet_home or os.environ.get("FLEET_HOME") or os.path.join(os.path.expanduser("~"), ".claude", "fleet")


def _conf(fleet_home=None):
    try:
        with open(os.path.join(_home(fleet_home), "machines.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def self_name(fleet_home=None):
    name = _conf(fleet_home).get("self")
    return name if isinstance(name, str) and name else socket.gethostname().split(".")[0]


def hub_name(fleet_home=None):
    hub = _conf(fleet_home).get("hub")
    return hub if isinstance(hub, str) and hub else self_name(fleet_home)


def machine_names(fleet_home=None):
    """`self`, this machine's name and every machine of machines.json: the one source of machine names."""
    conf = _conf(fleet_home)
    return {"self", self_name(fleet_home)} | {k for k, v in conf.items() if isinstance(v, dict)}


def is_hub(fleet_home=None):
    return hub_name(fleet_home) == self_name(fleet_home)


def _local(machine, fleet_home=None):
    return machine in ("self", self_name(fleet_home))


_HUBS = {}


def open_hub(fleet_home=None):
    """The hub's store, one connection per path in this process."""
    path = store.hub_db_path(_home(fleet_home))
    con = _HUBS.get(path)
    if con is None:
        con = store.connect(path)
        _HUBS[path] = con
    return con


# ---------------------------------------------------------------- ssh

def _remote_command(entry, args):
    import fleet
    m = {"python": entry.get("python") or "python3", "env": entry.get("env") if isinstance(entry.get("env"), dict) else {},
         "fleet": posixpath.join(posixpath.dirname(entry["fleet"]), "fleet_index_cli.py")}
    return fleet.remote_command(m, args)


def run_on(machine, args, *, stdin=None, timeout=8, fleet_home=None):
    """Run `fleet_index_cli.py <args>` on another machine; returns (exit code, stdout, stderr). Raises Unreachable
    when ssh cannot reach it or it takes longer than `timeout`."""
    entry = _conf(fleet_home).get(machine)
    if not isinstance(entry, dict) or not entry.get("ssh") or not entry.get("fleet"):
        raise Unreachable("no machine named %r in machines.json" % machine)
    cmd = [os.environ.get("FLEET_SSH") or "ssh"] + SSH_OPTS + ["--", entry["ssh"], _remote_command(entry, args)]
    env = dict(os.environ)
    if fleet_home:
        env["FLEET_HOME"] = fleet_home
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise Unreachable("%s timed out" % machine)
    except (OSError, subprocess.SubprocessError) as e:
        raise Unreachable("%s: %s" % (machine, e))
    if r.returncode == 255:
        lines = (r.stderr or "").strip().splitlines()
        raise Unreachable("%s: %s" % (machine, lines[-1] if lines else "ssh failed"))
    return r.returncode, r.stdout, r.stderr


def _json_end(out):
    import fleet
    try:
        return fleet.parse_remote_json(out)
    except fleet.RemoteError as e:
        raise Unreachable(str(e))


# ---------------------------------------------------------------- the hub's operations

def _query(payload):
    p = payload or {}
    kinds = p.get("kind")
    if isinstance(kinds, str):
        kinds = None if kinds in ("", "all") else [k.strip() for k in kinds.split(",") if k.strip()]
    limit = p.get("limit")
    try:
        limit = int(limit) if limit not in (None, "") else 300
    except (TypeError, ValueError):
        limit = 300
    return {"env": p.get("env") or "prod", "chains": p.get("chains") or "heads", "kinds": kinds,
            "machine": p.get("machine") or None, "owner": p.get("owner") or None, "q": p.get("q") or None,
            "limit": limit}


def hub_rows(query, fleet_home=None):
    """On the hub: the rows."""
    con = open_hub(fleet_home)
    return store.list_rows(con, **_query(query))


def basic_envelope(query, fleet_home=None):
    """A sessions_reply from the hub's rows alone, with observed facts as the journal carried them."""
    con = open_hub(fleet_home)
    q = _query(query)
    rows = store.list_rows(con, **q)
    hidden = con.execute("SELECT COUNT(*) FROM sessions WHERE env != 'prod'").fetchone()[0] if q["env"] == "prod" else 0
    sup = con.execute("SELECT COUNT(*) FROM sessions WHERE superseded_by IS NOT NULL").fetchone()[0] \
        if q["chains"] != "all" else 0
    now = time.time()
    me = self_name(fleet_home)
    return {"v": 1, "index": "up", "hub": me, "as_of": now,
            "machines": {me: {"reachable": True, "as_of": now, "stale": False, "reason": ""}},
            "counts": {"rows": len(rows), "hidden_dev": hidden, "superseded": sup}, "rows": rows}


def envelope(query, fleet_home=None):
    try:
        import fleet_sessions_api as api
    except ImportError:
        return basic_envelope(query, fleet_home)
    return api.envelope(query)


def _put_caches(row, previous_owner, fleet_home):
    """After a take: write the new row into the caches of the old owner's and the new owner's machines (5 s to
    connect, best effort). A cache that missed it learns the truth from its next journal reply."""
    hub = self_name(fleet_home)
    targets = []
    for o in (previous_owner, row["owner"]):
        m = hub if o.startswith("phone:") else o
        if m not in targets:
            targets.append(m)
    for m in targets:
        try:
            if _local(m, fleet_home):
                cache.write_truth(_home(fleet_home), [row])
            else:
                run_on(m, ["_cache-put"], stdin=json.dumps([row]), timeout=8, fleet_home=fleet_home)
        except (Unreachable, OSError, ValueError) as e:
            journal_log(fleet_home, "take %s: the cache on %s was not written (%s)" % (row["sid"], m, e))


def journal_log(fleet_home, text):
    try:
        path = os.path.join(_home(fleet_home), "hooks.log")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write("%s index: %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def hub_op(op, payload, fleet_home=None):
    """Run one hub operation here (this machine must be the hub). A refusal is a reply with ok false."""
    con = open_hub(fleet_home)
    hub = self_name(fleet_home)
    machines = machine_names(fleet_home)
    p = payload if isinstance(payload, dict) else {}
    try:
        if op == "apply":
            return store.apply_batch(con, p, hub=hub, machines=machines)
        if op == "take":
            reply = store.take(con, p.get("sid"), p.get("to"), p.get("expect_epoch"), p.get("by") or hub, hub=hub,
                               machines=machines, cwd=p.get("cwd"), release=p.get("release"))
            if reply.get("previous_owner") != reply.get("owner"):
                _put_caches(store.get_row(con, reply["sid"]), reply["previous_owner"], fleet_home)
            return reply
        if op == "chain":
            return store.chain(con, p.get("old_sid"), p.get("new_sid"), p.get("by"), p.get("expect_epoch"),
                               p.get("fields") or {}, hub=hub)
        if op == "owner":
            row = store.get_row(con, p.get("sid") or "")
            if row is None:
                raise store.Refused("no-session", "session %s is not in the index" % p.get("sid"))
            return {"sid": row["sid"], "owner": row["owner"], "epoch": row["epoch"],
                    "head": store.head_of(con, row["sid"]), "source": "hub", "stale": False,
                    "_truth": store.truth_of(con, row["sid"])}
        if op == "list":
            return envelope(p, fleet_home)
        if op == "show":
            row = store.get_row(con, p.get("sid") or "")
            if row is None:
                raise store.Refused("no-session", "session %s is not in the index" % p.get("sid"))
            return {"ok": True, "row": store.listed(con, row)}
        if op == "rename":
            return {"ok": True, "row": store.rename(con, p.get("sid") or "", p.get("name") or "")}
        if op == "delete":
            row = store.get_row(con, p.get("sid") or "")
            sids = store.delete_conversation(con, p.get("sid") or "")
            return {"ok": True, "deleted": sids, "machine": row["machine"] if row else None}
        if op == "end-host":
            return {"ok": True, "ended": store.end_host(con, p.get("owner"))}
        if op == "high-seq":
            return {"ok": True, "high_seq": store.high_seq(con, p.get("machine") or "")}
    except store.Refused as r:
        return r.reply()
    return {"ok": False, "code": "bad-request", "error": "unknown hub operation %r" % op}


def hub_call(op, payload, *, timeout=8, fleet_home=None):
    """A hub operation: in process on the hub, else over ssh. Raises HubDown when the hub does not answer."""
    if is_hub(fleet_home):
        return hub_op(op, payload, fleet_home)
    hub = hub_name(fleet_home)
    try:
        code, out, err = run_on(hub, ["_hub", op], stdin=json.dumps(payload), timeout=timeout, fleet_home=fleet_home)
        if code != 0:
            lines = (err or "").strip().splitlines()
            raise Unreachable("%s: %s" % (hub, lines[-1] if lines else "exit %d" % code))
        reply = _json_end(out)
    except Unreachable as e:
        raise HubDown(str(e))
    if not isinstance(reply, dict) or reply.get("code") == "not-hub":
        raise HubDown("%s does not act as the hub" % hub)
    return reply


def flush_now(fleet_home=None):
    """Send this machine's unsent journal entries to the hub. None when there was nothing or the hub is down."""
    fh = _home(fleet_home)

    def send(batch):
        reply = hub_call("apply", batch, fleet_home=fh)
        if "high_seq" not in reply:
            raise HubDown(reply.get("error") or "the hub refused the batch")
        return reply
    return journal.flush(fh, self_name(fh), send)


# ---------------------------------------------------------------- the verbs

def _out(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def _refusal(reply):
    sys.stderr.write((reply.get("error") or reply.get("code") or "refused") + "\n")
    return 2


def _hub_down(as_json=True):
    sys.stderr.write(store.HUB_DOWN + "\n")
    if as_json:
        _out({"ok": False, "code": "hub-down", "error": store.HUB_DOWN})
    return 3


def cmd_take(a):
    payload = {"sid": a.sid, "to": a.to, "expect_epoch": a.expect_epoch, "by": a.by or self_name()}
    if a.release:
        payload["release"] = a.release
    if a.cwd:
        payload["cwd"] = a.cwd
    try:
        reply = hub_call("take", payload, timeout=TAKE_TIMEOUT)
    except HubDown:
        return _hub_down(a.json)
    _out(reply)
    return 0 if reply.get("ok") else _refusal(reply)


def _read_stdin_json(default=None):
    data = sys.stdin.read()
    if not data.strip():
        return default
    return json.loads(data)


def cmd_chain(a):
    fields = _read_stdin_json({}) or {}
    payload = {"old_sid": a.old, "new_sid": a.new, "by": a.by, "expect_epoch": a.expect_epoch, "fields": fields}
    try:
        reply = hub_call("chain", payload)
    except HubDown:
        return _hub_down(a.json)
    _out(reply)
    return 0 if reply.get("ok") else _refusal(reply)


def _cache_owner(sid, now=None):
    row = cache.read(_home(), sid)
    if row is None:
        return None
    now = time.time() if now is None else now
    return {"sid": sid, "owner": row["owner"], "epoch": row["epoch"], "head": row.get("superseded_by") or sid,
            "source": "cache", "stale": now - float(row.get("cached_at") or 0) > store.STALE_AFTER}


def cmd_owner(a):
    try:
        reply = hub_call("owner", {"sid": a.sid}, timeout=a.timeout)
    except HubDown:
        reply = None
    if reply is not None and reply.get("ok") is not False:
        truth = reply.pop("_truth", None)
        if truth:
            try:
                cache.write_truth(_home(), {a.sid: truth})
            except (OSError, ValueError):
                pass
        _out(reply)
        return 0
    got = _cache_owner(a.sid)
    if got is None:
        sys.stderr.write("session %s is not in the index%s\n" % (a.sid, "" if reply else " and the hub is down"))
        return 2 if reply else 3
    if reply is not None:
        got["stale"] = True
    _out(got)
    return 0


REGISTRY_LINE_MAX = 200
REGISTRY_NAME_MAX = 60


def _registry_record(row):
    """A row in the old registry file's shape, for env's `@claude session list` (`list --registry`). No file is
    written: the index is the one store."""
    def cut(text, n):
        text = " ".join(str(text or "").split())
        return text if len(text) <= n else text[: n - 1] + "…"

    def iso(t):
        return "" if t is None else datetime.datetime.fromtimestamp(float(t)).astimezone().isoformat(
            timespec="seconds")

    src = row.get("name_source")
    name = row.get("name") if src in ("manual", "custom", "registry", "prompt") else None
    name = cut(name, REGISTRY_NAME_MAX) if name and src == "prompt" else name
    topic = row.get("topic")
    return {"version": 1, "sid": row["sid"],
            "name": name if name is not None else cut(row.get("first_prompt") or row.get("name"), REGISTRY_NAME_MAX),
            "machine": row.get("machine") or "", "account": row.get("account") or "", "cwd": row.get("cwd") or "",
            "last_prompt": cut(row.get("last_prompt"), REGISTRY_LINE_MAX),
            "last_answer": cut(row.get("last_answer"), REGISTRY_LINE_MAX), "updated": iso(row.get("updated")),
            "live": row.get("ended") is None, "owner": row.get("owner"), "owner_since": iso(row.get("owner_since")),
            "epoch": row.get("epoch"), "kind": row.get("kind") if row.get("kind") in ("chat", "job") else "chat",
            "topic": dict(topic) if isinstance(topic, dict) else None}


def list_reply(query, fleet_home=None):
    """The sessions_reply: from the hub; off the hub, the hub's answer over ssh, kept in last-list.json, and that
    copy with `index: down` and this machine's own cache rows when the hub does not answer."""
    if is_hub(fleet_home):
        return envelope(query, fleet_home)
    fh = _home(fleet_home)
    path = os.path.join(journal.index_dir(fh), "last-list.json")
    try:
        reply = hub_call("list", query, fleet_home=fh)
        if reply.get("rows") is not None:
            tmp = path + ".%d.tmp" % os.getpid()
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(reply, f)
            os.replace(tmp, path)
            return reply
        why = reply.get("error") or "the hub answered no rows"
    except HubDown as e:
        why = str(e)
    try:
        with open(path) as f:
            last = json.load(f)
    except (OSError, ValueError):
        last = {"v": 1, "hub": hub_name(fh), "as_of": None, "machines": {}, "counts": {}, "rows": []}
    me = self_name(fh)
    mine = [r for r in cache.all_rows(fh) if r.get("owner") == me]  # this machine's own rows: they stay here
    keep = [r for r in last.get("rows") or [] if r.get("owner") != me]
    for r in mine:
        row = {k: r.get(k) for k in store.FIELDS}
        row.update(observed={"live": None, "state": None, "where": None, "tmux": None, "pid": None,
                             "observed_at": None, "stale": True, "source": "none"},
                   key="%s:%s" % (r.get("machine") or me, r["sid"]), head=not r.get("superseded_by"),
                   chain=[r["sid"]])
        keep.append(row)
    last.update(index="down", reason=why, rows=keep)
    return last


def cmd_list(a):
    query = {"env": a.env, "chains": a.chains, "kind": a.kind, "machine": a.machine, "owner": a.owner, "q": a.q,
             "limit": a.limit}
    if a.stored and is_hub():
        reply = {"v": 1, "index": "up", "hub": self_name(), "as_of": time.time(), "rows": hub_rows(query)}
    elif is_hub():
        reply = envelope(query)
    else:
        try:
            import fleet_sessions_api  # noqa: F401
            reply = envelope(query)
        except ImportError:
            reply = list_reply(query)
    if a.registry:
        _out([_registry_record(r) for r in reply.get("rows") or []])
    else:
        _out(reply)
    return 0


def _show(sid):
    """The row with observed, head and chain, from the hub; None when the hub has none. Raises HubDown."""
    reply = hub_call("show", {"sid": sid})
    if reply.get("ok") is False:
        if reply.get("code") == "no-session":
            return None
        raise store.Refused(reply.get("code"), reply.get("error"))
    return reply["row"]


def cmd_show(a):
    try:
        row = _show(a.sid)
    except HubDown:
        row = cache.read(_home(), a.sid)
        if row is None:
            return _hub_down(False)
        _out(dict(row, index="down"))
        return 0
    if row is None:
        sys.stderr.write("session %s is not in the index\n" % a.sid)
        return 2
    _out(row)
    return 0


def _row_anywhere(sid):
    try:
        return _show(sid)
    except HubDown:
        return cache.read(_home(), sid)


def cmd_tail(a):
    row = _row_anywhere(a.sid)
    machine = (row or {}).get("machine") or "self"
    if row and row.get("owner", "").startswith("phone:"):
        machine = hub_name()
    if not _local(machine):
        if row and row.get("work"):
            sys.stderr.write("session %s is a work session: it is read only on its own machine\n" % a.sid)
            return 2
        try:
            code, out, err = run_on(machine, ["tail", a.sid, "--json", "--turns", str(a.turns)], timeout=30)
        except Unreachable as e:
            sys.stderr.write("%s does not answer (%s)\n" % (machine, e))
            return 3
        sys.stdout.write(out)
        sys.stderr.write(err)
        return code
    path = parse.find_transcript(a.sid)
    if not path:
        sys.stderr.write("no transcript of %s on %s\n" % (a.sid, self_name()))
        return 2
    _out({"sid": a.sid, "name": (row or {}).get("name") or "", "machine": self_name(),
          "turns": parse.turns(path, a.turns)})
    return 0


def cmd_note(a):
    try:
        note = _read_stdin_json()
    except ValueError:
        note = None
    if not isinstance(note, dict) or not isinstance(note.get("sid"), str) or note.get("event") not in store.EVENTS:
        sys.stderr.write("note reads {\"sid\", \"event\", \"fields\"} on stdin\n")
        return 2
    fields = dict(note.get("fields") or {})
    if fields.get("work") is True:
        fields = fleet_work.mask_fields(fields)
    why = store.fields_problem(fields)
    if why:
        sys.stderr.write(why + "\n")
        return 2
    entry = journal.append(_home(), self_name(), note["sid"], note["event"], fields, as_owner=a.as_owner)
    flush_now()
    _out(entry)
    return 0


def cmd_flush(a):
    if not os.path.isdir(_home()):
        return 0  # the hook's child of a FLEET_HOME that is gone (a test's temp folder): never make it again
    reply = flush_now()
    _out(reply if reply is not None else {"sent": False, "pending": len(journal.pending(_home()))})
    return 0


def _rename_here(machine, sid, name, timeout=30):
    """The rest of a rename, on the session's own machine: its fleet name and Claude Code's title (fleet.py
    `_rename-here`). Raises Unreachable."""
    import fleet
    if _local(machine):
        r = subprocess.run([sys.executable, os.path.join(HERE, "fleet.py"), "_rename-here", "--", sid] + name,
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise Unreachable((r.stderr or r.stdout).strip()[:300] or "exit %d" % r.returncode)
        return r.stdout
    try:
        return fleet.run_remote(machine, ["_rename-here", "--", sid] + name, timeout=timeout)
    except fleet.RemoteError as e:
        raise Unreachable(str(e))


def cmd_rename(a):
    name = " ".join(a.name)
    try:
        reply = hub_call("rename", {"sid": a.sid, "name": name})
    except HubDown:
        return _hub_down(False)
    if reply.get("ok") is False:
        return _refusal(reply)
    row = reply["row"]
    if a.name and not str(row.get("owner") or "").startswith("phone:"):
        try:
            _rename_here(row["machine"], row["sid"], a.name)
        except (Unreachable, subprocess.SubprocessError, OSError) as e:
            journal_log(None, "rename %s: the fleet name and title on %s were not changed (%s)"
                        % (a.sid, row["machine"], e))
    _out(row)
    return 0


def cmd_delete(a):
    try:
        reply = hub_call("delete", {"sid": a.sid})
    except HubDown:
        return _hub_down(False)
    if reply.get("ok") is False:
        return _refusal(reply)
    _out(reply)
    return 0


def _on_row_machine(a, verb, args, timeout=240):
    """Run `verb` on the machine of the row of `a.sid` when that is not this one. -> (row, exit code or None when
    the work is this machine's)."""
    row = _row_anywhere(a.sid)
    machine = (row or {}).get("machine") or "self"
    if _local(machine):
        return row, None
    try:
        code, out, err = run_on(machine, [verb, "--", a.sid] + args, timeout=timeout)
    except Unreachable as e:
        sys.stderr.write("%s does not answer (%s)\n" % (machine, e))
        return row, 3
    sys.stdout.write(out)
    sys.stderr.write(err)
    return row, code


def cmd_describe(a):
    row = _row_anywhere(a.sid)
    if row and row.get("work"):
        sys.stderr.write("session %s is a work session: it is never described\n" % a.sid)
        return 2
    row, code = _on_row_machine(a, "describe", [])
    if code is not None:
        return code
    import fleet_history as hist
    try:
        text = hist.describe_transcript(parse.find_transcript(a.sid), (row or {}).get("cwd"))
    except hist.HistoryError as e:
        sys.stderr.write("%s: %s\n" % (a.sid, e))
        return 2
    entry = journal.append(_home(), self_name(), a.sid, "describe", {"description": store.cut(text, 2000)})
    flush_now()
    _out({"sid": a.sid, "description": text, "seq": entry["seq"]})
    return 0


def cmd_ask(a):
    row, code = _on_row_machine(a, "ask", a.question)
    if code is not None:
        return code
    import fleet_history as hist
    try:
        text = hist.ask_transcript(parse.find_transcript(a.sid), (row or {}).get("cwd"), " ".join(a.question))
    except hist.HistoryError as e:
        sys.stderr.write("%s: %s\n" % (a.sid, e))
        return 2
    sys.stdout.write(text + "\n")
    return 0


def cmd_end_host(a):
    try:
        reply = hub_call("end-host", {"owner": a.owner})
    except HubDown:
        return _hub_down(False)
    _out(reply)
    return 0 if reply.get("ok") else _refusal(reply)


def cmd_rebuild(a):
    if not is_hub():
        sys.stderr.write("rebuild runs on the hub (%s)\n" % hub_name())
        return 2
    dumps, unreachable = {}, {}
    me = self_name()
    dumps[me] = cache.dump(_home())
    for m, entry in sorted(_conf().items()):
        if not isinstance(entry, dict) or m == me:
            continue
        try:
            code, out, err = run_on(m, ["_cache-dump"], timeout=30)
            if code != 0:
                raise Unreachable((err or "").strip()[-200:] or "exit %d" % code)
            dumps[m] = _json_end(out)
        except Unreachable as e:
            unreachable[m] = str(e)
    report = store.rebuild(open_hub(), dumps, dry_run=a.dry_run)
    report["unreachable"] = unreachable
    report["dry_run"] = bool(a.dry_run)
    _out(report)
    return 0


def cmd_backup(a):
    if not is_hub():
        sys.stderr.write("backup runs on the hub (%s)\n" % hub_name())
        return 2
    _out({"path": store.backup(open_hub(), label="manual")})
    return 0


def cmd_hub(a):
    if not is_hub():
        _out({"ok": False, "code": "not-hub", "error": "%s is not the hub (%s is)" % (self_name(), hub_name())})
        return 0
    try:
        payload = _read_stdin_json({}) or {}
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        _out({"ok": False, "code": "bad-request", "error": "a hub operation reads a JSON object on stdin"})
        return 0
    _out(hub_op(a.op, payload))
    return 0


def cmd_cache_put(a):
    rows = _read_stdin_json([])
    cache.write_truth(_home(), rows)
    _out({"ok": True, "n": len(rows or ())})
    return 0


def cmd_cache_dump(a):
    _out(cache.dump(_home()))
    return 0


def _importer(argv):
    try:
        import fleet_index_import as imp
    except ImportError:
        sys.stderr.write("fleet session import: the importer is not installed in this checkout yet\n")
        return 1
    return imp.main(argv)


# ---------------------------------------------------------------- argv

def parser():
    p = argparse.ArgumentParser(prog="fleet session", description="the session index")
    sub = p.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("take", help="move a session to another owner (the hub's compare-and-set)")
    s.add_argument("sid"); s.add_argument("--to", required=True); s.add_argument("--expect-epoch", type=int, required=True)
    s.add_argument("--by"); s.add_argument("--release", choices=["stopped", "phone", "gone", "none"])
    s.add_argument("--cwd"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("chain", help="a Claude Voice handover (fields as JSON on stdin)")
    s.add_argument("old"); s.add_argument("new"); s.add_argument("--by", required=True)
    s.add_argument("--expect-epoch", type=int, required=True); s.add_argument("--json", action="store_true")
    s = sub.add_parser("list", help="the sessions, as GET /api/sessions gives them")
    s.add_argument("--json", action="store_true"); s.add_argument("--env", default="prod")
    s.add_argument("--chains", default="heads"); s.add_argument("--kind"); s.add_argument("--machine")
    s.add_argument("--owner"); s.add_argument("--q"); s.add_argument("--limit", type=int, default=300)
    s.add_argument("--registry", action="store_true")
    s.add_argument("--stored", action="store_true",
                   help="on the hub: the stored rows only, without asking any machine what runs now")
    s = sub.add_parser("show"); s.add_argument("sid"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("owner"); s.add_argument("sid"); s.add_argument("--json", action="store_true")
    s.add_argument("--timeout", type=float, default=OWNER_TIMEOUT)
    s = sub.add_parser("tail"); s.add_argument("sid"); s.add_argument("--json", action="store_true")
    s.add_argument("--turns", type=int, default=20)
    s = sub.add_parser("note", help="journal one entry ({sid, event, fields} on stdin)")
    s.add_argument("--as", dest="as_owner")
    sub.add_parser("flush", help="send the unsent journal entries")
    s = sub.add_parser("rename"); s.add_argument("sid"); s.add_argument("name", nargs="*")
    s = sub.add_parser("delete"); s.add_argument("sid")
    s = sub.add_parser("describe"); s.add_argument("sid")
    s = sub.add_parser("ask"); s.add_argument("sid"); s.add_argument("question", nargs="+")
    s = sub.add_parser("end-host"); s.add_argument("owner")
    s = sub.add_parser("rebuild"); s.add_argument("--dry-run", action="store_true")
    sub.add_parser("backup")
    s = sub.add_parser("_hub"); s.add_argument("op")
    sub.add_parser("_cache-put")
    sub.add_parser("_cache-dump")
    return p


VERBS = {"take": cmd_take, "chain": cmd_chain, "list": cmd_list, "show": cmd_show, "owner": cmd_owner,
         "tail": cmd_tail, "note": cmd_note, "flush": cmd_flush, "rename": cmd_rename, "delete": cmd_delete,
         "describe": cmd_describe, "ask": cmd_ask, "end-host": cmd_end_host, "rebuild": cmd_rebuild,
         "backup": cmd_backup, "_hub": cmd_hub, "_cache-put": cmd_cache_put,
         "_cache-dump": cmd_cache_dump}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("import", "_import-dump"):
        return _importer(argv)
    a = parser().parse_args(argv)
    try:
        return VERBS[a.verb](a)
    except store.Refused as r:
        return _refusal(r.reply())


if __name__ == "__main__":
    sys.exit(main())
