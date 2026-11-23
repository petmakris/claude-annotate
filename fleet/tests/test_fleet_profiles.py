"""Launch profiles: the file formats, how a folder's profile resolves, the tool list, a folder's .claude-launch,
a profile save that commits and pushes only its two files, the page's API and the `fleet profile` verbs. Every
folder, repository, profile and server here is made up, under a temp home."""
import json
import os
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from fleet_testkit import fleet, world  # noqa: F401
import fleet_profiles as prof

MCP_STUB = """#!%s
import os, sys
with open(os.path.join(os.environ["MCP_STUB_DIR"], "calls"), "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:3] != ["mcp", "list"]:
    sys.exit(0)
if os.environ.get("MCP_STUB_FAIL"):
    sys.stderr.write("cannot list\\n"); sys.exit(1)
print("Checking MCP server health...")
print("")
print("github: npx -y github-server - \\u2713 Connected")
print("claude.ai Mail Box: https://mail.example/mcp - \\u2713 Connected")
print("plugin:thing:server: node x.js - \\u2713 Connected")
print("blocked: blocked-cmd - \\u2717 Failed to connect")
"""

WORK_ARGS = "# the work profile\n--plugin-dir ~/projects/skills\n--plugin-dir ~/projects/kit\n" \
            "--settings ~/projects/env-repo/claude/profiles/work.json\n"
WORK_JSON = {"permissions": {"deny": ["mcp__github", "mcp__unmanaged", "Bash(rm:*)"]},
             "enabledPlugins": {"beta@mk": False, "other@mk": False}}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), check=True, capture_output=True, text=True).stdout.strip()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class PW:
    """A home with two profile roots, one of them a git repository with a bare remote, a history, a global
    settings file and a stub `claude` that answers `mcp list`."""

    def __init__(self, world):
        self.world, mp = world, world.mp
        self.home = os.path.join(world.base, "u")
        mp.setenv("HOME", self.home)
        for k, v in (("GIT_AUTHOR_NAME", "T"), ("GIT_AUTHOR_EMAIL", "t@example.invalid"), ("GIT_COMMITTER_NAME", "T"),
                     ("GIT_COMMITTER_EMAIL", "t@example.invalid"), ("GIT_CONFIG_NOSYSTEM", "1")):
            mp.setenv(k, v)
        self.env = os.path.join(self.home, "projects", "env-repo")
        self.pdir = os.path.join(self.env, "claude", "profiles")
        write(os.path.join(self.pdir, "work.args"), WORK_ARGS)
        write(os.path.join(self.pdir, "work.json"), json.dumps(WORK_JSON, indent=2) + "\n")
        write(os.path.join(self.pdir, "bare.args"), "--settings ~/projects/env-repo/claude/profiles/bare.json\n")
        write(os.path.join(self.pdir, "bare.json"), "{}\n")
        write(os.path.join(self.env, "README"), "env\n")
        git(self.env, "init", "-q", "-b", "main")
        git(self.env, "add", "-A")
        git(self.env, "commit", "-q", "-m", "init")
        self.remote = os.path.join(world.base, "remote.git")
        subprocess.run(["git", "init", "-q", "--bare", self.remote], check=True)
        git(self.env, "remote", "add", "origin", self.remote)
        git(self.env, "push", "-q", "-u", "origin", "main")
        # a second root, listed in a roots file: its own profile, and a `work` that the first root shadows
        self.extra = os.path.join(self.home, "projects", "extra-repo")
        write(os.path.join(self.extra, "claude", "profiles", "side.args"), "--plugin-dir ~/projects/kit\n")
        write(os.path.join(self.extra, "claude", "profiles", "work.args"), "--plugin-dir ~/projects/nothing\n")
        write(os.path.join(self.home, ".roots"), "plain-word\n# a comment\n~/projects/extra-repo\n")
        self.conf = {"roots": ["~/projects/env-repo"], "roots_file": "~/.roots",
                     "default_dirs": ["~/projects/skills", "~/projects/kit"],
                     "locked": {"~/projects/skills": "your skills"}, "hidden": ["~/projects/self"]}
        self.save_conf()
        write(os.path.join(self.home, ".claude", "settings.json"), json.dumps({
            "permissions": {"deny": ["mcp__blocked"]},
            "enabledPlugins": {"alpha@mk": True, "beta@mk": True, "gamma@mk": False}}))
        # folders sessions ran in
        self.app = os.path.join(self.home, "projects", "app")
        self.lib = os.path.join(self.home, "projects", "group", "lib")
        for d in (self.app, self.lib, os.path.join(self.home, "projects", "self")):
            os.makedirs(d, exist_ok=True)
        write(os.path.join(self.home, "projects", "group", ".claude-launch"),
              prof.format_launch("bare", "~/projects/env-repo/claude/profiles/bare.args"))
        con = fleet.db()
        rows = [("s1", self.app, 100), ("s2", self.app, 300), ("s3", self.lib, 200),
                ("s4", os.path.join(self.home, "gone"), 400), ("s5", "/tmp", 500)]
        for sid, cwd, t in rows:
            con.execute("INSERT INTO conversations(session_id, cwd, started_at, last_seen_at) VALUES (?,?,?,?)",
                        (sid, cwd, t - 50, t))
        # the stub claude
        self.stub = os.path.join(world.base, "mcpstub")
        os.makedirs(self.stub)
        path = os.path.join(self.stub, "claude")
        write(path, MCP_STUB % sys.executable)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        mp.setenv("FLEET_CLAUDE_BIN", path)
        mp.setenv("MCP_STUB_DIR", self.stub)
        mp.delenv("MCP_STUB_FAIL", raising=False)
        fleet.PROFILE_TOOLS.mcp = fleet.PROFILE_TOOLS.audit = None

    def save_conf(self):
        write(os.path.join(os.environ["FLEET_HOME"], "profiles.json"), json.dumps(self.conf))

    def cfg(self):
        return fleet.profile_config()

    def mcp_calls(self):
        try:
            return [l for l in open(os.path.join(self.stub, "calls")).read().split("\n") if l == "mcp list"]
        except OSError:
            return []

    def work_json(self):
        with open(os.path.join(self.pdir, "work.json")) as f:
            return json.load(f)

    def work_args(self):
        with open(os.path.join(self.pdir, "work.args")) as f:
            return f.read()


