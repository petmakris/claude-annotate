"""The one session list (`GET /api/sessions`), the observed facts it reads, and the page's session writes.

The contract is fleet/docs/session-index.md, sections 10, 13 and 15. The hub's index holds the durable facts, one
row per session id. This module reads what each session is doing now from the machine it is on, at read time, and
puts the two together. `fleet ui`, `fleet session list --json`, `fleet sessions --json` and the pick plan all read
through here, so no surface merges rows itself.

Observed facts are kept per machine in $FLEET_HOME/index/observed/<machine>.json, only as the last answer: every
row says when its values were read (`observed_at`) and is `stale` past 60 s. The server answers from the list it
has and refreshes in the background (IndexFeed); a command waits for the machines.
"""
import concurrent.futures
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import fleet_history as hist

OBSERVE_TTL = 3.0    # a machine's last answer is used as it is while younger than this
OBSERVE_TIMEOUT = 8
STALE_AFTER = 60
LIMIT = 300          # rows that are not live; live rows always come
EVERY = 10 ** 9
LIST_TIMEOUT = 30
WRITE_TIMEOUT = 240  # ask and describe are a model call on the row's own machine
PAGE_POSTS = ("/api/sessions/open", "/api/sessions/stop", "/api/sessions/rename", "/api/sessions/delete",
              "/api/sessions/ask", "/api/sessions/describe", "/api/sessions/search")
_ATTEMPTS = {}       # machine -> the reason of this process's last failed read ("" when it answered)
# The hub keeps one connection to its store in this process (fleet_index_cli.open_hub), and each write is its own
# transaction on it. The server's threads (the list, the service routes) must take turns with it.
HUB_LOCK = threading.RLock()


def _fleet():
    import fleet
    return fleet


def _cli():
    import fleet_index_cli
    return fleet_index_cli


def _cache():
    import fleet_index_cache
    return fleet_index_cache


def index_dir():
    d = os.path.join(_fleet().private_home(), "index")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _write_private(path, data):
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------- the query

def parse_query(raw=None):
    """The query of section 10.1 from a URL's parse_qs dict, a CLI's values or a plain dict -> every key set.
    `kind` is a list or None. A bad value is a ValueError that says what the key takes."""
    raw = raw or {}

    def one(key, default=None):
        v = raw.get(key)
        if isinstance(v, (list, tuple)) and key != "kind":
            v = v[0] if v else None
        return default if v is None or v == "" else v

    env = one("env", "prod")
    if env not in ("prod", "all") and not str(env).startswith("dev:"):
        raise ValueError("env takes prod, all or dev:<sandbox>")
    chains = one("chains", "heads")
    if chains not in ("heads", "all"):
        raise ValueError("chains takes heads or all")
    kind = raw.get("kind", raw.get("kinds"))
    if isinstance(kind, str):
        kind = kind.split(",")
    kinds = sorted({k.strip() for part in kind or () for k in str(part).split(",") if k.strip()})
    if "all" in kinds or not kinds:
        kinds = None
    elif set(kinds) - {"chat", "job", "worker", "voice"}:
        raise ValueError("kind takes chat, job, worker, voice, a comma list of them, or all")
    try:
        limit = int(one("limit", LIMIT))
    except (TypeError, ValueError):
        raise ValueError("limit takes a number")
    return {"env": env, "chains": chains, "kind": kinds, "machine": one("machine"), "owner": one("owner"),
            "q": one("q"), "limit": max(0, limit)}


def query_args(query):
    out = ["--env", query["env"], "--chains", query["chains"], "--limit", str(query["limit"])]
    if query["kind"]:
        out += ["--kind", ",".join(query["kind"])]
    for key in ("machine", "owner", "q"):
        if query[key]:
            out += ["--" + key, str(query[key])]
    return out


def matches(row, query):
    """Whether a durable row is in the query's view (the filters the hub's store applies, for rows that do not come
    from it: this machine's cache while the hub is down)."""
    if query["env"] != "all" and (row.get("env") or "prod") != query["env"]:
        return False
    if query["chains"] == "heads" and row.get("superseded_by"):
        return False
    if query["kind"] and row.get("kind") not in query["kind"]:
        return False
    if query["machine"] and row.get("machine") != query["machine"]:
        return False
    if query["owner"] and row.get("owner") != query["owner"]:
        return False
    if query["q"]:
        text = " ".join(str(row.get(k) or "") for k in ("name", "last_prompt", "last_answer", "cwd")).lower()
        return all(w in text for w in query["q"].lower().split())
    return True


