"""A call outlives the server process that holds it: a server that stops leaves its open calls'
state behind, and the next server on the port carries them on under the same id and token."""
import asyncio
import json
import os
import sys
from unittest.mock import patch

from helpers import SERVER_AUTH, SERVER_TOKEN, SKILL_DIR, FakeSpeech, add_call, run, running_server, talk

files = talk.talk_files
CLIENT = str(SKILL_DIR / "talk_client.py")


def auth(token):
    return {"X-Talk-Token": token}


async def until(check, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.02)


def forget(call_id):
    for path in (files.call_file(call_id), files.state_file(call_id)):
        path.unlink(missing_ok=True)


async def serve(server, port=0):
    from aiohttp import web

    runner = web.AppRunner(talk.build_app(server))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    server.port = site._server.sockets[0].getsockname()[1]
    return runner


async def client_proc(*argv, **env):
    return await asyncio.create_subprocess_exec(
        sys.executable, CLIENT, *argv, env={**os.environ, "TALK_RECONNECT_S": "20", **env},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)


def test_a_call_survives_a_server_replacement_with_the_same_id_and_token(tmp_path):
    async def go():
        async with running_server() as (old_client, old, fake):
            call = add_call(old, tmp_path, call_id="kept-call", token="kept-token", topic="Kept")
            old.write_call_file(call)
            call.offer("first question", typed=True)
            await old_client.get("/api/turn?wait=1", headers=auth("kept-token"))
            await old_client.post("/api/reply", json={"id": "t1", "text": "First answer."}, headers=auth("kept-token"))
            await until(lambda: call.entries[-1].get("speech") == "ready")
            call.offer("second question", typed=False)
            await old_client.get("/api/turn?wait=1", headers=auth("kept-token"))
            await old.hand_over()
            during = (await old_client.get("/api/state", headers=auth("kept-token"))).status
            port = old.port
        async with running_server() as (client, new, fake):
            new.port = port
            adopted = talk.adopt_calls(new)
            state = await (await client.get("/api/state", headers=auth("kept-token"))).json()
            page = await (await client.get("/c/kept-call")).text()
            answer = next(e for e in state["entries"] if e["who"] == "claude")
            sound = await client.get(f"/c/kept-call/{answer['audio']}")
            reply = await client.post("/api/reply", json={"id": "t2", "text": "Second answer."}, headers=auth("kept-token"))
            again = await client.post("/api/reply", json={"id": "t1", "text": "First again."}, headers=auth("kept-token"))
            kept = new.calls["kept-call"]
            await until(lambda: kept.entries[-1].get("speech") == "ready")
            on_file = files.read(files.call_file("kept-call"))
            result = (during, [c.id for c in adopted], kept.token, state, page, sound.status, reply.status,
                      await again.json(), on_file, kept.ended, [e["text"] for e in kept.entries if e["who"] == "claude"])
            kept.end("test over")
        forget("kept-call")
        return result

    during, adopted, token, state, page, sound, reply, again, on_file, ended, answers = run(go())
    assert during == 503
    assert adopted == ["kept-call"] and token == "kept-token" and ended is None
    assert [e["text"] for e in state["entries"] if e["who"] == "you"] == ["first question", "second question"]
    assert state["working"] and not state["ended"]
    assert '"token": "kept-token"' in page and '"call": "kept-call"' in page and '"topic": "Kept"' in page
    assert sound == 200 and reply == 200
    assert "ignored" in again
    assert answers == ["First answer.", "Second answer."]
    assert (on_file["pid"], on_file["token"], on_file["format"]) == (os.getpid(), "kept-token", files.CALL_FORMAT)


