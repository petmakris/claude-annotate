"""`fleet tools`: the scanner on a made-up home (a plugin tree, a marketplace folder, settings with hooks, a
profiles.json, accounts), the merge across machines, and `/api/tools` over the fake ssh."""
import json
import os
import time

import pytest

from fleet_testkit import fleet, world  # noqa: F401
from test_fleet_ui import server  # noqa: F401

import fleet_tools as tools

SECRETS = ("SECRETURL", "SECRETHDR", "SECRETARG", "SECRETENV", "SECRETPROF", "SECRETAPP")


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text if isinstance(text, str) else json.dumps(text))


def skill(path, name, desc, manual=False):
    put(path, "---\nname: %s\ndescription: >\n  %s\n  second line\n%s---\n# %s\n"
        % (name, desc, "disable-model-invocation: true\n" if manual else "", name))


def make_home(base):
    """A home with two listed accounts sharing settings (alice, bob), one unlisted (carol), the launcher's profiles
    `full` and `lean`, a plugin dir, a marketplace folder, two marketplace plugins (one on, one idle), user skills,
    hooks (one drifted from its source), MCP servers holding secrets, and a project with a copy."""
    h = os.path.join(base, "home")
    p = os.path.join(h, "projects")
    put(os.path.join(h, ".config", "env", "claude-accounts"), "# order\nalice\nbob\ndefault alice\n")
    cache = os.path.join(h, ".claude", "plugins", "cache", "mkt")
    put(os.path.join(h, ".claude", "settings.json"), {
        "enabledPlugins": {"mkt-plug@mkt": True, "idle@mkt": False},
        "deniedMcpServers": [{"serverName": "blocked"}],
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/hooks/guard.sh"}]}],
                  "Stop": [{"hooks": [{"type": "command", "command": "~/.claude/hooks/drifty.sh --quiet"}]}]},
        "statusLine": {"type": "command", "command": "~/.claude/statusline.sh"}})
    put(os.path.join(h, ".claude", "hooks", "guard.sh"), "echo guard\n")
    put(os.path.join(h, ".claude", "hooks", "drifty.sh"), "echo edited by hand\n")
    put(os.path.join(h, ".claude", "statusline.sh"), "echo line\n")
    os.makedirs(os.path.join(h, ".claude-bob"))
    os.symlink(os.path.join(h, ".claude", "settings.json"), os.path.join(h, ".claude-bob", "settings.json"))
    os.symlink(os.path.join(h, ".claude", "plugins"), os.path.join(h, ".claude-bob", "plugins"))
    put(os.path.join(h, ".claude-carol", "settings.json"), {})
    put(os.path.join(h, ".claude", "plugins", "installed_plugins.json"), {"version": 2, "plugins": {
        "mkt-plug@mkt": [{"scope": "user", "installPath": os.path.join(cache, "mkt-plug", "1.0"), "version": "1.0"}],
        "idle@mkt": [{"scope": "user", "installPath": os.path.join(cache, "idle", "2.0"), "version": "2.0"}]}})
    put(os.path.join(h, ".claude", "plugins", "known_marketplaces.json"),
        {"mkt": {"source": {"source": "github", "repo": "acme/plugins"}}})
    skill(os.path.join(cache, "mkt-plug", "1.0", "skills", "shared-name", "SKILL.md"), "shared-name", "From the plugin.")
    put(os.path.join(cache, "mkt-plug", "1.0", "commands", "go.md"), "---\ndescription: Go somewhere.\n---\nbody\n")
    put(os.path.join(cache, "mkt-plug", "1.0", ".mcp.json"),
        {"mcpServers": {"plugsrv": {"type": "http", "url": "https://p.example/?k=SECRETURL"}}})
    skill(os.path.join(cache, "idle", "2.0", "skills", "lonely", "SKILL.md"), "lonely", "Nobody turns it on.")
    skill(os.path.join(h, ".claude", "skills", "shared-name", "SKILL.md"), "shared-name", "The user's own copy.")
    put(os.path.join(h, ".claude.json"), {
        "mcpServers": {
            "web": {"type": "http", "url": "https://x.example/?token=SECRETURL", "headers": {"Authorization": "Bearer SECRETHDR"}},
            "local": {"command": "run-it", "args": ["--key", "SECRETARG"], "env": {"K": "SECRETENV"}},
            "blocked": {"command": "nope"}},
        "claudeAiMcpEverConnected": ["claude.ai Mail"]})
    env = os.path.join(p, "env", "claude")
    put(os.path.join(env, ".claude-plugin", "plugin.json"), {"name": "own-skills"})
    skill(os.path.join(env, "skills", "alpha", "SKILL.md"), "alpha", "Typed by hand.", manual=True)
    skill(os.path.join(env, "skills", "_shared", "SKILL.md"), "_shared", "Never an item.")
    put(os.path.join(env, "hooks", "hooks.json"), {"description": "Plugin hook bundle.", "hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/run-hook.cmd\" session-start"}]}]}})
    put(os.path.join(env, "output-styles", "terse.md"), "---\nname: terse\ndescription: Short answers.\n---\n")
    put(os.path.join(env, "user-hooks", "guard.sh"), "echo guard\n")
    put(os.path.join(env, "user-hooks", "drifty.sh"), "echo the source\n")
    profiles = os.path.join(env, "profiles")
    put(os.path.join(profiles, "full.args"), "# everything\n--plugin-dir ~/projects/env/claude\n--plugin-dir ~/projects/market\n"
        "--settings ~/projects/env/claude/profiles/full.json\n--mcp-config ~/projects/env/claude/profiles/full.mcp.json\n")
    put(os.path.join(profiles, "full.json"), {"permissions": {"deny": ["mcp__web", "Bash(rm:*)"]}})
    put(os.path.join(profiles, "full.mcp.json"), {"mcpServers": {"extra": {"type": "http", "url": "https://e.example",
                                                                            "headers": {"X": "SECRETPROF"}}}})
    put(os.path.join(profiles, "lean.args"), "--plugin-dir ~/projects/env/claude\n--settings ~/projects/env/claude/profiles/lean.json\n")
    put(os.path.join(profiles, "lean.json"), {"enabledPlugins": {"mkt-plug@mkt": False},
                                              "deniedMcpServers": [{"serverName": "local"}],
                                              "env": {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}})
    market = os.path.join(p, "market")
    put(os.path.join(market, ".claude-plugin", "marketplace.json"), {"name": "market", "plugins": [
        {"name": "market", "source": "./", "strict": False, "skills": ["./skills/m1"]},
        {"name": "elsewhere", "source": "./sub"}]})
    skill(os.path.join(market, "skills", "m1", "SKILL.md"), "m1", "Listed in the marketplace entry.")
    skill(os.path.join(market, "skills", "m2", "SKILL.md"), "m2", "Not listed, so not loaded.")
    app = os.path.join(p, "app")
    put(os.path.join(app, ".claude-launch"), "profile full\n")
    put(os.path.join(app, ".git", "config"), '[core]\n\tbare = false\n[remote "origin"]\n\turl = git@example:acme/app.git\n')
    skill(os.path.join(app, ".claude", "skills", "shared-name", "SKILL.md"), "shared-name", "The project's copy.")
    put(os.path.join(app, ".claude", "settings.json"), {"hooks": {"PostToolUse": [
        {"matcher": "Edit", "hooks": [{"type": "command", "command": "node .claude/hooks/check.mjs"}]}]}})
    put(os.path.join(app, ".mcp.json"), {"mcpServers": {"appdb": {"command": "db", "env": {"PASS": "SECRETAPP"}}}})
    copy = os.path.join(p, "app-copy")
    put(os.path.join(copy, ".git", "config"), '[remote "origin"]\n\turl = git@example:acme/app.git\n')
    skill(os.path.join(copy, ".claude", "skills", "shared-name", "SKILL.md"), "shared-name", "A clone.")
    fh = os.path.join(base, "fleet-home")
    put(os.path.join(fh, "profiles.json"), {"roots": ["~/projects/env"], "default_dirs": ["~/projects/env/claude"]})
    return h, fh