def chain_of(rows, row):
    """The sids of `row`'s conversation among `rows`, oldest first, following `continues`."""
    same = {r["sid"]: r for r in rows if r.get("conversation") == row.get("conversation")}
    same.setdefault(row["sid"], row)
    after = {r.get("continues"): s for s, r in same.items() if r.get("continues")}
    start = next((s for s, r in sorted(same.items()) if r.get("continues") not in same), row["sid"])
    out = [start]
    while out[-1] in after and after[out[-1]] not in out:
        out.append(after[out[-1]])
    return out


def head_row(rows, sid):
    """The row that continues `sid` to the end of its chain, or None when `sid` is not among `rows`."""
    by_sid = {r["sid"]: r for r in rows}
    row, seen = by_sid.get(sid), set()
    while row and row.get("superseded_by") in by_sid and row["sid"] not in seen:
        seen.add(row["sid"])
        row = by_sid[row["superseded_by"]]
    return row


# ---------------------------------------------------------------- observed facts

def _work_test():
    """is_work(sid, folder, transcript) on this machine: the cache's word, else the one work rule."""
    f = _fleet()
    rule = f.work_rule()

    def test(sid, folder, transcript):
        try:
            row = _cache().read(f.fleet_home(), sid)
        except ImportError:
            row = None
        if row and row.get("work"):
            return True
        return bool(rule and rule(folder, transcript))
    return test


def observe_local():
    """This machine's `observe_reply`: every session a Claude process holds here, from `claude agents --json`, the
    claude tmux server and `ps`. A work session's tmux name is never given. When `claude agents --json` does not
    answer, this fails: "nothing runs here" is never guessed."""
    f = _fleet()
    agents = f.agents_list()
    if agents is None:
        raise f.FleetError("fleet: `claude agents --json` does not answer on %s." % f.self_machine())
    panes, _ = f.tmux_panes()
    parents = f.process_parents() if panes else {}
    transcripts = {r["session_id"]: r["transcript_path"] or ""
                   for r in f.db().execute("SELECT session_id, transcript_path FROM conversations")}
    is_work, rows = _work_test(), {}
    for sid, entry in f.fs.agent_index(agents).items():
        pid = entry.get("pid")
        if entry.get("kind") != "background" and not (pid and f.pid_running(pid)):
            continue
        where, tmux = f.fs.where_of(entry, True, panes, parents)
        if tmux and is_work(sid, entry.get("cwd"), transcripts.get(sid, "")):
            tmux = None
        state = str(entry.get("status") or entry.get("state") or "") or "unknown"
        rows[sid] = {"live": True, "state": state[:64], "where": where, "tmux": tmux,
                     "pid": int(pid) if pid else None}
    return {"machine": f.self_machine(), "as_of": time.time(), "rows": rows}


def _observed_path(machine):
    d = os.path.join(index_dir(), "observed")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return os.path.join(d, "".join(c if c.isalnum() or c in "_.-" else "_" for c in machine) + ".json")


def _observe_one(machine):
    """Read one machine now. -> (reply or None, reason it failed or "")."""
    f = _fleet()
    try:
        if machine == f.self_machine():
            reply = observe_local()
        else:
            reply = f.run_remote_json(machine, ["sessions", "observe", "--json"], timeout=OBSERVE_TIMEOUT, kind=dict,
                                      keys=("machine", "as_of", "rows"))
    except (f.RemoteError, f.FleetError) as e:
        return None, str(e).splitlines()[-1] if str(e) else "no answer"
    reply = {"machine": machine, "as_of": reply["as_of"], "rows": reply["rows"]}
    _write_private(_observed_path(machine), reply)
    return reply, ""


def observe_all(fresh=False):
    """Every machine's last answer, read again when older than OBSERVE_TTL (or when `fresh`), all in parallel.
    -> {machine: (reply or None, reachable, reason)}. A machine that does not answer keeps its last values."""
    f = _fleet()
    names = [f.self_machine()] + sorted(f.other_machines())
    out, ask = {}, []
    now = time.time()
    for m in names:
        kept = _read_json(_observed_path(m))
        if kept and not fresh and now - (kept.get("as_of") or 0) < OBSERVE_TTL and not _ATTEMPTS.get(m):
            out[m] = (kept, True, "")
        else:
            ask.append((m, kept))
    if ask:
        def one(m):
            with f.db_scope():
                return _observe_one(m)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ask)) as ex:
            for (m, kept), (reply, why) in zip(ask, ex.map(one, [m for m, _ in ask])):
                _ATTEMPTS[m] = why
                out[m] = (reply, True, "") if reply else (kept, False, why)
    return out


