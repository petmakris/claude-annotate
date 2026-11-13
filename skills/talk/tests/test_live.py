"""Live mode: the microphone stays open, and speech over an answer interrupts it. The server tells
Claude how far the user had heard, drops the answer's own words heard back, and gates on a keyword."""
import asyncio

from helpers import AUTH, run, running_app, silent_wav, talk

ANSWER = "The queue merges two turns. The first sets the pending id. The second only adds its lines."


async def _answer(call):
    await call.answer(ANSWER)
    return next(e for e in call.entries if e["who"] == "claude")


def test_speech_over_an_answer_tells_claude_how_far_the_user_heard(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            entry = await _answer(call)
            fake.heard = "wait, what is a pending id?"
            at = ANSWER.index("The second")
            said = await (await client.post(f"/api/listen?interrupted={entry['id']}&at={at}", data=silent_wav(), headers=AUTH)).json()
            turn = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            return said, turn

    said, turn = run(go())
    assert said["text"] == "wait, what is a pending id?"
    you = turn["said"][-1]
    assert you["text"] == "wait, what is a pending id?"
    assert you["interrupted"] == {"answer": 1, "heard": "The queue merges two turns. The first sets the pending id.",
                                  "rest_unheard": True}


def test_the_answer_heard_back_through_a_speaker_is_an_echo_not_a_turn(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            entry = await _answer(call)
            fake.heard = "the first sets the pending ID"
            at = ANSWER.index("The first") + 10
            said = await (await client.post(f"/api/listen?interrupted={entry['id']}&at={at}", data=silent_wav(), headers=AUTH)).json()
            return said, (await client.get("/api/turn?wait=0.1", headers=AUTH)).status

    assert run(go()) == ({"text": "", "echo": True}, 204)


def test_with_the_keyword_only_words_that_start_with_it_interrupt(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            entry = await _answer(call)
            path = f"/api/listen?keyword=1&interrupted={entry['id']}&at=10"
            out = []
            for heard in ("so anyway the dog", "Listen.", "Listen, why merge them?"):
                fake.heard = heard
                out.append(await (await client.post(path, data=silent_wav(), headers=AUTH)).json())
            turn = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            return out, turn

    (other, alone, asked), turn = run(go())
    assert other == {"text": "so anyway the dog", "ignored": True}
    assert alone == {"text": "", "keyword": True}
    assert asked["text"] == "why merge them?"
    assert [s["text"] for s in turn["said"]] == ["why merge them?"]


def test_cue_words_are_matched_as_words_at_the_start():
    assert talk.after_keyword("Listen, why?") == "why?"
    assert talk.after_keyword("Hold on. Why merge?") == "Why merge?"
    assert talk.after_keyword("wait") == ""
    assert talk.after_keyword("Περίμενε, γιατί;") == "γιατί;"
    assert talk.after_keyword("Listening is hard") is None
    assert talk.after_keyword("I said wait") is None


def test_mm_hm_over_an_answer_means_go_on_and_is_no_turn(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            entry = await _answer(call)
            out = []
            for heard in ("Mm-hm.", "yeah", "Okay, go on"):
                fake.heard = heard
                out.append(await (await client.post(f"/api/listen?interrupted={entry['id']}&at=10", data=silent_wav(), headers=AUTH)).json())
            return out, (await client.get("/api/turn?wait=0.1", headers=AUTH)).status

    out, status = run(go())
    assert out[0] == out[1] == {"text": "", "backchannel": True}
    assert out[2]["text"] == "Okay, go on" and status == 200  # more than a backchannel: a turn


def test_a_question_that_borrows_the_answers_words_is_not_taken_for_echo(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            entry = await _answer(call)
            fake.heard = "the pending id?"
            at = ANSWER.index("The first") + 10
            return await (await client.post(f"/api/listen?interrupted={entry['id']}&at={at}", data=silent_wav(), headers=AUTH)).json()

    said = run(go())
    assert said["text"] == "the pending id?" and "echo" not in said


def _listen(client, path="/api/listen?live=1"):
    async def go():
        return await (await client.post(path, data=silent_wav(), headers=AUTH)).json()
    return go()


def test_spoken_commands_are_no_turn_in_live_mode_and_plain_words_otherwise(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            out = []
            for heard in ("Go on.", "please repeat that", "Pause", "go back", "stop listening", "Συνέχισε"):
                fake.heard = heard
                out.append((await _listen(client)).get("command"))
            fake.heard = "go on"
            manual = await _listen(client, "/api/listen")  # Press to talk: everything said is a turn
            return out, manual

    out, manual = run(go())
    assert out == ["resume", "repeat", "pause", "back", "mute", "resume"]
    assert manual["text"] == "go on" and "entry" in manual


def test_never_mind_takes_back_what_claude_does_not_have_yet(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.heard = "what about the mapper?"
            said = await _listen(client)
            fake.heard = "Never mind."
            back = await _listen(client)
            empty = (await client.get("/api/turn?wait=0.1", headers=AUTH)).status
            entry = next(e for e in call.entries if e["id"] == said["entry"]["id"])
            return back, empty, entry

    back, empty, entry = run(go())
    assert back == {"text": "", "command": "withdraw", "withdrawn": True}
    assert empty == 204 and entry["withdrawn"] is True


def test_never_mind_after_claude_has_the_turn_reaches_claude_as_said(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.heard = "what about the mapper?"
            await _listen(client)
            await client.get("/api/turn?wait=1", headers=AUTH)  # Claude collected it
            fake.heard = "never mind"
            back = await _listen(client)
            turn = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            return back, turn

    back, turn = run(go())
    assert back["text"] == "never mind" and "entry" in back
    assert turn["said"] == [{"who": "you", "text": "never mind", "while_working": True}]


def test_undo_takes_back_a_turn_only_while_it_waits(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.heard = "first"
            first = (await _listen(client))["entry"]["id"]
            undone = await (await client.post("/api/withdraw", json={"entry": first}, headers=AUTH)).json()
            fake.heard = "second"
            second = (await _listen(client))["entry"]["id"]
            await client.get("/api/turn?wait=1", headers=AUTH)
            late = await (await client.post("/api/withdraw", json={"entry": second}, headers=AUTH)).json()
            return undone, late

    assert run(go()) == ({"withdrawn": True}, {"withdrawn": False})


def test_a_thought_left_hanging_waits_for_its_end(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "LIVE_JOIN_S", 0.3)

    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.heard = "so what about the"
            held = await _listen(client)
            fake.heard = "mapper?"
            joined = await _listen(client)
            fake.heard = "and then, um"
            alone = await _listen(client)
            turn1 = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()
            turn2 = await (await client.get("/api/turn?wait=1", headers=AUTH)).json()  # flushed after LIVE_JOIN_S
            return held, joined, alone, turn1, turn2

    held, joined, alone, turn1, turn2 = run(go())
    assert held == {"text": "so what about the", "held": True}
    assert joined["text"] == "so what about the mapper?"
    assert alone == {"text": "and then, um", "held": True}
    assert [s["text"] for s in turn1["said"]] == ["so what about the mapper?"]
    assert [s["text"] for s in turn2["said"]] == ["and then, um"]


def test_a_live_turn_makes_one_moment_once_in_the_calls_voice(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, call, fake):
            fake.heard = "a question"
            await _listen(client)
            for _ in range(50):
                if call.filler:
                    break
                await asyncio.sleep(0.05)
            await _listen(client)
            await asyncio.sleep(0.2)
            got = await client.get(f"/c/{call.id}/{call.filler}")
            return call.filler, fake.spoken.count("One moment."), got.status

    filler, made, status = run(go())
    assert filler.startswith("audio/filler.") and made == 1 and status == 200
