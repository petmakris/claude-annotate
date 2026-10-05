import asyncio

from helpers import CALL, instructions, running_app, talk


def run(coro):
    return asyncio.run(coro)


def test_meeting_instructions_name_the_voice_and_forbid_greeting_and_backchannel():
    text = talk.meeting_instructions("Nova", "Retry policy review", ["idempotency"])
    assert "You are Nova, a participant in an in-person meeting" in text
    assert "Never greet" in text and "Never backchannel" in text
    assert "say nothing at all while you wait" in text
    assert "without repeating your name" in text
    assert "idempotency" in text


def test_the_meeting_wake_path_says_room_never_user_learner_or_tutor():
    texts = [
        talk.wake_block([{"text": "hi there", "start": 0.0, "end": 1.0}], None, meeting=True),
        talk.MEETING_WAKE_LINE.format(said="what is the limit"),
        talk.MEETING_WAKE_NOW_LINE,
    ]
    for text in texts:
        for banned in ("user", "learner", "tutor"):
            assert banned not in text.lower()


def test_wake_now_in_meeting_mode_appends_the_silent_line(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20, name="Nova") as (c, ctl, log):
            ctl.attached.set()
            ctl.sessions = 2
            ctl.woke_with = {}
            await ctl.greet()
            return instructions(ctl)

    assert run(go()) == [talk.MEETING_WAKE_NOW_LINE]


def test_a_meeting_session_uses_the_meeting_instructions_and_the_wake_words(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20, name="Nova") as (c, ctl, log):
            ctl.hear({"text": "we keep hitting the retry limit", "start": 0.0, "end": 1.0})
            ctl.hear({"text": "Nova, what is the limit today?", "start": 2.0, "end": 3.0})
            return ctl.state, ctl.session_config()["instructions"]

    state, text = run(go())
    assert state == "waking"
    assert text.startswith("You are Nova, a participant")
    assert "tutor" not in text.lower()
    assert "Room: we keep hitting the retry limit" in text
    assert 'Just said, answer this: "Nova, what is the limit today?"' in text


def test_a_meeting_rejoin_block_labels_lines_room_and_the_voices_name(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20, name="Nova") as (c, ctl, log):
            ctl.state = "live"
            ctl.sessions = 1
            log.delta("input", "what is the retry limit")
            log.flush("You")
            return ctl.session_config()["instructions"]

    text = run(go())
    assert "Room: what is the retry limit" in text
    assert "Learner:" not in text and "Tutor:" not in text


def test_talk_keeps_the_tutor_voice(tmp_path):
    async def go():
        async with running_app(tmp_path) as (c, ctl, log):
            return ctl.session_config()["instructions"]

    assert run(go()).startswith("You are the voice of a thoughtful, sharp tutor")


def test_the_projector_view_is_the_same_call_page(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20) as (client, ctl, log):
            resp = await client.get(f"/c/{CALL}?view=projector")
            return resp.status, await resp.text()

    status, html = run(go())
    assert status == 200
    assert 'id="pbar"' in html and 'get("view") === "projector"' in html
    assert '"wakeName": "Nova"' in html and '"mode": "meeting"' in html


def test_a_meeting_sleeps_once_the_voice_has_been_quiet_even_while_the_room_keeps_talking(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20, name="Nova") as (c, ctl, log):
            ctl.state, ctl.session_id, ctl.sessions, ctl.greeted = "live", "s1", 1, True
            now = talk.time.time()
            ctl.last_exchange = now - 30  # the question was put to Nova 30 s ago
            ctl.last_output = now - 21  # and Nova finished answering 21 s ago
            for words in ("so anyway ", "the retry limit ", "is what we said"):  # the room talks among itself
                await ctl.on_event({"type": "session.input_transcript.delta", "delta": words})
            return ctl.should_sleep(talk.time.time())

    assert run(go()) is True


def test_a_new_question_to_the_meeting_voice_restarts_its_follow_up_window(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20, name="Nova") as (c, ctl, log):
            ctl.state, ctl.session_id, ctl.sessions, ctl.greeted = "live", "s1", 1, True
            ctl.last_output = talk.time.time() - 25
            await ctl.on_event({"type": "session.delegation.created", "delegation": {"id": "d1", "target": "client"}})
            await asyncio.sleep(0.4)  # the delegation becomes a turn
            ctl.turns.offer("d1", [])
            await ctl.turns.next(timeout=1)
            await ctl.answer("d1", text="Three.")
            ctl.last_output = talk.time.time() - 25  # the answer produced no speech: the reply still counts
            return ctl.should_sleep(talk.time.time())

    assert run(go()) is False


class BrokenBrain:
    async def stream(self, prompt, on_tool=None):
        raise RuntimeError("the brain is down")
        yield  # an async generator, like the real brains


def test_nothing_the_meeting_voice_is_told_mentions_a_learner_and_a_rejoin_says_nothing(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20, name="Nova") as (c, ctl, log):
            clock = [0.0]
            ctl.turns = talk.TurnQueue(clock=lambda: clock[0])
            ctl.state, ctl.session_id, ctl.sessions = "live", "s2", 2
            ctl.attached.set()
            await ctl.greet()  # the session that replaced one lost to a dropped connection
            rejoin = instructions(ctl)
            ctl.turns.offer("d1", [])
            await ctl.turns.next(timeout=1)
            clock[0] = 9.0
            await ctl.alert_if_stuck()  # the busy line
            await ctl.answer("d1", status="checking the code")  # a status line
            ctl.turns.offer("d2", [])
            clock[0] = 40.0
            await ctl.alert_if_stuck()  # the offline line
            ctl.stale_delegations.add("d2")
            await ctl.turns.next(timeout=1)
            await ctl.answer("d2", text="Three.")  # an answer to a session lost since
            await ctl.ensure_spoken("Three.", wait=0)  # an answer resent untied
            ctl.brain = BrokenBrain()
            await ctl.handoff("d3")  # the brain failed
            await ctl.reach_time_limit()
            return rejoin, instructions(ctl), log.end_reason

    rejoin, told, end_reason = run(go())
    assert talk.REJOIN_LINE not in rejoin
    assert rejoin == [talk.MEETING_REJOIN_LINE]
    assert "say nothing" in talk.MEETING_REJOIN_LINE.lower()
    assert len(told) == 7  # rejoin, busy, status, offline, stale answer, resend, brain failure: no time-limit line
    for line in told:
        assert "learner" not in line.lower(), line
    assert end_reason == "reached the 60 min limit"


def test_talk_still_says_goodbye_at_the_time_limit(tmp_path):
    async def go():
        async with running_app(tmp_path) as (c, ctl, log):
            ctl.greeted = True  # a session that never started has nobody to say goodbye to
            await ctl.reach_time_limit()
            return instructions(ctl)

    told = run(go())
    assert len(told) == 1 and "time limit" in told[0] and "learner" in told[0]