NOTHING = {"live": None, "state": None, "where": None, "tmux": None, "pid": None, "observed_at": None,
           "stale": True, "source": "none"}


def observed_for(row, seen, journal, now):
    """A row's observed facts: the newer of its machine's answer (`seen`, an observe_reply or None) and the newest
    values a journal entry carried (`journal`). A machine's answer that does not list a session says it is not
    running there, except for a phone's session, which no machine's process list can show."""
    phone = str(row.get("owner") or "").startswith("phone:")
    found = []
    if seen:
        hit = (seen.get("rows") or {}).get(row["sid"])
        if hit:
            found.append(dict(NOTHING, **hit, observed_at=seen.get("as_of"), source="machine"))
        elif not phone:
            found.append(dict(NOTHING, live=False, state="ended", where="none", observed_at=seen.get("as_of"),
                              source="machine"))
    if journal and journal.get("observed_at") is not None:
        values = {k: journal.get(k) for k in ("live", "state", "where", "tmux", "pid", "observed_at")}
        found.append(dict(NOTHING, **values, source="journal"))
    if not found:
        return dict(NOTHING)
    best = max(found, key=lambda o: o["observed_at"] or 0)
    if row.get("work"):
        best["tmux"] = None
    aged = now - (best["observed_at"] or 0) > STALE_AFTER
    best["stale"] = aged and not (phone and best["source"] == "journal")
    return best


# ---------------------------------------------------------------- the envelope

def _order(rows, limit):
    """Newest change first; at most `limit` rows that are not live, and every live one."""
    rows.sort(key=lambda r: (r.get("updated") or 0, r["sid"]), reverse=True)
    kept, quiet = [], 0
    for r in rows:
        if r["observed"]["live"] and not r["observed"]["stale"]:
            kept.append(r)
        elif quiet < limit:
            quiet += 1
            kept.append(r)
    return kept


def _listed(row, every, observed):
    out = dict(row)
    out.pop("observed", None)
    out.update(observed=observed, key="%s:%s" % (row["machine"], row["sid"]), head=not row.get("superseded_by"),
               chain=chain_of(every, row))
    return out


def _hub_rows(query):
    with HUB_LOCK:
        return _cli().hub_rows(query)


def _hub_envelope(query, fresh):
    f = _fleet()
    every = _hub_rows(dict(query, env="all", chains="all", kind=None, machine=None, owner=None, q=None, limit=EVERY))
    wanted = {r["sid"] for r in _hub_rows(dict(query, limit=EVERY))}
    seen = observe_all(fresh)
    now = time.time()
    machines = {}
    for m, (reply, reachable, why) in seen.items():
        at = reply.get("as_of") if reply else None
        machines[m] = {"reachable": reachable, "as_of": at, "stale": at is None or now - at > STALE_AFTER,
                       "reason": why}
    rows = []
    for r in every:
        if r["sid"] in wanted:
            reply = (seen.get(r["machine"]) or (None,))[0]
            rows.append(_listed(r, every, observed_for(r, reply, r.get("observed"), now)))
    rows = _order(rows, query["limit"])
    in_env = [r for r in every if query["env"] == "all" or (r.get("env") or "prod") == query["env"]]
    counts = {"rows": len(rows),
              "hidden_dev": 0 if query["env"] != "prod" else sum(
                  1 for r in every if str(r.get("env")).startswith("dev:") and not r.get("superseded_by")),
              "superseded": sum(1 for r in in_env if r.get("superseded_by")) if query["chains"] == "heads" else 0}
    return {"v": 1, "index": "up", "hub": f.hub_name(), "as_of": now, "machines": machines, "counts": counts,
            "rows": rows}


def _own_rows():
    try:
        return _cache().all_rows(_fleet().fleet_home())
    except ImportError:
        return []


