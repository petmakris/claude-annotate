"""Launch profiles: which tools a folder's new Claude Code sessions get, and what each profile keeps.

This reads and writes the files of a launcher that gives each folder a profile (stdlib, no fleet imports;
`fleet.py` wraps it):

- a folder's `.claude-launch` holds `profile <name>`; the nearest one walking up from a session's folder decides;
- `<root>/claude/profiles/<name>.args` names the plugin dirs (`--plugin-dir`), one `--settings` file and any
  `--mcp-config` files; the first root that has `<name>.args` keeps the profile;
- the settings file `<name>.json` switches MCP servers off (`permissions.deny`) and marketplace plugins off
  (`enabledPlugins` set to false).

Where the roots are, which plugin dirs the launcher always offers, which ones cannot be switched off and which are
never shown live in `$FLEET_HOME/profiles.json`, never in this repository:

    {"roots": ["~/projects/env"], "roots_file": "~/.env-profiles",
     "default_dirs": ["~/projects/env/claude"], "locked": {"~/projects/env/claude": "your skills"},
     "hidden": ["~/projects/some-dir"], "audit": {"command": ["python3", "/path/audit.py", "--json"], "hint": "..."}}

`roots_file` lists more roots, one per line; only lines naming a folder (holding a `/`) count. A save rewrites
the profile's two files and commits only them in the root's repository, then pushes when it has a remote.
"""
import json
import os
import re
import subprocess
import threading
import time

PROFILE_NAME = re.compile(r"^[a-z0-9-]+$")
LAUNCH_FILE = ".claude-launch"
TEMP_PREFIXES = ("/private/", "/tmp", "/var/folders")
TOOLS_TTL = 600  # seconds the MCP list and the audit count are kept


class ProfileError(Exception):
    """A refusal, with the HTTP status the page answers it with."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- settings and paths

def home():
    return os.path.expanduser("~")


def tilde(p):
    h = home()
    if p == h:
        return "~"
    return "~" + p[len(h):] if p.startswith(h + "/") else p


def untilde(p):
    return os.path.expanduser(p) if p == "~" or p.startswith("~/") else p


def settings(fleet_home):
    """profiles.json as a dict ({} when missing or broken)."""
    try:
        with open(os.path.join(fleet_home, "profiles.json")) as f:
            conf = json.load(f)
    except (OSError, ValueError):
        return {}
    return conf if isinstance(conf, dict) else {}


def _strings(v):
    return [x for x in v if isinstance(x, str) and x] if isinstance(v, list) else []


class Config:
    def __init__(self, conf):
        self.roots_listed = _strings(conf.get("roots"))
        self.roots_file = conf.get("roots_file") if isinstance(conf.get("roots_file"), str) else None
        self.default_dirs = _strings(conf.get("default_dirs"))
        locked = conf.get("locked")
        self.locked = {k: v if isinstance(v, str) and v else os.path.basename(k)
                       for k, v in (locked.items() if isinstance(locked, dict) else [])}
        self.hidden = _strings(conf.get("hidden"))
        audit = conf.get("audit") if isinstance(conf.get("audit"), dict) else {}
        self.audit_command = _strings(audit.get("command"))
        self.audit_hint = audit.get("hint") if isinstance(audit.get("hint"), str) else ""

    @property
    def configured(self):
        return bool(self.roots_listed)

    def roots(self):
        """The repositories whose claude/profiles/ hold profiles, in the launcher's order."""
        out = [untilde(r) for r in self.roots_listed]
        if self.roots_file:
            try:
                with open(untilde(self.roots_file)) as f:
                    lines = f.read().split("\n")
            except OSError:
                lines = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#") and "/" in line:
                    out.append(untilde(line))
        seen, roots = set(), []
        for r in out:
            if r not in seen and os.path.isdir(r):
                seen.add(r)
                roots.append(r)
        return roots

    def profile_dirs(self):
        return [(os.path.join(r, "claude", "profiles"), r) for r in self.roots()]

    def profile_home(self, name):
        """(dir, repo) of the first root holding <name>.args, as the launcher resolves `profile <name>`."""
        for d, repo in self.profile_dirs():
            if os.path.exists(os.path.join(d, name + ".args")):
                return d, repo
        return None


