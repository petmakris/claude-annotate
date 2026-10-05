import asyncio
import json
import os
import sys

from helpers import SKILL_DIR, TOKEN, run, running_app, spoken

CLIENT = str(SKILL_DIR / "talk_client.py")


def write_state(path, port):
    path.write_text(json.dumps({"port": port, "token": TOKEN, "out": "/tmp", "pid": 1}))


async def client_proc(state_path, *argv):
    return await asyncio.create_subprocess_exec(
        sys.executable, CLIENT, *argv,
        env={**os.environ, "TALK_STATE": str(state_path)},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )


async def finish(proc, stdin_text=None):
    out, err = await asyncio.wait_for(proc.communicate(stdin_text.encode() if stdin_text else None), 15)
    return proc.returncode, out.decode("utf-8"), err.decode("utf-8")


def test_doorbell_prints_a_turn_and_exits(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            proc = await client_proc(state, "doorbell", "--wait", "5")
            await asyncio.sleep(0.5)
            ctl.turns.offer("d1", [{"who": "you", "text": "hello"}])
            return await finish(proc)

    code, out, _ = run(go())
    assert code == 0
    assert out.startswith("TALK_TURN ")
    assert json.loads(out.split(" ", 1)[1]) == {"id": "d1", "said": [{"who": "you", "text": "hello"}]}


def test_doorbell_prints_non_ascii_speech_intact(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "Καλημέρα, wybierać"}])
            proc = await client_proc(state, "doorbell", "--wait", "5")
            return await finish(proc)

    code, out, _ = run(go())
    assert "Καλημέρα, wybierać" in out


def test_doorbell_prints_the_end(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.finish("learner finished", "/x/transcript.md")
            proc = await client_proc(state, "doorbell", "--wait", "5")
            return await finish(proc)

    code, out, _ = run(go())
    assert out.startswith("TALK_END ")
    assert json.loads(out.split(" ", 1)[1]) == {"reason": "learner finished", "transcript": "/x/transcript.md"}


def test_doorbell_keeps_waiting_through_empty_polls(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            proc = await client_proc(state, "doorbell", "--wait", "0.2")
            await asyncio.sleep(1.0)
            ctl.turns.offer("d1", [{"who": "you", "text": "late"}])
            return await finish(proc)

    code, out, _ = run(go())
    assert out.startswith("TALK_TURN ")


def test_doorbell_ends_when_the_server_is_gone(tmp_path):
    state = tmp_path / "state.json"
    write_state(state, 1)

    async def go():
        proc = await client_proc(state, "doorbell", "--wait", "1")
        return await finish(proc)

    code, out, _ = run(go())
    assert code == 0
    assert json.loads(out.split(" ", 1)[1]) == {"reason": "server unreachable"}


def test_doorbell_ends_when_there_is_no_state_file(tmp_path):
    async def go():
        proc = await client_proc(tmp_path / "missing.json", "doorbell", "--wait", "1")
        return await finish(proc)

    code, out, _ = run(go())
    assert out.startswith("TALK_END ")


def test_reply_sends_stdin_as_the_spoken_text(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "hi"}])
            await ctl.turns.next(timeout=1)
            proc = await client_proc(state, "reply", "d1")
            result = await finish(proc, "Hello there.")
            return result, spoken(ctl)

    (code, out, _), said = run(go())
    assert code == 0 and out.strip() == "sent"
    assert said == ["Hello there."]


def test_reply_to_a_turn_merged_into_a_newer_one_says_no_such_turn(tmp_path):
    """Two turns sent before the doorbell collects them become one, under the newer id."""
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "one"}])
            ctl.turns.offer("d2", [{"who": "you", "text": "two"}])
            proc = await client_proc(state, "reply", "d1")
            return await finish(proc, "Stale.")

    code, _, err = run(go())
    assert code == 2
    assert "no such turn" in err


def test_a_reply_to_an_earlier_turn_is_still_shown_after_a_newer_one_arrives(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "one"}])
            await ctl.turns.next(timeout=1)
            ctl.turns.offer("d2", [{"who": "you", "text": "two"}])
            proc = await client_proc(state, "reply", "d1")
            return await finish(proc, "The first answer."), spoken(ctl)

    (code, out, _), said = run(go())
    assert code == 0 and out.strip() == "sent"
    assert said == ["The first answer."]


def test_reply_status_does_not_read_stdin(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "check jira"}])
            await ctl.turns.next(timeout=1)
            proc = await client_proc(state, "reply", "d1", "--status", "checking Jira")
            return await finish(proc), ctl.turns.working

    (code, out, _), working = run(go())
    assert code == 0 and working


def test_reply_fails_cleanly_when_the_server_is_gone(tmp_path):
    state = tmp_path / "state.json"
    write_state(state, 1)

    async def go():
        proc = await client_proc(state, "reply", "d1")
        return await finish(proc, "Hello.")

    code, _, err = run(go())
    assert code == 2
    assert "not reachable" in err


def test_an_older_doorbell_exits_quietly_when_a_newer_one_arms(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            older = await client_proc(state, "doorbell", "--wait", "5")
            await asyncio.sleep(0.5)
            newer = await client_proc(state, "doorbell", "--wait", "5")
            first = await finish(older)
            ctl.turns.offer("d1", [{"who": "you", "text": "hello"}])
            return first, await finish(newer)

    (code, out, _), (_, newer_out, _) = run(go())
    assert code == 0
    assert out.startswith("doorbell superseded") and "TALK_" not in out
    assert newer_out.startswith("TALK_TURN ")


def test_reply_after_the_call_ended_exits_4(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "one"}])
            await ctl.turns.next(timeout=1)
            ctl.end("test")
            proc = await client_proc(state, "reply", "d1")
            return await finish(proc, "Too late."), spoken(ctl)

    (code, out, _), said = run(go())
    assert code == 4
    assert out.startswith("call ended")
    assert said == []


def test_reply_to_a_turn_that_never_existed_says_so(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            proc = await client_proc(state, "reply", "nope")
            return await finish(proc, "Hello.")

    code, _, err = run(go())
    assert code == 2
    assert "no such turn" in err


def test_status_cannot_be_combined_with_end():
    async def go():
        proc = await client_proc("/nonexistent", "reply", "d1", "--status", "checking", "--end")
        return await finish(proc)

    code, _, err = run(go())
    assert code == 2
    assert "--status cannot be combined with --end" in err


def test_reply_reports_board_problems(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path, code=tmp_path) as (client, ctl, log):
            write_state(state, client.server.port)
            ctl.turns.offer("d1", [{"who": "you", "text": "show me"}])
            await ctl.turns.next(timeout=1)
            proc = await client_proc(state, "reply", "d1")
            return await finish(proc, "[[show code: missing.py:1-5 | M]] Here.")

    code, out, _ = run(go())
    assert code == 0
    assert out.splitlines() == ["sent", "board: code not shown, no such file in the code folder: missing.py"]