def _durable(cached):
    """A cache file as a durable row: every field set, without the cache's own."""
    row = {"sid": None, "conversation": None, "name": "", "name_source": "", "kind": "chat", "env": "prod",
           "machine": None, "cwd": None, "account": None, "owner": None, "owner_since": 0, "epoch": 1,
           "continues": None, "superseded_by": None, "first_prompt": None, "last_prompt": None, "last_answer": None,
           "topic": None, "rc_name": None, "started": None, "updated": None, "ended": None, "end_reason": None,
           "description": None, "work": False}
    row.update({k: v for k, v in cached.items() if k in row})
    row["started"] = row["started"] if row["started"] is not None else cached.get("owner_since") or 0
    row["updated"] = row["updated"] if row["updated"] is not None else cached.get("cached_at") or 0
    return row


def _off_hub_envelope(query, hub):
    """Off the hub: the hub's answer, kept as the last list. When the hub does not answer, that copy with
    `index: "down"`, and the rows this machine owns replaced by its own cache's (section 10.4)."""
    f = _fleet()
    me = f.self_machine()
    own = {r["sid"]: _durable(r) for r in _own_rows() if r.get("owner") == me}
    path = os.path.join(index_dir(), "last-list.json")
    try:
        env = f.run_remote_json(hub, ["session", "list", "--json"] + query_args(query), timeout=LIST_TIMEOUT,
                                kind=dict, keys=("machines", "rows", "index"))
    except f.RemoteError as e:
        why = str(e).splitlines()[-1] if str(e) else "no answer"
        env = _read_json(path) or {"v": 1, "hub": hub, "as_of": 0, "machines": {}, "rows": [],
                                   "counts": {"rows": 0, "hidden_dev": 0, "superseded": 0}}
        now = time.time()
        try:
            mine, answered, mine_why = observe_local(), True, ""
        except f.FleetError as err:
            mine, answered, mine_why = None, False, str(err)
        rows = []
        for r in env["rows"]:
            if r.get("owner") == me:
                continue
            o = dict(r["observed"])
            o["stale"] = o.get("observed_at") is None or now - o["observed_at"] > STALE_AFTER
            if matches(r, query):
                rows.append(dict(r, observed=o))
        every = list(own.values())
        rows += [_listed(r, every, observed_for(r, mine, None, now)) for r in every if matches(r, query)]
        env = dict(env, index="down", reason="the hub %s did not answer (%s)" % (hub, why),
                   rows=_order(rows, query["limit"]))
        env["counts"] = dict(env["counts"], rows=len(env["rows"]))
        env["machines"] = dict(env["machines"])
        env["machines"][hub] = {"reachable": False, "as_of": (env["machines"].get(hub) or {}).get("as_of"),
                                "stale": True, "reason": why}
        env["machines"][me] = {"reachable": answered, "as_of": mine["as_of"] if mine else None,
                               "stale": mine is None, "reason": mine_why}
        return env
    _write_private(path, env)
    # a work row leaves this machine masked and comes back so; here, its own machine, it shows in full
    env["rows"] = [dict(r, **{k: own[r["sid"]][k] for k in ("name", "name_source", "cwd", "account", "first_prompt",
                                                              "last_prompt", "last_answer", "description")})
                   if r.get("work") and r.get("machine") == me and r["sid"] in own else r for r in env["rows"]]
    return env


def envelope(query=None, *, fresh=False):
    """The `sessions_reply` of `query` (see parse_query) as this machine sees it: on the hub from the index with
    every machine's observed facts, elsewhere the hub's answer, or the last one with `index: "down"`."""
    f = _fleet()
    query = parse_query(query)
    me, hub = f.self_machine(), _cli().hub_name()
    if hub != me and hub in f.other_machines():
        return _off_hub_envelope(query, hub)
    return _hub_envelope(query, fresh)


def index_rows():
    """Every durable row of the index, superseded and dev ones too, without reading any machine: for the pick
    plan. When the hub does not answer, this machine's cache. -> (rows, True when the hub answered)."""
    f = _fleet()
    try:
        cli = _cli()
    except ImportError:
        return [], False
    query = dict(parse_query({"env": "all", "chains": "all"}), limit=EVERY)
    try:
        if cli.hub_name() == f.self_machine() or cli.hub_name() not in f.other_machines():
            return _hub_rows(query), True
        env = f.run_remote_json(cli.hub_name(), ["session", "list", "--json"] + query_args(query),
                                timeout=LIST_TIMEOUT, kind=dict, keys=("rows",))
        if env.get("index") == "up":
            return env["rows"], True
    except (f.RemoteError, sqlite3.Error, OSError):
        pass
    return [_durable(r) for r in _own_rows()], False


# ---------------------------------------------------------------- the server's list