@pytest.fixture
def scanned(tmp_path):
    h, fh = make_home(str(tmp_path))
    ctx = tools.Ctx(home=h, fleet_home=fh, machine="alpha")
    return tools.scan(ctx, now=1000.0), ctx


def items(env, **match):
    return [i for i in env["items"] if all(i.get(k) == v for k, v in match.items())]


def one(env, **match):
    found = items(env, **match)
    assert len(found) == 1, (match, found)
    return found[0]


def test_accounts_come_from_the_accounts_file_and_unlisted_config_folders(scanned):
    env, _ = scanned
    assert env["accounts"] == [
        {"name": "alice", "dir": "~/.claude", "listed": True, "shares": ["bob"]},
        {"name": "bob", "dir": "~/.claude-bob", "listed": True, "shares": ["alice"]},
        {"name": "carol", "dir": "~/.claude-carol", "listed": False, "shares": []}]


def test_profiles_are_read_from_their_args_and_settings_with_the_launchers_default_last(scanned):
    env, _ = scanned
    by = {p["name"]: p for p in env["profiles"]}
    assert list(by) == ["full", "lean", "default"]
    assert by["full"]["plugin_dirs"] == ["~/projects/env/claude", "~/projects/market"]
    assert by["full"]["denied"] == ["mcp__web"]
    assert (by["lean"]["disabled"], by["lean"]["denied"], by["lean"]["connectors"]) == (["mkt-plug@mkt"], ["local"], False)
    assert by["default"]["plugin_dirs"] == ["~/projects/env/claude"]


