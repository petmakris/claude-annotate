"""Live mode: the microphone stays open, and speech over an answer interrupts it. The server tells
Claude how far the user had heard, drops the answer's own words heard back, and gates on a keyword."""
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