# ---------------------------------------------------------------- pure file formats

def format_launch(name, args_path):
    return "# Tools this tree gets: see %s\nprofile %s\n" % (args_path, name)


_STANDARD = re.compile(r"^# Tools this tree gets: see (~?/[^\n]*/claude/profiles/([a-z0-9-]+)\.args)\nprofile ([a-z0-9-]+)$")


def split_root_block(text):
    """(body, root). A `root <dir>` block (where a tree's sessions start) may sit under the standard two lines
    with comments of its own; such a file is still standard. Else root is ''."""
    lines = re.sub(r"\n+$", "", text).split("\n")
    tail = lines[2:]
    is_root = lambda l: re.match(r"^root\s+\S", l.strip()) is not None  # noqa: E731
    if not any(is_root(l) for l in tail) or not all(is_root(l) or l.strip().startswith("#") or not l.strip()
                                                    for l in tail):
        return text, ""
    return "\n".join(lines[:2]) + "\n", "\n".join(tail) + "\n"


def parse_standard_launch(text):
    """The profile a `.claude-launch` names when it is exactly the standard form, else None."""
    m = _STANDARD.match(split_root_block(text)[0].strip())
    if not m or m.group(2) != m.group(3):
        return None
    return m.group(3)


def parse_args(text):
    lines = text.split("\n")
    comments = []
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        comments.append(lines[i])
        i += 1
    tokens = [t for l in lines[i:] for t in re.sub(r"#.*$", "", l).strip().split()]
    out = {"comments": comments, "plugin_dirs": [], "settings": None, "mcp_configs": []}
    t = 0
    while t < len(tokens):
        if tokens[t] == "--plugin-dir" and t + 1 < len(tokens):
            out["plugin_dirs"].append(tokens[t + 1]); t += 1
        elif tokens[t] == "--settings" and t + 1 < len(tokens):
            out["settings"] = tokens[t + 1]; t += 1
        elif tokens[t] == "--mcp-config" and t + 1 < len(tokens):
            out["mcp_configs"].append(tokens[t + 1]); t += 1
        t += 1
    return out


def format_args(a):
    lines = list(a["comments"]) + ["--plugin-dir %s" % d for d in a["plugin_dirs"]]
    if a["settings"]:
        lines.append("--settings %s" % a["settings"])
    lines += ["--mcp-config %s" % m for m in a["mcp_configs"]]
    return "\n".join(lines) + "\n"


