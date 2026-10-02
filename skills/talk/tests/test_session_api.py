import asyncio

from helpers import AUTH, CALL, TOKEN, instructions, running_app, spoken, talk


def run(coro):
    return asyncio.run(coro)


def test_new_lines_returns_only_turns_not_yet_handed_over(tmp_path):
    log = talk.SessionLog(tmp_path, "t", "test")
    log.delta("input", "hello there")
    first = log.new_lines()
    log.delta("output", "hi, what's up")
    second = log.new_lines()
    assert first == [{"who": "you", "text": "hello there"}]
    assert second == [{"who": "voice", "text": "hi, what's up"}]
    assert log.new_lines() == []


def test_turn_endpoint_requires_the_token(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            resp = await client.get("/api/turn?wait=0.1")
            return resp.status

    assert run(go()) == 403


def test_turn_endpoint_returns_204_when_nothing_arrives(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            resp = await client.get("/api/turn?wait=0.1", headers=AUTH)
            return resp.status

    assert run(go()) == 204


def test_turn_endpoint_is_404_outside_session_mode(tmp_path):
    async def go():
        async with running_app(tmp_path, llm="claude-code") as (client, ctl, log):
            resp = await client.get("/api/turn?wait=0.1", headers=AUTH)
            return resp.status

    assert run(go()) == 404


def test_a_hand_off_arrives_as_a_turn(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            log.delta("input", "hello")
            log.flush("You")
            ctl.start_handoff("d1")
            resp = await client.get("/api/turn?wait=2", headers=AUTH)
            return resp.status, await resp.json()

    assert run(go()) == (200, {"type": "turn", "id": "d1", "said": [{"who": "you", "text": "hello"}]})


def test_a_reply_is_made_speakable_and_captioned(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.turns.offer("d1", [{"who": "you", "text": "which one?"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            resp = await client.post("/api/reply", json={"id": "d1", "text": "Use `EXTERNAL_ONLY` here."},
                                     headers=AUTH)
            return resp.status, spoken(ctl), log.latencies

    status, said, latencies = run(go())
    assert status == 200
    assert said == ["Use external only here."]
    assert len(latencies) == 1


def test_a_reply_to_a_superseded_turn_gets_409(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.turns.offer("d1", [{"who": "you", "text": "one"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            ctl.turns.offer("d2", [{"who": "you", "text": "two"}])
            resp = await client.post("/api/reply", json={"id": "d1", "text": "Stale."}, headers=AUTH)
            return resp.status, spoken(ctl)

    status, said = run(go())
    assert status == 409
    assert said == []


def test_a_board_tag_in_a_reply_reads_the_file_from_disk(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("x = 1\ny = 2\n")

    async def go():
        async with running_app(tmp_path, code=code) as (client, ctl, log):
            ctl.turns.offer("d1", [{"who": "you", "text": "show me"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            await client.post("/api/reply", json={"id": "d1", "text": "[[show code: a.py:1-2 | A]] Look at this."},
                              headers=AUTH)
            return ctl.board.items, spoken(ctl)

    items, said = run(go())
    assert items[0]["lines"] == ["x = 1", "y = 2"]
    assert said == ["Look at this."]


def test_unclosed_board_tag_does_not_swallow_the_next_reply(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.turns.offer("d1", [{"who": "you", "text": "draw it"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            await client.post("/api/reply", json={"id": "d1", "text": "[[show diagram | D]]\ngraph TD; A-->B"},
                              headers=AUTH)
            ctl.turns.offer("d2", [{"who": "you", "text": "and then?"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            await client.post("/api/reply", json={"id": "d2", "text": "Then it stops."}, headers=AUTH)
            return ctl.board.items, spoken(ctl)

    items, said = run(go())
    assert items[0]["kind"] == "diagram"
    assert said == ["Then it stops."]


def test_a_status_is_accepted_and_the_turn_keeps_working(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.turns.offer("d1", [{"who": "you", "text": "check jira"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            resp = await client.post("/api/reply", json={"id": "d1", "status": "checking Jira"}, headers=AUTH)
            return resp.status, ctl.turns.working, ctl.turns.replied

    assert run(go()) == (200, True, True)


def test_end_flag_closes_the_call(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.turns.offer("d1", [{"who": "you", "text": "let's stop here"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            await client.post("/api/reply", json={"id": "d1", "text": "Good talk.", "end": True}, headers=AUTH)
            return log.end_reason

    assert run(go()) == "learner finished"


def test_offline_alert_is_spoken_when_nobody_collects_a_turn(tmp_path):
    from live_turns import TurnQueue

    class Clock:
        t = 0.0

        def __call__(self):
            return self.t

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            clock = Clock()
            ctl.turns = TurnQueue(clock)
            ctl.turns.offer("d1", [{"who": "you", "text": "hello?"}])
            clock.t = 21
            await ctl.alert_if_stuck()
            return instructions(ctl)

    assert run(go()) == [talk.OFFLINE_LINE]


def test_status_is_not_tied_to_the_hand_off_so_the_answer_still_gets_spoken(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.turns.offer("d1", [{"who": "you", "text": "check jira"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            await client.post("/api/reply", json={"id": "d1", "status": "checking Jira"}, headers=AUTH)
            await client.post("/api/reply", json={"id": "d1", "text": "It is about R4."}, headers=AUTH)
            return [(e["type"], e["delegation_id"]) for e in ctl.ws.events]

    assert run(go()) == [("session.instructions.append", None), ("session.commentary.append", "d1")]


def test_busy_alert_is_not_tied_to_the_hand_off(tmp_path):
    from live_turns import TurnQueue

    class Clock:
        t = 0.0

        def __call__(self):
            return self.t

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            clock = Clock()
            ctl.turns = TurnQueue(clock)
            ctl.turns.offer("d1", [{"who": "you", "text": "hello"}])
            await ctl.turns.next(timeout=1)
            clock.t = 9
            await ctl.alert_if_stuck()
            return [(e["type"], e["delegation_id"]) for e in ctl.ws.events]

    assert run(go()) == [("session.instructions.append", None)]


async def post_activity(client, **body):
    return await client.post("/api/activity", json={"session_id": "me", "phase": "start", "tool": "Read",
                                                     "label": "Reading A.java", "doorbell": False, **body},
                             headers=AUTH)


def test_activity_requires_the_token(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            resp = await client.post("/api/activity", json={})
            return resp.status

    assert run(go()) == 403


def test_activity_resets_when_a_new_turn_is_delivered(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await post_activity(client, tool="Bash", label=None, doorbell=True)
            ctl.turns.offer("d1", [{"who": "you", "text": "one"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            await post_activity(client)
            first = len(ctl.activity)
            ctl.turns.offer("d2", [{"who": "you", "text": "two"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            return first, len(ctl.activity)

    assert run(go()) == (1, 0)


def test_state_carries_activity_and_the_turn_timer(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await post_activity(client, tool="Bash", label=None, doorbell=True)
            ctl.turns.offer("d1", [{"who": "you", "text": "one"}])
            await client.get("/api/turn?wait=1", headers=AUTH)
            await post_activity(client)
            state = await (await client.get("/api/state", headers=AUTH)).json()
            return state["working"], [a["label"] for a in state["activity"]], state["elapsed"] >= 0, state["quiet"] >= 0

    assert run(go()) == (True, ["Reading A.java"], True, True)


def test_the_call_page_is_served_only_at_its_own_address(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            right = await client.get(f"/c/{CALL}")
            root = await client.get("/")
            wrong = await client.get("/c/not-the-call")
            return right.status, TOKEN in await right.text(), root.status, TOKEN in await root.text(), wrong.status, TOKEN in await wrong.text()

    assert run(go()) == (200, True, 404, False, 404, False)


def test_state_requires_the_token(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            return (await client.get("/api/state")).status

    assert run(go()) == 403


async def delivered(client, ctl, turn_id, text="hi"):
    ctl.turns.offer(turn_id, [{"who": "you", "text": text}])
    await client.get("/api/turn?wait=1", headers=AUTH)


def test_a_second_doorbell_supersedes_the_first_with_409(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            older = asyncio.create_task(client.get("/api/turn?wait=5", headers=AUTH))
            await asyncio.sleep(0.1)
            newer = asyncio.create_task(client.get("/api/turn?wait=5", headers=AUTH))
            await asyncio.sleep(0.1)
            ctl.turns.offer("d1", [{"who": "you", "text": "hello"}])
            old, new = await older, await newer
            return old.status, new.status, (await new.json())["id"]

    assert run(go()) == (409, 200, "d1")


def test_a_reply_after_the_call_ended_gets_410(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await delivered(client, ctl, "d1")
            ctl.turns.finish("learner finished", "/x/transcript.md")
            resp = await client.post("/api/reply", json={"id": "d1", "text": "Late."}, headers=AUTH)
            return resp.status, spoken(ctl)

    assert run(go()) == (410, [])


def test_a_reply_to_an_unknown_turn_gets_404(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            resp = await client.post("/api/reply", json={"id": "nope", "text": "Hi."}, headers=AUTH)
            return resp.status

    assert run(go()) == 404


def test_a_status_after_the_answer_is_not_spoken(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await delivered(client, ctl, "d1")
            await client.post("/api/reply", json={"id": "d1", "text": "It is R4."}, headers=AUTH)
            resp = await client.post("/api/reply", json={"id": "d1", "status": "checking Jira"}, headers=AUTH)
            return resp.status, "ignored" in await resp.json(), spoken(ctl), instructions(ctl)

    assert run(go()) == (200, True, ["It is R4."], [])


def test_a_status_that_ends_the_call_is_refused(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await delivered(client, ctl, "d1")
            resp = await client.post("/api/reply", json={"id": "d1", "status": "wrapping up", "end": True},
                                     headers=AUTH)
            return resp.status, log.end_reason

    assert run(go()) == (400, "stopped")


def test_inside_a_diagram_only_the_closing_tag_is_a_tag(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await delivered(client, ctl, "d1")
            text = "[[show diagram | D]]\n```mermaid\ngraph TD\n  A[[Sub]] --> B\n```\n[[/show]] See the board."
            await client.post("/api/reply", json={"id": "d1", "text": text}, headers=AUTH)
            return ctl.board.items[0]["body"], spoken(ctl)

    body, said = run(go())
    assert body == "graph TD\n  A[[Sub]] --> B"
    assert said == ["See the board."]


def test_a_closing_tag_split_across_chunks_is_still_found():
    f = talk.MarkerFilter()
    parts = f.feed_ordered("[[show table | T]]\n| a |\n[[/sh") + f.feed_ordered("ow]] Done.")
    assert parts == [("marker", "show table | T"), ("text", "\n| a |\n"), ("marker", "/show"), ("text", " Done.")]


def test_an_unclosed_diagram_is_closed_at_the_end_of_a_claude_code_reply(tmp_path):
    class Brain:
        async def stream(self, prompt, on_tool=None):
            for chunk in ("[[show diagram | D]]\ngraph TD; A-->", "B"):
                yield chunk

    async def go():
        async with running_app(tmp_path, llm="claude-code") as (client, ctl, log):
            ctl.brain = Brain()
            await ctl.handoff("d1")
            return ctl.board.open, [i["body"] for i in ctl.board.items]

    assert run(go()) == (None, ["graph TD; A-->B"])


def test_a_long_code_range_is_cut_and_says_so(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("".join(f"x{i} = {i}\n" for i in range(100)))

    async def go():
        async with running_app(tmp_path, code=code) as (client, ctl, log):
            await delivered(client, ctl, "d1")
            resp = await client.post("/api/reply", json={"id": "d1", "text": "[[show code: a.py:1-90 | A]] Here."},
                                     headers=AUTH)
            return ctl.board.items[0], (await resp.json())["board_problems"]

    item, problems = run(go())
    assert len(item["lines"]) == 60
    assert item["title"] == "A (first 60 lines)"
    assert problems == ["code cut to lines 1-60 of a.py: at most 60 lines"]


def test_the_transcript_keeps_the_full_reply_without_board_tags(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await delivered(client, ctl, "d1")
            text = "It has two states.\n[[show table | States]]\n| a | b |\n[[/show]] Open and closed."
            await client.post("/api/reply", json={"id": "d1", "text": text}, headers=AUTH)
            return log.transcript.read_text()

    transcript = run(go())
    assert "> **Claude's full reply:**\n>\n> It has two states.\n>  Open and closed." in transcript
    assert "> _Shown on the board: States_" in transcript
    assert "[[" not in transcript


async def lose_connection(ctl):
    await ctl.on_event({"type": "session.closed", "reason": "connection_lost"})
    ctl.sideband_ended()


def test_a_lost_connection_opens_a_rejoin_window(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.session_id, ctl.sessions = "s1", 1
            log.delta("input", "what is a proposal")
            log.flush("You")
            await lose_connection(ctl)
            state = await (await client.get("/api/state", headers=AUTH)).json()

            async def fake_create(sdp):
                ctl.session_id = "s2"
                return 201, {"session": {"id": "s2"}}

            ctl.create = fake_create
            resp = await client.post("/api/session", json={"sdp": "v=0"}, headers=AUTH)
            return state, resp.status, ctl.done.is_set(), ctl.session_config()["instructions"]

    state, status, done, config = run(go())
    assert (state["rejoinable"], state["session_live"], state["done"]) == (True, False, False)
    assert 0 < state["rejoin_seconds"] <= talk.REJOIN_SECONDS
    assert status == 201 and not done
    assert "Learner: what is a proposal" in config


def test_the_call_ends_when_nobody_rejoins(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "REJOIN_SECONDS", 0.05)

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.session_id, ctl.sessions = "s1", 1
            await lose_connection(ctl)
            await asyncio.wait_for(ctl.done.wait(), 2)
            state = await (await client.get("/api/state", headers=AUTH)).json()
            resp = await client.post("/api/session", json={"sdp": "v=0"}, headers=AUTH)
            return log.end_reason, state["rejoinable"], resp.status

    assert run(go()) == ("connection lost", False, 409)


def test_a_hang_up_still_ends_the_call(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.session_id, ctl.sessions = "s1", 1
            await ctl.on_event({"type": "session.closed", "reason": "remote_hangup"})
            ctl.sideband_ended()
            return ctl.done.is_set(), ctl.rejoinable, log.end_reason

    assert run(go()) == (True, False, "browser hung up")


def test_an_answer_that_produces_no_speech_is_said_again_untied(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            await ctl.ensure_spoken("The deck has seventeen slides.", wait=0.01)
            return instructions(ctl)

    said = run(go())
    assert len(said) == 1 and "The deck has seventeen slides." in said[0]


def test_an_answer_that_was_spoken_is_not_repeated(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            task = asyncio.create_task(ctl.ensure_spoken("The deck has seventeen slides.", wait=0.05))
            await asyncio.sleep(0.01)
            await ctl.on_event({"type": "session.output_transcript.delta", "delta": "The deck has seventeen slides."})
            await task
            return instructions(ctl)

    assert run(go()) == []


def test_a_filler_said_in_place_of_the_answer_does_not_count_as_the_answer(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            answer = "Jocelyn asked whether the workflow triggers a simulation when a proposal opens."
            task = asyncio.create_task(ctl.ensure_spoken(answer, wait=0.05))
            await asyncio.sleep(0.01)
            await ctl.on_event({"type": "session.output_transcript.delta",
                                "delta": "Jocelyn, I'm still working on your question about what triggers it."})
            await task
            return instructions(ctl)

    said = run(go())
    assert len(said) == 1 and "the workflow triggers a simulation" in said[0]


def test_an_answer_waits_while_the_voice_is_still_speaking(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.last_output = talk.time.time()
            started = talk.time.time()
            await ctl.voice_say("Here it is.", "d1")
            return talk.time.time() - started, spoken(ctl)

    waited, said = run(go())
    assert waited >= 1.0 and said == ["Here it is."]