class IndexFeed:
    """The server's list, stale while refresh over envelope(): it answers at once with the last list of that query
    (every row says `observed_at`) and fetches a new one in the background when that is older than the TTL, so a
    sleeping machine's 8 s never holds the page. The first request of a query, and one with fresh=1, waits."""

    def __init__(self, ttl=OBSERVE_TTL):
        self.ttl, self.lock, self.items, self.busy = ttl, threading.Lock(), {}, set()

    def fetch(self, key, query, fresh=False):
        with _fleet().db_scope():
            val = envelope(query, fresh=fresh)
        with self.lock:
            self.items[key] = (time.time(), val)
        return val

    def refresh(self, key, query):
        try:
            self.fetch(key, query)
        except Exception as e:  # noqa: B902 - a failed background refresh keeps the last list
            _fleet().log_line("sessions: the page's refresh failed: %s" % e)
        finally:
            with self.lock:
                self.busy.discard(key)

    def get(self, query=None, fresh=False):
        query = parse_query(query)
        key = json.dumps(query, sort_keys=True)
        with self.lock:
            hit = self.items.get(key)
            start = bool(hit) and not fresh and key not in self.busy and time.time() - hit[0] >= self.ttl
            if start:
                self.busy.add(key)
        if not hit or fresh:
            return self.fetch(key, query, fresh)
        if start:
            threading.Thread(target=self.refresh, args=(key, query), daemon=True).start()
        return hit[1]

    def forget(self):
        with self.lock:
            self.items.clear()


# ---------------------------------------------------------------- the page's writes

PAGE_QUERY = {"limit": 2000}


def find_row(feed, key):
    """The row of `key` in the page's list (a fresh list when it is not in the last one), or a FleetError. The page
    can only act on a session the list holds."""
    f = _fleet()
    f.check_key(key)
    for fresh in (False, True):
        hit = next((r for r in feed.get(PAGE_QUERY, fresh)["rows"] if r["key"] == key), None)
        if hit:
            return hit
    raise f.FleetError("fleet: no session %s in the list." % key)