def test_a_plugin_dirs_items_carry_the_profiles_that_name_it(scanned):
    env, _ = scanned
    a = one(env, kind="skill", name="alpha")
    assert (a["provider"], a["invocation"], a["manual"], a["profiles"]) == ("own-skills", "/own-skills:alpha", True,
                                                                           ["full", "lean", "default"])
    assert a["purpose"] == "Typed by hand. second line"
    assert a["path"] == "~/projects/env/claude/skills/alpha/SKILL.md"
    assert a["accounts"] == ["alice", "bob", "carol"]
    assert not items(env, name="_shared")
    assert one(env, kind="output style", name="terse")["profiles"] == ["full", "lean", "default"]
    hook = one(env, kind="hook", provider="own-skills")
    assert (hook["name"], hook["events"], hook["purpose"]) == ("run-hook.cmd session-start", ["SessionStart"], "Plugin hook bundle.")


def test_a_marketplace_folder_loads_only_the_skills_of_its_own_entries(scanned):
    env, _ = scanned
    m1 = one(env, name="m1")
    assert (m1["provider"], m1["invocation"], m1["profiles"]) == ("market", "/market:m1", ["full"])
    assert not items(env, name="m2")


def test_a_marketplace_plugin_follows_the_user_setting_and_each_profiles_override(scanned):
    env, _ = scanned
    s = one(env, kind="skill", name="shared-name", provider="mkt-plug")
    assert (s["profiles"], s["accounts"], s["repo"]) == (["full", "default"], ["alice", "bob"], "acme/plugins")
    assert one(env, kind="command", name="go")["invocation"] == "/mkt-plug:go"
    srv = one(env, kind="MCP server", name="plugsrv")
    assert (srv["invocation"], srv["transport"], srv["profiles"]) == ("mcp__plugin_mkt-plug_plugsrv__*", "http", ["full", "default"])
    lonely = one(env, name="lonely")
    assert (lonely["profiles"], lonely["accounts"]) == ([], ["alice", "bob"])
    prov = {p["name"]: p for p in env["providers"]}
    assert prov["idle"]["enabled_by"] == "enabledPlugins idle@mkt (alice=false, bob=false)"