def standard_args(text):
    """True when the file holds only leading # lines, --plugin-dir and --mcp-config pairs and at most one
    --settings pair: a save rewrites it from what parse_args understood, so it must hold nothing else."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith("#"):
        i += 1
    tokens = [t for l in lines[i:] for t in l.strip().split()]
    settings_seen = 0
    t = 0
    while t < len(tokens):
        flag = tokens[t]
        value = tokens[t + 1] if t + 1 < len(tokens) else None
        if flag in ("--plugin-dir", "--settings", "--mcp-config") and value is not None \
                and not value.startswith("-") and not value.startswith("#"):
            if flag == "--settings":
                settings_seen += 1
                if settings_seen > 1:
                    return False
            t += 2
        else:
            return False
    return True


def mcp_deny_prefix(name):
    n = "claude_ai_" + name[len("claude.ai "):] if name.startswith("claude.ai ") else name
    return "mcp__" + re.sub(r"[^A-Za-z0-9_-]", "_", n)


def parse_mcp_list(out):
    """Servers from `claude mcp list`, leaving out plugin-provided ones (their plugin has its own switch)."""
    servers = []
    for line in out.split("\n"):
        m = re.match(r"^(.+?): \S.* - ", line)
        if not m or m.group(1).startswith("plugin:"):
            continue
        servers.append({"name": m.group(1), "prefix": mcp_deny_prefix(m.group(1))})
    return servers


def tool_is_on(p, t):
    if t["kind"] == "pluginDir":
        return t["id"] in p["pluginDirs"]
    if t["kind"] == "mcp":
        return t["id"] not in p["denied"]
    return t["id"] not in p["disabledPlugins"]


def commit_message(name, before, after, tools):
    """One line naming every switched tool: `profiles: personal — Gmail off, playwright on`."""
    changes = ["%s %s" % (t["label"], "on" if tool_is_on(after, t) else "off")
               for t in tools if tool_is_on(before, t) != tool_is_on(after, t)]
    return "profiles: %s — %s" % (name, ", ".join(changes)) if changes else "profiles: %s" % name


# ---------------------------------------------------------------- reading

def write_atomic(path, text):
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        f.write(text)
    try:
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _launch_file_in(d):
    f = os.path.join(d, LAUNCH_FILE)
    try:
        if os.path.isfile(f):
            with open(f) as fh:
                return fh.read()
    except OSError:
        pass
    return None


def resolve_source(folder):
    """here (own standard file), inherited (an ancestor's file), none (no file up to /) or custom (own file in
    any other form), resolved by the launcher's nearest-file walk."""
    own = _launch_file_in(folder)
    if own is not None:
        p = parse_standard_launch(own)
        if p:
            return {"kind": "here", "profile": p, "from": None, "content": None}
        return {"kind": "custom", "profile": None, "from": None, "content": own}
    d = os.path.dirname(folder)
    while True:
        t = _launch_file_in(d)
        if t is not None:
            p = parse_standard_launch(t)
            return {"kind": "inherited", "profile": p, "from": tilde(d), "content": None if p else t}
        if d == os.path.dirname(d):
            break
        d = os.path.dirname(d)
    return {"kind": "none", "profile": None, "from": None, "content": None}


READ_BYTES = 1 << 20  # transcripts can be hundreds of MB; the cwd is on one of the first lines


def _first_cwd(path):
    try:
        with open(path, "rb") as f:
            head = f.read(READ_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    for line in head.split("\n"):
        if '"cwd"' not in line:
            continue
        try:
            cwd = json.loads(line).get("cwd")
        except (ValueError, AttributeError):
            continue  # a record cut off by the read
        if isinstance(cwd, str):
            return cwd
    return None


def transcript_usage(projects=None):
    """[(folder, sessions, last seen)] from Claude Code's transcript folders (~/.claude/projects), so a folder
    is listed even when its sessions ran before the history hook recorded them. The folder comes from what the
    first five transcripts (in name order) recorded, never from the encoded directory name."""
    root = projects or os.path.join(home(), ".claude", "projects")
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for enc in names:
        d = os.path.join(root, enc)
        if not os.path.isdir(d):
            continue
        files = sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".jsonl"))
        cwd = next((c for c in (_first_cwd(f) for f in files[:5]) if c), None)
        if not cwd:
            continue
        times = []
        for f in files:
            try:
                times.append(os.stat(f).st_mtime)
            except OSError:
                pass
        out.append((cwd, len(times), max(times) if times else 0))
    return out


def merge_usage(*sources):
    """One (folder, sessions, last seen) per folder: the larger count and the later time of any source."""
    merged = {}
    for src in sources:
        for cwd, n, last in src:
            if not cwd:
                continue
            key = cwd.rstrip("/") or "/"
            a, b = merged.get(key, (0, 0))
            merged[key] = (max(a, n or 0), max(b, last or 0))
    return [(k, n, last) for k, (n, last) in merged.items()]


def scan_folders(usage):
    """The folders sessions ran in: usage is [(cwd, sessions, last_seen)]. Each still exists and
    is not a temp folder; any ancestor holding a .claude-launch is listed too. Busiest first."""
    h = home()
    used = {}
    for cwd, n, last in usage:
        if not cwd:
            continue
        cwd = cwd.rstrip("/") or "/"
        temp = not cwd.startswith(h + "/") and any(cwd.startswith(t) for t in TEMP_PREFIXES)
        if temp or not os.path.isdir(cwd):
            continue
        prev = used.get(cwd, (0, 0))
        used[cwd] = (prev[0] + (n or 0), max(prev[1], last or 0))
    rows = dict(used)
    for p in used:
        d = os.path.dirname(p)
        while d != os.path.dirname(d):
            if d not in rows and _launch_file_in(d) is not None:
                rows[d] = (0, 0)
            d = os.path.dirname(d)
    out = [{"path": p, "display": tilde(p), "sessions": n, "lastUsed": last or None, "source": resolve_source(p)}
           for p, (n, last) in rows.items()]
    out.sort(key=lambda f: (-f["sessions"], f["path"]))
    return out


