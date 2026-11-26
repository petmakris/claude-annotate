"""The tools inventory: every skill, command, agent, MCP server, hook and output style a machine's sessions can reach,
who provides it, where it lives, which launch profile turns it on and which account has it (stdlib only; `fleet.py`
wraps it as `fleet tools` and `GET /api/tools`, and imports nothing from here but the functions below).

`scan(ctx)` reads one machine, read-only: it never writes a file, never installs or enables anything, and reads
no MCP server's env, headers or arguments (only its name and transport). `merge(answers, ...)` joins the machines'
scans into one list: an item is one row with the machines that have it, and the findings are worked out on the
joined list.

What a scan reads (all under the user's home):

- accounts: `~/.config/env/claude-accounts` (one name per line, `default <name>` and `#` lines skipped; the first
  is `~/.claude`, any other `~/.claude-<name>`; with no file, `~/.claude` is the account `default`); a
  `~/.claude-<x>` folder holding a settings.json and not listed is an account `listed: false`.
- per account: settings.json (enabledPlugins, hooks, statusLine, deniedMcpServers, permissions.deny),
  plugins/installed_plugins.json and known_marketplaces.json, skills/, commands/, agents/, output-styles/, and the
  account's .claude.json (`~/.claude.json` for `~/.claude`, else `<dir>/.claude.json`): mcpServers names, the
  projects' mcpServers names and claudeAiMcpEverConnected.
- plugin roots: the --plugin-dir folders of every launch profile and the launcher's defaults, and every installed
  marketplace plugin: skills/*/SKILL.md (and one level deeper), commands/*.md, agents/*.md, hooks/hooks.json,
  .mcp.json, output-styles/*.md, plus what plugin.json declares. A root with only a marketplace.json loads the
  entries whose source is "./".
- projects: `~/projects/*` (and `~/projects/<group>/*` for a group folder that is no repository): .claude/skills,
  .claude/agents, .claude/commands, .claude/settings.json hooks and .mcp.json.
- launch profiles: fleet_profiles (profiles.json; without one, the env checkout's own profiles), each profile's
  .args and settings file.
- hook sources: `~/.claude/hooks/<x>` is compared with the same name in the hook source folder (tools.json
  `hook_sources`, else `<env>/claude/user-hooks`): `same`, `drifted` or `no source`.

$FLEET_HOME/tools.json holds what is the user's own and never in this repository: `company` (strings matched, case
blind, inside an item's provider or name), `company_label`, `hook_sources`, and `scan_home` (the home a scan reads,
for a test's fake machine; default the user's home). A satellite machine (an entry in
machines.json with `"satellite": true`) is never asked: it has nothing of its own.
"""
import glob
import hashlib
import json
import os
import re
import time

import fleet_profiles as prof

KINDS = ("skill", "command", "agent", "MCP server", "hook", "output style")
DEFAULT_PROFILE = "default"
PURPOSE_MAX = 280
CONNECTOR = "claude.ai connectors"
BUILTIN = "Claude Code built-in"
# Claude Code's own skills and agents have no file on disk; this list is kept by hand from a session's listing so
# that a plugin item of the same name shows as a duplicate.
BUILTINS = (
    ("skill", "update-config", "Configure the Claude Code harness through settings.json: hooks, permissions, env."),
    ("skill", "keybindings-help", "Customize keyboard shortcuts in keybindings.json."),
    ("skill", "code-review", "Review the current diff or a PR for correctness bugs at a chosen effort level."),
    ("skill", "simplify", "Review changed code for reuse, simplification and efficiency, then apply fixes."),
    ("skill", "fewer-permission-prompts", "Scan transcripts for read-only calls and add an allowlist."),
    ("skill", "claude-approvals", "Create or explain a Claude Approvals policy file."),
    ("skill", "loop", "Run a prompt or slash command on a recurring interval."),
    ("skill", "schedule", "Create, update, list or run cloud scheduled tasks."),
    ("skill", "claude-api", "Reference for the Claude API and the Anthropic SDK."),
    ("skill", "workflow-authoring", "Reference for writing a Workflow tool script."),
    ("skill", "run", "Launch and drive the project's app to see a change working."),
    ("skill", "plugin-authoring", "Make a mod: a theme, panel, status line, slash command or hook."),
    ("skill", "init", "Write a CLAUDE.md for the project."),
    ("skill", "security-review", "Security review of the pending changes."),
    ("skill", "dataviz", "Charts, plots and dashboards: palette, marks, accessibility."),
    ("agent", "claude", "Catch-all agent for tasks that fit no specific agent."),
    ("agent", "Explore", "Read-only search agent for broad searches."),
    ("agent", "general-purpose", "General-purpose researcher and multi-step executor."),
    ("agent", "Plan", "Architect agent that designs implementation plans."),
    ("agent", "statusline-setup", "Configures the Claude Code status line."),
    ("agent", "web-fetch", "Fetches and reads public web pages."),
)


# ---------------------------------------------------------------- small readers

