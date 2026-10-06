import asyncio
import threading
import time

from helpers import AUTH, CALL, run, running_app, silent_wav, talk


async def settle(call):
    """Let the background speech tasks finish."""
    for _ in range(50):
        if all(e.get("speech") in (None, "ready", "failed") for e in call.entries):
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
    assert entry["speech"] == "ready" and entry["audio"] == "audio/0001.wav"
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
    assert said == ["Look at the stage. That is all."]  # read in one request
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


def test_a_late_reply_names_the_transcript_for_the_recap(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("hi", typed=True)
            await call.turns.next(timeout=1)
            await client.post("/api/stop", headers=AUTH)
            late = await client.post("/api/reply", json={"id": "t1", "text": "Too late."}, headers=AUTH)
            return late.status, (await late.json())["transcript"]

    status, transcript = run(go())
    assert status == 410 and transcript.endswith("transcript.md")


def test_a_turn_heard_after_the_hand_over_began_is_refused_so_the_page_sends_it_again(tmp_path):
    from helpers import add_call, running_server

    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path)
            heard = fake.transcribe

            def slow(audio, language=None):
                server.handing_over = True  # the restart began while this was being heard
                return heard(audio, language)

            fake.transcribe = slow
            with __import__("unittest.mock").mock.patch.object(talk.speech, "transcribe", slow):
                resp = await client.post("/api/listen", data=silent_wav(), headers=AUTH)
            return resp.status, [e for e in call.entries if e["who"] == "you"]

    assert run(go()) == (503, [])


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