def test_the_page_view_after_adoption_still_holds_the_earlier_entries(tmp_path):
    async def go():
        async with running_server() as (old_client, old, fake):
            call = add_call(old, tmp_path, call_id="view-call", token="view-token")
            old.write_call_file(call)
            call.offer("show me the ports", typed=True)
            await old_client.get("/api/turn?wait=1", headers=auth("view-token"))
            await old_client.post("/api/reply", json={
                "id": "t1", "text": "[[show table | Ports]]\n| name | port |\n|---|---|\n| talk | 8766 |\n[[/show]] "
                                    "Talk listens here. [[key: talk is on 8766]]"}, headers=auth("view-token"))
            await until(lambda: call.entries[-1].get("speech") == "ready")
            before = await (await old_client.get("/api/state", headers=auth("view-token"))).json()
            await old.hand_over()
            port = old.port
        async with running_server() as (client, new, fake):
            new.port = port
            talk.adopt_calls(new)
            after = await (await client.get("/api/state", headers=auth("view-token"))).json()
            same = await (await client.get(f"/api/state?v={before['v']}", headers=auth("view-token"))).json()
            kept = new.calls["view-call"]
            kept.offer("point at it", typed=True)
            await client.get("/api/turn?wait=1", headers=auth("view-token"))
            pointed = await (await client.post("/api/reply", json={
                "id": kept.turns.snapshot()["open"][0], "text": "[[point Ports: row \"talk\"]] That row."},
                headers=auth("view-token"))).json()
            transcript = kept.transcript.read_text()
            keys, views = list(kept.keys), dict(kept.view_names)
            kept.end("test over")
        forget("view-call")
        return before, after, same, pointed, transcript, keys, views

    before, after, same, pointed, transcript, keys, views = run(go())
    assert after["entries"] == before["entries"]
    assert after["v"] != before["v"] and "same" not in same
    assert pointed["board_problems"] == []
    assert "**You:** show me the ports" in transcript and "**Key point:** talk is on 8766" in transcript
    assert transcript.count("# Test topic") == 1
    assert keys == [{"answer": 1, "text": "talk is on 8766"}]
    assert ("table", "ports", "") in views


def test_an_answer_still_being_read_aloud_is_read_by_the_next_server(tmp_path):
    async def go():
        async with running_server() as (old_client, old, fake):
            call = add_call(old, tmp_path, call_id="voice-call", token="voice-token")
            old.write_call_file(call)
            call.offer("q", typed=True)
            await old_client.get("/api/turn?wait=1", headers=auth("voice-token"))
            call.turns.accept_reply("t1")
            call.add("claude", "Never read.", audio=None, speech="making", cues=[], words=[],
                     speech_started=1.0, speech_estimate=2.0)
            await old.hand_over()
            port = old.port
        async with running_server() as (client, new, fake):
            new.port = port
            talk.adopt_calls(new)
            kept = new.calls["voice-call"]
            await until(lambda: kept.entries[-1].get("speech") == "ready")
            result = kept.entries[-1]["audio"], fake.spoken
            kept.end("test over")
        forget("voice-call")
        return result

    audio, spoken = run(go())
    assert audio and spoken == ["Never read."]


def test_a_call_open_when_its_server_stops_is_not_ended(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path, call_id="open-call", token="open-token")
            server.write_call_file(call)
            server.keep(call)
            waiting = asyncio.ensure_future(client.get("/api/turn?wait=20", headers=auth("open-token")))
            await asyncio.sleep(0.2)
            await server.hand_over()
            polled = await asyncio.wait_for(waiting, 5)
            call.closed.set()
            await asyncio.wait(server.tasks, timeout=5)
            return polled.status, call.ended, files.read(files.call_file("open-call")), files.read(files.state_file("open-call"))

    polled, ended, on_file, state = run(go())
    forget("open-call")
    assert polled == 204 and ended is None
    assert on_file and not on_file.get("ended") and files.adoptable(on_file)
    assert state["call"] == "open-call" and state["token"] == "open-token"


def test_an_ended_call_is_not_adopted(tmp_path, monkeypatch):
    finished = []
    monkeypatch.setattr(talk.stage_mod.wc, "finish_session", finished.append)

    async def go():
        async with running_server() as (client, old, fake):
            call = add_call(old, tmp_path, call_id="ended-call", token="ended-token")
            call.stage_sid = "260101-000000-ended"
            old.write_call_file(call)
            old.save_state(call)
            call.end("ended from the page")
            port = old.port
        async with running_server() as (client, new, fake):
            new.port = port
            adopted = talk.adopt_calls(new)
            state = await client.get("/api/state", headers=auth("ended-token"))
            return adopted, state.status, new.calls

    adopted, status, calls = run(go())
    assert adopted == [] and calls == {} and status == 403
    assert finished == ["260101-000000-ended"]
    assert files.read(files.call_file("ended-call")) is None and files.read(files.state_file("ended-call")) is None


def test_an_old_format_call_file_is_ended_not_adopted(tmp_path, monkeypatch):
    finished = []
    monkeypatch.setattr(talk.stage_mod.wc, "finish_session", finished.append)
    files.write_private(files.call_file("old-call"), {"port": 8793, "token": "old-token", "call": "old-call",
                                                       "pid": os.getpid(), "stage_sid": "260101-000000-old"})
    files.write_private(files.state_file("old-call"), {"call": "old-call", "token": "old-token"})

    async def go():
        async with running_server() as (client, new, fake):
            new.port = 8793
            return talk.adopt_calls(new), new.calls

    adopted, calls = run(go())
    assert adopted == [] and calls == {}
    assert finished == ["260101-000000-old"]
    assert files.read(files.call_file("old-call")) is None and files.read(files.state_file("old-call")) is None