def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            v = json.load(f)
    except (OSError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def read_text(path, limit=65536):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return None


def frontmatter(path):
    """The YAML front matter of a markdown file as flat strings (folded lines joined). With none, the first line
    of prose is the description."""
    text = read_text(path)
    if text is None:
        return {}
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return {"description": line[:300]}
        return {}
    out, key = {}, None
    for line in m.group(1).splitlines():
        km = re.match(r"^([A-Za-z_-]+):\s*(.*)$", line)
        if km and not line.startswith(" "):
            key, v = km.group(1), km.group(2).strip()
            out[key] = "" if v in (">", "|", ">-", "|-") else v.strip("\"'")
        elif key and line.strip():
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


def purpose(meta):
    s = re.sub(r"\s+", " ", meta.get("description", "")).strip()
    return s[:PURPOSE_MAX] + ("…" if len(s) > PURPOSE_MAX else "")


def truthy(v):
    return v is True or str(v).lower() == "true"


def file_hash(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def real(p):
    return os.path.realpath(os.path.expanduser(p))


def hook_name(cmd):
    """A hook's short name: the script it runs (with its first plain argument when the script is a dispatcher such
    as `run-hook.cmd session-start`), else its first 50 characters."""
    words = [w.strip("\"'") for w in cmd.split()]
    for i, t in enumerate(words):
        if "/" in t or re.search(r"\.(mjs|sh|py|js|cjs|ts|cmd)$", t):
            name = os.path.basename(t)
            if not re.match(r"^[A-Za-z0-9_][\w.-]*$", name):
                continue
            nxt = words[i + 1] if i + 1 < len(words) else ""
            if not re.search(r"\.(mjs|sh|py|js|cjs|ts)$", name) and re.match(r"^[a-z][a-z0-9-]*$", nxt):
                name += " " + nxt
            return name
    return cmd[:50]


def hook_entries(hooks):
    """{command: [event[matcher], ...]} of a settings or hooks.json `hooks` object."""
    by = {}
    if not isinstance(hooks, dict):
        return by
    for ev, lst in hooks.items():
        for e in lst if isinstance(lst, list) else []:
            if not isinstance(e, dict):
                continue
            for hk in e.get("hooks") or []:
                if isinstance(hk, dict) and isinstance(hk.get("command"), str):
                    tag = ev + ("[%s]" % e["matcher"] if e.get("matcher") else "")
                    if tag not in by.setdefault(hk["command"], []):
                        by[hk["command"]].append(tag)
    return by


def server_names(obj):
    """{name: transport} of an mcpServers object. Only the name and transport are read, never env, headers or args."""
    out = {}
    if isinstance(obj, dict):
        for name, v in obj.items():
            if isinstance(name, str):
                t = v.get("type") if isinstance(v, dict) else None
                if not isinstance(t, str):
                    t = "http" if isinstance(v, dict) and v.get("url") else "stdio"
                out[name] = t
    return out


# ---------------------------------------------------------------- context

class Ctx:
    """Where one machine's files are. Tests build one on a temp home."""

    def __init__(self, home=None, fleet_home=None, machine="here", env_dir=None, profiles_conf=None, conf=None,
                 projects=None):
        self.home = home or os.path.expanduser("~")
        self.fleet_home = fleet_home or os.path.join(self.home, ".claude", "fleet")
        self.machine = machine
        self.env_dir = env_dir if env_dir is not None else os.path.join(self.home, "projects", "env")
        self.profiles_conf = profiles_conf if profiles_conf is not None else prof.settings(self.fleet_home)
        self.conf = conf if conf is not None else read_json(os.path.join(self.fleet_home, "tools.json"))
        self.projects = projects or os.path.join(self.home, "projects")

    def tilde(self, p):
        p = str(p)
        if p == self.home:
            return "~"
        return "~" + p[len(self.home):] if p.startswith(self.home + "/") else p

    def untilde(self, p):
        p = str(p)
        if p == "~":
            return self.home
        return os.path.join(self.home, p[2:]) if p.startswith("~/") else p


def accounts_of(ctx):
    """[{name, dir, listed}] in the machine's order. A `~/.claude-<x>` folder with its own settings.json and no
    line in the accounts file is an account too, `listed: false`."""
    names = []
    text = read_text(os.path.join(ctx.home, ".config", "env", "claude-accounts"))
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and " " not in line and line not in names:
            names.append(line)
    out = []
    for i, n in enumerate(names):
        d = os.path.join(ctx.home, ".claude" if i == 0 else ".claude-" + n)
        if os.path.isdir(d):
            out.append({"name": n, "dir": d, "listed": True})
    if not out and os.path.isdir(os.path.join(ctx.home, ".claude")):
        out.append({"name": "default", "dir": os.path.join(ctx.home, ".claude"), "listed": False})
    known = {real(a["dir"]) for a in out}
    for d in sorted(glob.glob(os.path.join(ctx.home, ".claude-*"))):
        if os.path.isdir(d) and real(d) not in known and os.path.isfile(os.path.join(d, "settings.json")):
            out.append({"name": os.path.basename(d)[len(".claude-"):], "dir": d, "listed": False})
    return out


def claude_json(ctx, acct):
    if real(acct["dir"]) == real(os.path.join(ctx.home, ".claude")):
        return read_json(os.path.join(ctx.home, ".claude.json"))
    return read_json(os.path.join(acct["dir"], ".claude.json"))


# ---------------------------------------------------------------- profiles

def profile_config(ctx):
    conf = dict(ctx.profiles_conf or {})
    if not conf.get("roots") and os.path.isdir(os.path.join(ctx.env_dir, "claude", "profiles")):
        # No profiles.json on this machine: the env checkout's own profiles, as the launcher finds them.
        conf = dict(conf, roots=[ctx.env_dir], roots_file=conf.get("roots_file") or "~/.env-profiles")
    return conf


def read_profiles(ctx):
    """[{name, repo, source, plugin_dirs (real paths), plugin_dirs_shown, enabled {key: bool}, deny [prefix],
    denied_servers [name], connectors (bool), mcp_configs [path]}], the launcher's default last. Every ~ is this
    scan's home, never the process's."""
    conf = profile_config(ctx)
    roots = [ctx.untilde(r) for r in conf.get("roots") or [] if isinstance(r, str)]
    if isinstance(conf.get("roots_file"), str):
        for line in (read_text(ctx.untilde(conf["roots_file"])) or "").split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and "/" in line:
                roots.append(ctx.untilde(line))
    homes = {}
    for r in roots:
        d = os.path.join(r, "claude", "profiles")
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.endswith(".args"):
                    homes.setdefault(f[:-5], (d, r))
    out = []
    for name in sorted(homes):
        d, repo = homes[name]
        args_path = os.path.join(d, name + ".args")
        args = prof.parse_args(read_text(args_path) or "")
        named = ctx.untilde(args["settings"]) if args["settings"] else ""
        js_path = named if os.path.dirname(named) == d and named.endswith(".json") else os.path.join(d, name + ".json")
        out.append(profile_entry(ctx, name, repo, args["plugin_dirs"], read_json(js_path), args["mcp_configs"],
                                 ctx.tilde(args_path)))
    defaults = [d for d in conf.get("default_dirs") or [] if isinstance(d, str)] or launcher_defaults(ctx)
    if DEFAULT_PROFILE not in [p["name"] for p in out]:
        out.append(profile_entry(ctx, DEFAULT_PROFILE, None, defaults, {}, [], "the launcher's defaults"))
    return out


def launcher_defaults(ctx):
    """The --plugin-dir folders in the env launcher's CLAUDE_LAUNCH_DEFAULT_ARGS, read only when profiles.json names
    no default_dirs (the plugin dirs a folder with no .claude-launch gets)."""
    text = read_text(os.path.join(ctx.env_dir, "libexec", "claude", "launch")) or ""
    m = re.search(r"CLAUDE_LAUNCH_DEFAULT_ARGS=\((.*?)\n\)", text, re.S)
    out = []
    for line in (m.group(1) if m else "").splitlines():
        d = re.match(r'\s*--plugin-dir\s+"?([^"\s]+)"?', line)
        if d:
            out.append(d.group(1).replace("$ENV_DIR", ctx.env_dir).replace("${ENV_DIR}", ctx.env_dir))
    return out


def profile_entry(ctx, name, repo, plugin_dirs, js, mcp_configs, source):
    perms = js.get("permissions") if isinstance(js.get("permissions"), dict) else {}
    deny = [d for d in perms.get("deny") or [] if isinstance(d, str) and d.startswith("mcp__")]
    enabled = js.get("enabledPlugins") if isinstance(js.get("enabledPlugins"), dict) else {}
    env = js.get("env") if isinstance(js.get("env"), dict) else {}
    return {"name": name, "repo": ctx.tilde(repo) if repo else None, "source": source,
            "plugin_dirs": [real(ctx.untilde(d)) for d in plugin_dirs],
            "plugin_dirs_shown": [ctx.tilde(ctx.untilde(d)) for d in plugin_dirs],
            "enabled": {k: v for k, v in enabled.items() if isinstance(v, bool)}, "deny": deny,
            "denied_servers": denied_server_names(js),
            "connectors": str(env.get("ENABLE_CLAUDEAI_MCP_SERVERS", "")).lower() not in ("false", "0"),
            "mcp_configs": [ctx.untilde(m) for m in mcp_configs]}


def denied_server_names(settings):
    out = []
    for d in settings.get("deniedMcpServers") or []:
        n = d.get("serverName") if isinstance(d, dict) else d
        if isinstance(n, str):
            out.append(n)
    return out


def mcp_prefix(name, plugin=None):
    if plugin:
        return "mcp__plugin_%s_%s" % (re.sub(r"[^A-Za-z0-9_-]", "_", plugin), re.sub(r"[^A-Za-z0-9_-]", "_", name))
    return prof.mcp_deny_prefix(name)


def denied_by(p, name, prefix):
    if name in p["denied_servers"]:
        return True
    return any(prefix == d or prefix.startswith(d + "__") for d in p["deny"])


# ---------------------------------------------------------------- the scan

class Scan:
    def __init__(self, ctx):
        self.ctx = ctx
        self.items = {}
        self.providers = {}
        self.notes = []
        self.copies = {}
        self.accounts = accounts_of(ctx)
        self.profiles = read_profiles(ctx)
        self.all_profiles = [p["name"] for p in self.profiles]
        self.acct_names = [a["name"] for a in self.accounts]
        self.settings = {a["name"]: read_json(os.path.join(a["dir"], "settings.json")) for a in self.accounts}

    # -- items and providers

    def provider(self, name, ptype, root=None, repo=None, **extra):
        p = self.providers.setdefault(name, {"name": name, "type": ptype, "root": self.ctx.tilde(root) if root else None,
                                             "repo": repo, "profiles": [], "accounts": [], "installed": True})
        p.update({k: v for k, v in extra.items() if v is not None})
        return p

    def add(self, kind, name, provider, path, profiles, accounts, invocation, meta=None, scope=None, **extra):
        key = "|".join([kind, provider, name, scope or ""])
        item = self.items.get(key)
        if item is None:
            meta = meta or {}
            item = {"key": key, "kind": kind, "name": name, "provider": provider,
                    "provider_type": self.providers.get(provider, {}).get("type", "user"),
                    "repo": self.providers.get(provider, {}).get("repo"), "path": self.ctx.tilde(path) if path else "",
                    "invocation": invocation, "purpose": extra.pop("purpose", None) or purpose(meta),
                    "manual": truthy(meta.get("disable-model-invocation")), "profiles": [], "accounts": [],
                    "scope": self.ctx.tilde(scope) if scope else None}
            self.items[key] = item
        for k, v in extra.items():
            if v is not None:
                item[k] = v
        merge_list(item["profiles"], profiles)
        merge_list(item["accounts"], accounts)
        prov = self.providers.get(provider)
        if prov is not None:
            merge_list(prov["profiles"], profiles)
            merge_list(prov["accounts"], accounts)
        return item

    # -- one plugin root

    def plugin_root(self, root, provider, plugin, profiles, accounts, manifest=None, skill_dirs=None, hooks=True):
        """Every item a plugin root carries. `plugin` is the name its invocations start with."""
        manifest = manifest if manifest is not None else read_json(os.path.join(root, ".claude-plugin", "plugin.json"))
        if skill_dirs is None:
            skill_dirs = [os.path.dirname(s) for s in glob.glob(os.path.join(root, "skills", "*", "SKILL.md"))
                          + glob.glob(os.path.join(root, "skills", "*", "*", "SKILL.md"))]
            for extra in manifest.get("skills") or [] if isinstance(manifest.get("skills"), list) else []:
                d = os.path.normpath(os.path.join(root, extra))
                if os.path.isfile(os.path.join(d, "SKILL.md")):
                    skill_dirs.append(d)
                else:
                    skill_dirs += [os.path.dirname(s) for s in glob.glob(os.path.join(d, "*", "SKILL.md"))]
        for d in sorted(set(skill_dirs)):
            if os.path.basename(d).startswith("_"):
                continue
            f = os.path.join(d, "SKILL.md")
            if not os.path.isfile(f):
                continue
            meta = frontmatter(f)
            name = meta.get("name") or os.path.basename(d)
            self.add("skill", name, provider, f, profiles, accounts, "/%s:%s" % (plugin, name), meta)
        for f in sorted(glob.glob(os.path.join(root, "commands", "*.md"))):
            name = os.path.basename(f)[:-3]
            self.add("command", name, provider, f, profiles, accounts, "/%s:%s" % (plugin, name), frontmatter(f))
        for f in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
            meta = frontmatter(f)
            name = meta.get("name") or os.path.basename(f)[:-3]
            self.add("agent", name, provider, f, profiles, accounts, "%s:%s" % (plugin, name), meta)
        for f in sorted(glob.glob(os.path.join(root, "output-styles", "*.md"))):
            meta = frontmatter(f)
            name = meta.get("name") or os.path.basename(f)[:-3]
            self.add("output style", name, provider, f, profiles, accounts, "outputStyle: %s" % name, meta)
        if hooks:
            for hj in [os.path.join(root, "hooks", "hooks.json"), os.path.join(root, ".claude-plugin", "hooks.json")]:
                if os.path.isfile(hj):
                    h = read_json(hj)
                    for cmd, evs in hook_entries(h.get("hooks")).items():
                        self.add("hook", hook_name(cmd), provider, hj, profiles, accounts, "automatic",
                                 purpose=(h.get("description") if isinstance(h.get("description"), str) else None)
                                 or "Runs on " + ", ".join(evs), events=evs)
        servers = server_names(read_json(os.path.join(root, ".mcp.json")).get("mcpServers")
                               or read_json(os.path.join(root, ".mcp.json")))
        if isinstance(manifest.get("mcpServers"), dict):
            servers.update(server_names(manifest["mcpServers"]))
        elif isinstance(manifest.get("mcpServers"), str):
            servers.update(server_names(read_json(os.path.join(root, manifest["mcpServers"])).get("mcpServers")))
        for name, transport in sorted(servers.items()):
            pre = mcp_prefix(name, plugin)
            on = [p for p in profiles if not denied_by(self.profile(p), name, pre)]
            self.add("MCP server", name, provider, os.path.join(root, ".mcp.json"), on, accounts, pre + "__*",
                     purpose="MCP server of the %s plugin (%s)." % (plugin, transport), transport=transport,
                     denied=[p for p in profiles if p not in on] or None)

    def profile(self, name):
        return next(p for p in self.profiles if p["name"] == name)

    # -- plugin dirs of the launcher

    def plugin_dirs(self):
        roots = []
        for p in self.profiles:
            for d in p["plugin_dirs"]:
                if d not in roots:
                    roots.append(d)
        for root in roots:
            on = [p["name"] for p in self.profiles if root in p["plugin_dirs"]]
            if not os.path.isdir(root):
                self.notes.append("plugin dir %s of %s is missing" % (self.ctx.tilde(root), ", ".join(on)))
                continue
            manifest = read_json(os.path.join(root, ".claude-plugin", "plugin.json"))
            market = read_json(os.path.join(root, ".claude-plugin", "marketplace.json"))
            repo = repo_of(root)
            if manifest:
                name = manifest.get("name") if isinstance(manifest.get("name"), str) else os.path.basename(root)
                self.provider(name, "plugin dir", root, repo, enabled_by="--plugin-dir in " + ", ".join(on))
                self.plugin_root(root, name, name, on, self.acct_names, manifest)
            elif market:
                name = market.get("name") if isinstance(market.get("name"), str) else os.path.basename(root)
                self.provider(name, "plugin dir", root, repo, enabled_by="--plugin-dir in " + ", ".join(on))
                dirs, entries = [], []
                for e in market.get("plugins") or []:
                    if isinstance(e, dict) and e.get("source") in ("./", "."):
                        entries.append(e.get("name"))
                        if isinstance(e.get("skills"), list):
                            dirs += [os.path.normpath(os.path.join(root, s)) for s in e["skills"] if isinstance(s, str)]
                self.plugin_root(root, name, name, on, self.acct_names, {}, skill_dirs=dirs or None)
            else:
                name = os.path.basename(root)
                self.provider(name, "plugin dir", root, repo, enabled_by="--plugin-dir in " + ", ".join(on))
                self.plugin_root(root, name, name, on, self.acct_names, {})

    # -- marketplace plugins

    def installed_plugins(self):
        plugin_dir_reals = {d for p in self.profiles for d in p["plugin_dirs"]}
        seen_files = {}
        for a in self.accounts:
            path = real(os.path.join(a["dir"], "plugins", "installed_plugins.json"))
            seen_files.setdefault(path, []).append(a["name"])
        for path, accts in seen_files.items():
            data = read_json(path).get("plugins")
            markets = read_json(os.path.join(os.path.dirname(path), "known_marketplaces.json"))
            for key, entries in sorted((data or {}).items()):
                if not isinstance(entries, list) or "@" not in key:
                    continue
                pname, market = key.split("@", 1)
                user = next((e for e in entries if isinstance(e, dict) and e.get("scope") == "user"), None)
                entry = user or next((e for e in entries if isinstance(e, dict)), None)
                if not entry or not isinstance(entry.get("installPath"), str):
                    continue
                root = entry["installPath"]
                msrc = markets.get(market, {}).get("source", {}) if isinstance(markets.get(market), dict) else {}
                if msrc.get("source") == "directory" and isinstance(msrc.get("path"), str):
                    # A directory marketplace loads its plugins straight from the checkout.
                    live = os.path.normpath(os.path.join(msrc["path"], self.market_source(msrc["path"], pname) or "."))
                    if os.path.isdir(live):
                        root = live
                if real(root) in plugin_dir_reals or not os.path.isdir(root):
                    continue
                profiles, accounts = [], []
                for an in accts:
                    on_user = (self.settings.get(an, {}).get("enabledPlugins") or {}).get(key)
                    for p in self.profiles:
                        if p["enabled"].get(key, on_user is True) and p["name"] not in profiles:
                            profiles.append(p["name"])
                    if on_user is True or any(p["enabled"].get(key) for p in self.profiles):
                        accounts.append(an)
                scope = None if user else entry.get("projectPath")
                repo = repo_of(root) or msrc.get("repo") or msrc.get("path") or market
                setting = [an + "=" + str((self.settings.get(an, {}).get("enabledPlugins") or {}).get(key)).lower()
                           for an in accts]
                self.provider(pname, "plugin", root, repo, marketplace=market, version=entry.get("version"),
                              enabled_by="enabledPlugins %s (%s)" % (key, ", ".join(setting)),
                              scope=self.ctx.tilde(scope) if scope else None)
                if scope:
                    profiles = []
                self.plugin_root(root, pname, pname, profiles, accounts or accts)
                merge_list(self.providers[pname]["accounts"], accts if not accounts else [])
                self.providers[pname]["enabled_accounts"] = accounts

    def market_source(self, market_root, pname):
        m = read_json(os.path.join(market_root, ".claude-plugin", "marketplace.json"))
        for e in m.get("plugins") or []:
            if isinstance(e, dict) and e.get("name") == pname and isinstance(e.get("source"), str):
                return e["source"]
        return None

    # -- the accounts' own folders

    def user_level(self):
        by_dir = {}
        for a in self.accounts:
            by_dir.setdefault(real(a["dir"]), []).append(a["name"])
        plugin_files = {real(i["path"].replace("~", self.ctx.home, 1)) for i in self.items.values() if i["path"]}
        for d, accts in by_dir.items():
            for f in sorted(glob.glob(os.path.join(d, "skills", "*", "SKILL.md"))):
                meta = frontmatter(f)
                name = meta.get("name") or os.path.basename(os.path.dirname(f))
                self.provider("user skills", "user", None, None)
                self.add("skill", name, "user skills", f, self.all_profiles, accts, "/" + name, meta)
            for f in sorted(glob.glob(os.path.join(d, "commands", "*.md"))):
                name = os.path.basename(f)[:-3]
                self.provider("user commands", "user", None, None)
                self.add("command", name, "user commands", f, self.all_profiles, accts, "/" + name, frontmatter(f))
            for f in sorted(glob.glob(os.path.join(d, "agents", "*.md"))):
                meta = frontmatter(f)
                name = meta.get("name") or os.path.basename(f)[:-3]
                self.provider("user agents", "user", None, None)
                self.add("agent", name, "user agents", f, self.all_profiles, accts, name, meta)
            for f in sorted(glob.glob(os.path.join(d, "output-styles", "*.md"))):
                meta = frontmatter(f)
                name = meta.get("name") or os.path.basename(f)[:-3]
                if real(f) in plugin_files:
                    for i in self.items.values():
                        if i["kind"] == "output style" and i["path"] and real(self.ctx.untilde(i["path"])) == real(f):
                            i["notes"] = "Linked into %s/output-styles." % self.ctx.tilde(d)
                            merge_list(i["profiles"], self.all_profiles)
                            merge_list(i["accounts"], accts)
                    continue
                self.provider("user output styles", "user", None, None)
                self.add("output style", name, "user output styles", f, self.all_profiles, accts,
                         "outputStyle: " + name, meta)

    def settings_hooks(self):
        sources = [self.ctx.untilde(s) for s in self.ctx.conf.get("hook_sources") or [] if isinstance(s, str)] \
            or [os.path.join(self.ctx.env_dir, "claude", "user-hooks")]
        by_file = {}
        for a in self.accounts:
            by_file.setdefault(real(os.path.join(a["dir"], "settings.json")), []).append(a["name"])
        for path, accts in by_file.items():
            s = read_json(path)
            for cmd, evs in hook_entries(s.get("hooks")).items():
                name = hook_name(cmd)
                script = self.ctx.untilde(cmd.split()[0]) if cmd.split() else ""
                drift = None
                if os.path.isfile(script) and script.endswith(name):
                    src = next((os.path.join(sd, name) for sd in sources if os.path.isfile(os.path.join(sd, name))),
                               None)
                    drift = "no source" if not src else "same" if file_hash(src) == file_hash(script) else "drifted"
                    source = self.ctx.tilde(src) if src else None
                else:
                    source = None
                self.provider("user hooks", "user", None, None)
                self.add("hook", name, "user hooks", script if os.path.isfile(script) else path, self.all_profiles,
                         accts, "automatic", purpose="Settings hook on " + ", ".join(evs), events=evs,
                         drift=drift, source=source)
            sl = s.get("statusLine")
            if isinstance(sl, dict) and isinstance(sl.get("command"), str):
                self.provider("user hooks", "user", None, None)
                cmd = sl["command"]
                self.add("hook", hook_name(cmd), "user hooks", self.ctx.untilde(cmd.split()[0]), self.all_profiles,
                         accts, "statusLine command", purpose="The status line.", events=["statusLine"])

    def mcp_servers(self):
        by_file = {}
        for a in self.accounts:
            cj = os.path.join(self.ctx.home, ".claude.json") \
                if real(a["dir"]) == real(os.path.join(self.ctx.home, ".claude")) else os.path.join(a["dir"], ".claude.json")
            by_file.setdefault(real(cj), (cj, []))[1].append(a["name"])
        for _, (cj, accts) in by_file.items():
            data = read_json(cj)
            global_denied = set()
            for an in accts:
                global_denied.update(denied_server_names(self.settings.get(an, {})))
            for name, transport in sorted(server_names(data.get("mcpServers")).items()):
                pre = mcp_prefix(name)
                on = [p["name"] for p in self.profiles if not denied_by(p, name, pre) and name not in global_denied]
                self.provider("user MCP servers", "user", None, None)
                self.add("MCP server", name, "user MCP servers", cj, on, accts, pre + "__*",
                         purpose="User MCP server (%s)." % transport, transport=transport,
                         denied=[p for p in self.all_profiles if p not in on] or None)
            for name in data.get("claudeAiMcpEverConnected") or []:
                if not isinstance(name, str):
                    continue
                pre = mcp_prefix(name)
                on = [p["name"] for p in self.profiles if p["connectors"] and not denied_by(p, name, pre)
                      and name not in global_denied]
                self.provider(CONNECTOR, "connector", None, "claude.ai account")
                self.add("MCP server", name, CONNECTOR, cj, on, accts, pre + "__*",
                         purpose="claude.ai connector of the account.", transport="connector",
                         denied=[p for p in self.all_profiles if p not in on] or None)
            for folder, pdata in sorted((data.get("projects") or {}).items()):
                if not isinstance(pdata, dict):
                    continue
                for name, transport in sorted(server_names(pdata.get("mcpServers")).items()):
                    self.project_server(folder, name, transport, cj, accts)

    def project_server(self, folder, name, transport, path, accts):
        prof_name = self.folder_profile(folder)
        pre = mcp_prefix(name)
        on = [prof_name] if prof_name and not denied_by(self.profile(prof_name), name, pre) else []
        label = "project: " + os.path.basename(folder.rstrip("/"))
        self.provider(label, "project", folder, repo_of(folder))
        self.add("MCP server", name, label, path, on, accts, pre + "__*", scope=folder,
                 purpose="Project MCP server (%s)." % transport, transport=transport)

    def folder_profile(self, folder):
        name = launch_profile(folder)[0] or DEFAULT_PROFILE
        return name if name in self.all_profiles else None

    def profile_mcp_configs(self):
        for p in self.profiles:
            for cfg in p["mcp_configs"]:
                for name, transport in sorted(server_names(read_json(cfg).get("mcpServers")).items()):
                    label = "profile %s" % p["name"]
                    self.provider(label, "profile", cfg, repo_of(cfg))
                    self.add("MCP server", name, label, cfg, [p["name"]], self.acct_names, mcp_prefix(name) + "__*",
                             purpose="MCP server the %s profile adds (%s)." % (p["name"], transport),
                             transport=transport)

    def project_dirs(self):
        """Every ~/projects/<x>, and the folders of a group folder (one that is no repository). A worktree, or a
        group folder's clone of a repository a top folder already holds, is a copy: it is counted on that folder's
        provider (`copies`), not scanned again."""
        top, grouped = [], []
        for d in sorted(glob.glob(os.path.join(self.ctx.projects, "*"))):
            if not os.path.isdir(d) or os.path.basename(d).startswith("."):
                continue
            top.append(d)
            if not os.path.exists(os.path.join(d, ".git")) and not os.path.isdir(os.path.join(d, ".claude")):
                grouped += [s for s in sorted(glob.glob(os.path.join(d, "*"))) if os.path.isdir(s)]
        origins, out = {}, []
        for d in top:
            o = git_origin(d)
            if o and o in origins:
                self.copies.setdefault(origins[o], []).append(self.ctx.tilde(d))
                continue
            if o:
                origins[o] = d
            out.append(d)
        for d in grouped:
            o = git_origin(d)
            if os.path.isfile(os.path.join(d, ".git")) or o and o in origins:
                if o in origins:
                    self.copies.setdefault(origins[o], []).append(self.ctx.tilde(d))
                continue
            out.append(d)
        return out

    def projects(self):
        for d in self.project_dirs():
            label = "project: " + os.path.relpath(d, self.ctx.projects)
            prof_name = self.folder_profile(d)
            on = [prof_name] if prof_name else []
            found = False
            for f in sorted(glob.glob(os.path.join(d, ".claude", "skills", "*", "SKILL.md"))):
                found = found or self.provider(label, "project", d, repo_of(d))
                meta = frontmatter(f)
                name = meta.get("name") or os.path.basename(os.path.dirname(f))
                self.add("skill", name, label, f, on, self.acct_names, "/" + name, meta, scope=d)
            for f in sorted(glob.glob(os.path.join(d, ".claude", "agents", "*.md"))):
                found = found or self.provider(label, "project", d, repo_of(d))
                meta = frontmatter(f)
                name = meta.get("name") or os.path.basename(f)[:-3]
                self.add("agent", name, label, f, on, self.acct_names, name, meta, scope=d)
            for f in sorted(glob.glob(os.path.join(d, ".claude", "commands", "*.md"))):
                found = found or self.provider(label, "project", d, repo_of(d))
                name = os.path.basename(f)[:-3]
                self.add("command", name, label, f, on, self.acct_names, "/" + name, frontmatter(f), scope=d)
            sj = os.path.join(d, ".claude", "settings.json")
            for cmd, evs in hook_entries(read_json(sj).get("hooks")).items():
                found = found or self.provider(label, "project", d, repo_of(d))
                self.add("hook", hook_name(cmd), label, sj, on, self.acct_names, "automatic",
                         purpose="Project hook on " + ", ".join(evs), events=evs, scope=d)
            mj = os.path.join(d, ".mcp.json")
            for name, transport in sorted(server_names(read_json(mj).get("mcpServers")).items()):
                self.project_server(d, name, transport, mj, self.acct_names)
            if self.copies.get(d) and label in self.providers:
                self.providers[label]["copies"] = self.copies[d]

    def builtins(self):
        self.provider(BUILTIN, "builtin", None, "Claude Code")
        for kind, name, text in BUILTINS:
            self.add(kind, name, BUILTIN, "", self.all_profiles, self.acct_names,
                     "/" + name if kind == "skill" else "subagent_type " + name, purpose=text)

    def run(self):
        self.plugin_dirs()
        self.installed_plugins()
        self.user_level()
        self.settings_hooks()
        self.mcp_servers()
        self.profile_mcp_configs()
        self.projects()
        self.builtins()
        return self


def merge_list(into, more):
    for x in more or []:
        if x not in into:
            into.append(x)


def git_origin(folder):
    """The `origin` URL in a checkout's .git/config (read as a file, no git process), or None."""
    text = read_text(os.path.join(folder, ".git", "config"))
    m = re.search(r'\[remote "origin"\][^\[]*?url\s*=\s*(\S+)', text or "")
    return m.group(1) if m else None


def repo_of(path):
    """The basename of the git repository holding `path`, or None."""
    p = os.path.realpath(path)
    if os.path.isfile(p):
        p = os.path.dirname(p)
    while p and p != os.path.dirname(p):
        if os.path.exists(os.path.join(p, ".git")):
            return os.path.basename(p)
        p = os.path.dirname(p)
    return None


LAUNCH_LINE = re.compile(r"^\s*profile\s+([a-z0-9-]+)\s*$", re.M)


def launch_profile(folder):
    """(profile, own): the profile the nearest .claude-launch walking up from `folder` names (any file with a
    `profile <name>` line, as the launcher reads it), and whether that file is the folder's own."""
    d = os.path.realpath(folder)
    first = True
    while True:
        text = read_text(os.path.join(d, prof.LAUNCH_FILE))
        if text is not None:
            m = LAUNCH_LINE.search(text)
            return (m.group(1) if m else None), first
        if d == os.path.dirname(d):
            return None, False
        d, first = os.path.dirname(d), False


def folders_of(ctx, profiles):
    """[{path, profile}] for every project folder: the profile its nearest .claude-launch names, else default."""
    names = [p["name"] for p in profiles]
    out = []
    for d in sorted(glob.glob(os.path.join(ctx.projects, "*"))):
        if not os.path.isdir(d) or os.path.basename(d).startswith("."):
            continue
        name, own = launch_profile(d)
        out.append({"path": ctx.tilde(d), "profile": name if name in names else DEFAULT_PROFILE, "own": own})
    return out


def scan(ctx, now=None):
    """One machine's inventory: {machine, as_of, accounts, profiles, providers, items, notes}."""
    s = Scan(ctx).run()
    items = sorted(s.items.values(), key=lambda i: (KINDS.index(i["kind"]), i["provider"].lower(), i["name"].lower()))
    profiles = [{"name": p["name"], "repo": p["repo"], "source": p["source"], "plugin_dirs": p["plugin_dirs_shown"],
                 "enabled": sorted(k for k, v in p["enabled"].items() if v),
                 "disabled": sorted(k for k, v in p["enabled"].items() if not v),
                 "denied": sorted(set(p["deny"] + p["denied_servers"])), "connectors": p["connectors"],
                 "mcp_configs": [ctx.tilde(m) for m in p["mcp_configs"]]} for p in s.profiles]
    accounts = [{"name": a["name"], "dir": ctx.tilde(a["dir"]), "listed": a["listed"],
                 "shares": shared_with(a, s.accounts)} for a in s.accounts]
    return {"machine": ctx.machine, "as_of": now or time.time(), "accounts": accounts, "profiles": profiles,
            "folders": folders_of(ctx, s.profiles), "providers": sorted(s.providers.values(), key=lambda p: p["name"].lower()),
            "items": items, "notes": s.notes}


def shared_with(acct, accounts):
    """Names of the other accounts whose settings.json is the same file (a linked account)."""
    me = real(os.path.join(acct["dir"], "settings.json"))
    return [a["name"] for a in accounts if a is not acct and real(os.path.join(a["dir"], "settings.json")) == me]


# ---------------------------------------------------------------- the merge

def company_of(item, needles):
    hay = (item.get("provider", "") + " " + item.get("name", "")).lower()
    return any(n.lower() in hay for n in needles if isinstance(n, str) and n)


def merge(answers, machines, conf=None, now=None):
    """Join machines' scans. `answers` {machine: scan dict}; `machines` {machine: {status, as_of, reason}} in the
    order to show, every machine asked or not (a satellite is `satellite`, never `not read`). Items get
    `machines` {machine: true|false|null} over the machines that are not satellites (null: not read),
    `on` {machine: {profiles, accounts, path, drift}} and `company`. Findings come last."""
    conf = conf or {}
    needles = conf.get("company") if isinstance(conf.get("company"), list) else []
    shown = [m for m, e in machines.items() if e.get("status") != "satellite"]
    read = [m for m in shown if m in answers]
    items, providers, profiles, accounts, notes = {}, {}, {}, {}, []
    for m in read:
        env = answers[m]
        for it in env.get("items") or []:
            row = items.get(it["key"])
            if row is None:
                row = dict(it, profiles=[], accounts=[], on={})
                row["machines"] = {x: (None if x not in read else False) for x in shown}
                items[it["key"]] = row
            row["machines"][m] = True
            row["on"][m] = {k: it.get(k) for k in ("profiles", "accounts", "path", "drift", "source", "denied")
                            if it.get(k) is not None}
            merge_list(row["profiles"], it.get("profiles"))
            merge_list(row["accounts"], it.get("accounts"))
            if it.get("drift") == "drifted":
                row["drift"] = "drifted"
        for p in env.get("providers") or []:
            row = providers.setdefault(p["name"], dict(p, profiles=[], accounts=[], machines=[], on={}))
            row["on"][m] = {"profiles": p.get("profiles") or [], "enabled_by": p.get("enabled_by"),
                            "scope": p.get("scope")}
            merge_list(row["profiles"], p.get("profiles"))
            merge_list(row["accounts"], p.get("accounts"))
            merge_list(row["machines"], [m])
        for p in env.get("profiles") or []:
            row = profiles.setdefault(p["name"], dict(p, machines=[]))
            merge_list(row["machines"], [m])
        for a in env.get("accounts") or []:
            row = accounts.setdefault(a["name"], dict(a, machines=[]))
            merge_list(row["machines"], [m])
        notes += ["%s: %s" % (m, n) for n in env.get("notes") or []]
    order = [p for p in [x for m in read for x in [q["name"] for q in answers[m].get("profiles") or []]]]
    prof_order = []
    merge_list(prof_order, [p for p in order if p != DEFAULT_PROFILE] + ([DEFAULT_PROFILE] if DEFAULT_PROFILE in order else []))
    rows = sorted(items.values(), key=lambda i: (KINDS.index(i["kind"]) if i["kind"] in KINDS else 99,
                                                 i["provider"].lower(), i["name"].lower()))
    for i, row in enumerate(rows):
        row["id"] = i + 1
        row["company"] = company_of(row, needles)
    for p in providers.values():
        p["company"] = company_of({"provider": p["name"], "name": ""}, needles)
        p["counts"] = {}
        for r in rows:
            if r["provider"] == p["name"]:
                p["counts"][r["kind"]] = p["counts"].get(r["kind"], 0) + 1
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in KINDS}
    per_machine = {m: {k: sum(1 for r in rows if r["kind"] == k and r["machines"].get(m)) for k in KINDS}
                   for m in read}
    return {"as_of": now or time.time(), "machines": machines, "shown_machines": shown,
            "company_label": conf.get("company_label") if isinstance(conf.get("company_label"), str) else "Company",
            "kinds": list(KINDS), "counts": counts, "per_machine": per_machine, "profiles": [profiles[p] for p in prof_order],
            "accounts": list(accounts.values()), "providers": sorted(providers.values(), key=lambda p: p["name"].lower()),
            "folders": {m: answers[m].get("folders") or [] for m in read}, "items": rows,
            "findings": findings(rows, providers, prof_order), "notes": notes}


def findings(rows, providers, profile_names):
    """What the inventory flags: [{kind, title, detail, ids}]."""
    out = []
    groups = {}
    for r in rows:
        groups.setdefault((r["kind"], r["name"].lower()), []).append(r)
    for (kind, _), rs in sorted(groups.items()):
        provs = []
        merge_list(provs, [r["provider"] for r in rs])
        if len(provs) > 1:
            out.append({"kind": "duplicate", "title": "%s %s comes from %d providers" % (kind, rs[0]["name"], len(provs)),
                        "detail": ", ".join(provs), "ids": [r["id"] for r in rs]})
    for p in sorted(providers.values(), key=lambda p: p["name"].lower()):
        if p.get("type") != "plugin":
            continue
        idle = [m for m, on in sorted(p.get("on", {}).items()) if not on.get("scope") and not on.get("profiles")]
        if idle:
            ids = [r["id"] for r in rows if r["provider"] == p["name"]]
            why = "; ".join("%s: %s" % (m, p["on"][m].get("enabled_by") or "") for m in idle)
            out.append({"kind": "no profile", "title": "%s is installed on %s but on no profile there"
                        % (p["name"], " and ".join(idle)), "detail": why, "ids": ids, "machines": idle})
    for r in rows:
        if r["kind"] == "hook" and r.get("drift") == "drifted":
            where = [m for m, on in r["on"].items() if on.get("drift") == "drifted"]
            src = next((on.get("source") for on in r["on"].values() if on.get("source")), "")
            out.append({"kind": "drift", "title": "hook %s differs from its source" % r["name"],
                        "detail": "on %s; source %s" % (", ".join(where), src), "ids": [r["id"]]})
    for r in rows:
        if r["kind"] == "MCP server" and not r["profiles"] and r.get("denied"):
            out.append({"kind": "denied", "title": "MCP server %s is denied in every profile" % r["name"],
                        "detail": r["provider"], "ids": [r["id"]]})
    return out


def text_lines(env):
    """`fleet tools` without --json."""
    lines = []
    for m, e in env["machines"].items():
        st = e.get("status")
        if st == "satellite":
            lines.append("%s: satellite, nothing of its own" % m)
        elif st != "read":
            lines.append("%s: %s%s" % (m, st, " (%s)" % e["reason"] if e.get("reason") else ""))
    lines.append("  ".join("%s %d" % (k if k == "MCP server" else k, n) for k, n in env["counts"].items()))
    for m, c in env.get("per_machine", {}).items():
        lines.append("%s: %s" % (m, ", ".join("%s %d" % (k, n) for k, n in c.items())))
    for f in env["findings"]:
        lines.append("! %s: %s" % (f["title"], f["detail"]))
    for n in env.get("notes") or []:
        lines.append("note: " + n)
    return lines