def index_verb(verb, sid, *text):
    """`fleet session <verb> -- SID [TEXT]` in its own process: the index's own rules (what may be deleted or
    described, and which machine does the work) live in that command, and its output is the page's answer."""
    f = _fleet()
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fleet_index_cli.py")
    try:
        r = subprocess.run([sys.executable, path, verb, "--", sid] + list(text), capture_output=True, text=True,
                           timeout=WRITE_TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise f.FleetError("fleet: %s did not finish: %s" % (verb, e))
    if r.returncode != 0:
        lines = (r.stderr or r.stdout or "").strip().splitlines()
        raise f.FleetError(lines[-1] if lines else "fleet: %s failed (exit %d)." % (verb, r.returncode))
    return r.stdout.strip()


def _durable_of(row):
    return {k: v for k, v in row.items() if k not in ("observed", "key", "head", "chain")}


def describe(row):
    """Describe a row on its own machine. The description reaches the index through that machine's journal, and the
    hub takes an entry only from the row's owner, at the epoch its writer knows. A machine knows that from its cache,
    which it does not have for a row it never journaled (an imported one), so the row is put there first. The index
    is read back: a description that did not arrive is an error, never a quiet success."""
    f, cli = _fleet(), _cli()
    if row.get("work"):
        raise f.FleetError("fleet: a work session is never described.")
    if row["owner"] != row["machine"]:
        raise f.FleetError("fleet: %s owns this session, not %s: take it there first, then describe it."
                           % (row["owner"], row["machine"]))
    cached = json.dumps([_durable_of(row)])
    if row["machine"] == f.self_machine():
        _cache().write_truth(f.fleet_home(), json.loads(cached))
    else:
        try:
            code, _, err = cli.run_on(row["machine"], ["_cache-put"], stdin=cached)
        except cli.Unreachable as e:
            raise f.FleetError("fleet: %s does not answer (%s)." % (row["machine"], e))
        if code != 0:
            raise f.FleetError("fleet: %s: %s" % (row["machine"], (err.strip().splitlines() or ["failed"])[-1]))
    try:
        text = json.loads(index_verb("describe", row["sid"]).splitlines()[-1])["description"]
    except (ValueError, KeyError, IndexError):
        raise f.FleetError("fleet: describe gave no description.")
    now, _ = index_rows()
    got = next((r.get("description") for r in now if r["sid"] == row["sid"]), None)
    if not got:
        raise f.FleetError("fleet: the description was written on %s but the index has not taken it yet: "
                           "see hooks.log on the hub." % row["machine"])
    return {"output": text}


def search(query_text, rows):
    """Search by meaning over the descriptions the index holds: the history's one search, given the index's rows."""
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    mem.executescript(hist.SCHEMA)
    have = {r["name"] for r in mem.execute("PRAGMA table_info(conversations)")}
    if "unreadable" not in have:
        mem.execute("ALTER TABLE conversations ADD COLUMN unreadable INTEGER")
    keys = {}
    for r in rows:
        keys[r["sid"]] = r["key"]
        mem.execute("INSERT INTO conversations (session_id, cwd, manual_name, first_prompt, description, started_at,"
                    " last_seen_at) VALUES (?,?,?,?,?,?,?)",
                    (r["sid"], r.get("cwd"), r.get("name") or None, r.get("first_prompt"), r.get("description"),
                     r.get("started"), r.get("updated")))
    try:
        res = hist.search(mem, query_text)
    finally:
        mem.close()
    return {"hits": [{"key": keys[h["id"]], "why": h["why"]} for h in res["hits"]],
            "described": res["described"], "total": res["total"]}


def _member_of(row):
    """The live fleet member that holds this conversation, on the row's machine, or None."""
    f = _fleet()
    rows, _, _ = f.all_members(False)
    mine = [m for m in rows if m.get("conversation", m["session_id"]) == row["conversation"]
            and m.get("status") == "alive"]
    return next((m for m in mine if (m.get("machine") or f.self_machine()) == row["machine"]), None)


def _open(body, row):
    f = _fleet()
    line = "@claude pick --open %s" % row["key"]
    target = f.text_field(body, "target", limit=64)
    if target == "copy":
        return {"copy": line}
    if target != f.self_machine() and target not in f.other_machines():
        raise f.FleetError("fleet: no machine named %r." % target)
    if f.screen_of(target) == "none":
        raise f.FleetError("fleet: %s has no screen to open a window on; copy the line instead." % target)
    return dict(f.on_machine(target, "_open-window", row["key"], f.open_window), copy=line)


def _stop(body, row):
    f = _fleet()
    if body.get("force") is True:
        return f.on_machine(row["machine"], "_force-stop", row["key"], f.force_stop)
    member = _member_of(row)
    if not member:
        raise f.FleetError("fleet: %s is not a fleet member, so it cannot be told to wrap up; an idle one in a "
                           "window can be stopped with force." % (row["name"] or row["key"]))
    target = "%s@%s" % (member["name"], row["machine"])
    res = f.control("stop", target)
    if res["action"] != "stopped":
        res["thread"], _ = f.captured(f.send, "tell", target, f.WRAP_UP_TELL, f.PAGE)
    return res


def post(path, body, feed):
    """The Sessions tab's writes. A request names a session by its key and a machine by name, both checked against
    the list and machines.json; it never carries a command. -> (status, json)."""
    f = _fleet()
    if path not in PAGE_POSTS:
        return 404, {"error": "not found"}
    try:
        if path == "/api/sessions/search":
            rows = feed.get(PAGE_QUERY)["rows"]
            return 200, search(f.text_field(body, "query", limit=500), rows)
        row = find_row(feed, f.text_field(body, "key", limit=200))
        if path == "/api/sessions/open":
            return 200, _open(body, row)
        if path == "/api/sessions/stop":
            res = _stop(body, row)
        elif path == "/api/sessions/rename":
            name = " ".join(f.text_field(body, "name", limit=200).split())
            res = {"output": index_verb("rename", row["sid"], *name.split())}
        elif path == "/api/sessions/delete":
            res = {"output": index_verb("delete", row["sid"])}
        elif path == "/api/sessions/describe":
            res = describe(row)
        else:
            if row.get("work") and row["machine"] != f.self_machine():  # the answer would carry its words here
                raise f.FleetError("fleet: %s is a work session: it is read only on %s."
                                   % (row["name"] or row["sid"][:8], row["machine"]))
            return 200, {"answer": index_verb("ask", row["sid"], f.text_field(body, "question", limit=2000))}
        feed.forget()
        return 200, res
    except hist.HistoryError as e:
        return 400, {"error": str(e)}
    except f.FleetError as e:
        return 400, {"error": str(e).splitlines()[0] if str(e) else "failed"}
