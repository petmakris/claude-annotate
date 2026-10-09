"""One talk server holds every call of the machine: a launch opens a call on it, each session reaches
its own call, and the user talks in one call at a time (the floor)."""
import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from helpers import AUTH, CALL, SERVER_AUTH, add_call, run, running_app, running_server, served_server, talk


@pytest.fixture
def no_outside(monkeypatch):
    """VoiceStudio is up, the stage daemon answers, the voice resolves: nothing outside the test runs."""
    monkeypatch.setattr(talk.speech, "ensure_running", lambda **kw: {})
    monkeypatch.setattr(talk.speech, "resolve_voice", lambda voice: ("profile-1", None))
    monkeypatch.setattr(talk.stage_mod, "ensure_stage", lambda cwd, slug, title: {
        "url": f"http://127.0.0.1:3080/s/{slug}/", "slug": slug, "sid": f"260101-000000-{'0' * 15}1"})


def launch_args(tmp_path, *more):
    return talk.build_parser().parse_args(["--topic", "The deck", "--no-open", "--out", str(tmp_path / "out"), *more])


def test_a_launch_opens_a_call_on_the_server_and_prints_where_it_is(tmp_path, monkeypatch, capsys, no_outside):
    with served_server() as (server, info):
        monkeypatch.setattr(talk, "start_server", lambda port: info)
        code = talk.launch(launch_args(tmp_path, "--url-base", "https://talk.mac", "--stage-base", "https://wc.mac"))
        out = capsys.readouterr().out.splitlines()
        call = next(iter(server.calls.values()))
        written = talk.talk_files.read(talk.talk_files.call_file(call.id))
    assert code == 0
    assert f"Link https://talk.mac/c/{call.id}" in out
    assert f"Call {call.id}" in out
    assert "Calls https://talk.mac/" in out
    stage = next(line for line in out if line.startswith("Stage "))
    assert stage.startswith(f"Stage https://wc.mac/s/{call.stage_slug}/ (folder ")
    assert written["token"] == call.token and written["port"] == info["port"]
    assert call.topic == "The deck" and call.voice == "profile-1"


def test_two_launches_share_one_server(tmp_path, monkeypatch, capsys, no_outside):
    with served_server() as (server, info):
        monkeypatch.setattr(talk, "start_server", lambda port: info)
        assert talk.launch(launch_args(tmp_path)) == 0
        assert talk.launch(launch_args(tmp_path / "second")) == 0
        ids = list(server.calls)
    assert len(ids) == 2 and ids[0] != ids[1]


def test_without_voicestudio_a_call_is_refused_at_start_not_mid_call(tmp_path, monkeypatch, capsys):
    def down(**kw):
        raise talk.speech.SpeechError("cannot reach VoiceStudio at http://127.0.0.1:1")

    monkeypatch.setattr(talk.speech, "ensure_running", down)
    with served_server() as (server, info):
        monkeypatch.setattr(talk, "start_server", lambda port: info)
        code = talk.launch(launch_args(tmp_path))
        calls = dict(server.calls)
    assert code == 2 and calls == {}
    assert "Start the VoiceStudio app" in capsys.readouterr().out


