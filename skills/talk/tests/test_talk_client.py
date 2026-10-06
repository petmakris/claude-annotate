import asyncio
import json
import os
import sys

from pathlib import Path

from helpers import CALL, SKILL_DIR, TOKEN, add_call, run, running_app, running_server, spoken

CLIENT = str(SKILL_DIR / "talk_client.py")


def run_dir(state_path) -> Path:
    """Each test keeps its call files in a folder of its own, next to `state_path`."""
    return Path(state_path).parent / "run"


def write_state(path, port, call_id=CALL, token=TOKEN):
    calls = run_dir(path) / "calls"
    calls.mkdir(parents=True, exist_ok=True)
    (calls / f"{call_id}.json").write_text(json.dumps({"port": port, "token": token, "call": call_id, "pid": 1}))


async def client_proc(state_path, *argv):
    return await asyncio.create_subprocess_exec(
        sys.executable, CLIENT, *argv,
        env={**os.environ, "TALK_RUN_DIR": str(run_dir(state_path))},
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
    assert json.loads(out.split(" ", 1)[1]) == {"reason": "no call is open"}


def test_each_session_reaches_its_own_call_by_its_id(tmp_path):
    """Two calls on one server: a doorbell and a reply that name a call never touch the other."""
    state = tmp_path / "state.json"

    async def go():
        async with running_server() as (client, server, fake):
            a = add_call(server, tmp_path, call_id="call-a", token="token-a", topic="A")
            b = add_call(server, tmp_path, call_id="call-b", token="token-b", topic="B")
            write_state(state, client.server.port, "call-a", "token-a")
            write_state(state, client.server.port, "call-b", "token-b")
            b.turns.offer("t1", [{"who": "you", "text": "for b"}])
            bell = await client_proc(state, "doorbell", "--call", "call-b", "--wait", "5")
            rang = await finish(bell)
            reply = await finish(await client_proc(state, "reply", "t1", "--call", "call-b"), "Answer for B.")
            return rang, reply, spoken(a), spoken(b)

    (_, rang, _), (code, out, _), said_a, said_b = run(go())
    assert json.loads(rang.split(" ", 1)[1])["said"] == [{"who": "you", "text": "for b"}]
    assert code == 0 and out.strip() == "sent"
    assert said_a == [] and said_b == ["Answer for B."]


def test_with_several_calls_open_a_command_must_name_one(tmp_path):
    state = tmp_path / "state.json"
    write_state(state, 1, "call-a")
    write_state(state, 1, "call-b")

    async def go():
        return await finish(await client_proc(state, "reply", "t1"), "Hi.")

    code, _, err = run(go())
    assert code == 2
    assert "several calls are open; name one with --call (call-a, call-b)" in err


def test_a_doorbell_for_a_call_that_is_not_open_ends(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        return await finish(await client_proc(state, "doorbell", "--call", "gone", "--wait", "1"))

    _, out, _ = run(go())
    assert json.loads(out.split(" ", 1)[1]) == {"reason": "call gone is not open on this machine"}


def test_a_doorbell_for_a_call_the_server_closed_says_it_ended(tmp_path):
    state = tmp_path / "state.json"

    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path)
            write_state(state, client.server.port)
            call.end("test")
            call.turns.end_collected.set()
            await server.close(call)
            return await finish(await client_proc(state, "doorbell", "--wait", "1"))

    _, out, _ = run(go())
    assert json.loads(out.split(" ", 1)[1]) == {"reason": "the call has ended"}


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


def test_a_reply_the_server_did_not_confirm_in_time_says_not_to_resend(monkeypatch, capsys):
    import socket

    import talk_client

    def slow(*a, **k):
        raise socket.timeout("timed out")

    monkeypatch.setattr(talk_client, "load_state", lambda call_id: {"port": 1, "token": "t"})
    monkeypatch.setattr(talk_client, "request", slow)
    monkeypatch.setattr(talk_client.sys, "stdin", __import__("io").StringIO("Hello."))
    assert talk_client.reply("c", "t1", None, False) == 2
    assert "do not resend it" in capsys.readouterr().err


def test_an_ended_call_or_a_dead_server_leaves_no_call_to_guess(tmp_path, monkeypatch):
    import talk_files

    monkeypatch.setenv("TALK_RUN_DIR", str(tmp_path))
    talk_files.write_private(talk_files.call_file("live"), {"port": 1, "token": "t", "pid": os.getpid()})
    talk_files.write_private(talk_files.call_file("ended"), {"port": 1, "token": "t", "pid": os.getpid(), "ended": True})
    talk_files.write_private(talk_files.call_file("dead"), {"port": 1, "token": "t", "pid": 2 ** 22 + 12345})
    assert talk_files.open_calls() == ["live"]
    assert talk_files.call_ids() == ["dead", "ended", "live"]


def test_an_ended_call_marks_its_file(tmp_path, monkeypatch):
    import talk
    import talk_files
    from helpers import make_args

    monkeypatch.setenv("TALK_RUN_DIR", str(tmp_path))
    server = talk.Server("s", port=8799)
    call = add_call(server, tmp_path, call_id="c1")
    server.write_call_file(call)
    assert talk_files.open_calls() == ["c1"]
    call.end("test over")
    assert talk_files.read(talk_files.call_file("c1"))["ended"] is True and talk_files.open_calls() == []


def test_a_call_id_never_starts_with_an_option_character(monkeypatch):
    import argparse

    import talk

    ids = iter(["-AbCdEfGhIjKlMnOpQrSt", "_AbCdEfGhIjKlMnOpQrSt", "AbCd-fGhIjKlMnOpQrSt"])
    monkeypatch.setattr(talk.secrets, "token_urlsafe", lambda n: next(ids))
    assert talk.new_call_id() == "AbCd-fGhIjKlMnOpQrSt"
    parser = argparse.ArgumentParser()
    parser.add_argument("--call")
    assert parser.parse_args(["--call=-AbCd"]).call == "-AbCd"