def test_a_call_whose_state_is_missing_or_does_not_match_is_ended(tmp_path, monkeypatch):
    finished = []
    monkeypatch.setattr(talk.stage_mod.wc, "finish_session", finished.append)
    base = {"port": 8792, "pid": os.getpid(), "format": files.CALL_FORMAT}
    files.write_private(files.call_file("no-state"), {**base, "token": "a", "call": "no-state", "stage_sid": "s1"})
    files.write_private(files.call_file("wrong-token"), {**base, "token": "b", "call": "wrong-token", "stage_sid": "s2"})
    files.write_private(files.state_file("wrong-token"), {"format": files.CALL_FORMAT, "call": "wrong-token",
                                                           "token": "not-b"})

    async def go():
        async with running_server() as (client, new, fake):
            new.port = 8792
            return talk.adopt_calls(new)

    assert run(go()) == []
    assert sorted(finished) == ["s1", "s2"]
    assert files.read(files.call_file("no-state")) is None and files.read(files.call_file("wrong-token")) is None


def test_quit_with_handover_stops_with_calls_open_and_health_says_it_can(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path, call_id="busy-call", token="busy-token")
            health = await (await client.get("/api/health", headers=SERVER_AUTH)).json()
            plain = (await client.post("/api/quit", headers=SERVER_AUTH)).status
            handover = (await client.post("/api/quit", json={"handover": True}, headers=SERVER_AUTH)).status
            return health["handover"], plain, handover, server.stop.is_set(), server.calls["busy-call"].ended

    assert run(go()) == (True, 409, 200, True, None)


def test_a_doorbell_waits_through_a_server_replacement_and_gets_the_next_turn(tmp_path):
    async def go():
        old = talk.Server(SERVER_TOKEN)
        runner = await serve(old)
        port = old.port
        call = add_call(old, tmp_path, call_id="bell-call", token="bell-token")
        old.write_call_file(call)
        old.save_state(call)
        proc = await client_proc("doorbell", "--call=bell-call", "--wait", "2")
        await asyncio.sleep(0.5)
        await old.hand_over()
        await runner.cleanup()
        old.speech.shutdown()
        await asyncio.sleep(1.5)
        new = talk.Server(SERVER_TOKEN)
        new.port = port
        runner = await serve(new, port)
        talk.adopt_calls(new)
        new.calls["bell-call"].offer("after the restart", typed=True)
        out, err = await asyncio.wait_for(proc.communicate(), 20)
        new.calls["bell-call"].end("test over")
        new.speech.shutdown()
        await runner.cleanup()
        forget("bell-call")
        return proc.returncode, out.decode(), err.decode()

    code, out, err = run(go())
    assert code == 0, err
    assert out.startswith("TALK_TURN ")
    assert json.loads(out.split(" ", 1)[1])["said"] == [{"who": "you", "text": "after the restart"}]


def test_a_reply_sent_while_the_server_is_gone_reaches_the_next_one(tmp_path):
    fake = FakeSpeech()

    async def go():
        old = talk.Server(SERVER_TOKEN)
        runner = await serve(old)
        port = old.port
        call = add_call(old, tmp_path, call_id="reply-call", token="reply-token")
        old.write_call_file(call)
        call.offer("q", typed=True)
        assert (await call.turns.next(timeout=1))["id"] == "t1"
        await old.hand_over()
        await runner.cleanup()
        old.speech.shutdown()
        proc = await client_proc("reply", "t1", "--call=reply-call")
        proc.stdin.write(b"Answered after the restart.")
        proc.stdin.close()
        await asyncio.sleep(1.5)
        new = talk.Server(SERVER_TOKEN)
        new.port = port
        runner = await serve(new, port)
        talk.adopt_calls(new)
        out, err = await asyncio.wait_for(proc.communicate(), 20)
        texts = [e["text"] for e in new.calls["reply-call"].entries if e["who"] == "claude"]
        new.calls["reply-call"].end("test over")
        new.speech.shutdown()
        await runner.cleanup()
        forget("reply-call")
        return proc.returncode, out.decode(), err.decode(), texts

    with patch.object(talk.speech, "speak", fake.speak):
        code, out, err, texts = run(go())
    assert (code, out.strip()) == (0, "sent"), err
    assert texts == ["Answered after the restart."]