def test_a_long_answer_is_read_in_one_request_with_its_progress_timed(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("explain", typed=True)
            await call.turns.next(timeout=1)
            fake.hold = threading.Semaphore(0)
            text = "First sentence. " + " ".join(f"Then sentence number {i} follows." for i in range(12))
            await client.post("/api/reply", json={"id": "t1", "text": text}, headers=AUTH)
            entry = call.entries[-1]
            for _ in range(100):
                if entry["speech"] == "making":
                    break
                await asyncio.sleep(0.02)
            making = dict(entry)
            state = await (await client.get("/api/state", headers=AUTH)).json()
            fake.hold.release()
            await settle(call)
            whole = await client.get(f"/c/{CALL}/{entry['audio']}")
            return making, state, entry, fake.spoken, await whole.read()

    making, state, entry, said, whole = run(go())
    assert making["speech"] == "making" and making["audio"] is None
    assert making["speech_started"] > 0 and making["speech_estimate"] > 1
    assert abs(state["now"] - time.time()) < 5  # the page times the bar against the server's clock
    assert len(said) == 1 and entry["speech"] == "ready" and entry["audio"] == "audio/0001.wav"
    assert whole == silent_wav()


def test_the_estimate_learns_from_what_answers_took(monkeypatch):
    import speech
    monkeypatch.setattr(speech, "_rates", {})
    text = "x" * 400
    before = speech.estimate(text)
    speech.learn(text, before * 3)
    assert speech.estimate(text) > before * 1.5
    speech.learn("short", 1000)  # too short to tell anything
    assert speech.estimate(text) < before * 3


def test_every_shown_word_is_timed_in_order(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            call.offer("explain", typed=True)
            await call.turns.next(timeout=1)
            text = "First sentence comes alone.\n\nThen a second, with `EXTERNAL_ONLY` in it. And a third one here."
            await client.post("/api/reply", json={"id": "t1", "text": text}, headers=AUTH)
            await settle(call)
            return call.entries[-1]

    entry = run(go())
    words = entry["words"]
    assert [entry["text"][a:b] for a, b, _, _ in words] == entry["text"].split()
    starts = [t0 for _, _, t0, _ in words]
    assert starts == sorted(starts) and all(t0 <= t1 for _, _, t0, t1 in words)
    assert words[-1][3] <= 1.0  # the whole answer is one second of audio


def test_align_words_matches_what_was_heard_and_shares_out_the_rest():
    text = "Lowercasing means storing every address."
    heard = [("Lower", 0.2, 0.4), ("casing", 0.5, 0.9), ("means", 1.0, 1.2), ("storing", 1.3, 1.6),
             ("every", 1.7, 1.9), ("address", 2.0, 2.4)]
    words = talk.align_words(text, 0, len(text), heard, 2.6, offset=10.0)
    assert [text[a:b] for a, b, _, _ in words] == text.split()
    assert words[1][2:] == [11.0, 11.2]  # "means" as heard, shifted by the piece's offset
    assert words[0][2] == 10.0 and words[0][3] == 11.0  # "Lowercasing" fills the gap before "means"
    assert words[-1][2:] == [12.0, 12.4]  # "address." matches "address"
    even = talk.align_words("a bb", 0, 4, [], 3.0, offset=0.0)
    assert even == [[0, 1, 0.0, 1.0], [2, 4, 1.0, 3.0]]


# -- forgiving board tags -------------------------------------------------------


def split(tmp_path, text):
    """A reply split by a call with no stage: (spoken text, board items, board problems)."""
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    shown = call.split_reply(text)
    return " ".join(shown.split()), call.board.items, call.board.problems


def test_an_unknown_board_kind_is_named_and_its_body_kept_out_of_the_speech(tmp_path):
    spoken, items, problems = split(tmp_path, "Hi. [[show chart | Sales]] a,b [[/show]] Bye.")
    assert spoken == "Hi. Bye." and items == []
    assert len(problems) == 1 and 'unknown board kind "chart"' in problems[0]


def test_tag_heads_are_forgiving(tmp_path):
    spoken, items, problems = split(tmp_path, "Hi. [[show: table | X]]\n| a | b |\n|---|---|\n| 1 | 2 |\n[[/show]] Bye.")
    assert [(i["kind"], i["title"]) for i in items] == [("table", "X")]
    assert "|" not in spoken and problems == []
    for head in ("show table", "show-table", "show:table", "SHOW Table", "table", "grid"):
        _, items, problems = split(tmp_path, f"[[{head} | T]]| a |\n|---|\n| 1 |[[/show]]")
        assert [i["kind"] for i in items] == ["table"] and problems == [], head
    for head in ("show mermaid", "show graph", "flowchart", "diagram"):
        _, items, problems = split(tmp_path, f"[[{head} | D]]graph TD; A-->B[[/show]]")
        assert [i["kind"] for i in items] == ["diagram"] and problems == [], head


def test_a_block_never_closed_keeps_only_its_table_and_says_the_rest(tmp_path):
    spoken, items, problems = split(tmp_path, "Hi. [[show table | T]]\n| a |\n|---|\n| 1 |\n\nThen I explain more.")
    assert [(i["kind"], i["body"]) for i in items] == [("table", "| a |\n|---|\n| 1 |")]
    assert "Then I explain more." in spoken and "|" not in spoken
    assert any("missing [[/show]]" in p for p in problems)


def test_a_new_show_tag_closes_a_block_left_open(tmp_path):
    spoken, items, problems = split(tmp_path, "[[show table | A]]\n| a |\n|---|\n\nSaid. "
                                              "[[show diagram | B]] graph TD; A-->B [[/show]] End.")
    assert [i["title"] for i in items] == ["A", "B"]
    assert spoken == "Said. End."
    assert len(problems) == 1 and 'missing [[/show]] after "A"' in problems[0]


def test_tags_after_a_block_left_open_still_work_and_a_colon_names_the_board(tmp_path):
    reply = ("[[show diagram: Flow]]\n```mermaid\ngraph LR\n  S[Server] --> D[Doorbell]\n```\n"
             "It starts here. [[point: node S]] The server listens. [[key: the doorbell wakes Claude]]\n"
             "[[show table: Parts]]\n| Part | Job |\n|---|---|\n| talk.py | the page |\n"
             "[[point: row \"talk.py\"]] This serves the page. [[key: talk.py serves the page]]")
    spoken, items, problems = split(tmp_path, reply)
    assert [(i["kind"], i["title"]) for i in items if i["kind"] != "keys"][:2] == [("diagram", "Flow"), ("table", "Parts")]
    assert "[[" not in spoken and "It starts here." in spoken and "This serves the page." in spoken
    assert sum("missing [[/show]]" in p for p in problems) == 2


def test_diagrams_are_checked_before_the_stage_draws_them(tmp_path):
    _, items, problems = split(tmp_path, "[[show mermaid | Flow]] graph TD; A-->B [[/show]]")
    assert [i["kind"] for i in items] == ["diagram"] and problems == []
    _, items, problems = split(tmp_path, "[[show diagram | Bad]] A-->B [[/show]]")
    assert [i["kind"] for i in items] == ["diagram"]
    assert any("does not start with a Mermaid type" in p for p in problems)
    _, _, problems = split(tmp_path, "[[show diagram | Br]]graph TD\nA[f(x)] --> B[(Store)][[/show]]")
    assert len(problems) == 1 and 'A["f(x)"]' in problems[0]
    _, _, problems = split(tmp_path, '[[show diagram | Ok]]graph TD\nA["f(x)"] --> B[(Store)][[/show]]')
    assert problems == []


def test_empty_blocks_unclosed_tags_and_stray_closes_are_reported_or_harmless(tmp_path):
    spoken, items, problems = split(tmp_path, "[[show table | Nothing]][[/show]] Hi.")
    assert items == [] and problems == ['empty table "Nothing" not shown'] and spoken == "Hi."
    spoken, _, problems = split(tmp_path, "Hi. [[note: never closed\nThe rest is said.")
    assert spoken == "Hi. The rest is said."
    assert problems == ["a tag was not closed with ]]: [[note: never closed"]
    spoken, _, problems = split(tmp_path, "Hi. [[/show]] Bye.")
    assert spoken == "Hi. Bye." and problems == []


def test_an_untagged_table_or_mermaid_fence_goes_on_the_stage(tmp_path):
    spoken, items, problems = split(tmp_path, "Look at this.\n| a | b |\n|---|---|\n| 1 | 2 |\nThat is all.")
    assert spoken == "Look at this. That is all."
    assert [(i["kind"], i["title"]) for i in items] == [("table", "a · b")]
    assert problems == ["table shown without a tag; wrap it in [[show table | title]] next time"]
    spoken, items, problems = split(tmp_path, "First this. Here is the flow:\n```mermaid\ngraph TD\nA-->B\n```\nDone.")
    assert spoken == "First this. Here is the flow: Done."
    assert [(i["kind"], i["title"], i["body"]) for i in items] == [("diagram", "Here is the flow", "graph TD\nA-->B")]
    assert any("without a tag" in p for p in problems)
    spoken, items, _ = split(tmp_path, "One pipe | here | is prose.")
    assert items == [] and spoken == "One pipe | here | is prose."


def test_view_names_are_distinct_for_greek_titles_and_stable_per_title(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    a, b = call.view_name("Βήμα 1 αρχή", "table"), call.view_name("Βήμα 1 τέλος", "table")
    assert a != b and talk.stage_mod.model.NAME_RE.match(a) and talk.stage_mod.model.NAME_RE.match(b)
    assert call.view_name("Βήμα 1 αρχή", "table") == a
    assert call.view_name("Flow", "diagram") == "flow"
    assert call.view_name("flow!", "diagram") != "flow"  # same slug, other title
    assert call.view_name("", "diagram") != call.view_name("", "diagram")
    long = call.view_name("x" * 200, "code")
    assert talk.stage_mod.model.NAME_RE.match(long)
    call.split_reply("[[show table | Same]]| a |\n|---|\n| 1 |[[/show]] [[show table | Same]]| b |\n|---|\n| 2 |[[/show]]")
    assert [i["view"] for i in call.board.items] == ["same", "same"]


# -- the board follows the voice -------------------------------------------------


def cues_of(tmp_path, text, code=None):
    """A reply answered by a call with no stage: (its claude entry, board problems)."""
    from helpers import make_args
    call = talk.Call(make_args(code=code), "T", tmp_path / "out")
    with __import__("unittest.mock").mock.patch.object(call, "speak", lambda entry: asyncio.sleep(0)):
        entry = run(call.answer(text))
    return entry, call.board.problems


def focus_cues(tmp_path, text, code=None):
    from helpers import make_args
    call = talk.Call(make_args(code=code), "T", tmp_path / "out")
    with __import__("unittest.mock").mock.patch.object(call, "speak", lambda entry: asyncio.sleep(0)):
        entry = run(call.answer(text))
    frames = {i["view"]: i["scene"]["frames"] for i in call.board.items if i.get("scene")}
    focus = [(c["view"], frames[c["view"]][c["n"]]["focus"]) for c in entry["cues"] if c["kind"] == "frame"]
    return entry, call.board.problems, focus


def test_each_board_tag_becomes_a_cue_where_it_stood(tmp_path):
    text = ("First part. [[show table | A]]\n| x |\n|---|\n| 1 |\n[[/show]] About A. "
            "[[show diagram | B]] graph TD; P-->Q [[/show]] About B.")
    entry, problems = cues_of(tmp_path, text)
    said, cues = entry["text"], entry["cues"]
    assert "" not in said and problems == []
    assert [(c["kind"], c["view"]) for c in cues] == [("front", "a"), ("front", "b")]
    assert abs(cues[0]["at"] - said.index("About A")) <= 1
    assert abs(cues[1]["at"] - said.index("About B")) <= 1


def test_a_point_lights_up_lines_of_the_last_board_and_a_bad_point_is_reported(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("".join(f"line_{i} = {i}\n" for i in range(1, 11)))
    entry, problems, focus = focus_cues(tmp_path, "[[show code: a.py:1-5 | C]] Look. [[point: lines 2-3]] These two.", code)
    assert problems == []
    assert entry["cues"][1] == {"at": entry["text"].index("These"), "kind": "frame", "view": "c", "n": 1}
    assert focus == [("c", ["line:2", "line:3"])]
    _, problems = cues_of(tmp_path, "[[show code: a.py:1-5 | C]] Look. [[point: line 9]] There.", code)
    assert problems == ['point not shown: line 9 is outside lines 1-5 of "C"']
    _, problems = cues_of(tmp_path, "[[show code: a.py:1-5 | C]] Look. [[point Nope: row 1]] There.", code)
    assert problems == ['point not shown: no board titled "Nope" in this call']
    entry, problems = cues_of(tmp_path, "[[show code: a.py:1-5 | C]] Look. [[point: wibble]] There.", code)
    assert problems == ['point not shown: expected line N, lines A-B, row N, row "text", node ID or step ID']
    assert [c["kind"] for c in entry["cues"]] == ["front"] and "wibble" not in entry["text"]


def test_points_name_rows_and_nodes_and_a_titled_board(tmp_path):
    text = ('[[show table | Ports]]| Name | Port |\n|---|---|\n| talk | 8766 |\n| Δαίμων | 3080 |[[/show]] '
            '[[show diagram | Request path: page]] graph TD; Page-->Queue [[/show]] Two boards. '
            '[[point Ports: row 2]] The second row. [[point ports: row "daimon"]] Same row. '
            '[[point Request path: page: node Queue]] The queue. [[POINT: node Page]] The page.')
    entry, problems, focus = focus_cues(tmp_path, text)
    assert problems == ['point not shown: no row of "Ports" starts with "daimon"']
    assert focus == [("ports", ["row#2"]), ("request-path-page", ["node:Queue"]), ("request-path-page", ["node:Page"])]
    entry, problems, focus = focus_cues(tmp_path, text.replace('row "daimon"', 'row "δαιμων"'))
    assert problems == [] and focus[:2] == [("ports", ["row#2"]), ("ports", ["row#2"])]
    _, problems = cues_of(tmp_path, "[[show table | T]]| a |\n|---|\n| 1 |[[/show]] One. [[point: row 4]] No.")
    assert problems == ['point not shown: "T" has 1 rows, not row 4']
    _, problems = cues_of(tmp_path, "[[show table | T]]| a |\n|---|\n| 1 |[[/show]] One. [[point: line 1]] No.")
    assert problems == ['point not shown: "T" is a table; use row N or row "text"']


def test_boards_all_placed_at_the_end_are_reported(tmp_path):
    entry, problems = cues_of(tmp_path, "Here is the answer, said first. [[show table | A]]| a |\n|---|\n| 1 |[[/show]]"
                                        "[[show table | B]]| b |\n|---|\n| 2 |[[/show]]")
    assert [c["at"] for c in entry["cues"]] == [len(entry["text"])] * 2
    assert problems == ["all boards were placed after the last sentence, so the stage cannot follow the voice; "
                        "put each tag before the sentence about it"]
    _, problems = cues_of(tmp_path, "Said first. [[show table | A]]| a |\n|---|\n| 1 |[[/show]]")
    assert problems == []  # one board at the end is fine


def test_an_untagged_table_gets_its_cue_in_order(tmp_path):
    entry, _ = cues_of(tmp_path, "[[show diagram | D]] graph TD; A-->B [[/show]] First. Then this.\n"
                                 "| k | v |\n|---|---|\n| a | 1 |\nAfter the table.")
    said = entry["text"]
    assert [(c["view"], c["at"]) for c in entry["cues"]] == [("d", 0), ("k-v", said.index("\n") + 1)]


# -- what changed, and key points ------------------------------------------------


def git_repo(path):
    import os
    import subprocess
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
    path.mkdir()
    (path / "a.py").write_text("def old_name():\n    return 1\n")
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "start"]):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)
    return path


def test_a_change_tag_shows_what_changed_from_git(tmp_path):
    code = git_repo(tmp_path / "code")
    (code / "a.py").write_text("def new_name():\n    return 1\n")
    spoken, items, problems = split_in(tmp_path, "[[show change: a.py | What I changed]] I renamed it.", code)
    assert spoken == "I renamed it." and problems == []
    (item,) = items
    assert item["kind"] == "change" and item["title"] == "What I changed" and item["view"] == "what-i-changed"
    assert (item["added"], item["removed"], item["path"], item["lang"]) == (1, 1, "a.py", "py")
    name, source, title = talk.stage_view(item)
    assert source == {k: item[k] for k in talk.CHANGE_FIELDS} and source["format"] == "change"
    _, items, _ = split_in(tmp_path, "[[diff: a.py]] Same, shorter.", code)
    assert [i["title"] for i in items] == ["What changed in a.py"]
    entry, problems, focus = focus_cues(tmp_path, "[[show change: a.py | Edit]] Renamed. [[point: line 1]] This line.", code)
    assert problems == [] and focus == [("edit", ["line:1"])]
    _, problems = cues_of(tmp_path, "[[show change: a.py | Edit]] Renamed. [[point: line 9]] No.", code)
    assert problems == ['point not shown: line 9 is not in the new lines shown in "Edit" (1-2)']


def split_in(tmp_path, text, code):
    from helpers import make_args
    call = talk.Call(make_args(code=code), "T", tmp_path / "out")
    shown = call.split_reply(text)
    return " ".join(shown.split()), call.board.items, call.board.problems


def test_a_change_that_cannot_be_shown_is_a_problem(tmp_path):
    code = git_repo(tmp_path / "code")
    _, items, problems = split_in(tmp_path, "[[show change: a.py | What I changed]] I renamed it.", code)
    assert items == [] and problems == ["change not shown, no changes in a.py"]
    _, _, problems = split_in(tmp_path, "[[show change: a.py since ;rm | X]] Hi.", code)
    assert problems == ["change not shown, not a git revision: ;rm"]


def test_key_points_build_up_over_the_call(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    with __import__("unittest.mock").mock.patch.object(call, "speak", lambda entry: asyncio.sleep(0)):
        first = run(call.answer("The queue holds turns. [[key: turns wait in a queue]] The doorbell takes them. "
                                "[[Key point: the doorbell wakes the session]]"))
        second = run(call.answer("Long one. [[key: " + "word " * 40 + "]]"))
    assert [k["answer"] for k in call.keys] == [1, 1, 2]
    assert call.keys[0]["text"] == "turns wait in a queue"
    assert first["text"] == "The queue holds turns. The doorbell takes them."
    keys = [c for c in first["cues"] if c["kind"] == "key"]
    assert [(c["view"], c["index"]) for c in keys] == [("key-points", 1), ("key-points", 2)]
    assert keys[0]["at"] == first["text"].index("The doorbell")
    assert len(call.keys[2]["text"]) <= 120 and call.keys[2]["text"].endswith("word…")
    assert "key point too long, keep it under 12 words" in call.board.problems
    assert [c["index"] for c in second["cues"]] == [3]
    chips = [e for e in call.entries if e["who"] == "board"]
    assert [(e["text"], e["view"], e["kind"], e["added"]) for e in chips] == [
        ("Key points: +2", "key-points", "points", 2), ("Key points: +1", "key-points", "points", 1)]
    transcript = call.transcript.read_text()
    assert "**Key point:** turns wait in a queue" in transcript and transcript.count("**Key point:**") == 3
    assert call.view_name("Key points", "table") != "key-points"  # a board titled so gets a view of its own


def test_keys_at_the_end_are_not_boards_placed_late(tmp_path):
    entry, problems = cues_of(tmp_path, "Said first. [[key: one]] [[key: two]]")
    assert problems == [] and [c["kind"] for c in entry["cues"]] == ["key", "key"]


def test_every_tag_the_skill_teaches_is_one_the_parser_reads():
    import re
    doc = (talk.Path(talk.__file__).parent / "SKILL.md").read_text()
    section = doc.split("### Teaching with the board", 1)[1].split("### What a turn may do", 1)[0]
    tags = [t.replace("\\|", "|").strip() for t in re.findall(r"\[\[(.+?)\]\]", section)]
    assert len(tags) >= 10
    for tag in tags:
        verb, kind, _, _ = talk.parse_head(tag)
        known = (verb == "/show" or (verb == "show" and kind in talk.BOARD_KINDS)
                 or talk.parse_point(tag) is not None or talk.parse_key(tag) is not None or tag.startswith("note:")
                 or talk.stage_scene.parse_verb(tag) is not None)
        assert known, tag
    for tag in tags:
        point = talk.parse_point(tag)
        if point and "N" not in point[1] and "X" not in point[1] and "..." not in tag:
            assert talk._POINT_TARGET.fullmatch(point[1]), tag


def test_a_tag_that_opens_a_line_leaves_no_indent(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    shown = call.split_reply("Intro.\n\n[[show table|X]]| a |\n|---|\n| 1 |[[/show]]\n"
                             "[[point: row 1]] The skills live under claude.")
    assert "\n The" not in shown and shown.endswith("\nThe skills live under claude.")
    cue = call.reply_cues[-1]
    assert cue["kind"] == "frame" and shown[cue["at"]:].startswith("The skills")
    assert call.split_reply("Keep\n    this indent.") == "Keep\n    this indent."


def test_short_table_separators_count_as_gfm_reads_them(tmp_path):
    assert talk.table_first_cells("| k | v |\n|--|--|\n| a | 1 |\n| b | 2 |") == ["a", "b"]
    assert talk.table_first_cells("| k | v |\n|:-|-:|\n| a | 1 |") == ["a"]
    spoken, items, _ = split(tmp_path, "Look.\n| k | v |\n|:--|--:|\n| a | 1 |\nDone.")
    assert [i["kind"] for i in items] == ["table"] and "|" not in spoken
    _, problems = cues_of(tmp_path, "[[show table | T]]| k | v |\n|--|--|\n| a | 1 |\n| b | 2 |[[/show]] Two. "
                                    "[[point: row 3]] No.")
    assert problems == ['point not shown: "T" has 2 rows, not row 3']


def test_show_with_an_underscore_is_a_board_tag():
    assert talk.parse_head("show_table") == ("show", "table", "", "")
    assert talk.parse_head("SHOW_diagram | D")[:2] == ("show", "diagram")


def test_a_row_is_matched_by_the_text_the_stage_shows(tmp_path):
    table = "[[show table | T]]| Name | v |\n|---|---|\n| `foo` | 1 |\n| [docs](https://x) | 2 |\n| **bold** | 3 |[[/show]] "
    entry, problems, focus = focus_cues(tmp_path, table + 'Rows. [[point: row "foo"]] One. [[point: row "docs"]] Two. '
                                                         '[[point: row "`bold`"]] Three.')
    assert problems == []
    assert focus == [("t", ["row#1"]), ("t", ["row#2"]), ("t", ["row#3"])]
    _, problems = cues_of(tmp_path, table + 'Rows. [[point: row "https://x"]] No.')
    assert problems == ['point not shown: no row of "T" starts with "https://x"']


def test_a_node_is_one_the_flowchart_defines_not_any_word(tmp_path):
    def problems_for(body, node):
        return cues_of(tmp_path, f"[[show diagram | D]]{body}[[/show]] Flow. [[point: node {node}]] No.")[1]

    assert problems_for("graph TD; A[label text]-->B\nB --> Aβ", "Aβ") == []
    assert problems_for("graph TD; A[label text]-->B", "label") == ['point not shown: no node label in "D"']
    assert problems_for("flowchart LR\n  A -.-> B & C\n  C:::hot", "C") == []
    assert problems_for("---\ntitle: F\n---\ngraph TD\nA-->B", "B") == []
    assert problems_for("graph TD\nsubgraph S1 [Group]\nA\nend\nS1-->C", "S1") == []
    assert problems_for("graph TD\nA@{ shape: rect }\nA-->B", "A") == []
    _, problems = cues_of(tmp_path, "[[show diagram | D]]graph TD; A[Ask]-->B[[/show]] Flow. [[point: node TD]] No.")
    assert problems == ['point not shown: no node TD in "D"']


# -- one identity per board: how a view is named is how a point finds it ---------------------------


def test_a_title_written_in_another_case_updates_its_board(tmp_path):
    _, items, problems = split(tmp_path, "[[show table | Ports]]| a |\n|---|\n| 1 |[[/show]] One. "
                                         "[[show table | ports]]| a |\n|---|\n| 2 |[[/show]] Two.")
    assert [i["view"] for i in items] == ["ports", "ports"] and problems == []


def test_a_point_finds_the_board_of_its_kind_and_exact_title_first(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("\n".join(f"x{i}" for i in range(1, 6)) + "\n")
    entry, problems, focus = focus_cues(tmp_path, "[[show code: a.py:1-5 | Request flow]] Code. "
                                                  "[[show diagram | Request flow]]graph TD; A-->B[[/show]] Flow. "
                                                  "[[point Request flow: line 3]] Here. [[point Request flow: node B]] There.",
                                        code)
    views = [view for view, _ in focus]
    assert problems == [] and views[0] == "request-flow" and views[1] != views[0]
    entry, problems, focus = focus_cues(tmp_path, "[[show table | Plan]]| a |\n|---|\n| 1 |[[/show]] T. "
                                                  "[[show diagram | plan]]graph TD; A-->B[[/show]] D. [[point Plan: row 1]] Here.")
    assert problems == [] and focus == [("plan", ["row#1"])]


def test_two_files_of_one_name_get_two_views(tmp_path):
    code = tmp_path / "code"
    for d in ("a", "b"):
        (code / d).mkdir(parents=True)
        (code / d / "__init__.py").write_text(f"{d} = 1\n")
    _, items, problems = split_in(tmp_path, "[[show code: a/__init__.py:1-1]] A. [[show code: b/__init__.py:1-1]] B.", code)
    assert problems == [] and len({i["view"] for i in items}) == 2


def test_two_untagged_tables_with_one_header_get_two_views(tmp_path):
    _, items, _ = split(tmp_path, "First:\n\n| Field | Value |\n|---|---|\n| a | 1 |\n\nThen:\n\n"
                                  "| Field | Value |\n|---|---|\n| b | 2 |\n\nDone.")
    assert len(items) == 2 and items[0]["view"] != items[1]["view"]


# -- inside a block, tags read as they read outside it -----------------------------------------


def test_a_bare_kind_tag_inside_an_open_block_starts_a_new_board(tmp_path):
    spoken, items, problems = split(tmp_path, "[[show diagram | A]]graph TD\nA-->B\n\nNow [[table | B]]| x |\n|---|\n| 1 |[[/show]] done")
    assert [(i["kind"], i["title"]) for i in items] == [("diagram", "A"), ("table", "B")]
    assert items[0]["body"] == "graph TD\nA-->B" and "Now" in spoken and "done" in spoken


def test_a_spaced_close_tag_closes_the_block(tmp_path):
    spoken, items, problems = split(tmp_path, "[[show diagram | A]]graph TD\nA-->B[[/ show]] done")
    assert items[0]["body"] == "graph TD\nA-->B" and spoken == "done" and problems == []


def test_a_mermaid_subroutine_named_show_stays_in_the_diagram(tmp_path):
    spoken, items, problems = split(tmp_path, "[[show diagram | Flow]]graph TD\nA-->B[[Show results]]\nB-->C\n[[/show]] after.")
    assert items[0]["body"] == "graph TD\nA-->B[[Show results]]\nB-->C" and spoken == "after."
    assert problems == []


def test_a_caption_after_the_closing_fence_is_said(tmp_path):
    spoken, items, problems = split(tmp_path, "[[show diagram | F]]\n```mermaid\ngraph TD\nA-->B\n```\n"
                                              "The request goes left to right.[[/show]] Done.")
    assert items[0]["body"] == "graph TD\nA-->B" and problems == []
    assert spoken == "The request goes left to right. Done."


# -- what a tag asks for is checked against what the stage can show ----------------------------


def test_a_highlight_is_ordered_and_one_outside_the_code_is_a_problem(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("\n".join(f"x{i}" for i in range(1, 11)) + "\n")
    _, items, problems = split_in(tmp_path, "[[show code: a.py:5-10 highlight 8-6 | A]] Hi.", code)
    assert items[0]["highlight"] == [6, 8] and problems == []
    _, items, problems = split_in(tmp_path, "[[show code: a.py:5-10 highlight 1-2 | B]] Hi.", code)
    assert items[0]["highlight"] is None and problems == ["highlight 1-2 is outside lines 5-10 shown of a.py; not marked"]


def test_a_range_past_the_end_says_where_it_was_cut(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("\n".join(f"x{i}" for i in range(1, 11)) + "\n")
    _, items, problems = split_in(tmp_path, "[[show code: a.py:5-200]] Hi.", code)
    assert items[0]["title"] == "a.py" and len(items[0]["lines"]) == 6
    assert problems == ["code cut at line 10, the end of a.py"]


def test_a_node_point_in_a_diagram_the_stage_cannot_light_is_a_problem(tmp_path):
    _, problems = cues_of(tmp_path, "[[show diagram | S]]sequenceDiagram\nAlice->>Bob: hi[[/show]] Hi. [[point S: node Alice]] Her.")
    assert problems == ['point not shown: "S" is not a graph or flowchart, so the stage cannot light a node in it']
    for word in ("end", "Yes"):
        _, problems = cues_of(tmp_path, "[[show diagram | G]]graph TD\nsubgraph Backend\nA -- Yes --> B\nend[[/show]] "
                                        f"Hi. [[point G: node {word}]] It.")
        assert problems == [f'point not shown: no node {word} in "G"']


def test_mermaid_types_the_stage_draws_are_not_a_problem():
    for first in ("C4Container", "xychart", "kanban", "architecture-beta", "block", "packet-beta", "radar-beta",
                  "classDiagram-v2"):
        assert talk.diagram_problems(f"{first}\n  x", "D") == [], first


def test_a_second_untagged_fence_is_titled_by_its_own_sentence(tmp_path):
    _, items, _ = split(tmp_path, "First:\n```mermaid\ngraph TD\nA-->B\n```\nThen the second flow:\n"
                                  "```Mermaid\ngraph TD\nC-->D\n```\nDone.")
    assert [i["title"] for i in items] == ["First", "Then the second flow"]


def test_untagged_tables_without_a_trailing_pipe_or_with_a_key_on_a_row_are_found(tmp_path):
    spoken, items, _ = split(tmp_path, "Look:\n\n| a | b\n|---|---\n| 1 | 2\n\nDone.")
    assert len(items) == 1 and spoken == "Look: Done."
    spoken, items, _ = split(tmp_path, "Look:\n\n| a | b |\n|---|---|\n| 1 | 2 | [[key: one]]\n| 3 | 4 |\n\nDone.")
    assert len(items) == 1 and table_rows(items[0]["body"]) == ["1", "3"] and "| 3" not in spoken


def table_rows(body):
    return talk.table_first_cells(body)


def test_table_rows_are_counted_and_matched_as_the_stage_does(tmp_path):
    assert talk.table_first_cells("| a | b |\n|---|---|\n| `a \\| b` | 1 |\nx | y") == ["`a | b`", "x"]
    entry, problems, focus = focus_cues(tmp_path, "[[show table | T]]| k | v |\n|---|---|\n| `a \\| b` | 1 |\n| Straße | 2 |[[/show]] "
                                                  "One. [[point T: row \"a | b\"]] Two. [[point T: row \"STRASSE\"]] Three.")
    assert focus == [("t", ["row#1"])]
    assert problems == ['point not shown: no row of "T" starts with "STRASSE"']


def test_a_row_with_an_apostrophe_can_be_pointed_at(tmp_path):
    entry, problems, focus = focus_cues(tmp_path, "[[show table | T]]| k |\n|---|\n| don't retry |[[/show]] One. "
                                                  "[[point T: row \"don't retry\"]] Two.")
    assert problems == [] and focus == [("t", ["row#1"])]


# -- verbs: a scene's frames, landing on the word after each tag --------------------------------

WORKED = ("[[show diagram | advisory drops :workflows]]\nflowchart LR\n  subgraph adv[\":advisory\"]\n"
          "    pws[ProposalWorkflowServiceImpl]\n    legacy[web.workflows.legacy]\n  end\n  wf[\":workflows\"]\n"
          "  engine[(Flowable engine)]\n  pws -->|imports 3 types| wf\n  wf --> engine\n  pws --> legacy\n[[/show]]\n"
          "Start with the class at the centre of this. [[+ pws]] The proposal workflow service lives in advisory, "
          "[[+ pws->wf]] and until now it imported three types from the workflows module, [[+ wf->engine]] which is "
          "the module that owns Flowable. [[focus pws->wf]] That one import is the only reason advisory depended on "
          "workflows. [[strike pws->wf]] [[focus none]] On this branch that edge is gone. [[+ legacy, pws->legacy]] "
          "[[focus legacy]] The same three types now live inside advisory, in a legacy package next door. "
          "[[callout legacy: ProposalFlags, ProposalWorkflowService, ProcessInstanceView]] "
          "[[key: one class tied advisory to :workflows]]")


def test_verbs_become_frames_of_their_scene_on_the_word_after_each_tag(tmp_path):
    entry, problems, focus = focus_cues(tmp_path, WORKED)
    said = entry["text"]
    assert "[[" not in said and said.startswith("Start with the class")
    assert [c["kind"] for c in entry["cues"]] == ["front"] + ["frame"] * 6 + ["key"]
    assert [(c["n"], said[c["at"]:c["at"] + 9]) for c in entry["cues"] if c["kind"] == "frame"] == [
        (1, "The propo"), (2, "and until"), (3, "which is "), (4, "That one "), (5, "On this b"), (6, "The same ")]
    assert focus[3] == ("advisory-drops-workflows", ["edge:pws->wf#0"]) and focus[4][1] == []
    assert focus[5][1] == ["node:legacy"]
    assert problems == ['"strike" is not supported yet; dropped', '"callout" is not supported yet; dropped']


def test_repairs_are_reported_and_counted_on_the_scene(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    call.split_reply("[[show diagram | Flow]]graph TD; Page-->Queue[[/show]] One. [[+ Pag]] Two. [[+ Queue->Page]] "
                     "Three. [[+ nothing]] Four. [[all]] Five.")
    assert call.board.problems == ['"Pag" in "Flow" read as node:Page',
                                   '"Queue->Page" in "Flow" read as Page->Queue: that edge only goes the other way',
                                   '"nothing" in "Flow" matches nothing; dropped']
    assert call.board.items[0]["scene"]["repairs"] == 3


def test_a_verb_before_any_board_or_on_a_diagram_that_cannot_step_is_reported(tmp_path):
    _, problems = cues_of(tmp_path, "Hello. [[+ A]] There.")
    assert problems == ["+ not shown: no board has been shown yet"]
    entry, problems = cues_of(tmp_path, "[[show diagram | S]]sequenceDiagram\nAlice->>Bob: hi[[/show]] Hi. [[next]] Her.")
    assert problems == ['verbs step flowcharts, code, changes and tables for now; "S" is shown whole']
    assert [c["kind"] for c in entry["cues"]] == ["front"]
    _, problems = cues_of(tmp_path, "[[show table | T]]| a |\n|---|\n| 1 |[[/show]] Hi. [[+ Nope: row 1]] No.")
    assert problems == ['+ not shown: no board titled "Nope" in this call']


def test_two_scenes_in_one_reply_count_their_own_frames(tmp_path):
    entry, problems, focus = focus_cues(tmp_path, "[[show diagram | One]]graph TD; A-->B[[/show]] First. [[+ A]] Here A. "
                                                  "[[show diagram | Two]]graph TD; C-->D[[/show]] Then. [[+ C->D]] Here C. "
                                                  "[[+ One: A->B]] Back to one.")
    frames = [(c["view"], c["n"]) for c in entry["cues"] if c["kind"] == "frame"]
    assert problems == [] and frames == [("one", 1), ("two", 1), ("one", 2)]


CLOUDS = "| Name | Region |\n|---|---|\n| Azure | eu |\n| AWS | us |\n| GCP | eu |\n| OVH | fr |"


def test_a_board_of_more_than_three_things_and_no_verbs_comes_in_one_sentence_at_a_time(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    shown = call.split_reply(f"[[show table | Clouds]]{CLOUDS}[[/show]] Azure first. AWS is next. GCP follows. "
                             "OVH closes it. Done.")
    assert [(c["n"], shown[c["at"]:c["at"] + 5]) for c in call.reply_cues if c["kind"] == "frame"] == [
        (1, "Azure"), (2, "AWS i"), (3, "GCP f"), (4, "OVH c")]
    built = call.board.items[0]["scene"]
    rows = [[k for k in f["show"] if k.startswith("row#")] for f in built["frames"]]  # each row brings its cells
    assert built["start"] == "empty" and [len(r) for r in rows] == [0, 1, 2, 3, 4, 4]
    assert call.board.problems == ['"Clouds" has 4 elements and no verbs, so it was stepped one sentence at a time '
                                   "(dump); tag the word that names each thing"]


def test_fewer_sentences_than_things_bring_several_in_at_once(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    call.split_reply("[[show diagram | D]]graph TD; A-->B; B-->C; C-->D[[/show]] It starts at A. It ends at D.")
    built = call.board.items[0]["scene"]
    assert [len(f["show"]) for f in built["frames"]] == [0, 3, 7, 7]


def test_a_small_board_code_and_a_board_said_last_are_never_stepped(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("".join(f"x{i} = {i}\n" for i in range(1, 11)))
    for text in ("[[show table | T]]| a |\n|---|\n| 1 |\n| 2 |\n| 3 |[[/show]] One. Two. Three. Four.",
                 "[[show code: a.py:1-10 | C]] One. Two. Three. Four. Five.",
                 f"All said first. [[show table | Clouds]]{CLOUDS}[[/show]]"):
        _, items, problems = split_in(tmp_path, text, code)
        assert "scene" not in items[0] and problems == [], text


def test_an_untagged_table_is_stepped_like_a_tagged_one(tmp_path):
    from helpers import make_args
    call = talk.Call(make_args(), "T", tmp_path / "out")
    call.split_reply(f"Here they are.\n{CLOUDS}\nAzure first. AWS next. GCP then. OVH last.")
    assert call.board.items[0]["scene"]["steps"] == 4


SEQ = ('{"actors": [{"id": "p", "label": "Page"}, {"id": "s", "label": "Server"}], "steps": ['
       '{"id": "s1", "from": "p", "to": "s", "arrow": "request", "label": "send"},'
       '{"id": "s2", "from": "s", "to": "s", "arrow": "self", "label": "queue"},'
       '{"id": "s3", "from": "s", "to": "p", "arrow": "event", "label": "answer"},'
       '{"id": "s4", "from": "p", "to": "p", "arrow": "self", "label": "play"}]}')
FLOW = ('{"nodes": [{"id": "a", "role": "entry", "label": "Turn"}, {"id": "b", "role": "success", "label": "Played"}],'
        ' "edges": [{"from": "a", "to": "b"}]}')


def _call(tmp_path):
    from helpers import make_args
    return talk.Call(make_args(), "T", tmp_path / "out")


def test_a_sequence_spec_is_drawn_by_the_shared_tool_and_steps_one_sentence_at_a_time(tmp_path):
    call = _call(tmp_path)
    call.split_reply(f"[[show sequence | Turn]] {SEQ} [[/show]] The page sends. It queues. It answers. It plays.")
    item = call.board.items[0]
    name, source, title = talk.stage_view(item)
    assert (item["kind"], source["format"], source["tool"], title) == ("sequence", "visual", "sequence", "Turn")
    assert 'data-key="step:s1"' in source["html"] and 'data-key="step:s1"' in source["key"]
    shown = [set(f["show"]) for f in item["scene"]["frames"]]
    assert "step:s1" in shown[1] and "step:s2" not in shown[1] and "step:s4" in shown[4]
    assert not [p for p in call.board.problems if "stepped one sentence at a time" in p]


def test_a_bad_spec_never_reaches_the_stage_and_the_board_says_why(tmp_path):
    call = _call(tmp_path)
    call.split_reply('[[show sequence | Turn]] {"actors": [], "steps": []} [[/show]] Nothing to see.')
    assert call.board.items == []
    assert any("requires at least 2 actors" in p for p in call.board.problems)


def test_a_flowchart_written_in_mermaid_stays_a_mermaid_diagram_and_a_spec_becomes_a_visual(tmp_path):
    call = _call(tmp_path)
    call.split_reply(f"[[show flowchart | Old]] graph LR; A-->B [[/show]] One. [[show flowchart | New]] {FLOW} [[/show]] Two.")
    old, new = call.board.items
    assert old["kind"] == "diagram" and talk.stage_view(old)[1]["format"] == "diagram"
    assert new["kind"] == "flowchart" and talk.stage_view(new)[1]["tool"] == "flowchart"


def test_a_point_lights_a_step_or_a_node_of_a_visual(tmp_path):
    call = _call(tmp_path)
    call.split_reply(f"[[show sequence | Turn]] {SEQ} [[/show]] [[+ s1]] It sends. [[point: step s3]] It answers.")
    frames = call.board.items[0]["scene"]["frames"]
    assert frames[2]["focus"] == ["step:s3"]
    call.split_reply(f"[[show flowchart | Floor]] {FLOW} [[/show]] [[point: node b]] Played.")
    assert call.board.items[-1]["scene"]["frames"][1]["focus"] == ["node:b"]
    call.split_reply("[[point Turn: step s9]] No such step.")
    assert any("no step s9" in p for p in call.board.problems)


def test_a_point_on_a_visual_lights_its_step_while_the_rest_still_comes_in_a_sentence_at_a_time(tmp_path):
    call = _call(tmp_path)
    call.split_reply(f"[[show sequence | Turn]] {SEQ} [[/show]] The page sends. It queues. [[point: step s3]] It answers. "
                     "It plays.")
    built = call.board.items[0]["scene"]
    assert built["start"] == "empty" and built["steps"] == 4
    shown = [set(f["show"]) for f in built["frames"]]
    assert "step:s1" in shown[1] and "step:s3" not in shown[2]
    assert "step:s3" in shown[3] and built["frames"][3]["focus"] == ["step:s3"]


def test_an_unclosed_spec_ends_with_its_json_and_the_speech_after_it_is_said(tmp_path):
    spoken, items, problems = split(tmp_path, f"Here. [[show sequence | P]] {SEQ} The client asks. The server answers.")
    assert [i["kind"] for i in items] == ["sequence"]
    assert spoken == "Here. The client asks. The server answers."
    assert problems[0] == 'missing [[/show]] after "P", closed it at the end of the sequence'


def test_a_spec_under_a_mermaid_name_is_drawn_by_its_tool_and_a_wrong_tool_is_named(tmp_path):
    call = _call(tmp_path)
    call.split_reply(f"[[show flow | F]] {FLOW} [[/show]] Played.")
    assert call.board.items[0]["kind"] == "flowchart"
    assert call.board.problems[0] == '"F" is a flowchart spec, so it was drawn as one; write [[show flowchart | ...]]'
    call.split_reply(f"[[show sequence | S]] {FLOW} [[/show]] Played.")
    assert "this looks like a flowchart spec" in call.board.problems[-1]


def test_a_board_that_breaks_never_costs_the_answer(tmp_path, monkeypatch):
    call = _call(tmp_path)
    monkeypatch.setattr(call, "compile_scenes", lambda *a: 1 / 0)
    shown = call.split_reply_safely(f"The page sends. [[show sequence | P]] {SEQ} [[/show]] It answers. [[+ s1]] Done.")
    assert " ".join(shown.split()) == "The page sends. It answers. Done."
    assert "the boards of this answer failed (ZeroDivisionError" in call.board.problems[-1]


def test_a_point_names_a_flowchart_node_whose_id_has_a_dot(tmp_path):
    call = _call(tmp_path)
    spec = FLOW.replace('"id": "b"', '"id": "api.gw"').replace('"to": "b"', '"to": "api.gw"')
    call.split_reply(f"[[show flowchart | F]] {spec} [[/show]] [[point: node api.gw]] The gateway.")
    assert call.board.problems == [] and call.board.items[0]["scene"]["frames"][1]["focus"] == ["node:api.gw"]


def test_rows_are_the_first_tables_up_to_a_blank_line(tmp_path):
    assert talk.table_first_cells("| k |\n|---|\n| one |\n| two |\n\n| x |\n|---|\n| y |") == ["one", "two"]