@pytest.fixture
def pw(world):
    yield PW(world)
    fleet.PROFILE_TOOLS.mcp = fleet.PROFILE_TOOLS.audit = None


# ---------------------------------------------------------------- file formats

def test_a_standard_launch_file_names_its_profile_and_anything_else_is_custom():
    std = prof.format_launch("work", "~/projects/env-repo/claude/profiles/work.args")
    assert std == "# Tools this tree gets: see ~/projects/env-repo/claude/profiles/work.args\nprofile work\n"
    assert prof.parse_standard_launch(std) == "work"
    assert prof.parse_standard_launch(std.replace("profile work", "profile other")) is None  # comment and line disagree
    assert prof.parse_standard_launch("profile work\n") is None
    assert prof.parse_standard_launch(std + "--plugin-dir ~/x\n") is None
    # a file written before its profile moved repositories is still standard
    assert prof.parse_standard_launch(std.replace("env-repo", "elsewhere")) == "work"


def test_a_root_block_under_the_standard_lines_keeps_the_file_standard():
    std = prof.format_launch("work", "~/r/claude/profiles/work.args")
    body, root = prof.split_root_block(std + "# start the sessions one level up\nroot ~/projects/top\n")
    assert body == std and root == "# start the sessions one level up\nroot ~/projects/top\n"
    assert prof.parse_standard_launch(std + "root ~/projects/top\n") == "work"
    assert prof.split_root_block(std + "# only a comment\n") == (std + "# only a comment\n", "")
    assert prof.split_root_block(std + "root ~/x\nprofile y\n")[1] == ""


def test_an_args_file_round_trips_and_only_the_standard_flags_count_as_standard():
    a = prof.parse_args(WORK_ARGS + "--mcp-config ~/m.json\n")
    assert a == {"comments": ["# the work profile"], "plugin_dirs": ["~/projects/skills", "~/projects/kit"],
                 "settings": "~/projects/env-repo/claude/profiles/work.json", "mcp_configs": ["~/m.json"]}
    assert prof.format_args(a) == WORK_ARGS + "--mcp-config ~/m.json\n"
    assert prof.standard_args(WORK_ARGS)
    assert not prof.standard_args(WORK_ARGS + "--model opus\n")
    assert not prof.standard_args(WORK_ARGS + "--settings ~/second.json\n")
    assert not prof.standard_args("--plugin-dir\n")


