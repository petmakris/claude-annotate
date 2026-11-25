"""fleet sessions: one list of every Claude Code session on every machine, and the plan that lands in one.

Stdlib only, Python 3.9+, no fleet imports: fleet.py reads the sources (history, `claude agents --json`, tmux,
ps, the registry, other machines) and hands them in; this module only shapes them. Shared contract (tests pin
it; `fleet/ui/fixtures/sessions.json` and `open-plans.json` are its examples):

  envelope = {"machines": {name: {reachable, stale, as_of, reason, fleet, screen, unreadable, tmux_server}},
              "hub": name, "as_of": t, "rows": [row, ...]}
  row = {key, id, machine, name, named, folder, about, kind, where, tmux, state, pid, member, held, unanswered,
         free, started, last_seen, ended, end_reason, live_on, copies, stale, as_of, masked, registry}
  plan = {kind, key, id, machine, name, tmux, folder, pid, state, member, message, force, run_on_owner}

`where` is tmux (a live interactive session inside a pane of the claude tmux server, found by walking the pid's
parents up to a pane pid), window (live and interactive, outside tmux), bg (a background job of the daemon) or
none. `kind` is worker, job or chat (`kind_of`). A row of the work rule (a work account's transcript, or a
folder under a path profile, as the env repo's own test says) is `masked` when it leaves its machine: no
folder, first prompt or tmux name, and a name only when it is not taken from the prompt.
"""
import fnmatch
import re
import time

KEY_RE = re.compile(r"^[a-z0-9-]+:[0-9a-f-]{8,36}$")
ID_RE = re.compile(r"^[0-9a-f-]{8,36}$")
WORKER_PREFIXES = ("job:", "dashboard-worker")
JOB_FOLDERS = ("*/tmp/*", "/tmp/*", "*/.local/state/lungo/*", "*/lomem-checkouts/*", "*/.scratch/*")
KINDS = ("chat", "job", "worker")
RECENT = 14 * 86400   # an unnamed chat older than this is left out of the default view
LIMIT = 300           # rows per machine, newest first; live rows always come
SLUG_MAX = 40
PLAN_KINDS = ("attach-tmux", "attach-bg", "resume", "wrap-up-then-resume", "blocked-window", "refuse-offline",
              "refuse-no-folder", "refuse-live-elsewhere", "refuse-registry")


# ---------------------------------------------------------------- kinds and names

def kind_of(name, folder, rules=None):
    """worker, job or chat. `rules` (sessions.json) adds `worker_prefixes` and `job_folders` to the defaults."""
    rules = rules or {}
    prefixes = WORKER_PREFIXES + tuple(p for p in rules.get("worker_prefixes") or () if isinstance(p, str))
    if any((name or "").startswith(p) for p in prefixes):
        return "worker"
    globs = JOB_FOLDERS + tuple(g for g in rules.get("job_folders") or () if isinstance(g, str))
    f = (folder or "").rstrip("/") + "/"
    if folder and any(fnmatch.fnmatchcase(f, g) or fnmatch.fnmatchcase(f, g.rstrip("*")) for g in globs):
        return "job"
    return "chat"


def slug(name, sid):
    """The tmux session name a resume makes: the display name in [A-Za-z0-9_-], at most 40 characters; an
    unnamed session is its id's first 8. Deterministic, so two opens of one conversation pick the same name."""
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name or "").strip("-")[:SLUG_MAX].strip("-")
    return s or (sid or "")[:8]


def parse_since(text, now=None):
    """`--since`: 14d, 6h, 30m, or epoch seconds -> epoch seconds, or None."""
    if not text:
        return None
    now = now or time.time()
    m = re.match(r"^(\d+(?:\.\d+)?)([dhm]?)$", str(text).strip())
    if not m:
        raise ValueError("--since takes 14d, 6h, 30m or epoch seconds, not %r" % text)
    n, unit = float(m.group(1)), m.group(2)
    return now - n * {"d": 86400, "h": 3600, "m": 60}[unit] if unit else n


