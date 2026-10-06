import asyncio
import json
import os
import sys

from pathlib import Path

from helpers import SERVER_TOKEN, SKILL_DIR, add_call, run, running_app, running_server

sys.path.insert(0, str(SKILL_DIR))

from talk_activity import describe  # noqa: E402

HOOK = str(SKILL_DIR / "talk_activity.py")


def run_dir(state_path) -> Path:
    return Path(state_path).parent / "run"


def write_server(state_path, port, **extra):
    """The server's file, as the hook finds it: in a run folder of this test's own."""
    folder = run_dir(state_path) / "servers"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{port}.json").write_text(json.dumps({"port": port, "token": SERVER_TOKEN, **extra}))


def test_read_names_the_file_and_lines():
    assert describe("Read", {"file_path": "/a/b/EDR.java", "offset": 30, "limit": 28}) == "Reading EDR.java lines 30–57"


def test_read_without_a_range_names_only_the_file():
    assert describe("Read", {"file_path": "/a/b/Task.java"}) == "Reading Task.java"


def test_grep_names_the_pattern_and_where():
    assert describe("Grep", {"pattern": "enum Visibility", "path": "/repo/advisory"}) == 'Searching for "enum Visibility" in advisory'


def test_bash_uses_its_description():
    assert describe("Bash", {"command": "git log -3", "description": "Show recent commits"}) == "Show recent commits"


def test_talk_client_calls_are_not_shown():
    assert describe("Bash", {"command": "python3 /x/talk_client.py doorbell", "description": "Arm"}) is None
    assert describe("Bash", {"command": "python3 /x/talk_client.py reply d1 <<'EOF'"}) is None


def test_mcp_calls_name_the_service_and_the_key_argument():
    label = describe("mcp__plugin_atlassian_atlassian__getJiraIssue", {"issueIdOrKey": "ABC-123", "cloudId": "x"})
    assert label == "Atlassian: getJiraIssue ABC-123"


def test_tool_search_is_not_shown():
    assert describe("ToolSearch", {"query": "select:X"}) is None


def test_unknown_tools_show_their_name():
    assert describe("NotebookEdit", {}) == "NotebookEdit"


async def run_hook(state_path, event):
    proc = await asyncio.create_subprocess_exec(
        sys.executable, HOOK, env={**os.environ, "TALK_RUN_DIR": str(run_dir(state_path))},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    await asyncio.wait_for(proc.communicate(json.dumps(event).encode()), 10)
    return proc.returncode


def event(session, phase, tool, tool_input):
    return {"session_id": session, "hook_event_name": phase, "tool_name": tool, "tool_input": tool_input}


def test_the_doorbell_claims_the_session_and_other_sessions_are_ignored(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_server(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "hi"}])
            await ctl.turns.next(timeout=1)
            await run_hook(state, event("me", "PreToolUse", "Bash",
                                        {"command": "python3 /x/talk_client.py doorbell"}))
            await run_hook(state, event("other", "PreToolUse", "Read", {"file_path": "/x/Other.java"}))
            await run_hook(state, event("me", "PreToolUse", "Read", {"file_path": "/x/EDR.java"}))
            await run_hook(state, event("me", "PostToolUse", "Read", {"file_path": "/x/EDR.java"}))
            return [(a["label"], a["state"]) for a in ctl.activity]

    assert run(go()) == [("Reading EDR.java", "done")]