def test_mcp_servers_are_names_and_transport_only_and_follow_each_profiles_denials(scanned):
    env, _ = scanned
    text = json.dumps(env)
    for secret in SECRETS:
        assert secret not in text  # no env value, header, argument or URL of a server ever reaches the inventory
    assert one(env, name="web")["profiles"] == ["lean", "default"]
    assert one(env, name="local")["profiles"] == ["full", "default"]
    assert (one(env, name="local")["transport"], one(env, name="web")["transport"]) == ("stdio", "http")
    blocked = one(env, name="blocked")
    assert (blocked["profiles"], blocked["denied"]) == ([], ["full", "lean", "default"])
    mail = one(env, name="claude.ai Mail")
    assert (mail["provider"], mail["profiles"], mail["invocation"]) == ("claude.ai connectors", ["full", "default"],
                                                                        "mcp__claude_ai_Mail__*")
    extra = one(env, name="extra")
    assert (extra["provider"], extra["profiles"]) == ("profile full", ["full"])


def test_settings_hooks_say_whether_their_copy_drifted_from_the_source(scanned):
    env, _ = scanned
    guard, drifty = one(env, name="guard.sh"), one(env, name="drifty.sh")
    assert (guard["drift"], guard["events"], guard["source"]) == ("same", ["PreToolUse[Bash]"], "~/projects/env/claude/user-hooks/guard.sh")
    assert (drifty["drift"], drifty["path"]) == ("drifted", "~/.claude/hooks/drifty.sh")
    assert one(env, name="statusline.sh")["events"] == ["statusLine"]
    assert guard["accounts"] == ["alice", "bob"]


def test_a_projects_items_take_its_folders_profile_and_a_clone_is_counted_once(scanned):
    env, _ = scanned
    s = one(env, kind="skill", name="shared-name", provider="project: app")
    assert (s["profiles"], s["scope"]) == (["full"], "~/projects/app")
    assert one(env, name="check.mjs")["events"] == ["PostToolUse[Edit]"]
    assert one(env, name="appdb")["profiles"] == ["full"]
    assert not [i for i in env["items"] if "app-copy" in i["provider"]]
    assert {p["name"]: p for p in env["providers"]}["project: app"]["copies"] == ["~/projects/app-copy"]
    folders = {f["path"]: f for f in env["folders"]}
    assert folders["~/projects/app"] == {"path": "~/projects/app", "profile": "full", "own": True}
    assert folders["~/projects/market"]["profile"] == "default"


def test_the_scan_writes_nothing(tmp_path):
    h, fh = make_home(str(tmp_path))
    before = sorted((r, tuple(sorted(f))) for r, _, f in os.walk(str(tmp_path)))
    tools.scan(tools.Ctx(home=h, fleet_home=fh, machine="alpha"))
    assert sorted((r, tuple(sorted(f))) for r, _, f in os.walk(str(tmp_path))) == before


def test_merge_joins_machines_and_never_calls_a_satellite_not_read(scanned):
    env, _ = scanned
    other = json.loads(json.dumps(env))
    other["machine"] = "beta"
    other["items"] = [dict(i, profiles=[]) for i in other["items"] if i["name"] != "alpha"]
    for p in other["providers"]:
        p["profiles"] = []
    machines = {"alpha": {"status": "read"}, "beta": {"status": "stale", "as_of": 5}, "gamma": {"status": "unreachable"},
                "sat": {"status": "satellite"}}
    m = tools.merge({"alpha": env, "beta": other}, machines, {"company": ["mkt-plug"], "company_label": "Work"}, now=2000.0)
    assert m["shown_machines"] == ["alpha", "beta", "gamma"]
    alpha, shared = one(m, name="alpha"), one(m, provider="mkt-plug", kind="skill")
    assert alpha["machines"] == {"alpha": True, "beta": False, "gamma": None}
    assert shared["machines"] == {"alpha": True, "beta": True, "gamma": None}
    assert shared["on"]["beta"]["profiles"] == [] and shared["on"]["alpha"]["profiles"] == ["full", "default"]
    assert (shared["company"], alpha["company"], m["company_label"]) == (True, False, "Work")
    assert m["counts"]["skill"] == len(items(env, kind="skill"))
    assert m["per_machine"]["beta"]["skill"] == m["per_machine"]["alpha"]["skill"] - 1
    assert [i["id"] for i in m["items"]] == list(range(1, len(m["items"]) + 1))