def parse_kinds(text):
    """`--kind`: chat (the default), job, worker, a comma list, or all."""
    if not text:
        return {"chat"}
    if text == "all":
        return set(KINDS)
    out = {k.strip() for k in text.split(",") if k.strip()}
    if not out or out - set(KINDS):
        raise ValueError("--kind takes chat, job, worker, a comma list of them, or all")
    return out


# ---------------------------------------------------------------- tmux

def parse_panes(text):
    """`tmux list-panes -a -F '#{pane_pid} #{session_name}'` -> {pane pid: session name}."""
    out = {}
    for line in (text or "").splitlines():
        parts = line.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].isdigit():
            out[int(parts[0])] = parts[1]
    return out


def parse_parents(text):
    """`ps -A -o pid=,ppid=` -> {pid: parent pid}."""
    out = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            out[int(parts[0])] = int(parts[1])
    return out


def pane_of(pid, panes, parents):
    """The tmux session a process runs in: its pid or the nearest parent that is a pane's pid, else None."""
    seen = set()
    p = pid
    while isinstance(p, int) and p > 1 and p not in seen and len(seen) < 64:
        if p in panes:
            return panes[p]
        seen.add(p)
        p = parents.get(p)
    return None


# ---------------------------------------------------------------- one machine's rows

def agent_index(agents):
    """sessionId -> its entry of `claude agents --json` (the one with a pid when there are several)."""
    out = {}
    for a in agents or ():
        sid = a.get("sessionId")
        if sid and (sid not in out or a.get("pid")):
            out[sid] = a
    return out


def where_of(entry, live, panes, parents):
    """(where, tmux session) of a session from its entry of `claude agents --json`."""
    if not entry:
        return "none", None
    if entry.get("kind") == "background":
        return "bg", None
    if entry.get("pid") and live:
        t = pane_of(int(entry["pid"]), panes, parents)
        return ("tmux", t) if t else ("window", None)
    return "none", None


def build_rows(machine, history, agents, members, panes, parents, alive=None, rules=None, is_work=None,
               now=None, only_id=None):
    """This machine's rows, unfiltered and in full.

    history: dicts {id, names: [(name, source)...] best first, folder, about, started, last_seen, ended,
             end_reason, transcript}; agents: `claude agents --json`; members: local_members() entries;
    alive(pid) says whether a pid runs here; is_work(folder, transcript) is the work rule (None = no rule)."""
    now = now or time.time()
    alive = alive or (lambda pid: True)
    idx = agent_index(agents)
    mem = {m["session_id"]: m for m in members or ()}
    out, done = [], set()

    def row(sid, names, folder, about, started, last_seen, ended, end_reason, transcript):
        entry = idx.get(sid)
        live = bool(entry) and (entry.get("kind") == "background" or (entry.get("pid") and alive(entry["pid"])))
        where, tmux = where_of(entry, live, panes, parents) if live else ("none", None)
        m = mem.get(sid)
        fleet_name = m["name"] if m else ""
        name, source = next(((n, s) for n, s in names if n), (fleet_name, "fleet") if fleet_name else ("", ""))
        if not name and entry and entry.get("name"):
            name, source = entry["name"], "agent"
        state = str(entry.get("status") or entry.get("state") or "") if live else ""
        r = {"key": "%s:%s" % (machine, sid), "id": sid, "machine": machine, "name": name, "named": bool(name),
             "folder": folder or "", "about": about or "", "kind": kind_of(name, folder, rules),
             "where": where, "tmux": tmux, "state": state, "pid": entry.get("pid") if live and entry else None,
             "member": bool(m), "held": list(m["held"]) if m else [], "unanswered": list(m["unanswered"]) if m else [],
             "free": bool(m and m.get("free")), "started": started, "last_seen": last_seen, "ended": ended,
             "end_reason": end_reason or "", "live_on": [machine] if live else [], "copies": [], "stale": False,
             "as_of": now, "masked": False, "registry": None}
        r["_work"] = bool(is_work and is_work(folder, transcript))
        r["_name_from_prompt"] = source in ("ai",)
        r["_fleet_name"] = fleet_name
        return r

    for h in history:
        if only_id and not h["id"].startswith(only_id):
            continue
        done.add(h["id"])
        out.append(row(h["id"], h.get("names") or [], h.get("folder"), h.get("about"), h.get("started"),
                       h.get("last_seen"), h.get("ended"), h.get("end_reason"), h.get("transcript")))
    for sid, entry in idx.items():  # live sessions the history has not recorded (yet)
        if sid in done or (only_id and not sid.startswith(only_id)):
            continue
        if entry.get("kind") != "background" and not (entry.get("pid") and alive(entry["pid"])):
            continue
        st = (entry.get("startedAt") or 0) / 1000.0 or None
        out.append(row(sid, [], entry.get("cwd"), "", st, now, None, "", None))
    return out