def test_the_mcp_list_gives_deny_prefixes_and_leaves_plugin_servers_out():
    out = "Checking...\n\ngithub: npx gh - ✓ Connected\nclaude.ai Mail Box: https://x - ✓ Connected\n" \
          "plugin:a:b: node - ✓ Connected\n"
    assert prof.parse_mcp_list(out) == [{"name": "github", "prefix": "mcp__github"},
                                        {"name": "claude.ai Mail Box", "prefix": "mcp__claude_ai_Mail_Box"}]


def test_the_commit_message_names_every_switched_tool():
    tools = [{"id": "~/k", "kind": "pluginDir", "label": "k"}, {"id": "mcp__g", "kind": "mcp", "label": "g"},
             {"id": "p@m", "kind": "plugin", "label": "p"}]
    before = {"pluginDirs": ["~/k"], "denied": [], "disabledPlugins": []}
    after = {"pluginDirs": [], "denied": ["mcp__g"], "disabledPlugins": []}
    assert prof.commit_message("work", before, after, tools) == "profiles: work — k off, g off"
    assert prof.commit_message("work", before, before, tools) == "profiles: work"


# ---------------------------------------------------------------- reading

def test_a_folder_resolves_by_the_nearest_launch_file(pw):
    assert prof.resolve_source(pw.lib) == {"kind": "inherited", "profile": "bare", "from": "~/projects/group",
                                           "content": None}
    assert prof.resolve_source(pw.app)["kind"] == "none"
    write(os.path.join(pw.app, ".claude-launch"), "profile work\n")
    assert prof.resolve_source(pw.app) == {"kind": "custom", "profile": None, "from": None, "content": "profile work\n"}
    sub = os.path.join(pw.app, "sub")
    os.makedirs(sub)
    assert prof.resolve_source(sub) == {"kind": "inherited", "profile": None, "from": "~/projects/app",
                                        "content": "profile work\n"}


def test_folders_come_from_the_history_busiest_first_with_launch_file_ancestors(pw):
    folders = prof.scan_folders(fleet.profile_usage())
    assert [(f["display"], f["sessions"], f["lastUsed"]) for f in folders] == [
        ("~/projects/app", 2, 300), ("~/projects/group/lib", 1, 200), ("~/projects/group", 0, None)]
    # a folder that is gone and a temp folder are left out
    assert folders[2]["source"]["kind"] == "here"


def test_profiles_resolve_in_root_order_and_say_which_repository_keeps_them(pw):
    profiles = {p["name"]: p for p in prof.read_profiles(pw.cfg())}
    assert sorted(profiles) == ["bare", "side", "work"]
    assert profiles["work"] == {"name": "work", "repo": "~/projects/env-repo",
                                "pluginDirs": ["~/projects/skills", "~/projects/kit"],
                                "denied": ["mcp__github", "mcp__unmanaged", "Bash(rm:*)"],
                                "disabledPlugins": ["beta@mk", "other@mk"]}
    assert profiles["side"]["repo"] == "~/projects/extra-repo"


def test_a_settings_path_outside_the_profiles_folder_is_never_used(pw):
    write(os.path.join(pw.pdir, "work.args"), "--settings ~/elsewhere/evil.json\n")
    assert prof.profile_files(pw.cfg(), "work")[1] == os.path.join(pw.pdir, "work.json")


def test_the_tools_are_the_plugin_dirs_servers_and_enabled_plugins_minus_what_is_hidden_or_denied(pw):
    pw.conf["default_dirs"].append("~/projects/self")
    pw.save_conf()
    mcp, err = fleet.PROFILE_TOOLS.mcp_list()
    tools = prof.build_tools(pw.cfg(), mcp)
    assert err is None
    assert [(t["kind"], t["id"], t["label"], t["locked"]) for t in tools] == [
        ("pluginDir", "~/projects/skills", "your skills", True),
        ("pluginDir", "~/projects/kit", "kit", False),  # the shadowed work.args in the second root offers nothing
        ("mcp", "mcp__github", "github", False),
        ("mcp", "mcp__claude_ai_Mail_Box", "Mail Box", False),
        ("plugin", "alpha@mk", "alpha", False),
        ("plugin", "beta@mk", "beta", False),
    ]
    ids = [t["id"] for t in tools]
    assert "~/projects/self" not in ids and "mcp__blocked" not in ids and "gamma@mk" not in ids
    assert not any(i.startswith("mcp__plugin") for i in ids)