def test_findings_name_duplicates_idle_plugins_drifted_hooks_and_servers_denied_everywhere(scanned):
    env, _ = scanned
    m = tools.merge({"alpha": env}, {"alpha": {"status": "read"}})
    by = {}
    for f in m["findings"]:
        by.setdefault(f["kind"], []).append(f)
    dup = [f for f in by["duplicate"] if "shared-name" in f["title"]][0]
    assert dup["title"] == "skill shared-name comes from 3 providers"
    assert dup["detail"] == "mkt-plug, project: app, user skills"
    assert [f["title"] for f in by["no profile"]] == ["idle is installed on alpha but on no profile there"]
    assert [f["title"] for f in by["drift"]] == ["hook drifty.sh differs from its source"]
    assert [f["title"] for f in by["denied"]] == ["MCP server blocked is denied in every profile"]
    assert set(by) == {"duplicate", "no profile", "drift", "denied"}


def tool_machine(world, host, base):
    """Give a fake machine a made-up home to scan (tools.json scan_home)."""
    h, fh = make_home(base)
    os.makedirs(host.home, exist_ok=True)
    put(os.path.join(host.home, "tools.json"), {"scan_home": h, "company": ["mkt"]})
    put(os.path.join(host.home, "profiles.json"), json.load(open(os.path.join(fh, "profiles.json"))))
    return h


def test_api_tools_merges_every_machine_and_keeps_a_satellite_and_a_silent_machines_last_answer(world, server, monkeypatch):
    monkeypatch.setenv("FLEET_ENV_DIR", "")
    bee = world.host("bee")
    world.link(bee, extra={"sat": {"ssh": "sat", "fleet": "/x/fleet.py", "satellite": True},
                           "gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    tool_machine(world, world.here, os.path.join(world.base, "t-here"))
    tool_machine(world, bee, os.path.join(world.base, "t-bee"))
    old = {"machine": "gone", "as_of": time.time() - 3600, "items": [
        {"key": "skill|far|kept|", "kind": "skill", "name": "kept", "provider": "far", "profiles": [], "accounts": []}],
        "providers": [], "profiles": [], "accounts": []}
    put(os.path.join(world.here.home, "seen", "tools-gone.json"), old)
    code, data = server("/api/tools")
    assert code == 200
    st = data["machines"]
    assert (st["here"]["status"], st["bee"]["status"], st["sat"]["status"]) == ("read", "read", "satellite")
    assert st["gone"]["status"] == "stale" and st["gone"]["reason"]  # its last answer, saying why it is old
    assert data["shown_machines"] == ["here", "bee", "gone"]
    assert not [h for h, _ in world.ssh_log() if h == "sat"]  # a satellite is never asked
    alpha = one(data, name="alpha")
    assert alpha["machines"] == {"here": True, "bee": True, "gone": False}
    assert one(data, name="kept")["machines"] == {"here": False, "bee": False, "gone": True}
    assert one(data, provider="mkt-plug", kind="skill")["company"] is True
    assert json.load(open(os.path.join(world.here.home, "seen", "tools-bee.json")))["machine"] == "bee"
    for secret in SECRETS:
        assert secret not in json.dumps(data)


def test_fleet_tools_local_prints_this_machines_scan_as_json(world, monkeypatch):
    monkeypatch.setenv("FLEET_ENV_DIR", "")
    world.link()
    tool_machine(world, world.here, os.path.join(world.base, "t-here"))
    code = fleet.main(["tools", "--json", "--local"])
    out = json.loads(world.capsys.readouterr().out)
    assert code == 0 and out["machine"] == "here"
    assert set(out) == {"machine", "as_of", "accounts", "profiles", "folders", "providers", "items", "notes"}
    assert one(out, name="alpha")["profiles"] == ["full", "lean", "default"]
