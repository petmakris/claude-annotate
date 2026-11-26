"""fleet sessions: the rows `@claude pick` shows, and the plan that lands in one.

Stdlib only, Python 3.9+, no fleet imports: fleet.py reads the sources (the session index through
fleet_sessions_api, and this machine's history, `claude agents --json`, tmux and ps) and hands them in; this module
only shapes them. Shared contract (tests pin it; `fleet/ui/fixtures/sessions.json` and `open-plans.json` are its
examples):

  envelope = {"machines": {name: {reachable, stale, as_of, reason, fleet, screen, unreadable, tmux_server}},
              "hub": name, "as_of": t, "rows": [row, ...]}
  row = {key, id, machine, name, named, folder, about, kind, where, tmux, state, pid, member, held, unanswered,
         free, started, last_seen, ended, end_reason, live_on, copies, stale, as_of, masked, registry}
  plan = {kind, key, id, machine, name, tmux, folder, pid, state, member, message, force, run_on_owner, head, take}

The list holds one row per session id, from the session index (fleet/docs/session-index.md); `registry` is the
row's owner. `fleet sessions --local` gives this machine's own facts, which the plan reads.

`where` is tmux (a live interactive session inside a pane of the claude tmux server, found by walking the pid's
parents up to a pane pid), window (live and interactive, outside tmux), bg (a background job of the daemon) or
none. `kind` is worker, job or chat (`kind_of`). A row of the work rule is `masked` when it leaves its machine: no
folder, first prompt or tmux name, and a name only when it is not taken from the prompt.

A plan's `head` is the sid it acts on (a superseded sid resolves to its chain's head) and `take` is null, or
{sid, to, expect_epoch}: `take-then-resume` means the picker runs `@claude session take SID --to <machine>` and
then resumes there.
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
PLAN_KINDS = ("attach-tmux", "attach-bg", "resume", "take-then-resume", "wrap-up-then-resume", "blocked-window",
              "refuse-offline", "refuse-no-folder", "refuse-live-elsewhere")
NEVER_TAKEN = ("job", "worker")  # the index refuses to move them: they are read, or resumed where they are


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
             end_reason, transcript, work} (this machine's rows of the session index); agents: `claude agents --json`; members: local_members() entries;
    alive(pid) says whether a pid runs here; is_work(folder, transcript) is the work rule (None = no rule)."""
    now = now or time.time()
    alive = alive or (lambda pid: True)
    idx = agent_index(agents)
    mem = {m["session_id"]: m for m in members or ()}
    out, done = [], set()

    def row(sid, names, folder, about, started, last_seen, ended, end_reason, transcript, work=False):
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
        r["_work"] = bool(work) or bool(is_work and is_work(folder, transcript))
        r["_name_from_prompt"] = source in ("ai",)
        r["_fleet_name"] = fleet_name
        return r

    for h in history:
        if only_id and not h["id"].startswith(only_id):
            continue
        done.add(h["id"])
        out.append(row(h["id"], h.get("names") or [], h.get("folder"), h.get("about"), h.get("started"),
                       h.get("last_seen"), h.get("ended"), h.get("end_reason"), h.get("transcript"), h.get("work")))
    for sid, entry in idx.items():  # live sessions the index has not recorded (yet)
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


# ---------------------------------------------------------------- rows of the index

def newest_copy(rows):
    """Of the copies machines hold of one session: the live one, else the newest."""
    live = [r for r in rows if r["live_on"] and not r["stale"]]
    if live:
        return live[0]
    return max(rows, key=lambda r: (r["last_seen"] or r["started"] or 0, not r["stale"]))


def from_index(r, machines, me, member=None):
    """A row of `GET /api/sessions` in the shape the picker reads. machines: that reply's machine entries;
    member: the fleet member that holds the row's conversation, or None."""
    o = r.get("observed") or {}
    live = o.get("live") is True
    m = machines.get(r["machine"]) or {}
    masked = bool(r.get("work")) and r["machine"] != me
    where = o.get("where") if live and o.get("where") in ("tmux", "window", "bg") else "none"
    return {"key": r["key"], "id": r["sid"], "machine": r["machine"], "name": r.get("name") or "",
            "named": bool(r.get("name")), "folder": r.get("cwd") or "", "about": r.get("first_prompt") or "",
            "kind": r["kind"] if r.get("kind") in KINDS else "chat", "where": where,
            "tmux": o.get("tmux") if where == "tmux" else None, "state": (o.get("state") or "") if live else "",
            "pid": o.get("pid") if live else None, "member": bool(member),
            "held": list(member.get("held") or []) if member else [],
            "unanswered": list(member.get("unanswered") or []) if member else [],
            "free": bool(member and member.get("free")), "started": r.get("started"),
            "last_seen": r.get("updated"), "ended": r.get("ended"), "end_reason": r.get("end_reason") or "",
            "live_on": [r["machine"]] if live else [], "copies": [], "stale": m.get("reachable", True) is False,
            "as_of": o.get("observed_at") or m.get("as_of"), "masked": masked, "registry": r.get("owner")}


# ---------------------------------------------------------------- the plan

def when_words(t):
    return time.strftime("%H:%M", time.localtime(t)) if t else "an unknown time"


def owner_words(owner):
    return "the phone" if str(owner).startswith("phone:") else str(owner)


def index_copy(index, machines, here):
    """The copy of a session no machine gave facts of (a phone's own session, or a machine that did not answer),
    from its index row."""
    m = machines.get(index["machine"]) or {}
    down = bool(m.get("stale")) or m.get("reachable", True) is False
    return {"key": "%s:%s" % (index["machine"], index["sid"]), "id": index["sid"], "machine": index["machine"],
            "name": index.get("name") or "", "folder": index.get("cwd") or "", "tmux": None, "pid": None,
            "state": "", "where": "none", "member": False, "live_on": [], "stale": down,
            "as_of": m.get("as_of"), "masked": bool(index.get("work")) and here not in (None, index["machine"]),
            "started": index.get("started"), "last_seen": index.get("updated")}