def test_the_mcp_list_is_kept_for_ten_minutes_and_a_failed_one_is_not_kept(pw):
    pw.world.mp.setenv("MCP_STUB_FAIL", "1")
    assert fleet.ui_profiles()["toolsError"].startswith("claude mcp list failed")
    pw.world.mp.delenv("MCP_STUB_FAIL")
    assert fleet.ui_profiles()["toolsError"] is None
    fleet.ui_profiles()
    assert len(pw.mcp_calls()) == 2
    fleet.ui_profiles(refresh=True)
    assert len(pw.mcp_calls()) == 3


def test_the_page_says_when_profiles_are_not_set_up(pw):
    os.unlink(os.path.join(os.environ["FLEET_HOME"], "profiles.json"))
    d = fleet.ui_profiles()
    assert d["configured"] is False and d["folders"] == [] and pw.mcp_calls() == []
    code, body = fleet.ui_profiles_write("/api/profiles/folder", {"folder": pw.app, "profile": "work"})
    assert code == 409 and "not set up" in body["error"]


# ---------------------------------------------------------------- a folder's profile

def test_setting_a_profile_writes_the_standard_file_and_inherit_removes_it(pw):
    git(pw.app, "init", "-q")
    res = prof.set_folder_profile(pw.cfg(), fleet.profile_usage(), pw.app, "work")
    assert res["source"]["kind"] == "here" and res["source"]["profile"] == "work"
    assert open(os.path.join(pw.app, ".claude-launch")).read() == \
        "# Tools this tree gets: see ~/projects/env-repo/claude/profiles/work.args\nprofile work\n"
    assert ".claude-launch" in open(os.path.join(pw.app, ".git", "info", "exclude")).read().split("\n")
    prof.set_folder_profile(pw.cfg(), fleet.profile_usage(), pw.app, "side")  # a second root's profile
    assert "see ~/projects/extra-repo/claude/profiles/side.args" in open(os.path.join(pw.app, ".claude-launch")).read()
    assert open(os.path.join(pw.app, ".git", "info", "exclude")).read().count(".claude-launch") == 1
    res = prof.set_folder_profile(pw.cfg(), fleet.profile_usage(), pw.app, None)
    assert res["source"]["kind"] == "none" and not os.path.exists(os.path.join(pw.app, ".claude-launch"))


def test_a_custom_file_a_root_line_an_unknown_profile_or_folder_are_refused(pw):
    cfg, usage = pw.cfg(), fleet.profile_usage()
    with pytest.raises(prof.ProfileError) as e:
        prof.set_folder_profile(cfg, usage, os.path.join(pw.home, "projects"), "work")
    assert e.value.status == 400 and "not a folder the page lists" in str(e.value)
    with pytest.raises(prof.ProfileError) as e:
        prof.set_folder_profile(cfg, usage, pw.app, "nope")
    assert e.value.status == 400
    with pytest.raises(prof.ProfileError) as e:
        prof.set_folder_profile(cfg, usage, pw.app, "../x")
    assert e.value.status == 400
    write(os.path.join(pw.app, ".claude-launch"), "--plugin-dir ~/x\n")
    with pytest.raises(prof.ProfileError) as e:
        prof.set_folder_profile(cfg, usage, pw.app, "work")
    assert e.value.status == 409 and open(os.path.join(pw.app, ".claude-launch")).read() == "--plugin-dir ~/x\n"
    # a root line survives a profile change, and makes inherit a hand edit
    group = os.path.join(pw.home, "projects", "group")
    write(os.path.join(group, ".claude-launch"), prof.format_launch("bare", "~/a/claude/profiles/bare.args")
          + "root ~/projects/top\n")
    prof.set_folder_profile(cfg, usage, group, "work")
    assert open(os.path.join(group, ".claude-launch")).read().endswith("profile work\nroot ~/projects/top\n")
    with pytest.raises(prof.ProfileError) as e:
        prof.set_folder_profile(cfg, usage, group, None)
    assert e.value.status == 409 and os.path.exists(os.path.join(group, ".claude-launch"))


# ---------------------------------------------------------------- a profile save

def save(pw, **change):
    body = {"name": "work", "pluginDirs": ["~/projects/skills", "~/projects/kit"], "denied": ["mcp__github"],
            "disabledPlugins": ["beta@mk"]}
    body.update(change)
    return prof.save_profile(pw.cfg(), fleet.PROFILE_TOOLS, body)


