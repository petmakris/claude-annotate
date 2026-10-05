import asyncio
import json

from helpers import AUTH, RecordingSocket, instructions, running_app, talk
from live_turns import OFFLINE_AFTER


def run(coro):
    return asyncio.run(coro)


def seg(text, start=0.0, end=1.0, **extra):
    return {"text": text, "start": start, "end": end, **extra}


def live(ctl, log, quiet_since=1000.0):
    """A greeted live session, quiet since `quiet_since`."""
    ctl.session_id, ctl.sessions, ctl.greeted = "s1", 1, True
    ctl.attached.set()
    log.last_learner_speech = quiet_since
    ctl.last_output = quiet_since


async def sleep_through(ctl, reason="client_closed"):
    """sleep(), with GPT-Live answering the close the way it does: session.closed, then the sideband ends."""
    task = asyncio.create_task(ctl.sleep(wait=2))
    await asyncio.sleep(0)
    await ctl.on_event({"type": "session.closed", "reason": reason})
    ctl.sideband_ended()
    await task


class FakeResponse:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def json(self, content_type=None):
        return self._body

    async def text(self):
        return self._body if isinstance(self._body, str) else json.dumps(self._body)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSideband(RecordingSocket):
    """A sideband GPT-Live closes without a word: iterating it ends at once."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()
        return False


class FakeHttp:
    """Stands in for OpenAI's session-create endpoint and records what was sent."""

    def __init__(self, status=201, body=None, on_post=None):
        self.status = status
        self.body = body if body is not None else {"session": {"id": "s2"}, "transport": {"sdp": "v=0"}}
        self.sent = []
        self.on_post = on_post  # runs while the POST is in flight
        self.attached: list[tuple[str, FakeSideband]] = []

    def post(self, url, headers=None, json=None, **kwargs):
        self.sent.append(json)
        if self.on_post:
            self.on_post()
        return FakeResponse(self.status, self.body)

    def ws_connect(self, url, headers=None, **kwargs):
        ws = FakeSideband()
        self.attached.append((url, ws))
        return ws


# -- live -> dormant -----------------------------------------------------------