def test_each_session_shows_only_on_the_call_its_doorbell_named(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_server() as (client, server, fake):
            a = add_call(server, tmp_path, call_id="call-a", token="token-a")
            b = add_call(server, tmp_path, call_id="call-b", token="token-b")
            write_server(state, client.server.port)
            for call in (a, b):
                call.turns.offer("d1", [{"who": "you", "text": "hi"}])
                await call.turns.next(timeout=1)
            await run_hook(state, event("one", "PreToolUse", "Bash",
                                        {"command": "python3 /x/talk_client.py doorbell --call call-a"}))
            await run_hook(state, event("two", "PreToolUse", "Bash",
                                        {"command": "python3 '/x/talk_client.py' doorbell --call 'call-b'"}))
            await run_hook(state, event("one", "PreToolUse", "Read", {"file_path": "/x/A.java"}))
            await run_hook(state, event("two", "PreToolUse", "Read", {"file_path": "/x/B.java"}))
            return [x["label"] for x in a.activity], [x["label"] for x in b.activity]

    assert run(go()) == (["Reading A.java"], ["Reading B.java"])


def test_the_hook_exits_cleanly_without_a_call(tmp_path):
    code = run(run_hook(tmp_path / "missing.json", event("me", "PreToolUse", "Read", {"file_path": "/x"})))
    assert code == 0


def test_the_hook_exits_cleanly_when_the_server_is_gone(tmp_path):
    state = tmp_path / "state.json"
    write_server(state, 1)
    code = run(run_hook(state, event("me", "PreToolUse", "Read", {"file_path": "/x"})))
    assert code == 0


SHIM = str(SKILL_DIR / "hooks" / "talk-activity.sh")


async def run_shim(state_path, event):
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh", SHIM, env={**os.environ, "TALK_RUN_DIR": str(run_dir(state_path))},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await asyncio.wait_for(proc.communicate(json.dumps(event).encode()), 10)
    return proc.returncode, out + err


def test_the_shim_is_silent_without_a_call(tmp_path):
    code, output = run(run_shim(tmp_path / "missing.json", event("me", "PreToolUse", "Read", {"file_path": "/x"})))
    assert (code, output) == (0, b"")


def test_the_shim_forwards_to_the_script_named_in_the_state_file(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_server(state, client.server.port, activity_script=HOOK)
            ctl.turns.offer("d1", [{"who": "you", "text": "hi"}])
            await ctl.turns.next(timeout=1)
            await run_shim(state, event("me", "PreToolUse", "Bash", {"command": "python3 /x/talk_client.py doorbell"}))
            await run_shim(state, event("me", "PreToolUse", "Read", {"file_path": "/x/EDR.java"}))
            return [a["label"] for a in ctl.activity]

    assert run(go()) == ["Reading EDR.java"]


def test_the_shim_survives_a_state_file_naming_a_missing_script(tmp_path):
    state = tmp_path / "state.json"
    write_server(state, 1, activity_script="/nowhere/talk_activity.py")
    code, output = run(run_shim(state, event("me", "PreToolUse", "Read", {"file_path": "/x"})))
    assert (code, output) == (0, b"")


def run_through_hook(tmp_path, *events):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_server(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "hi"}])
            await ctl.turns.next(timeout=1)
            await run_hook(state, event("me", "PreToolUse", "Bash", {"command": "python3 /x/talk_client.py doorbell"}))
            for e in events:
                await run_hook(state, e)
            return [(a["label"], a["state"]) for a in ctl.activity]

    return run(go())


def test_a_failed_tool_call_is_finished(tmp_path):
    assert run_through_hook(tmp_path, event("me", "PreToolUse", "Read", {"file_path": "/x/EDR.java"}),
                            event("me", "PostToolUseFailure", "Read", {"file_path": "/x/EDR.java"})) \
        == [("Reading EDR.java", "done")]


def test_a_denied_tool_call_is_finished(tmp_path):
    assert run_through_hook(tmp_path, event("me", "PreToolUse", "Bash", {"command": "rm -rf x", "description": "Remove x"}),
                            event("me", "PermissionDenied", "Bash", {"command": "rm -rf x", "description": "Remove x"})) \
        == [("Remove x", "done")]


def test_the_session_stopping_finishes_every_tool_still_running(tmp_path):
    stop = {"session_id": "me", "hook_event_name": "Stop"}
    assert run_through_hook(tmp_path, event("me", "PreToolUse", "Read", {"file_path": "/x/A.java"}),
                            event("me", "PreToolUse", "Grep", {"pattern": "x"}), stop) \
        == [("Reading A.java", "done"), ('Searching for "x"', "done")]