def test_a_call_needs_a_topic(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            resp = await client.post("/api/calls", json={"out": str(tmp_path)}, headers=SERVER_AUTH)
            return resp.status, server.calls

    assert run(go()) == (400, {})


def test_only_the_server_token_opens_a_call(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path)
            resp = await client.post("/api/calls", json={"topic": "T", "out": str(tmp_path)}, headers=AUTH)
            return resp.status

    assert run(go()) == 403


def test_taking_the_floor_shows_on_every_other_call(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path, call_id="a", token="ta", topic="Alpha")
            add_call(server, tmp_path, call_id="b", token="tb", topic="Beta")
            before = await (await client.get("/api/state", headers={"X-Talk-Token": "tb"})).json()
            took = await (await client.post("/api/floor", json={}, headers={"X-Talk-Token": "ta"})).json()
            same = await (await client.get(f"/api/state?v={before['v']}", headers={"X-Talk-Token": "tb"})).json()
            return before, took, same

    before, took, after = run(go())
    assert before["floor_call"] is None and [c["topic"] for c in before["calls"]] == ["Alpha"]
    assert took == {"floor_n": 1}
    assert not after.get("same")
    assert after["floor_call"] == "a" and after["floor_n"] == 1
    assert after["calls"][0]["floor"] is True


def test_an_answer_not_yet_played_is_new_on_the_other_calls(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path, call_id="a", token="ta", topic="Alpha")
            b = add_call(server, tmp_path, call_id="b", token="tb", topic="Beta")
            entry = b.add("claude", "An answer.")
            seen = await (await client.get("/api/state", headers={"X-Talk-Token": "ta"})).json()
            await client.post("/api/floor", json={"heard": entry["id"]}, headers={"X-Talk-Token": "tb"})
            played = await (await client.get("/api/state", headers={"X-Talk-Token": "ta"})).json()
            return seen["calls"][0], played["calls"][0]

    seen, played = run(go())
    assert seen["unheard"] == 1 and played["unheard"] == 0 and played["floor"] is True


def test_a_heard_that_is_not_a_number_is_ignored(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path)
            for heard in ("3", True, None, [1]):
                await client.post("/api/floor", json={"heard": heard}, headers=AUTH)
            broken = await client.post("/api/floor", data=b"{not json", headers={**AUTH, "Content-Type": "application/json"})
            return call.heard_upto, broken.status

    assert run(go()) == (-1, 200)


def test_the_list_of_calls_opens_only_after_a_call_page_was_opened(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path, topic="Alpha")
            home_before = await client.get("/")
            list_before = await client.get("/api/calls")
            page = await client.get(f"/c/{CALL}")
            home_after = await client.get("/")
            listed = await (await client.get("/api/calls")).json()
            return home_before.status, list_before.status, page.status, home_after.status, await home_after.text(), listed

    home_before, list_before, page, home_after, html, listed = run(go())
    assert (home_before, list_before, page, home_after) == (404, 403, 200, 200)
    assert "Talk calls" in html and '<link rel="stylesheet" href="/static/tokens.css">' in html
    assert [c["topic"] for c in listed["calls"]] == ["Alpha"]


def test_a_closed_call_says_it_ended(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path)
            call.end("test")
            call.turns.end_collected.set()
            await server.close(call)
            state = await client.get("/api/state", headers=AUTH)
            turn = await client.get("/api/turn?wait=0", headers=AUTH)
            stranger = await client.get("/api/state", headers={"X-Talk-Token": "never-issued"})
            return state.status, turn.status, stranger.status, server.calls

    assert run(go()) == (410, 410, 403, {})


def test_closing_a_call_lets_go_of_the_floor(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path)
            server.take_floor(call)
            call.end("test")
            call.turns.end_collected.set()
            await server.close(call)
            return server.floor

    assert run(go()) is None


def test_health_reports_the_code_and_the_calls(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path)
            ok = await (await client.get("/api/health", headers=SERVER_AUTH)).json()
            refused = await client.get("/api/health", headers=AUTH)
            return ok, refused.status

    ok, refused = run(go())
    assert ok["calls"] == 1 and ok["code"] == talk.code_version() and refused == 403


def test_the_server_will_not_quit_with_calls_open(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path)
            busy = await client.post("/api/quit", headers=SERVER_AUTH)
            server.calls.clear()
            done = await client.post("/api/quit", headers=SERVER_AUTH)
            return busy.status, done.status, server.stop.is_set()

    assert run(go()) == (409, 200, True)


def test_speech_serves_recordings_then_the_floor_then_the_rest():
    queue = talk.SpeechQueue()
    floor = {"call": "a"}
    listen = queue.lane(lambda: 0)
    lane_a = queue.lane(lambda: 1 if floor["call"] == "a" else 2)
    lane_b = queue.lane(lambda: 1 if floor["call"] == "b" else 2)
    gate, started, order = threading.Event(), threading.Event(), []
    first = lane_a.submit(lambda: (started.set(), gate.wait(5)))
    assert started.wait(5)  # the worker is busy with `first`, so the jobs below queue up
    jobs = [lane_a.submit(order.append, "a"), lane_b.submit(order.append, "b"), listen.submit(order.append, "listen")]
    floor["call"] = "b"  # the floor moves while they wait: b goes before a
    gate.set()
    for job in [first, *jobs]:
        job.result(5)
    queue.shutdown()
    assert order == ["listen", "b", "a"]


def test_a_closed_lane_drops_what_it_has_not_started():
    queue = talk.SpeechQueue()
    lane = queue.lane(lambda: 1)
    gate, started = threading.Event(), threading.Event()
    busy = lane.submit(lambda: (started.set(), gate.wait(5)))
    assert started.wait(5)
    waiting = lane.submit(lambda: "never")
    lane.shutdown()
    gate.set()
    busy.result(5)
    queue.shutdown()
    assert waiting.cancelled()
    with pytest.raises(RuntimeError):
        lane.submit(lambda: None)


def test_a_server_on_current_code_is_reused(monkeypatch):
    info = {"port": 8766, "token": "t"}
    monkeypatch.setattr(talk, "running_server", lambda port: info)
    monkeypatch.setattr(talk, "server_health", lambda i: {"code": talk.code_version(), "calls": 0})
    assert talk.start_server(8766) is info


def test_a_server_on_older_code_with_calls_open_is_joined(monkeypatch, capsys):
    info = {"port": 8766, "token": "t"}
    monkeypatch.setattr(talk, "running_server", lambda port: info)
    monkeypatch.setattr(talk, "server_health", lambda i: {"code": "older", "calls": 2})
    assert talk.start_server(8766) is info
    assert "older code" in capsys.readouterr().out


def test_a_server_that_fails_to_start_says_why(tmp_path, monkeypatch):
    log = talk.talk_files.run_dir() / "server.log"
    monkeypatch.setattr(talk, "running_server", lambda port: None)
    monkeypatch.setattr(talk, "port_held", lambda port: False)

    def spawn(port, log_path):
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("talk: port 8766 is in use: address already in use\n")
        return SimpleNamespace(poll=lambda: 1)

    monkeypatch.setattr(talk, "spawn_server", spawn)
    with pytest.raises(SystemExit) as err:
        talk.start_server(8766)
    assert "port 8766 is in use" in str(err.value) and str(log) in str(err.value)


def test_the_page_loads_its_styles_and_code_from_static_files(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            html = await (await client.get(f"/c/{CALL}")).text()
            css = await client.get("/static/call.css")
            js = await (await client.get("/static/call.js")).text()
            tokens = await client.get("/static/tokens.css")
            missing = await client.get("/static/nope.css")
            escape = await client.get("/static/..%2Ftalk.py")
            other = await client.get("/static/call.html")
            return html, css.status, css.content_type, js, tokens.status, missing.status, escape.status, other.status

    html, css_status, css_type, js, tok, missing, escape, other = run(go())
    assert '<script src="/static/call.js"></script>' in html and '"token": "test-token"' in html
    assert '<link rel="stylesheet" href="/static/tokens.css">' in html
    assert (css_status, css_type, tok) == (200, "text/css", 200)
    assert "window.CFG" in js and "__CONFIG__" not in js
    assert (missing, escape, other) == (404, 404, 404)


def test_an_edited_page_file_changes_the_code_version(tmp_path, monkeypatch):
    skill = tmp_path / "talk"
    (skill / "static").mkdir(parents=True)
    (tmp_path / "stage").mkdir()
    (skill / "talk.py").write_text("x")
    (skill / "static" / "call.js").write_text("a")
    monkeypatch.setattr(talk, "SKILL_DIR", skill)
    before = talk.code_version()
    (skill / "static" / "call.js").write_text("b")
    assert talk.code_version() != before


def test_the_page_files_are_the_ones_read_at_start_not_the_ones_on_disk_now(tmp_path, monkeypatch):
    """A git pull while a call is open must not hand a reloaded page new code for old markup."""
    monkeypatch.setattr(talk, "STATIC_DIR", tmp_path)  # what is on disk now: nothing

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            js = await client.get("/static/call.js")
            return js.status, await js.text()

    status, js = run(go())
    assert status == 200 and "window.CFG" in js


def test_a_server_on_another_port_never_hides_the_first_or_its_calls(tmp_path):
    files = talk.talk_files
    main = talk.Server("main-token", port=8766)
    main_call = add_call(main, tmp_path, call_id="main-call", token="main-call-token")
    main.write_files()
    files.write_private(files.call_file("other-call"), {"port": 8799, "token": "t", "pid": 1})
    talk.drop_stale_calls(8799)  # a test server starting on 8799
    assert files.read(files.call_file("main-call"))["token"] == "main-call-token"
    assert files.read(files.call_file("other-call")) is None
    assert files.read(files.server_file(8766))["token"] == "main-token"
    # Even a file removed by hand comes back on the server's next tick.
    files.server_file(8766).unlink()
    files.call_file("main-call").unlink()
    main.write_files()
    assert files.read(files.server_file(8766))["token"] == "main-token"
    assert files.read(files.call_file("main-call"))["port"] == 8766
    main_call.end("test over")
    for path in (files.server_file(8766), files.call_file("main-call")):
        path.unlink(missing_ok=True)


def test_a_new_server_ends_the_stages_of_calls_a_dead_server_left_behind(monkeypatch):
    files = talk.talk_files
    ended = []
    monkeypatch.setattr(talk.stage_mod.wc, "finish_session", ended.append)
    files.write_private(files.call_file("killed-call"), {"port": 8798, "token": "t", "pid": 1,
                                                          "stage_sid": "260101-000000-killed"})
    files.write_private(files.call_file("no-stage-call"), {"port": 8798, "token": "t", "pid": 1})
    files.write_private(files.call_file("other-port-call"), {"port": 8797, "token": "t", "pid": 1,
                                                              "stage_sid": "260101-000000-other"})
    talk.drop_stale_calls(8798)
    assert ended == ["260101-000000-killed"]
    assert files.read(files.call_file("killed-call")) is None
    assert files.read(files.call_file("no-stage-call")) is None
    assert files.read(files.call_file("other-port-call"))["stage_sid"] == "260101-000000-other"
    files.call_file("other-port-call").unlink()


def test_a_call_file_records_its_stage_so_a_later_server_can_end_it(tmp_path):
    files = talk.talk_files
    server = talk.Server("stage-token", port=8796)
    call = add_call(server, tmp_path, call_id="staged-call", token="staged-call-token")
    call.stage_sid = "260101-000000-staged"
    server.write_call_file(call)
    assert files.read(files.call_file("staged-call"))["stage_sid"] == "260101-000000-staged"
    call.end("test over")
    files.call_file("staged-call").unlink()


# -- who holds the port: a server this launch cannot reach is named, never raced --------------


def test_a_port_held_by_a_server_without_a_run_file_is_reported_not_raced(monkeypatch):
    monkeypatch.setattr(talk, "running_server", lambda port: None)
    monkeypatch.setattr(talk, "port_held", lambda port: True)
    monkeypatch.setattr(talk, "port_answer", lambda port: "talk")
    monkeypatch.setattr(talk, "port_holder", lambda port: "52619")
    monkeypatch.setattr(talk, "PORT_WAIT_S", 0.0)
    with pytest.raises(SystemExit) as err:
        talk.start_server(8766)
    assert str(err.value) == ("talk: port 8766 is held by a talk server this launch has no token for (its run file is "
                              "missing or stale), pid 52619; stop it with `kill 52619`, or pass --port <another port>")


def test_a_server_on_older_code_is_found_through_the_old_run_file(tmp_path):
    files = talk.talk_files
    with served_server() as (server, info):
        files.write_private(files.legacy_server_file(), {**info, "pid": 1})
        try:
            assert talk.running_server(info["port"]) == {**info, "pid": 1}
            assert talk.port_answer(info["port"]) == "talk"
        finally:
            files.legacy_server_file().unlink()


def test_doctor_fails_when_the_port_is_held_by_a_server_it_cannot_reach(monkeypatch, capsys):
    monkeypatch.setattr(talk.speech, "ensure_running", lambda **kw: {})
    monkeypatch.setattr(talk.speech, "describe", lambda info: "fake engine")
    monkeypatch.setattr(talk.speech, "resolve_voice", lambda v: ("v", None))
    monkeypatch.setattr(talk.speech, "speak", lambda *a, **k: talk.speech.Spoken(audio=b"", ext="wav", duration=0))
    monkeypatch.setattr(talk.speech, "transcribe", lambda *a: "the doorbell is ready")
    monkeypatch.setattr(talk.stage_mod, "daemon_status", lambda: None)
    monkeypatch.setattr(talk, "running_server", lambda port: None)
    monkeypatch.setattr(talk, "port_held", lambda port: True)
    monkeypatch.setattr(talk, "port_answer", lambda port: "busy")
    monkeypatch.setattr(talk, "port_holder", lambda port: "55803")
    assert talk.doctor(talk.build_parser().parse_args(["--doctor", "--port", "8766"])) == 1
    out = capsys.readouterr().out
    assert "[FAIL] no talk server this launch can reach, yet port 8766 is held by a server that does not answer" in out
    assert "kill 55803" in out and "no talk server on port" not in out and "all checks passed" not in out


def test_a_refused_quit_joins_the_older_server_and_says_so(monkeypatch, capsys):
    import urllib.error
    info = {"port": 8766, "token": "t"}
    monkeypatch.setattr(talk, "running_server", lambda port: info)
    monkeypatch.setattr(talk, "server_health", lambda i: {"code": "older", "calls": 1, "open": 0, "pid": 7})

    def refuse(*a, **k):
        raise urllib.error.HTTPError("u", 409, "calls are open", {}, None)

    monkeypatch.setattr(talk, "server_request", refuse)
    assert talk.start_server(8766) is info
    assert "pid 7) runs older code older and a call opened on it meanwhile" in capsys.readouterr().out


def test_an_older_server_holding_only_ended_calls_is_replaced(monkeypatch):
    info = {"port": 8766, "token": "t"}
    asked = []
    health = iter([{"code": "older", "calls": 1, "open": 0, "pid": 7}, None, None])
    monkeypatch.setattr(talk, "running_server", lambda port: info if not asked else None)
    monkeypatch.setattr(talk, "server_health", lambda i: next(health, None))
    monkeypatch.setattr(talk, "server_request", lambda i, method, path, *a, **k: asked.append(path) or {})
    monkeypatch.setattr(talk, "spawn_server", lambda port, log: (_ for _ in ()).throw(RuntimeError("spawned")))
    with pytest.raises(RuntimeError, match="spawned"):
        talk.start_server(8766)
    assert asked == ["/api/quit"]


def test_health_counts_open_calls_and_quit_waits_for_a_call_being_opened(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            add_call(server, tmp_path).end("over")
            health = await (await client.get("/api/health", headers=SERVER_AUTH)).json()
            server.registering = 1
            refused = (await client.post("/api/quit", headers=SERVER_AUTH)).status
            server.registering = 0
            quit_ok = (await client.post("/api/quit", headers=SERVER_AUTH)).status
            return health, refused, quit_ok, server.stop.is_set()

    health, refused, quit_ok, stopped = run(go())
    assert (health["calls"], health["open"], health["engine"]) == (1, 0, talk.speech.name())
    assert (refused, quit_ok, stopped) == (409, 200, True)


def test_a_call_is_not_opened_on_a_server_that_is_stopping(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            server.stop.set()
            resp = await client.post("/api/calls", json={"topic": "T", "out": str(tmp_path)}, headers=SERVER_AUTH)
            return resp.status, server.registering

    assert run(go()) == (503, 0)


# -- replies: what was sent is what is shown, once ------------------------------------------


def test_an_empty_reply_is_refused_and_leaves_the_turn_open(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await client.get("/api/turn?wait=1", headers=AUTH)
            resp = await client.post("/api/reply", json={"id": "t1", "text": "  \n"}, headers=AUTH)
            return resp.status, (await resp.json())["error"], call.turns.working

    assert run(go()) == (400, "nothing to say: the reply is empty", True)


def test_a_resent_reply_is_not_shown_or_said_twice(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await client.get("/api/turn?wait=1", headers=AUTH)
            first = await (await client.post("/api/reply", json={"id": "t1", "text": "Hello once."}, headers=AUTH)).json()
            again = await (await client.post("/api/reply", json={"id": "t1", "text": "Hello once."}, headers=AUTH)).json()
            return first, again, [e["text"] for e in call.entries if e["who"] == "claude"]

    first, again, shown = run(go())
    assert "ignored" not in first and "already answered" in again["ignored"] and shown == ["Hello once."]


def test_the_newest_doorbell_names_the_session_whose_work_is_shown(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    call.record_activity({"session_id": "old", "doorbell": True})
    call.record_activity({"session_id": "new", "doorbell": True})
    assert call.record_activity({"session_id": "new", "phase": "start", "tool": "Bash", "label": "ls"})
    assert not call.record_activity({"session_id": "old", "phase": "start", "tool": "Bash", "label": "ls"})


def test_a_turn_being_worked_on_is_not_ended_as_idle(tmp_path):
    from helpers import make_args

    async def go(active):
        call = talk.Call(make_args(idle_minutes=0.05), "T", tmp_path / "out")
        call.last_seen = time.time()
        call.offer("do the long thing", typed=True)
        await call.turns.next(timeout=0)
        call.last_turn = time.time() - 60
        if active:
            call.turns.note_activity()
        task = asyncio.ensure_future(talk.watch(call))
        await asyncio.sleep(1.3)
        task.cancel()
        return call.ended

    import asyncio
    assert run(go(True)) is None
    assert run(go(False)) == "nothing was said for 0.05 minutes"


def test_a_call_whose_page_was_never_opened_stays_open(tmp_path):
    from helpers import make_args

    async def go():
        call = talk.Call(make_args(), "T", tmp_path / "out")
        call.started = time.time() - 20 * 60
        task = asyncio.ensure_future(talk.watch(call))
        await asyncio.sleep(1.3)
        task.cancel()
        return call.ended

    import asyncio
    assert run(go()) is None


def test_any_failure_while_speaking_leaves_the_answer_failed_not_making(tmp_path):
    import wave

    def broken(text, voice, wav=False):
        raise wave.Error("file does not start with RIFF id")

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            talk.speech.speak = broken
            call.offer("hi", typed=True)
            await client.get("/api/turn?wait=1", headers=AUTH)
            await client.post("/api/reply", json={"id": "t1", "text": "Hello."}, headers=AUTH)
            for _ in range(50):
                entry = next(e for e in call.entries if e["who"] == "claude")
                if entry["speech"] not in ("pending", "making"):
                    return entry
                await asyncio.sleep(0.05)
            return entry

    import asyncio
    entry = run(go())
    assert entry["speech"] == "failed" and "RIFF" in entry["speech_error"]


OFFERED = [{"id": "en-US-AvaMultilingualNeural", "name": "Ava", "note": "American"},
           {"id": "el-GR-AthinaNeural", "name": "Athina", "note": "Greek only"}]


def test_the_page_picks_a_voice_and_the_next_answers_are_read_in_it(tmp_path, monkeypatch):
    monkeypatch.setattr(talk.speech, "voices", lambda: OFFERED)

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await call.answer("Before the change.")
            wrong = await client.post("/api/voice", json={"voice": "en-US-Nobody"}, headers=AUTH)
            right = await client.post("/api/voice", json={"voice": "el-GR-AthinaNeural"}, headers=AUTH)
            await call.answer("After the change.")
            for _ in range(100):  # its audio is made off the loop
                if len(fake.voices) == 2:
                    break
                await asyncio.sleep(0.02)
            return wrong.status, await right.json(), fake.voices, call.voice
    assert run(go()) == (400, {"voice": "el-GR-AthinaNeural"}, ["test-voice", "el-GR-AthinaNeural"], "el-GR-AthinaNeural")


def test_a_voice_sample_is_made_once_and_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(talk.speech, "voices", lambda: OFFERED)
    monkeypatch.setattr(talk, "DATA_DIR", tmp_path / "data")

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            first = await client.get(f"/c/{CALL}/voice/el-GR-AthinaNeural")
            again = await client.get(f"/c/{CALL}/voice/el-GR-AthinaNeural")
            other = await client.get(f"/c/{CALL}/voice/en-US-Nobody")
            return first.status, again.status, other.status, fake.spoken, sorted(p.name for p in (tmp_path / "data" / "voices").iterdir())
    assert run(go()) == (200, 200, 404, ["Hi, I am Athina. Γεια σας, με λένε Athina."], ["el-GR-AthinaNeural.wav"])