def keep(r, kinds, named_only=False, since=None, now=None, default_recent=True):
    """Whether a row is in the view. A live row is kept whatever its age or name (its kind still counts)."""
    if r["kind"] not in kinds:
        return False
    if r["live_on"]:
        return True
    if named_only and not r["named"]:
        return False
    seen = r["last_seen"] or r["started"] or 0
    if since is not None and seen < since:
        return False
    if default_recent and since is None and not r["named"] and seen < (now or time.time()) - RECENT:
        return False
    return True


def select(rows, kinds, named_only=False, since=None, limit=LIMIT, now=None, default_recent=True):
    """The rows of the view, newest first; at most `limit` that are not live, and every live one. The default view
    (`default_recent`: no --kind given) leaves out unnamed sessions older than 14 days."""
    rows = [r for r in rows if keep(r, kinds, named_only, since, now, default_recent)]
    rows.sort(key=lambda r: r["last_seen"] or r["started"] or 0, reverse=True)
    live = [r for r in rows if r["live_on"]]
    rest = [r for r in rows if not r["live_on"]][:max(0, limit)]
    chosen = {id(r) for r in live + rest}
    return [r for r in rows if id(r) in chosen]


def mask(r):
    """The row as another machine may hold it, when it is of the work rule."""
    if not r.get("_work"):
        return r
    r = dict(r)
    if r.get("_name_from_prompt"):
        r["name"], r["named"] = "", False
    r.update(folder="", about="", tmux=None, masked=True)
    return r


def public(r):
    """A row without its internal fields."""
    return {k: v for k, v in r.items() if not k.startswith("_")}


def tmux_holders(panes, parents, agents, alive=None):
    """tmux session -> ids of the live Claude sessions inside it (an empty list: a session with no Claude)."""
    out = {name: [] for name in panes.values()}
    alive = alive or (lambda pid: True)
    for a in agents or ():
        if a.get("pid") and a.get("sessionId") and alive(a["pid"]):
            t = pane_of(int(a["pid"]), panes, parents)
            if t is not None:
                out.setdefault(t, []).append(a["sessionId"])
    return out


# ---------------------------------------------------------------- every machine

def owner_of(rows, record):
    """The row that owns a session id among its copies (one per machine). The seamless registry's owner wins
    when it holds a copy; else the machine where it is live; else the newest last_seen."""
    if record:
        target = record.get("_machine")
        hit = [r for r in rows if r["machine"] == target]
        if hit:
            return hit[0]
    live = [r for r in rows if r["live_on"] and not r["stale"]]
    if live:
        return live[0]
    return max(rows, key=lambda r: (r["last_seen"] or r["started"] or 0, not r["stale"]))


def merge(per_machine, registry=None, hub_main=None):
    """Rows of every machine -> one row per session id. per_machine: {machine: rows}; registry: {sid: record}
    with `owner` (a machine, or phone:...), whose machine a phone owner maps to is `hub_main`."""
    by_id = {}
    for machine in sorted(per_machine):
        for r in per_machine[machine]:
            by_id.setdefault(r["id"], []).append(r)
    out = []
    for sid, copies in by_id.items():
        rec = dict((registry or {}).get(sid) or {}) or None
        if rec:
            owner = str(rec.get("owner") or rec.get("machine") or "")
            rec["_machine"] = hub_main if owner.startswith("phone:") else owner
        first = owner_of(copies, rec)
        own = dict(first)
        own["live_on"] = sorted({m for r in copies for m in r["live_on"]})
        own["copies"] = sorted(r["machine"] for r in copies if r is not first)
        own["registry"] = (rec or {}).get("owner") or (rec or {}).get("machine") or None
        out.append(own)
    out.sort(key=lambda r: r["last_seen"] or r["started"] or 0, reverse=True)
    return out