def test_a_save_rewrites_the_two_files_keeps_what_the_page_does_not_manage_and_pushes(pw):
    write(os.path.join(pw.env, "README"), "someone else's edit\n")  # another session's work stays out of the commit
    res = save(pw, pluginDirs=["~/projects/skills"], denied=["mcp__claude_ai_Mail_Box"],
               disabledPlugins=["beta@mk", "alpha@mk"])
    assert res["committed"] and res["pushed"] and res["hasRemote"] and res["pushError"] is None
    assert res["message"] == "profiles: work — kit off, github on, Mail Box off, alpha off"
    assert pw.work_args() == "# the work profile\n--plugin-dir ~/projects/skills\n" \
                             "--settings ~/projects/env-repo/claude/profiles/work.json\n"
    js = pw.work_json()
    assert js["permissions"]["deny"] == ["mcp__unmanaged", "Bash(rm:*)", "mcp__claude_ai_Mail_Box"]
    assert js["enabledPlugins"] == {"beta@mk": False, "other@mk": False, "alpha@mk": False}
    assert git(pw.env, "show", "--name-only", "--format=%s", "HEAD").split("\n") == [
        res["message"], "", "claude/profiles/work.args", "claude/profiles/work.json"]
    assert git(pw.env, "status", "--porcelain") == "M README"
    assert git(pw.remote, "log", "-1", "--format=%s", "main") == res["message"]


def test_a_save_with_nothing_switched_commits_nothing(pw):
    head = git(pw.env, "rev-parse", "HEAD")
    assert save(pw)["committed"] is False and git(pw.env, "rev-parse", "HEAD") == head


def test_a_save_is_refused_before_anything_is_written(pw):
    before = (pw.work_args(), pw.work_json())
    for change, status, words in (
            ({"pluginDirs": ["~/projects/kit"]}, 400, "cannot be switched off"),
            ({"denied": ["mcp__invented"]}, 400, "unknown tools"),
            ({"name": "nope"}, 404, "no profile"),
            ({"denied": "mcp__github"}, 400, "list of strings")):
        with pytest.raises(prof.ProfileError) as e:
            save(pw, **change)
        assert e.value.status == status and words in str(e.value)
    pw.world.mp.setenv("MCP_STUB_FAIL", "1")
    fleet.PROFILE_TOOLS.mcp = None  # a good list is kept for ten minutes; this is the first, failed, listing
    with pytest.raises(prof.ProfileError) as e:
        save(pw, denied=[])
    assert e.value.status == 503
    pw.world.mp.delenv("MCP_STUB_FAIL")
    fleet.PROFILE_TOOLS.mcp = None
    git(pw.env, "branch", "pr-tip")
    with pytest.raises(prof.ProfileError) as e:
        save(pw, denied=[])
    assert e.value.status == 409 and "pr-tip" in str(e.value)
    git(pw.env, "branch", "-D", "pr-tip")
    write(os.path.join(pw.pdir, "work.args"), WORK_ARGS + "--model opus\n")
    with pytest.raises(prof.ProfileError) as e:
        save(pw, denied=[])
    assert e.value.status == 409 and "edit it by hand" in str(e.value)
    write(os.path.join(pw.pdir, "work.args"), before[0])
    assert (pw.work_args(), pw.work_json()) == before


def test_a_repository_without_a_remote_keeps_the_commit_and_reports_no_failure(pw):
    git(pw.env, "remote", "remove", "origin")
    res = save(pw, denied=[])
    assert res["committed"] and not res["pushed"] and res["hasRemote"] is False and res["pushError"] is None


# ---------------------------------------------------------------- the page and the CLI

