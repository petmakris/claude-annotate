import asyncio

from helpers import AUTH, CALL, run, running_app, silent_wav, talk


async def settle(call):
    """Let the background speech tasks finish."""
    for _ in range(50):
        if all(e.get("speech") != "pending" for e in call.entries):
            return
        await asyncio.sleep(0.02)


def test_every_api_route_needs_the_token(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            statuses = []
            for method, path in [("get", "/api/state"), ("post", "/api/listen"), ("post", "/api/say"),
                                 ("get", "/api/turn?wait=0"), ("post", "/api/reply"), ("post", "/api/activity")]:
                statuses.append((await getattr(client, method)(path)).status)
            return statuses

    assert run(go()) == [403] * 6


def test_the_page_needs_the_call_id(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            return (await client.get("/c/wrong")).status, (await client.get(f"/c/{CALL}")).status

    assert run(go()) == (404, 200)


def test_a_recording_becomes_a_turn(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.heard = "show me the queue"
            resp = await client.post("/api/listen?lang=el", data=silent_wav(), headers=AUTH)
            turn = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            return await resp.json(), turn, fake.languages

    said, turn, languages = run(go())
    assert said["text"] == "show me the queue"
    assert turn == {"type": "turn", "id": "t1", "said": [{"who": "you", "text": "show me the queue"}]}
    assert languages == ["el"]


def test_a_recording_with_nothing_heard_is_no_turn(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.heard = ""
            said = await (await client.post("/api/listen", data=silent_wav(), headers=AUTH)).json()
            return said, (await client.get("/api/turn?wait=0.1", headers=AUTH)).status

    assert run(go()) == ({"text": ""}, 204)


def test_a_speech_failure_reaches_the_page(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.fail = "cannot reach VoiceStudio"
            resp = await client.post("/api/listen", data=silent_wav(), headers=AUTH)
            return resp.status, await resp.json()

    status, body = run(go())
    assert status == 502 and "VoiceStudio" in body["error"]


def test_typed_text_becomes_a_turn_marked_typed(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await client.post("/api/say", json={"text": "  what about put back?  "}, headers=AUTH)
            turn = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            return turn, call.entries[-1]

    turn, entry = run(go())
    assert turn["said"] == [{"who": "you", "text": "what about put back?"}]
    assert entry["typed"] is True


def test_an_answer_is_shown_at_once_then_read_aloud_and_served(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            resp = await client.post("/api/reply", json={"id": "t1", "text": "Use EXTERNAL_ONLY here."}, headers=AUTH)
            shown = dict(call.entries[-1])
            await settle(call)
            entry = call.entries[-1]
            audio = await client.get(f"/c/{CALL}/{entry['audio']}")
            stranger = await client.get(f"/c/wrong/{entry['audio']}")
            return await resp.json(), shown, entry, audio.status, await audio.read(), stranger.status, fake.spoken

    body, shown, entry, status, audio, stranger, said = run(go())
    assert body == {"ok": True, "board_problems": []}
    assert shown["text"] == "Use EXTERNAL_ONLY here."
    assert entry["speech"] == "ready" and entry["audio"] == "audio/0001.mp3"
    assert status == 200 and audio == silent_wav() and stranger == 404
    assert said == ["Use external only here."]


def test_an_answer_voicestudio_cannot_read_is_still_shown(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            fake.fail = "HTTP 500"
            await client.post("/api/reply", json={"id": "t1", "text": "Here it is."}, headers=AUTH)
            await settle(call)
            return call.entries[-1]

    entry = run(go())
    assert entry["text"] == "Here it is." and entry["speech"] == "failed" and "500" in entry["speech_error"]


def test_a_status_is_shown_not_spoken_and_ignored_after_the_answer(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("check jira", typed=True)
            await call.turns.next(timeout=1)
            first = await (await client.post("/api/reply", json={"id": "t1", "status": "checking Jira"},
                                             headers=AUTH)).json()
            await client.post("/api/reply", json={"id": "t1", "text": "Done."}, headers=AUTH)
            late = await (await client.post("/api/reply", json={"id": "t1", "status": "still checking"},
                                            headers=AUTH)).json()
            await settle(call)
            return first, late, [(e["who"], e["text"]) for e in call.entries], fake.spoken

    first, late, entries, said = run(go())
    assert first == {"ok": True} and "ignored" in late
    assert ("status", "checking Jira") in entries and ("status", "still checking") not in entries
    assert said == ["Done."]


def test_notes_and_board_tags_leave_the_spoken_text(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n")

    async def go():
        async with running_app(tmp_path, code=tmp_path) as (client, call, fake):
            call.offer("show", typed=True)
            await call.turns.next(timeout=1)
            await client.post("/api/reply", json={"id": "t1", "text": (
                "[[show code: a.py:1-2 | The file]]Look at the stage. [[note: follow up on y]]"
                "[[show diagram | Flow]]graph TD; A[[Sub]]-->B[[/show]]That is all.")}, headers=AUTH)
            await settle(call)
            return [(e["who"], e["text"]) for e in call.entries], fake.spoken, call.board.items

    entries, said, items = run(go())
    assert ("board", "The file") in entries and ("board", "Flow") in entries
    assert ("note", "follow up on y") in entries
    assert ("claude", "Look at the stage. That is all.") in entries
    assert said == ["Look at the stage. That is all."]
    assert items[1]["body"] == "graph TD; A[[Sub]]-->B"


def test_a_wrap_up_ends_the_call_and_the_doorbell_hears_it(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("bye", typed=True)
            await call.turns.next(timeout=1)
            await client.post("/api/reply", json={"id": "t1", "text": "Bye for now.", "end": True}, headers=AUTH)
            end = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            after = await client.post("/api/say", json={"text": "wait"}, headers=AUTH)
            await settle(call)
            return end, after.status, call.view()["ended"]

    end, after, ended = run(go())
    assert end["type"] == "end" and end["reason"] == "wrapped up by Claude"
    assert end["transcript"].endswith("transcript.md")
    assert after == 410 and ended == "wrapped up by Claude"


def test_ending_from_the_page_reaches_the_doorbell_and_refuses_replies(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            await client.post("/api/stop", headers=AUTH)
            end = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            late = await client.post("/api/reply", json={"id": "t1", "text": "Too late."}, headers=AUTH)
            return end["reason"], late.status

    assert run(go()) == ("ended from the page", 410)


def test_state_answers_same_until_something_changes(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            first = await (await client.get("/api/state", headers=AUTH)).json()
            same = await (await client.get(f"/api/state?v={first['v']}", headers=AUTH)).json()
            call.offer("hi", typed=True)
            changed = await (await client.get(f"/api/state?v={first['v']}", headers=AUTH)).json()
            return same, changed

    same, changed = run(go())
    assert same.get("same") is True
    assert changed["entries"][-1]["text"] == "hi"


def test_activity_from_the_answering_session_shows_while_it_works(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await client.get("/api/turn?wait=1", headers=AUTH)
            post = lambda body: client.post("/api/activity", json=body, headers=AUTH)  # noqa: E731
            await post({"session_id": "me", "phase": "start", "tool": "Bash", "doorbell": True})
            await post({"session_id": "other", "phase": "start", "tool": "Read", "label": "Reading b.py"})
            await post({"session_id": "me", "phase": "start", "tool": "Read", "label": "Reading a.py"})
            during = [(a["label"], a["state"]) for a in call.view()["activity"]]
            await post({"session_id": "me", "phase": "end", "tool": "Read", "label": "Reading a.py"})
            return during, [(a["label"], a["state"]) for a in call.view()["activity"]]

    during, after = run(go())
    assert during == [("Reading a.py", "running")]
    assert after == [("Reading a.py", "done")]


def test_the_transcript_records_the_call(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hello", typed=False)
            await call.turns.next(timeout=1)
            await client.post("/api/reply", json={"id": "t1", "text": "Hi."}, headers=AUTH)
            await settle(call)
            return call.transcript.read_text()

    text = run(go())
    assert "**You:** hello" in text and "**Claude:** Hi." in text


def test_a_recording_in_auto_mode_lets_whisper_detect_the_language(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            await client.post("/api/listen?lang=auto", data=silent_wav(), headers=AUTH)
            await client.post("/api/listen", data=silent_wav(), headers=AUTH)
            return fake.languages

    assert run(go()) == [None, None]


def test_without_voicestudio_talk_stops_at_start_not_mid_call(tmp_path, monkeypatch, capsys):
    def down(**kw):
        raise talk.speech.SpeechError("cannot reach VoiceStudio at http://127.0.0.1:1")

    monkeypatch.setattr(talk.speech, "ensure_running", down)
    monkeypatch.setattr("sys.argv", ["talk.py", "--topic", "T"])
    assert talk.main() == 2
    assert "Start the VoiceStudio app" in capsys.readouterr().out
