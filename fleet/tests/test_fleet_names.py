"""One name: a session's Claude Code name and its fleet name are kept equal, and an unnamed interactive session is
asked to name itself on its second prompt."""
import json
import os

from fleet_testkit import fleet, world  # noqa: F401


def prompt(world, who, title=None):
    """What Claude Code's UserPromptSubmit hook hands the naming hook, as `who`; returns the hook's output."""
    who.env(world.mp)
    data = {"hook_event_name": "UserPromptSubmit", "session_id": who.sid, "transcript_path": who.transcript,
            "prompt": "x"}
    if title is not None:
        data["session_title"] = title
    return fleet.name_hook(data)


def interactive(world):
    world.mp.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")


def members(world, who):
    return {m["name"]: m["session_id"] for m in json.loads(world.run(who, "ls", "--json")[1])}


def test_an_unnamed_interactive_session_is_asked_on_its_second_prompt_only(world):
    interactive(world)
    a = world.session("alpha", transcript=True)
    assert prompt(world, a) is None  # first prompt: often only navigation
    a.append_transcript("look at the fleet canary")
    out = prompt(world, a)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert out["hookSpecificOutput"]["additionalContext"].startswith("Fleet naming:")
    a.append_transcript("second")
    assert prompt(world, a) is None  # asked once at prompt 2; next at prompt 5
    a.append_transcript("third")
    a.append_transcript("fourth")
    assert "additionalContext" in prompt(world, a)["hookSpecificOutput"]
    for _ in range(5):
        a.append_transcript("more")
        assert prompt(world, a) is None  # never a third time


def test_a_headless_job_or_a_named_session_is_never_asked(world):
    world.mp.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    a = world.session("alpha", transcript=True)
    a.append_transcript("one")
    assert prompt(world, a) is None
    interactive(world)
    b = world.session("beta", transcript=True)
    b.append_transcript("one")
    assert prompt(world, b, title="my-own-name") is None


def test_fleet_name_renames_the_member_now_and_claude_at_the_next_prompt(world):
    a = world.session("alpha", transcript=True)
    world.member(a)
    prompt(world, a, title="alpha")
    code, out, err = world.run(a, "name", "Voice  sandbox rescue")
    assert code == 0, err
    assert out.splitlines() == ["this session is now called Voice sandbox rescue (Claude Code shows it from the next prompt)",
                                "renamed in the fleet: alpha -> Voice sandbox rescue"]
    assert members(world, a) == {"Voice sandbox rescue": a.sid}
    assert prompt(world, a, title="alpha") == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                                     "sessionTitle": "Voice sandbox rescue"}}
    assert prompt(world, a, title="Voice sandbox rescue") is None  # handed over once


def test_fleet_name_refuses_a_sentence(world):
    a = world.session("alpha")
    code, _, err = world.run(a, "name", "this is a whole sentence that names nothing well")
    assert code == 1 and "not a short name" in err
    assert world.run(a, "name", "x@y")[0] == 1


def test_a_claude_rename_renames_the_member_and_the_old_name_still_reaches_it(world):
    a, b = world.session("alpha", transcript=True), world.session("beta", transcript=True)
    world.member(a), world.member(b)
    prompt(world, a, title="alpha")
    assert prompt(world, a, title="fleet-naming") is None  # `/rename fleet-naming`, seen at the next prompt
    assert members(world, b) == {"fleet-naming": a.sid, "beta": b.sid}
    code, out, err = world.run(b, "tell", "alpha", "hello")
    assert code == 0, err
    assert "alpha is now called fleet-naming" in out
    assert "message 1 to fleet-naming:" in out
    assert [m["message"]["content"] for m in a.messages()][-1].count("Fleet tell 1 from beta: hello") == 1


def test_names_match_ignoring_case_spaces_and_hyphens(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a, "Fleet Naming")
    world.member(b)
    code, out, err = world.run(b, "tell", "fleet-naming", "hi")
    assert code == 0 and "message 1 to Fleet Naming:" in out, err


def test_join_without_a_name_refuses_a_session_with_none_and_takes_name_2_when_held(world):
    interactive(world)
    a, b = world.session("alpha", transcript=True), world.session("beta", transcript=True)
    prompt(world, b)  # the hook saw no title: b has no name yet
    code, _, err = world.run(b, "join")
    assert code == 2 and "has no name yet" in err and "fleet name" in err
    world.member(a, "voice-rescue")
    assert world.run(b, "name", "voice-rescue")[0] == 0
    code, out, err = world.run(b, "join")
    assert code == 0 and out.splitlines()[0] == "joined the fleet as voice-rescue-2", err
    code, _, err = world.member(b, "voice-rescue")  # a name given by hand that a live member holds is refused
    assert code == 1 and "taken by a live member" in err


def test_join_with_a_name_becomes_the_claude_name(world):
    a = world.session("alpha", transcript=True)
    prompt(world, a, title="old-title")
    world.member(a, "new-name")
    assert prompt(world, a, title="old-title")["hookSpecificOutput"]["sessionTitle"] == "new-name"


def test_history_rename_of_a_session_not_running_writes_claude_s_title_records(world):
    a, b = world.session("alpha", transcript=True), world.session("beta", transcript=True)
    b.record_start()
    b.die()
    code, out, err = world.run(a, "history", "rename", b.sid, "bike bag")
    assert code == 0 and out.strip() == "%s is now bike bag" % b.sid[:8], err
    last = json.loads(open(b.transcript).read().splitlines()[-1])
    assert last == {"type": "custom-title", "customTitle": "bike bag", "sessionId": b.sid}
    side = os.path.join(os.path.dirname(b.transcript), b.sid, "custom-title.json")
    assert json.load(open(side)) == {"customTitle": "bike bag"}
    v = json.loads(world.run(a, "history", "show", b.sid, "--json")[1])
    assert v["name"] == "bike bag"


def test_the_hook_never_fails_a_prompt(world, capsys):
    world.mp.setenv("FLEET_HOME", "/dev/null/nope")
    world.mp.setattr("sys.stdin", __import__("io").StringIO('{"session_id": "s1", "hook_event_name": "UserPromptSubmit"}'))
    assert fleet.hook_name() == 0
    assert capsys.readouterr().out == ""