def test_a_quiet_live_call_sleeps_after_dormant_after_seconds(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            return ctl.should_sleep(1044.0), ctl.should_sleep(1045.0)

    assert run(go()) == (False, True)


def test_recent_speech_from_either_side_keeps_the_call_live(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            ctl.last_output = 1030.0
            voice = ctl.should_sleep(1050.0)
            ctl.last_output, log.last_learner_speech = 1000.0, 1030.0
            learner = ctl.should_sleep(1050.0)
            return voice, learner

    assert run(go()) == (False, False)


def test_no_sleep_while_a_turn_waits_or_the_brain_works(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            ctl.turns.offer("d1", [{"who": "you", "text": "check jira"}])
            pending = ctl.should_sleep(2000.0)
            await ctl.turns.next(timeout=1)
            working = ctl.should_sleep(2000.0)
            ctl.turns.accept_reply("d1")
            ctl.thinking = True
            thinking = ctl.should_sleep(2000.0)
            ctl.thinking = False
            return pending, working, thinking, ctl.should_sleep(2000.0)

    assert run(go()) == (False, False, False, True)


def test_should_sleep_waits_while_a_delegation_has_not_yet_become_a_turn(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            ctl.delegations.add("d1")  # session.delegation.created just fired; enqueue_turn's 0.35 s hasn't run
            return ctl.should_sleep(2000.0)

    assert run(go()) is False


def test_dormant_after_zero_never_sleeps(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=0) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            return ctl.should_sleep(99999.0)

    assert run(go()) is False


def test_sleep_closes_the_session_without_ending_the_call_or_opening_a_rejoin_window(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await sleep_through(ctl)
            return (ctl.state, ctl.session_id, ctl.done.is_set(), ctl.rejoinable, log.end_reason,
                    ctl.dormant_task is not None)

    assert run(go()) == ("dormant", None, False, False, "stopped", True)


def test_sleep_sends_session_close_on_the_sideband(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ws = ctl.ws
            await sleep_through(ctl)
            return [e["type"] for e in ws.events]

    assert run(go()) == ["session.close"]


def test_a_close_reported_as_connection_lost_during_sleep_is_still_a_sleep(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await sleep_through(ctl, reason="connection_lost")
            return ctl.state, ctl.rejoinable, ctl.done.is_set(), log.end_reason

    assert run(go()) == ("dormant", False, False, "stopped")


def test_a_real_drop_while_live_still_opens_the_rejoin_window(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await ctl.on_event({"type": "session.closed", "reason": "connection_lost"})
            ctl.sideband_ended()
            return ctl.state, ctl.rejoinable

    assert run(go()) == ("live", True)


def test_the_idle_end_does_not_apply_while_dormancy_is_on(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, idle_minutes=5) as (client, ctl, log):
            log.last_learner_speech = 0.0
            with_dormancy = ctl.idle_expired(3600.0)
            ctl.args.dormant_after = 0
            return with_dormancy, ctl.idle_expired(3600.0)

    assert run(go()) == (False, True)


def test_a_dormant_call_still_ends_at_its_time_limit(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, max_minutes=60) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.limit_at = talk.time.time() - 1
            await asyncio.wait_for(ctl.dormant_watch(every=0.01), 2)
            return ctl.done.is_set(), log.end_reason

    assert run(go()) == (True, "reached the 60 min limit")


# -- a wake racing a sleep still in flight --------------------------------------


def test_a_wake_while_the_old_session_is_still_closing_is_deferred_not_lost(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            log.voice_seconds = 12.5
            task = asyncio.create_task(ctl.sleep(wait=2))
            await asyncio.sleep(0)  # sleep() has sent session.close and is waiting for it
            ctl.hear(seg("Nova, are you still there"))  # a wake arrives before the old session is gone
            still_dormant = ctl.state  # the wake must not have moved state yet
            await ctl.on_event({"type": "session.closed", "reason": "client_closed"})
            ctl.sideband_ended()
            await task
            return (still_dormant, ctl.state, ctl.done.is_set(), ctl.rejoinable, log.end_reason,
                    ctl.greeted, ctl.voice_base, ctl.wake_segment["text"])

    still_dormant, state, done, rejoinable, end_reason, greeted, voice_base, wake_text = run(go())
    assert still_dormant == "dormant"
    assert (state, done, rejoinable, end_reason) == ("waking", False, False, "stopped")
    assert greeted is False
    assert voice_base == 12.5
    assert wake_text == "Nova, are you still there"


def test_what_is_heard_while_sleep_is_closing_survives_into_the_seed(tmp_path):
    async def go():
        # wake="name": the words below do not wake the call, so this exercises a plain sleep -> rest(),
        # not the wake-during-sleep race covered above.
        async with running_app(tmp_path, dormant_after=45, wake="name") as (client, ctl, log):
            live(ctl, log)
            task = asyncio.create_task(ctl.sleep(wait=2))
            await asyncio.sleep(0)
            ctl.hear(seg("we should lower the limit"))  # heard while the old session is still closing
            await ctl.on_event({"type": "session.closed", "reason": "client_closed"})
            ctl.sideband_ended()
            await task
            return ctl.heard_since

    assert run(go()) == [seg("we should lower the limit")]


def test_a_stale_close_never_touches_a_session_created_after_it(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            old_ws = ctl.ws
            ctl.sleeping_ws = old_ws  # sleep() is still waiting for this (old) session's close
            ctl.state = "dormant"
            new_ws = RecordingSocket()
            ctl.ws = new_ws  # a new session has already attached, ahead of the old close arriving
            await ctl.on_event({"type": "session.closed", "reason": "client_closed"})
            return ctl.ws is new_ws, new_ws.closed

    still_new, new_closed = run(go())
    assert still_new is True
    assert new_closed is False


def test_wake_block_caps_the_just_said_text_at_500_characters():
    said = "x" * 600
    text = talk.wake_block([], {"text": said})
    assert f'"{said[:500]}"' in text
    assert said not in text


# -- dormant -> waking ---------------------------------------------------------


def test_talk_wakes_on_two_words_and_not_on_a_cough(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, wake="speech") as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("hm"))
            after_cough = ctl.state
            ctl.hear(seg("what about retries"))
            return after_cough, ctl.state, ctl.wake_segment["text"]

    assert run(go()) == ("dormant", "waking", "what about retries")


def test_a_meeting_wakes_only_on_its_name_or_a_sound_alike(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, wake="name", name="Nova", sounds_like="Noa, Nover",
                               mode="meeting") as (client, ctl, log):
            start = ctl.state
            ctl.hear(seg("Nora, what do you think about the retry limit"))
            ctl.hear(seg("Novak has the numbers"))
            before = ctl.state
            ctl.hear(seg("noa, lower it to three?"))
            return start, before, ctl.state

    assert run(go()) == ("dormant", "dormant", "waking")


def test_what_the_ear_hears_goes_into_the_transcript_and_the_next_turn(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("we should lower the limit"))
            return log.new_lines(), log.transcript.read_text(), log.conversation_text()

    lines, transcript, conversation = run(go())
    assert lines == [{"who": "room", "text": "we should lower the limit"}]
    assert "**Room:** we should lower the limit" in transcript
    assert "Room: we should lower the limit" in conversation


def test_an_empty_segment_is_not_written_down(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("", energy_only=True, end=0.3))
            return log.new_lines(), ctl.heard_since, ctl.state

    assert run(go()) == ([], [], "dormant")


# -- waking -> live: the seeded session ------------------------------------------


def test_the_woken_session_carries_the_dormant_transcript_and_the_wake_words(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, wake="name") as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("we were talking about retries"))
            ctl.hear(seg("Nova, should it be three?"))
            return ctl.session_config()["instructions"]

    text = run(go())
    assert "Room: we were talking about retries" in text
    assert 'Just said, answer this: "Nova, should it be three?"' in text
    assert "Room: Nova, should it be three?" not in text  # the wake words appear once, as the question


def test_the_dormant_transcript_is_cut_to_the_last_6000_characters(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.heard_since = [seg(f"early {i} " + "x" * 90) for i in range(100)]
            ctl.state = "waking"
            return ctl.session_config()["instructions"]

    text = run(go())
    assert "early 99" in text and "early 0 " not in text


def test_a_rejoin_after_a_drop_keeps_its_own_block(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.sessions = 1
            log.delta("input", "what is a proposal")
            log.flush("You")
            return ctl.session_config()["instructions"]

    text = run(go())
    assert talk.REJOIN_INTRO in text and "Learner: what is a proposal" in text
    assert "Just said" not in text


def test_a_successful_wake_goes_live_and_clears_what_was_heard(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.http = FakeHttp()
            ctl.run_sideband = lambda: asyncio.sleep(0)
            ctl.state = "dormant"
            ctl.hear(seg("Nova, is it three?"))
            status, _ = await ctl.create("v=0")
            sent = ctl.http.sent[0]["session"]["instructions"]
            return status, ctl.state, ctl.heard_since, ctl.wake_segment, ctl.woke_with["text"], sent

    status, state, heard, pending, woke, sent = run(go())
    assert (status, state, heard, pending, woke) == (201, "live", [], None, "Nova, is it three?")
    assert 'Just said, answer this: "Nova, is it three?"' in sent


def test_a_failed_wake_stays_dormant_and_keeps_the_wake_words_for_the_next_attempt(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.http = FakeHttp(status=429, body={"error": {"message": "insufficient_quota"}})
            ctl.run_sideband = lambda: asyncio.sleep(0)
            ctl.state = "dormant"
            ctl.hear(seg("Nova, is it three?"))
            status, body = await ctl.create("v=0")
            return status, "no credit" in body["error"], ctl.state, ctl.session_config()["instructions"]

    status, reported, state, config = run(go())
    assert (status, reported, state) == (429, True, "dormant")
    assert 'Just said, answer this: "Nova, is it three?"' in config


def test_a_woken_session_does_not_greet_and_hands_the_wake_words_on(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.attached.set()
            ctl.sessions = 2
            ctl.woke_with = seg("Nova, is it three?")
            await ctl.greet()
            return instructions(ctl)

    said = run(go())
    assert said == [talk.WAKE_LINE.format(said="Nova, is it three?")]


def test_wake_now_without_words_just_says_it_is_listening(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.attached.set()
            ctl.sessions = 2
            ctl.woke_with = {}
            await ctl.greet()
            return instructions(ctl)

    assert run(go()) == [talk.WAKE_NOW_LINE]


def test_wake_words_the_voice_never_handed_off_are_offered_to_the_brain(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.session_id = "s2"
            ctl.state = "dormant"
            ctl.hear(seg("Nova, what is two plus two"))
            await ctl.ensure_wake_handed_off(wait=0.01)
            event = await ctl.turns.next(timeout=1)
            return event["said"], event["id"] in ctl.stale_delegations

    said, untied = run(go())
    assert said == [{"who": "room", "text": "Nova, what is two plus two"}] and untied


def test_wake_words_the_voice_did_hand_off_are_not_offered_twice(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.session_id = "s2"
            ctl.delegations.add("d9")
            await ctl.ensure_wake_handed_off(wait=0.01)
            return ctl.turns.pending

    assert run(go()) is False


# -- a turn the brain never collects must not hold a paid session open ----------


def test_a_turn_nobody_collects_stops_holding_the_session_once_the_offline_alert_fires(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            clock = [0.0]
            ctl.turns = talk.TurnQueue(clock=lambda: clock[0])
            live(ctl, log, quiet_since=1000.0)
            ctl.turns.offer("d1", [{"who": "you", "text": "check jira"}])
            held = ctl.should_sleep(2000.0)
            clock[0] = OFFLINE_AFTER + 1  # the brain is gone: no doorbell, no tool calls
            await ctl.alert_if_stuck()  # the offline line is spoken
            return held, ctl.should_sleep(2000.0), ctl.idle_expired(2000.0)

    held, sleeps, ends = run(go())
    assert (held, sleeps) == (False, True)
    assert ends is False  # the backstop sleeps the call; it does not end it


def test_a_turn_pending_past_idle_minutes_stops_holding_the_session(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, idle_minutes=5) as (client, ctl, log):
            clock = [0.0]
            ctl.turns = talk.TurnQueue(clock=lambda: clock[0])
            live(ctl, log, quiet_since=1000.0)
            ctl.turns.offer("d1", [{"who": "you", "text": "check jira"}])
            clock[0] = 4 * 60
            ctl.turns.note_activity()  # tool calls keep the offline alert from firing
            early = ctl.should_sleep(2000.0)
            clock[0] = 5 * 60 + 1
            ctl.turns.note_activity()
            alert = ctl.turns.check()
            return early, alert, ctl.should_sleep(2000.0)

    assert run(go()) == (False, None, True)


def test_a_stuck_turn_still_waits_for_the_quiet_window(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            clock = [0.0]
            ctl.turns = talk.TurnQueue(clock=lambda: clock[0])
            live(ctl, log, quiet_since=1000.0)
            ctl.turns.offer("d1", [])
            clock[0] = OFFLINE_AFTER + 1
            await ctl.alert_if_stuck()
            ctl.last_output = 1990.0  # the offline line is still being spoken
            return ctl.should_sleep(2000.0)

    assert run(go()) is False


def test_a_session_created_after_the_call_ended_is_closed_at_once_not_attached(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ws = None
            ctl.http = FakeHttp(on_post=ctl.done.set)  # End is pressed while the POST is in flight
            sidebands = []
            ctl.run_sideband = lambda: sidebands.append(True) or asyncio.sleep(0)
            status, body = await ctl.create("v=0")
            await asyncio.sleep(0)
            (url, ws), = ctl.http.attached
            return (status, "ended" in body["error"], ctl.session_id, ctl.sessions, sidebands, url,
                    [e["type"] for e in ws.events], ws.closed)

    status, said, session_id, sessions, sidebands, url, sent, closed = run(go())
    assert (status, said, session_id, sessions, sidebands) == (410, True, None, 0, [])
    assert url.endswith("/live/sessions/s2/attach")
    assert sent == ["session.close"] and closed


def test_a_failed_wake_reported_by_the_page_goes_back_to_dormant_only_while_no_session_exists(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("what about retries"))
            ctl.session_id = "s2"  # the POST won the race: the report is stale
            stale = ctl.wake_failed("no microphone"), ctl.state
            ctl.session_id = None
            resp = await client.post("/api/wake-failed", headers=AUTH, json={"reason": "no microphone"})
            return stale, (await resp.json())["dormant"], ctl.state, ctl.wake_segment["text"]

    assert run(go()) == ((False, "waking"), True, "dormant", "what about retries")
