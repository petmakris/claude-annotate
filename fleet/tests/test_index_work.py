"""Work sessions: one rule decides, the writing machine masks, the hub refuses what is left, and no word of a work
session reaches the hub, a journal or a cache dump."""
import json
import os

import pytest

from index_testkit import cluster, hub, index_env, sid, transcript  # noqa: F401

import fleet_work  # noqa: E402


def rules_file(fh, **conf):
    os.makedirs(fh, exist_ok=True)
    with open(os.path.join(fh, "work.json"), "w") as f:
        json.dump(dict({"accounts": ["first", "second"], "profile_paths": [], "own_profiles": None}, **conf), f)


def test_a_missing_rules_file_fails_closed_only_on_a_machine_with_the_env_repo(tmp_path):
    home = tmp_path / "h"
    home.mkdir()
    r = fleet_work.load_rules(str(tmp_path / "fleet"), home=str(home))
    assert (r.fail_closed, fleet_work.is_work("/anywhere", None, r)) == (False, False)
    (home / "projects" / "env").mkdir(parents=True)
    r = fleet_work.load_rules(str(tmp_path / "fleet"), home=str(home))
    assert (r.fail_closed, fleet_work.is_work("/anywhere", None, r)) == (True, True)


def test_the_rule_reads_accounts_profile_paths_and_launch_profiles(tmp_path):
    home = tmp_path / "h"
    work = tmp_path / "work-profile"
    own = tmp_path / "own"
    (work / "claude" / "profiles").mkdir(parents=True)
    (work / "claude" / "profiles" / "client.args").write_text("")
    own.mkdir()
    (own / "mine.args").write_text("")
    fh = str(tmp_path / "fleet")
    rules_file(fh, profile_paths=[str(work)], own_profiles=str(own))
    r = fleet_work.load_rules(fh, home=str(home))
    assert fleet_work.account_of(str(home / ".claude"), r) == "first"
    assert fleet_work.account_of(str(home / ".claude-second"), r) == "second"
    assert fleet_work.account_of(str(home / ".claude-acme"), r) is None
    assert fleet_work.is_work("/x", str(home / ".claude-acme" / "projects" / "-x" / "s.jsonl"), r)
    assert not fleet_work.is_work("/x", str(home / ".claude" / "projects" / "-x" / "s.jsonl"), r)
    assert fleet_work.is_work(str(work / "repo"), None, r)
    launched = tmp_path / "proj"
    (launched / "sub").mkdir(parents=True)
    (launched / ".claude-launch").write_text("profile client\n")
    assert fleet_work.is_work(str(launched / "sub"), None, r)
    (launched / ".claude-launch").write_text("profile mine\n")
    assert not fleet_work.is_work(str(launched / "sub"), None, r)


def test_a_rule_that_raises_says_work(monkeypatch):
    r = fleet_work.Rules(["first"], [], None, home="/h")
    monkeypatch.setattr(fleet_work, "_work_folder", lambda f, r: 1 / 0)
    assert fleet_work.is_work("/x", None, r) is True


def test_masking_removes_every_word_and_the_hub_check_names_what_is_left():
    fields = {"name": "client numbers check", "name_source": "ai", "first_prompt": "p", "last_prompt": "p",
              "last_answer": "a", "cwd": "/w", "account": None, "description": "d", "rc_name": "r",
              "kind": "chat", "observed": {"live": True, "tmux": "client", "observed_at": 1.0}, "work": True}
    assert fleet_work.mask_fields(fields) == {"kind": "chat", "observed": {"live": True, "observed_at": 1.0},
                                              "work": True}
    assert fleet_work.work_refusal(fleet_work.mask_fields(fields)) is None
    assert fleet_work.mask_fields({"name": "my title", "name_source": "custom"})["name"] == "my title"
    for k in fleet_work.FORBIDDEN:
        assert fleet_work.work_refusal({"work": True, k: None}) == "a work entry carries %s" % k
    assert fleet_work.work_refusal({"name": "x", "name_source": "prompt"}) == \
        "a work entry carries a name taken from a prompt"
    assert fleet_work.work_refusal({"observed": {"tmux": "c", "observed_at": 1.0}}) == "a work entry carries a tmux name"


def test_the_hub_refuses_a_work_entry_that_carries_words_and_stores_none_of_it(hub):
    e = hub.entry("mac", sid(1), "start", {"work": True, "last_prompt": "secret"})
    assert hub.apply("mac", e)["results"][0]["outcome"] == "work-refused"
    assert hub.row(sid(1)) is None
    hub.start("mac", sid(2), {"work": True})
    e = hub.entry("mac", sid(2), "prompt", {"last_prompt": "secret"})
    assert hub.apply("mac", e)["results"][0]["outcome"] == "work-refused"
    assert hub.row(sid(2))["last_prompt"] is None


def test_a_work_sessions_bytes_are_in_no_hub_db_journal_or_cache_dump(cluster, index_env):
    mac, main, lat = cluster["mac"], cluster["main"], cluster["lat"]
    folder = str(index_env / "work" / "client")
    os.makedirs(folder)
    rules_file(mac.home, profile_paths=[str(index_env / "work")])
    prompt, answer, title = "check the client's numbers in q3.xlsx", "The totals match.", "client numbers check"
    s = sid(3)
    path = transcript(mac.file("t", s + ".jsonl"), [prompt, "and the totals?"], ["Looking.", answer])
    with open(path, "a") as f:
        f.write(json.dumps({"type": "ai-title", "aiTitle": title}) + "\n")
    base = {"session_id": s, "transcript_path": path, "cwd": folder}
    for ev in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
        extra = {"prompt": "and the totals?"} if ev == "UserPromptSubmit" else {}
        assert mac.hook(dict(base, hook_event_name=ev, **extra), FLEET_RC_NAME="client-rc").returncode == 0
    note = {"sid": s, "event": "describe", "fields": {"work": True, "description": "about " + title,
                                                      "last_prompt": prompt, "cwd": folder}}
    assert mac.cli("note", stdin=json.dumps(note)).returncode == 0
    assert mac.cli("take", s, "--to", "lat", "--expect-epoch", "1", "--json").returncode == 2
    assert mac.cli("list", "--json").returncode == 0
    assert lat.cli("list", "--json").returncode == 0
    dump = mac.cli("_cache-dump")
    assert dump.returncode == 0
    assert main.cli("rebuild").returncode == 0
    row = main.hub_row(s)
    assert (row["work"], row["owner"], row["name"], row["cwd"], row["last_prompt"]) == (True, "mac", "", None, None)
    assert (mac.cache(s)["owner"], mac.cache(s)["work"]) == ("mac", True)
    needles = [folder, prompt, "and the totals?", answer, title, "client-rc"]
    places = [mac.file("index", "journal.jsonl")]
    for root in (main.home, lat.home, str(index_env / "backups")):
        for d, _, files in os.walk(root):
            places += [os.path.join(d, f) for f in files]
    assert any(p.endswith("hub.db") for p in places)
    found = []
    for p in places:
        with open(p, "rb") as f:
            data = f.read()
        found += ["%s in %s" % (n, p) for n in needles if n.encode() in data]
    found += ["%s in the cache dump" % n for n in needles if n in dump.stdout]
    assert found == []