def test_a_doorbell_for_an_old_format_call_still_ends_at_once_when_the_server_is_gone(tmp_path):
    files.write_private(files.call_file("old-bell"), {"port": 1, "token": "t", "call": "old-bell", "pid": os.getpid()})

    async def go():
        proc = await client_proc("doorbell", "--call=old-bell", "--wait", "1")
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
        return out.decode()

    out = run(go())
    files.call_file("old-bell").unlink()
    assert json.loads(out.split(" ", 1)[1]) == {"reason": "server unreachable"}


def test_a_doorbell_gives_up_once_no_server_carries_the_call_on(tmp_path):
    files.write_private(files.call_file("lost-call"), {"port": 1, "token": "t", "call": "lost-call",
                                                        "pid": os.getpid(), "format": files.CALL_FORMAT})

    async def go():
        proc = await client_proc("doorbell", "--call=lost-call", "--wait", "1", TALK_RECONNECT_S="1.5")
        out, _ = await asyncio.wait_for(proc.communicate(), 15)
        return out.decode()

    out = run(go())
    files.call_file("lost-call").unlink()
    assert json.loads(out.split(" ", 1)[1]) == {"reason": "server unreachable"}


# -- the deliberate restart ----------------------------------------------------------------


def test_restart_refuses_a_server_that_would_end_its_open_calls(monkeypatch, capsys):
    info = {"port": 8766, "token": "t"}
    asked = []
    monkeypatch.setattr(talk, "running_server", lambda port: info)
    monkeypatch.setattr(talk, "server_health", lambda i: {"code": "older", "calls": 1, "open": 1, "pid": 7})
    monkeypatch.setattr(talk, "server_request", lambda *a, **k: asked.append(a) or {})
    assert talk.restart_server(8766) == 2
    assert asked == []
    assert "would end its 1 open call(s) if stopped, so it was not restarted" in capsys.readouterr().out


def test_restart_hands_the_calls_over_to_a_new_server(monkeypatch, capsys):
    info = {"port": 8766, "token": "t"}
    asked = []
    health = iter([{"code": "older", "calls": 2, "open": 2, "pid": 7, "handover": True}, None, None,
                   {"code": talk.code_version(), "open": 2, "pid": 8, "handover": True}])
    monkeypatch.setattr(talk, "running_server", lambda port: info)
    monkeypatch.setattr(talk, "server_health", lambda i: next(health, None))
    monkeypatch.setattr(talk, "port_held", lambda port: False)
    monkeypatch.setattr(talk, "server_request", lambda i, method, path, body=None, **k: asked.append((path, body)) or {})
    monkeypatch.setattr(talk, "spawn_and_wait", lambda port: {"port": port, "token": "new"})
    assert talk.restart_server(8766) == 0
    assert asked == [("/api/quit", {"handover": True})]
    out = capsys.readouterr().out
    assert "pid 8" in out and "2 call(s) carried over" in out


def test_restart_leaves_a_server_that_will_not_stop_alone(monkeypatch, capsys):
    info = {"port": 8766, "token": "t"}
    spawned = []
    monkeypatch.setattr(talk, "running_server", lambda port: info)
    monkeypatch.setattr(talk, "server_health", lambda i: {"code": "older", "open": 1, "pid": 7, "handover": True})
    monkeypatch.setattr(talk, "port_held", lambda port: True)
    monkeypatch.setattr(talk, "server_request", lambda *a, **k: {})
    monkeypatch.setattr(talk, "spawn_and_wait", lambda port: spawned.append(port))
    monkeypatch.setattr(talk, "PORT_WAIT_S", 0.0)
    monkeypatch.setattr(talk, "HANDOVER_S", 0.0)
    assert talk.restart_server(8766) == 2
    assert spawned == []
    assert "did not stop when asked; nothing was changed" in capsys.readouterr().out


def test_a_launch_joins_a_server_with_calls_open_and_names_the_restart(monkeypatch, capsys):
    info = {"port": 8766, "token": "t"}
    monkeypatch.setattr(talk, "running_server", lambda port: info)
    monkeypatch.setattr(talk, "server_health", lambda i: {"code": "older", "calls": 1, "open": 1, "handover": True})
    assert talk.start_server(8766) is info
    assert "--restart" in capsys.readouterr().out


def test_a_server_waits_for_the_previous_one_to_exit_before_carrying_its_calls(monkeypatch):
    alive = iter([True, True, False])
    monkeypatch.setattr(files, "pid_alive", lambda pid: next(alive, False))
    monkeypatch.setattr(talk.time, "sleep", lambda s: None)
    talk.wait_for_exit(12345)
    assert next(alive, "done") == "done"