def _read_json(path):
    try:
        with open(path) as f:
            v = json.load(f)
    except (OSError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def profile_files(cfg, name):
    """(args, json) of a profile. The settings file named in .args counts only when it lies in the profiles
    folder, so a hand-edited .args can never point a save at another file."""
    found = cfg.profile_home(name)
    d = found[0] if found else (cfg.profile_dirs()[0][0] if cfg.profile_dirs() else "")
    args = os.path.join(d, name + ".args")
    fallback = os.path.join(d, name + ".json")
    named = None
    if os.path.exists(args):
        with open(args) as f:
            named = parse_args(f.read())["settings"]
    js = untilde(named) if named else fallback
    ok = os.path.dirname(js) == d and js.endswith(".json")
    return args, js if ok else fallback


def read_profiles(cfg):
    homes = {}
    for d, repo in cfg.profile_dirs():
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            if f.endswith(".args"):
                homes.setdefault(f[:-5], repo)
    out = []
    for name in sorted(homes):
        args_path, json_path = profile_files(cfg, name)
        with open(args_path) as f:
            args = parse_args(f.read())
        js = _read_json(json_path)
        perms = js.get("permissions") if isinstance(js.get("permissions"), dict) else {}
        deny = perms.get("deny")
        enabled = js.get("enabledPlugins") if isinstance(js.get("enabledPlugins"), dict) else {}
        out.append({"name": name, "repo": tilde(homes[name]), "pluginDirs": args["plugin_dirs"],
                    "denied": [d for d in deny if isinstance(d, str)] if isinstance(deny, list) else [],
                    "disabledPlugins": [k for k, v in enabled.items() if v is False]})
    return out


class ToolCache:
    """The MCP list and the audit count, each kept for TOOLS_TTL seconds. A failed MCP listing is not kept."""

    def __init__(self, claude_bin):
        self.claude_bin = claude_bin
        self.lock = threading.Lock()
        self.mcp = None   # (at, servers, error)
        self.audit = None  # (at, count)

    def _stale(self, entry, refresh):
        return refresh or entry is None or time.time() - entry[0] > TOOLS_TTL

    def mcp_list(self, refresh=False):
        with self.lock:
            if self._stale(self.mcp, refresh):
                try:
                    # From the home folder, so no project .mcp.json leaks in; stdin closed, so nothing waits on it.
                    r = subprocess.run([self.claude_bin(), "mcp", "list"], cwd=home(), stdin=subprocess.DEVNULL,
                                       capture_output=True, text=True, timeout=90)
                    if r.returncode != 0:
                        raise OSError((r.stderr or r.stdout or "exit %d" % r.returncode).strip()[-300:])
                    self.mcp = (time.time(), parse_mcp_list(r.stdout), None)
                except (OSError, subprocess.SubprocessError) as e:
                    self.mcp = (0, [], "claude mcp list failed: %s" % e)
            return self.mcp[1], self.mcp[2]

    def audit_count(self, cfg, refresh=False):
        if not cfg.audit_command:
            return None
        with self.lock:
            if self._stale(self.audit, refresh):
                try:
                    r = subprocess.run([untilde(c) for c in cfg.audit_command], stdin=subprocess.DEVNULL,
                                       capture_output=True, text=True, timeout=120)
                    found = json.loads(r.stdout)
                    count = len(found) if isinstance(found, list) else None
                except (OSError, subprocess.SubprocessError, ValueError):
                    count = None
                self.audit = (time.time(), count)
            return self.audit[1]


def build_tools(cfg, mcp):
    s = _read_json(os.path.join(home(), ".claude", "settings.json"))
    perms = s.get("permissions") if isinstance(s.get("permissions"), dict) else {}
    global_deny = set(_strings(perms.get("deny")))
    enabled = s.get("enabledPlugins") if isinstance(s.get("enabledPlugins"), dict) else {}
    hidden = {untilde(h) for h in cfg.hidden}
    dirs = []
    for d in list(cfg.default_dirs) + list(cfg.locked) + [d for p in read_profiles(cfg) for d in p["pluginDirs"]]:
        if d not in dirs and untilde(d) not in hidden:
            dirs.append(d)
    tools = [{"id": d, "kind": "pluginDir", "label": cfg.locked.get(d) or os.path.basename(d.rstrip("/")),
              "locked": d in cfg.locked} for d in dirs]
    tools += [{"id": m["prefix"], "kind": "mcp", "label": re.sub(r"^claude\.ai ", "", m["name"]), "locked": False}
              for m in mcp if m["prefix"] not in global_deny]
    tools += [{"id": k, "kind": "plugin", "label": k.split("@")[0], "locked": False}
              for k, v in enabled.items() if v is True]
    return tools


def read_config(cfg, cache, usage, refresh=False):
    """Everything the page shows."""
    if not cfg.configured:
        return {"configured": False, "folders": [], "profiles": [], "tools": [], "toolsError": None,
                "auditFindings": None, "auditHint": "", "home": home()}
    mcp, err = cache.mcp_list(refresh)
    return {"configured": True, "folders": scan_folders(usage), "profiles": read_profiles(cfg),
            "tools": build_tools(cfg, mcp), "toolsError": err, "auditFindings": cache.audit_count(cfg, refresh),
            "auditHint": cfg.audit_hint, "home": home()}


# ---------------------------------------------------------------- writing

def _git(cwd, *args):
    r = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise subprocess.CalledProcessError(r.returncode, args, r.stdout, r.stderr)
    return r.stdout.strip()


def _has_remote(repo):
    try:
        return _git(repo, "remote") != ""
    except subprocess.CalledProcessError:
        return False


def _exclude_from_git(folder):
    """Keep .claude-launch out of a repository's history when the folder is the top of one. Best effort."""
    try:
        top = _git(folder, "rev-parse", "--show-toplevel")
        if os.path.realpath(top) != os.path.realpath(folder):
            return
        rel = _git(folder, "rev-parse", "--git-path", "info/exclude")
        path = rel if os.path.isabs(rel) else os.path.join(folder, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        current = ""
        if os.path.exists(path):
            with open(path) as fh:
                current = fh.read()
        if LAUNCH_FILE in current.split("\n"):
            return
        with open(path, "a") as f:
            f.write(("\n" if current and not current.endswith("\n") else "") + LAUNCH_FILE + "\n")
    except (OSError, subprocess.CalledProcessError):
        pass


def _profile_exists(cfg, name):
    return isinstance(name, str) and PROFILE_NAME.match(name) is not None and cfg.profile_home(name) is not None


def set_folder_profile(cfg, usage, folder, profile, any_folder=False):
    """Write the folder's standard .claude-launch, or remove it (profile None: inherit). A custom file is never
    touched; a root line survives a profile change and makes inherit a hand edit. The page may write only to a
    folder it lists; the CLI (any_folder) to any existing folder."""
    if not isinstance(folder, str) or not os.path.isabs(folder):
        raise ProfileError(400, "not an absolute folder: %s" % folder)
    if any_folder:
        if not os.path.isdir(folder):
            raise ProfileError(400, "no such folder: %s" % folder)
    elif not any(f["path"] == folder for f in scan_folders(usage)):
        raise ProfileError(400, "not a folder the page lists: %s" % folder)
    f = os.path.join(folder, LAUNCH_FILE)
    if os.path.lexists(f) and not os.path.isfile(f):
        raise ProfileError(409, "%s is not a regular file; fix it by hand" % f)
    own = None
    if os.path.isfile(f):
        with open(f) as fh:
            own = fh.read()
    if own is not None and parse_standard_launch(own) is None:
        raise ProfileError(409, "%s is a custom file; edit it by hand" % f)
    root = split_root_block(own)[1] if own is not None else ""
    if profile is None:
        if root:
            raise ProfileError(409, "%s also says where sessions start (a root line); edit it by hand" % f)
        if own is not None:
            os.unlink(f)
    else:
        if not _profile_exists(cfg, profile):
            raise ProfileError(400, "no profile named %s" % profile)
        write_atomic(f, format_launch(profile, tilde(profile_files(cfg, profile)[0])) + root)
        _exclude_from_git(folder)
    return {"folder": folder, "source": resolve_source(folder)}


def _assert_can_commit(repo):
    try:
        git_dir = _git(repo, "rev-parse", "--git-dir")
    except subprocess.CalledProcessError:
        raise ProfileError(409, "%s is not a git repository; cannot commit the profile" % repo)
    if not os.path.isabs(git_dir):
        git_dir = os.path.join(repo, git_dir)
    try:
        _git(repo, "symbolic-ref", "-q", "HEAD")
    except subprocess.CalledProcessError:
        raise ProfileError(409, "%s has a detached HEAD; check out a branch first" % repo)
    for name, what in (("MERGE_HEAD", "a merge"), ("CHERRY_PICK_HEAD", "a cherry-pick"),
                       ("rebase-merge", "a rebase"), ("rebase-apply", "a rebase")):
        if os.path.exists(os.path.join(git_dir, name)):
            raise ProfileError(409, "%s is in the middle of %s; finish it first" % (repo, what))
    if os.path.exists(os.path.join(git_dir, "index.lock")):
        raise ProfileError(409, "%s has an index.lock; another git command is running or crashed" % repo)
    try:
        _git(repo, "show-ref", "--verify", "--quiet", "refs/heads/pr-tip")
    except subprocess.CalledProcessError:
        return
    # A pr-tip branch means an uncommit flow is open: the index is the reviewed set and HEAD is its base.
    raise ProfileError(409, "an uncommit flow is open in %s (a pr-tip branch exists); finish it first" % tilde(repo))


def _merge_list(old, managed, wanted):
    """Keep existing entries in their order, drop one only when the page manages it and the request leaves it
    out, then append what the request newly adds."""
    out = []
    for x in [x for x in old if x not in managed or x in wanted] + list(wanted):
        if x not in out:
            out.append(x)
    return out


def _string_list(body, key):
    v = body.get(key)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ProfileError(400, "%s must be a list of strings" % key)
    out = []
    for x in v:
        if x not in out:
            out.append(x)
    return out


def save_profile(cfg, cache, body):
    """Rewrite a profile's .args and .json from the page's switches, commit only those two files in the
    profile's repository, and push when it has a remote."""
    name = body.get("name")
    if not _profile_exists(cfg, name):
        raise ProfileError(404, "no profile named %s" % name)
    plugin_dirs = _string_list(body, "pluginDirs")
    denied = _string_list(body, "denied")
    disabled = _string_list(body, "disabledPlugins")
    args_path, json_path = profile_files(cfg, name)
    with open(args_path) as f:
        args_text = f.read()
    if not standard_args(args_text):
        raise ProfileError(409, "%s holds more than plugin dirs, MCP config files and one settings file; "
                                "edit it by hand" % args_path)
    if os.path.exists(json_path):
        try:
            with open(json_path) as f:
                js = json.load(f)
        except ValueError:
            js = None
        if not isinstance(js, dict):
            raise ProfileError(409, "%s is not a JSON object; fix it by hand" % json_path)
    else:
        js = {}
    before = next(p for p in read_profiles(cfg) if p["name"] == name)
    mcp, err = cache.mcp_list(False)
    # Without the server list every deny entry looks unmanaged, and a server just switched on would stay off.
    if err:
        raise ProfileError(503, "MCP server list unavailable; press Refresh tools and retry")
    tools = build_tools(cfg, mcp)
    known = lambda kind: {t["id"] for t in tools if t["kind"] == kind}  # noqa: E731
    dirs, servers, plugins = known("pluginDir"), known("mcp"), known("plugin")
    for d in cfg.locked:
        if d not in plugin_dirs:
            raise ProfileError(400, "%s cannot be switched off" % d)
    unknown = [d for d in plugin_dirs if d not in dirs and d not in before["pluginDirs"]] \
        + [d for d in denied if d not in servers and d not in before["denied"]] \
        + [p for p in disabled if p not in plugins and p not in before["disabledPlugins"]]
    if unknown:
        raise ProfileError(400, "unknown tools: %s" % ", ".join(unknown))
    pdir, repo = cfg.profile_home(name)
    _assert_can_commit(repo)

    args = parse_args(args_text)
    new_dirs = _merge_list(args["plugin_dirs"], dirs, plugin_dirs)
    settings_path = "%s/%s.json" % (tilde(pdir), name)
    if new_dirs != args["plugin_dirs"] or args["settings"] != settings_path:
        write_atomic(args_path, format_args(dict(args, plugin_dirs=new_dirs, settings=settings_path)))

    perms = js.get("permissions") if isinstance(js.get("permissions"), dict) else {}
    old_deny = [d for d in perms.get("deny") if isinstance(d, str)] if isinstance(perms.get("deny"), list) else []
    new_deny = _merge_list(old_deny, servers, denied)
    nxt = dict(js)
    if new_deny != old_deny or ("deny" in perms and not isinstance(perms["deny"], list)):
        nxt["permissions"] = dict(perms, deny=new_deny)
    old_enabled = js.get("enabledPlugins") if isinstance(js.get("enabledPlugins"), dict) else {}
    enabled = {}
    for k, v in old_enabled.items():
        if k not in plugins:
            enabled[k] = v
        elif k in disabled:
            enabled[k] = False
        elif v is not False:
            enabled[k] = v
    for k in disabled:
        enabled.setdefault(k, False)
    if enabled != old_enabled:
        if enabled:
            nxt["enabledPlugins"] = enabled
        else:
            nxt.pop("enabledPlugins", None)
    if nxt != js or not os.path.exists(json_path):
        write_atomic(json_path, json.dumps(nxt, indent=2, ensure_ascii=False) + "\n")

    paths = [os.path.relpath(args_path, repo), os.path.relpath(json_path, repo)]
    remote = _has_remote(repo)
    if not _git(repo, "status", "--porcelain", "--", *paths):
        return {"committed": False, "commit": None, "message": None, "pushed": False, "pushError": None,
                "hasRemote": remote}
    message = commit_message(name, before, {"pluginDirs": plugin_dirs, "denied": denied,
                                            "disabledPlugins": disabled}, tools)
    # Naming the paths commits only them, so another session's staged or unstaged work never rides along; `add`
    # runs on untracked paths only, so a refused commit leaves the index as it was.
    untracked = []
    for p in paths:
        if os.path.exists(os.path.join(repo, p)):
            try:
                _git(repo, "ls-files", "--error-unmatch", "--", p)
            except subprocess.CalledProcessError:
                untracked.append(p)
    try:
        if untracked:
            _git(repo, "add", "--", *untracked)
        _git(repo, "commit", "--only", "-q", "-m", message, "--", *paths)
    except subprocess.CalledProcessError as e:
        raise ProfileError(409, "saved, not committed: %s" % ((e.stderr or e.stdout or str(e)).strip()[-500:]))
    commit = _git(repo, "rev-parse", "--short", "HEAD")
    res = {"committed": True, "commit": commit, "message": message, "pushed": False, "pushError": None,
           "hasRemote": remote}
    if not remote:
        return res
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -oBatchMode=yes")
    try:
        r = subprocess.run(["git", "-C", repo, "push", "-q"], capture_output=True, text=True, timeout=180, env=env,
                           stdin=subprocess.DEVNULL)
        if r.returncode == 0:
            res["pushed"] = True
        else:
            res["pushError"] = (r.stderr or r.stdout or "exit %d" % r.returncode).strip()[-500:]
    except subprocess.TimeoutExpired:
        res["pushError"] = "push timed out after 180s"
    return res