def plan(key, copies, machines, holders=None, folder_ok=None, index=None, here=None, to=None):
    """What landing in session `key` means, as data (the contract in the module's docstring).

    copies: one row of live facts per machine that has the session (`fleet sessions --local`); machines: the
    envelope's machine entries; holders: {machine: tmux_holders}; folder_ok: {machine: bool}; index: the chain
    head's row of the session index, or None when the index does not hold it; here: the machine computing the plan
    (a masked row it cannot land in from here is `run_on_owner`); to: where the session should land, a machine or a
    phone owner; by default the machine of `key`.

    The index says who owns a session. A session owned elsewhere and live nowhere is `take-then-resume`: only take
    moves it. A live session is attached or refused, never moved over."""
    machine_key, sid = key.split(":", 1)
    holders, folder_ok = holders or {}, folder_ok or {}
    own = None
    if index:
        own = next((r for r in copies if r["machine"] == index["machine"]), None) or index_copy(index, machines, here)
    own = own or newest_copy(copies)
    owner = index["owner"] if index else own["machine"]
    phone = str(owner).startswith("phone:")
    takes = bool(index) and not index.get("work") and index.get("kind") not in NEVER_TAKEN
    dest = to or (machine_key if takes else own["machine"])
    to_phone = str(dest).startswith("phone:")
    moves = bool(index) and (takes or to_phone) and dest != owner  # take itself refuses what it never moves
    live = [r for r in copies if r["live_on"] and not r["stale"]]
    live.sort(key=lambda r: r["machine"] != own["machine"])
    L = live[0] if live else None
    base = L or own

    def out(kind, message="", tmux=None, force=False, row=None, machine=None, take=None):
        r = row or base
        name = r.get("_fleet_name") or r["name"] if r.get("member") else r["name"]
        if index:  # one session, one name: the index's
            name = name if r.get("member") else index.get("name") or name
        return {"kind": kind, "key": r["key"], "id": r["id"], "machine": machine or r["machine"], "name": name,
                "tmux": "" if r.get("masked") else (tmux if tmux is not None else (r.get("tmux") or "")),
                "folder": "" if r.get("masked") else (r.get("folder") or ""), "pid": r.get("pid"),
                "state": r.get("state") or "", "member": bool(r.get("member")), "message": message,
                "force": bool(force), "run_on_owner": bool(r.get("masked") and here and here != r["machine"]),
                "head": r["id"], "take": take}

    def offline(machine, row):
        m = machines.get(machine) or {}
        why = m.get("reason") or "no answer"
        return out("refuse-offline", "%s: not answering (%s); last answer at %s. It may still be running there, so "
                   "it is not resumed anywhere else." % (machine, why, when_words(m.get("as_of") or row.get("as_of"))),
                   row=row)

    def down(machine):
        m = machines.get(machine) or {}
        return bool(m.get("stale")) or m.get("reachable", True) is False

    def session_name(machine):
        name = slug(label_name, sid)
        held = (holders.get(machine) or {}).get(name)
        return "%s-%s" % (name[:SLUG_MAX - 9], sid[:8]) if held is not None and sid not in held else name

    label_name = (index or {}).get("name") or own["name"] or base["name"]
    label = label_name or sid[:8]
    if L:
        wrong = bool(index) and not phone and L["machine"] != owner or phone or \
            not index and L["machine"] != own["machine"]
        if not (to_phone and L["machine"] == owner):
            if to_phone:
                return out("refuse-live-elsewhere", "%s is live on %s, which does not own it (%s does): it is not "
                           "given to the phone" % (label, L["machine"], owner_words(owner)), row=L)
            if L["where"] == "tmux":
                return out("attach-tmux", row=L)
            if L["where"] == "bg":
                return out("attach-bg", row=L)
            if wrong:
                return out("refuse-live-elsewhere", "%s is live on %s in a window, not in tmux: it is not resumed "
                           "on %s" % (label, L["machine"], owner_words(owner) if index else own["machine"]), row=L)
            if L.get("member"):
                return out("wrap-up-then-resume", "%s is a fleet member in a window: it is told to wrap up and "
                           "leave, then resumed in tmux once its process is gone" % label,
                           tmux=slug(label_name, sid), row=L)
            idle = (L.get("state") or "") == "idle"
            return out("blocked-window", "open in a window on %s, status %s, pid %s: it is not a fleet member, so "
                       "it cannot be told to leave%s" % (L["machine"], L.get("state") or "unknown", L.get("pid"),
                                                          "" if idle else "; it is never stopped while it works"),
                       force=idle, row=L)
    if moves:
        for needed in (None if phone else owner, None if to_phone else dest):
            if needed and down(needed):
                return offline(needed, own)
        return out("take-then-resume", "%s is on %s: it is taken to %s first, then resumed there"
                   % (label, owner_words(owner), owner_words(dest)),
                   tmux="" if to_phone else session_name(dest), row=own, machine=dest,
                   take={"sid": own["id"], "to": dest, "expect_epoch": index["epoch"]})
    if own["stale"] or (machines.get(own["machine"]) or {}).get("reachable", True) is False:
        return offline(own["machine"], own)
    if folder_ok.get(own["machine"]) is False:
        return out("refuse-no-folder", "%s: the folder %s is gone; it is not created again"
                   % (own["machine"], own.get("folder") or "of this session"), tmux="", row=own)
    return out("resume", tmux=session_name(own["machine"]), row=own)