# ---------------------------------------------------------------- the plan

def when_words(t):
    return time.strftime("%H:%M", time.localtime(t)) if t else "an unknown time"


def plan(key, copies, machines, holders=None, folder_ok=None, registry=None, here=None):
    """What landing in session `key` means, as data (the contract in the module's docstring).

    copies: every row of that id, one per machine that has it (stale ones from the cache); machines: the
    envelope's machine entries; holders: {machine: tmux_holders}; folder_ok: {machine: bool}; registry: the
    registry record of the id, or None; here: the machine computing the plan (a masked row it cannot land in
    from here is `run_on_owner`)."""
    machine_key, sid = key.split(":", 1)
    holders, folder_ok = holders or {}, folder_ok or {}
    rec = dict(registry or {}) or None
    if rec:
        o = str(rec.get("owner") or rec.get("machine") or "")
        rec["_machine"] = None if o.startswith("phone:") else o
    own = owner_of(copies, rec)
    live = [r for r in copies if r["live_on"] and not r["stale"]]
    live.sort(key=lambda r: r["machine"] != own["machine"])
    L = live[0] if live else None
    base = L or own

    def out(kind, message="", tmux=None, force=False, row=None):
        r = row or base
        name = r.get("_fleet_name") or r["name"] if r.get("member") else r["name"]
        return {"kind": kind, "key": r["key"], "id": r["id"], "machine": r["machine"], "name": name,
                "tmux": "" if r.get("masked") else (tmux if tmux is not None else (r.get("tmux") or "")),
                "folder": "" if r.get("masked") else (r.get("folder") or ""), "pid": r.get("pid"),
                "state": r.get("state") or "", "member": bool(r.get("member")), "message": message,
                "force": bool(force), "run_on_owner": bool(r.get("masked") and here and here != r["machine"])}

    label = own["name"] or base["name"] or sid[:8]
    if L:
        if L["where"] == "tmux":
            return out("attach-tmux", row=L)
        if L["where"] == "bg":
            return out("attach-bg", row=L)
        if L["machine"] != own["machine"]:
            return out("refuse-live-elsewhere", "%s is live on %s in a window, not in tmux: it is not resumed on %s"
                       % (label, L["machine"], own["machine"]), row=L)
        if L.get("member"):
            return out("wrap-up-then-resume", "%s: told to wrap up and leave; it resumes in tmux once its process "
                       "is gone" % label, tmux=slug(own["name"], sid), row=L)
        idle = (L.get("state") or "") == "idle"
        return out("blocked-window", "open in a window on %s, status %s, pid %s: it is not a fleet member, so it "
                   "cannot be told to leave%s" % (L["machine"], L.get("state") or "unknown", L.get("pid"),
                                                  "" if idle else "; it is never stopped while it works"),
                   force=idle, row=L)
    if rec and rec["_machine"] is None:
        return out("refuse-registry", "%s is on the phone now: take it back with @claude -r first" % label, row=own)
    m = machines.get(own["machine"]) or {}
    if own["stale"] or not m.get("reachable", True):
        why = m.get("reason") or "no answer"
        return out("refuse-offline", "%s: not answering (%s); last answer at %s. It may still be running there, so "
                   "it is not resumed anywhere else." % (own["machine"], why, when_words(m.get("as_of") or own["as_of"])),
                   row=own)
    if folder_ok.get(own["machine"]) is False:
        return out("refuse-no-folder", "%s: the folder %s is gone; it is not created again"
                   % (own["machine"], own.get("folder") or "of this session"), tmux="", row=own)
    name = slug(own["name"], sid)
    held = (holders.get(own["machine"]) or {}).get(name)
    if held is not None and sid not in held:
        name = "%s-%s" % (name[:SLUG_MAX - 9], sid[:8])
    return out("resume", tmux=name, row=own)
