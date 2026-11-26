"""The recorder hook: one entry per lifecycle event, named by the one parser, jobs as kind=job, never failing."""
import json
import os
import subprocess

from index_testkit import ROOT, hub, index_env, sid, transcript  # noqa: F401

import fleet_index_hook as hook  # noqa: E402
import fleet_index_journal as journal  # noqa: E402
import fleet_index_parse as parse  # noqa: E402
import fleet_index_store as store  # noqa: E402
import fleet_work  # noqa: E402

RULES = fleet_work.Rules(home="/nowhere")


def entry(payload, fh, **env):
    return hook.entry_for(payload, environ=env, fleet_home=fh, machine="main", rules=RULES, now=100.0)


def test_each_event_is_one_entry_with_the_parsers_facts_and_observed_values(index_env):
    fh = str(index_env / "fleet")
    p = transcript(str(index_env / "t.jsonl"), ["fix the build please"], ["It builds now."])
    base = {"session_id": sid(1), "transcript_path": p, "cwd": "/home/me/app"}
    start = entry(dict(base, hook_event_name="SessionStart"), fh)
    assert start["event"] == "start"
    assert start["fields"]["name"] == "fix the build please" and start["fields"]["name_source"] == "prompt"
    assert start["fields"]["observed"] == {"live": True, "state": "idle", "observed_at": 100.0}
    prompt = entry(dict(base, hook_event_name="UserPromptSubmit", prompt="and the docs?"), fh)
    assert (prompt["fields"]["last_prompt"], prompt["fields"]["last_answer"]) == ("and the docs?", "")
    assert prompt["fields"]["observed"]["state"] == "busy"
    stop = entry(dict(base, hook_event_name="Stop"), fh)
    assert (stop["fields"]["last_prompt"], stop["fields"]["last_answer"]) == ("fix the build please", "It builds now.")
    end = entry(dict(base, hook_event_name="SessionEnd", reason="logout"), fh)
    assert (end["fields"]["end_reason"], end["fields"]["observed"]["live"]) == ("logout", False)
    assert entry(dict(base, hook_event_name="PreToolUse"), fh) is None
    assert all(e["fields"]["kind"] == "chat" and e["fields"]["work"] is False for e in (start, prompt, stop, end))


def test_a_custom_title_wins_over_an_ai_title_and_the_name_is_cut_like_the_registry(index_env):
    p = transcript(str(index_env / "t.jsonl"), ["x " * 80], ["ok"])
    with open(p, "a") as f:
        f.write(json.dumps({"type": "ai-title", "aiTitle": "an ai title"}) + "\n")
    facts = parse.session_facts(p, event="stop", hook={})
    assert (facts["name"], facts["name_source"]) == ("an ai title", "ai")
    with open(p, "a") as f:
        f.write(json.dumps({"type": "custom-title", "customTitle": "my title"}) + "\n")
    assert parse.session_facts(p, event="stop", hook={})["name"] == "my title"
    q = transcript(str(index_env / "u.jsonl"), ["word " * 30])
    name = parse.session_facts(q, event="stop", hook={})["name"]
    assert len(name) == 60 and name.endswith("…")


def test_a_detached_job_is_kind_job_named_by_its_detach_name_unless_interactive(index_env):
    fh = str(index_env / "fleet")
    payload = {"session_id": sid(2), "hook_event_name": "SessionStart", "cwd": "/home/me/app"}
    job = entry(payload, fh, CLAUDE_DETACH_NAME="osidx-2-hub", CLAUDE_CODE_ENTRYPOINT="sdk-cli")
    assert (job["fields"]["kind"], job["fields"]["name"], job["fields"]["name_source"]) == ("job", "osidx-2-hub", "job")
    chat = entry(payload, fh, CLAUDE_DETACH_NAME="osidx-2-hub", CLAUDE_CODE_ENTRYPOINT="cli")
    assert chat["fields"]["kind"] == "chat" and "name" not in chat["fields"]


def test_a_resumed_session_the_machine_does_not_know_journals_epoch_0(index_env):
    fh = str(index_env / "fleet")
    e = entry({"session_id": sid(3), "hook_event_name": "SessionStart", "source": "resume"}, fh)
    assert e["epoch_seen"] == 0
    assert entry({"session_id": sid(3), "hook_event_name": "SessionStart", "source": "startup"}, fh)["epoch_seen"] is None


def test_record_appends_and_flushes_and_never_fails(index_env, monkeypatch):
    fh = str(index_env / "fleet")
    assert hook.record({"session_id": sid(4), "hook_event_name": "SessionStart", "cwd": "/a"}) == 0
    con = store.connect(store.hub_db_path(fh))
    assert store.get_row(con, sid(4))["owner"]
    assert journal.pending(fh) == []
    monkeypatch.setattr(hook, "entry_for", lambda *a, **k: 1 / 0)
    assert hook.record({"session_id": sid(5), "hook_event_name": "Stop"}) == 0
    assert "ZeroDivisionError" in open(os.path.join(fh, "hooks.log")).read()
    monkeypatch.setenv("FLEET_NO_RECORD", "1")
    assert hook.record({"session_id": sid(6), "hook_event_name": "Stop"}) == 0


def test_record_sh_journals_every_event_and_keeps_the_history_off_prompts(index_env):
    fh = str(index_env / "fleet")
    env = dict(os.environ)
    for ev in ("SessionStart", "UserPromptSubmit"):
        payload = json.dumps({"session_id": sid(7), "hook_event_name": ev, "cwd": "/a", "prompt": "hi"})
        r = subprocess.run(["sh", os.path.join(ROOT, "hooks", "record.sh")], input=payload, capture_output=True,
                           text=True, env=env, timeout=60)
        assert (r.returncode, r.stdout) == (0, "")
    events = [e["event"] for e in journal._entries(fh)]
    assert events == ["start", "prompt"]
    con = store.connect(store.hub_db_path(fh))
    assert store.get_row(con, sid(7))["last_prompt"] == "hi"


def test_hooks_json_runs_the_recorder_on_all_four_events():
    h = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))
    for ev in ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"):
        cmds = [x["command"] for grp in h["hooks"][ev] for x in grp["hooks"]]
        assert any(c.endswith('/hooks/record.sh"') for c in cmds), ev


def test_turns_follow_env_tails_rule(index_env):
    p = transcript(str(index_env / "t.jsonl"), ["one", "two", "three"], ["a1", "a2"])
    got = parse.turns(p, 2)
    assert [(t["role"], t["text"]) for t in got] == [("user", "two"), ("assistant", "a2"), ("user", "three")]