@pytest.fixture
def page(world, pw):
    srv = fleet.make_ui_server(port=0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = "127.0.0.1:%d" % srv.server_address[1]

    def call(method, path, body=None, headers=None):
        h = {"Host": host, "Authorization": "Bearer " + srv.fleet_token}
        if method == "POST":
            h.update({"Origin": "http://" + host, "Content-Type": "application/json"})
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        req = urllib.request.Request("http://" + host + path, method=method, headers=h,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            r = urllib.request.urlopen(req, timeout=60)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield call
    srv.shutdown()
    srv.server_close()


def test_the_page_reads_and_writes_profiles_through_the_api(pw, page):
    code, d = page("GET", "/api/profiles")
    assert code == 200 and d["configured"] and d["toolsError"] is None and d["home"] == pw.home
    assert [f["display"] for f in d["folders"]] == ["~/projects/app", "~/projects/group/lib", "~/projects/group"]
    assert [p["name"] for p in d["profiles"]] == ["bare", "side", "work"]
    code, d = page("POST", "/api/profiles/folder", {"folder": pw.app, "profile": "work"})
    assert code == 200 and d["source"]["profile"] == "work"
    code, d = page("POST", "/api/profiles/folder", {"folder": "/etc", "profile": "work"})
    assert code == 400
    code, d = page("POST", "/api/profiles/save", {"name": "work", "pluginDirs": ["~/projects/skills", "~/projects/kit"],
                                                  "denied": [], "disabledPlugins": ["beta@mk"]})
    assert code == 200 and d["pushed"] and d["message"] == "profiles: work — github on"


def test_a_profile_write_must_come_from_the_page_itself(pw, page):
    body = {"folder": pw.app, "profile": "work"}
    refused = [page("POST", "/api/profiles/folder", body, {"Origin": "http://evil.example"}),
               page("POST", "/api/profiles/folder", body, {"Content-Type": "text/plain"}),
               page("POST", "/api/profiles/folder", body, {"Authorization": None})]
    assert [c for c, _ in refused] == [403, 403, 401]
    assert not os.path.exists(os.path.join(pw.app, ".claude-launch"))
    assert page("GET", "/api/profiles", headers={"Host": "evil.example"})[0] == 403


def test_fleet_profile_ls_show_and_set(pw, world):
    world.capsys.readouterr()
    assert fleet.main(["profile", "ls"]) == 0
    out = world.capsys.readouterr().out.split("\n")
    assert out[0].split() == ["~/projects/app", "none", "(the", "launcher's", "defaults)"]
    assert out[1].split() == ["~/projects/group/lib", "bare", "from", "~/projects/group"]
    # the CLI may set any existing folder, listed or not
    fresh = os.path.join(pw.home, "projects", "fresh")
    os.makedirs(fresh)
    assert fleet.main(["profile", "set", fresh, "work"]) == 0
    assert world.capsys.readouterr().out.strip() == "~/projects/fresh now runs work, set here"
    assert fleet.main(["profile", "show", fresh]) == 0
    out = world.capsys.readouterr().out
    assert "kept in ~/projects/env-repo" in out and "denied      mcp__github" in out
    assert fleet.main(["profile", "set", fresh, "inherit"]) == 0
    assert world.capsys.readouterr().out.strip() == "~/projects/fresh now runs none (the launcher's defaults)"
    assert fleet.main(["profile", "set", fresh, "nope"]) == 1
    assert "no profile named nope" in world.capsys.readouterr().err


def test_folders_also_come_from_transcripts_the_history_never_recorded(pw):
    old = os.path.join(pw.home, "projects", "old_one")  # an underscore: the encoded directory name cannot say so
    os.makedirs(old)
    proj = os.path.join(pw.home, ".claude", "projects", "-projects-old-one")
    write(os.path.join(proj, "a.jsonl"), '{"type": "summary"}\n{"cwd": "%s", "type": "user"}\n' % old)
    write(os.path.join(proj, "b.jsonl"), '{"cwd": "%s"}\n' % old)
    write(os.path.join(proj, "c.jsonl"), '{"cwd": "%s", "cut off' % old)
    os.utime(os.path.join(proj, "b.jsonl"), (900, 900))
    os.utime(os.path.join(proj, "a.jsonl"), (950, 950))
    os.utime(os.path.join(proj, "c.jsonl"), (800, 800))
    # the history's own folder, seen in transcripts too: the larger count and the later time win
    write(os.path.join(pw.home, ".claude", "projects", "-projects-app", "x.jsonl"), '{"cwd": "%s"}\n' % pw.app)
    os.utime(os.path.join(pw.home, ".claude", "projects", "-projects-app", "x.jsonl"), (1000, 1000))
    folders = prof.scan_folders(fleet.profile_usage())
    assert [(f["display"], f["sessions"], f["lastUsed"]) for f in folders] == [
        ("~/projects/old_one", 3, 950), ("~/projects/app", 2, 1000), ("~/projects/group/lib", 1, 200),
        ("~/projects/group", 0, None)]
