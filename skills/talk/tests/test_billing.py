"""Paid GPT-Live time that nobody sees: every way a session can stay open, billed by the second, after
the call has stopped using it. No OpenAI session is created: FakeHttp stands in for OpenAI."""
import asyncio
import json
import time
from types import SimpleNamespace

from helpers import running_app, talk
from test_dormant import FakeHttp, FakeSideband, live


def run(coro):
    return asyncio.run(coro)


def text(event: dict):
    return SimpleNamespace(type=SimpleNamespace(name="TEXT"), data=json.dumps(event))


class ScriptedSideband(FakeSideband):
    """A sideband that delivers these events, then ends."""

    def __init__(self, events):
        super().__init__()
        self.script = [text(e) for e in events]

    async def __anext__(self):
        if not self.script:
            raise StopAsyncIteration
        return self.script.pop(0)


class ScriptedHttp(FakeHttp):
    """The first attach plays `first`; every later one (a discard) is a plain FakeSideband."""

    def __init__(self, first, **kw):
        super().__init__(**kw)
        self.first = first

    def ws_connect(self, url, headers=None, **kwargs):
        ws = ScriptedSideband(self.first) if not self.attached else FakeSideband()
        self.attached.append((url, ws))
        return ws


async def settle(ctl):
    for _ in range(20):
        await asyncio.sleep(0)
    await ctl.settle_closes(timeout=2)


# -- M2: a sideband that ends without session.closed leaves the session open ----------------------


def test_a_sideband_that_drops_without_closed_reattaches_and_closes_the_session(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.http = ScriptedHttp(first=[])  # the network drops: no session.closed
            await ctl.run_sideband()
            await settle(ctl)
            return ctl.done.is_set(), [(url, [e["type"] for e in ws.events]) for url, ws in ctl.http.attached]

    done, attached = run(go())
    assert done  # the call itself ends as before
    assert len(attached) == 2
    assert attached[1][0].endswith("/live/sessions/s1/attach")
    assert attached[1][1] == ["session.close"]


def test_a_sideband_that_saw_session_closed_does_not_reattach(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.http = ScriptedHttp(first=[{"type": "session.closed", "reason": "remote_hangup"}])
            await ctl.run_sideband()
            await settle(ctl)
            return len(ctl.http.attached)

    assert run(go()) == 1


def test_a_lost_connection_keeps_its_rejoin_window_and_is_not_reattached(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.http = ScriptedHttp(first=[{"type": "session.closed", "reason": "connection_lost"}])
            await ctl.run_sideband()
            await settle(ctl)
            ctl.rejoin_task.cancel()
            return ctl.rejoinable, len(ctl.http.attached)

    assert run(go()) == (True, 1)


def test_a_sleep_whose_close_is_never_confirmed_closes_the_session_over_a_new_attach(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.http = FakeHttp()
            await ctl.sleep(wait=0.05)  # GPT-Live never answers: sleep() closes the sideband
            ctl.sideband_ended()  # what run_sideband's end does next
            await settle(ctl)
            return ctl.state, [(url, [e["type"] for e in ws.events]) for url, ws in ctl.http.attached]

    state, attached = run(go())
    assert state == "dormant"  # the call sleeps as before
    assert attached == [(f"{talk.OPENAI_API.replace('https://', 'wss://')}/live/sessions/s1/attach",
                         ["session.close"])]


def test_a_sideband_that_fails_to_attach_still_closes_the_session(tmp_path):
    class FailingOnce(FakeHttp):
        def ws_connect(self, url, headers=None, **kwargs):
            if not self.attached:
                self.attached.append((url, None))
                raise OSError("network unreachable")
            return super().ws_connect(url, headers, **kwargs)

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.http = FailingOnce()
            await ctl.run_sideband()
            await settle(ctl)
            return [(ws.events if ws else None) for _, ws in ctl.http.attached]

    assert run(go()) == [None, [{"type": "session.close", "event_id": "close_1"}]]


# -- M3: a session that never reports session.started ----------------------------------------------


def events_of(ctl):
    return [e["type"] for e in ctl.ws.events]


def test_the_time_limit_applies_before_the_session_is_greeted(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, max_minutes=1) as (client, ctl, log):
            ctl.session_id, ctl.sessions = "s1", 1
            ctl.attached.set()
            ctl.limit_at = time.time() - 3600  # the limit passed an hour ago
            ticker = asyncio.create_task(ctl.tick())
            await asyncio.sleep(0.8)
            ticker.cancel()
            return ctl.closing, events_of(ctl), log.end_reason

    closing, sent, reason = run(go())
    assert closing
    assert "session.instructions.append" not in sent  # nobody can hear a goodbye
    assert reason == "reached the 1 min limit"


async def created(ctl, **http):
    """create() against FakeHttp, with a sideband that attaches and stays open."""
    ctl.ws = None
    ctl.http = FakeHttp(**http)

    async def attach():
        ctl.ws = talk_socket()
        ctl.attached.set()

    ctl.run_sideband = attach
    status, body = await ctl.create("v=0")
    await asyncio.sleep(0)
    return status, body


def talk_socket():
    from helpers import RecordingSocket
    return RecordingSocket()


def test_a_session_that_never_starts_is_closed_and_the_call_goes_back_to_dormant(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, mode="meeting", wake="name") as (client, ctl, log):
            ctl.start_timeout = 0.05
            ctl.hear({"text": "Nova, what now?", "start": 0.0, "end": 1.0})
            await created(ctl)
            ws = ctl.ws
            await asyncio.sleep(0.2)
            sent = [e["type"] for e in ws.events]
            ctl.sideband_ended("s2")  # GPT-Live closes; the sideband ends
            await settle(ctl)
            return sent, ctl.state, ctl.session_id, ctl.failed_starts, ctl.wake_segment

    sent, state, session_id, failed, wake = run(go())
    assert sent == ["session.close"]
    assert (state, session_id, failed) == ("dormant", None, 1)
    assert wake is None  # not retried on its own: each attempt is billed at least 15 s


def test_a_first_session_that_never_starts_is_closed_and_the_page_may_start_again(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=0) as (client, ctl, log):
            ctl.start_timeout = 0.05
            await created(ctl)
            ws = ctl.ws
            await asyncio.sleep(0.2)
            ctl.sideband_ended("s2")
            await settle(ctl)
            ctl.rejoin_task.cancel()
            return [e["type"] for e in ws.events], ctl.done.is_set(), ctl.rejoinable, ctl.session_id

    assert run(go()) == (["session.close"], False, True, None)


def test_a_session_that_started_is_left_alone_by_the_start_watchdog(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.start_timeout = 0.1
            await created(ctl)
            await ctl.greet()
            await asyncio.sleep(0.3)
            return events_of(ctl), ctl.failed_starts

    sent, failed = run(go())
    assert "session.close" not in sent and failed == 0


def test_a_transcript_on_the_sideband_counts_as_started(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.session_id, ctl.sessions = "s1", 1
            ctl.attached.set()
            await ctl.on_event({"type": "session.output_transcript.delta", "delta": "Hello"})
            await asyncio.sleep(0.05)
            return ctl.greeted

    assert run(go()) is True


def test_a_usage_report_on_the_sideband_counts_as_started(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.session_id, ctl.sessions = "s1", 1
            ctl.attached.set()
            await ctl.on_event({"type": "session.usage.updated", "usage": {"seconds": 3}})
            await asyncio.sleep(0.05)
            return ctl.greeted

    assert run(go()) is True


def test_a_wake_failure_reported_after_create_closes_the_unusable_session(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, mode="meeting", wake="name") as (client, ctl, log):
            ctl.hear({"text": "Nova, what now?", "start": 0.0, "end": 1.0})
            await created(ctl)
            ws = ctl.ws
            dormant = ctl.wake_failed("setRemoteDescription failed")  # the page cannot use the session
            await asyncio.sleep(0.05)
            return dormant, [e["type"] for e in ws.events]

    assert run(go()) == (False, ["session.close"])


def test_a_session_created_after_the_page_gave_up_on_the_wake_is_closed_at_once(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, mode="meeting", wake="name") as (client, ctl, log):
            ctl.ws = None
            ctl.hear({"text": "Nova, what now?", "start": 0.0, "end": 1.0})
            # The page's microphone fails while its POST is in flight: its wake-failed report wins the race.
            ctl.http = FakeHttp(on_post=lambda: ctl.wake_failed("no microphone"))
            ctl.run_sideband = lambda: asyncio.sleep(0)
            status, _ = await ctl.create("v=0")
            (url, ws), = ctl.http.attached
            return status, ctl.session_id, ctl.state, [e["type"] for e in ws.events]

    assert run(go()) == (410, None, "dormant", ["session.close"])


# -- M4: a turn the brain collected and never answered ---------------------------------------------


async def collected(ctl, log, clock):
    ctl.turns = talk.TurnQueue(clock=lambda: clock[0])
    live(ctl, log)
    ctl.turns.offer("d1", [{"who": "you", "text": "x"}])
    await ctl.turns.next(timeout=1)  # the brain collected it, then went silent


def test_a_collected_turn_silent_for_two_minutes_stops_holding_the_session(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            clock = [0.0]
            await collected(ctl, log, clock)
            clock[0] = 119
            early = ctl.brain_absent(), ctl.should_sleep(5000.0)
            clock[0] = 121
            return early, (ctl.brain_absent(), ctl.should_sleep(5000.0))

    assert run(go()) == ((False, False), (True, True))


def test_hook_activity_or_a_status_keeps_a_working_turn_present(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            clock = [0.0]
            await collected(ctl, log, clock)
            clock[0] = 100
            ctl.turns.note_activity()  # a tool call from the brain session
            clock[0] = 200
            after_activity = ctl.brain_absent()
            clock[0] = 215
            await ctl.answer("d1", status="checking the code")
            clock[0] = 510  # a turn that sent a status is allowed 300 s
            after_status = ctl.brain_absent()
            clock[0] = 516
            return after_activity, after_status, ctl.brain_absent()

    assert run(go()) == (False, False, True)


def test_without_dormancy_a_silent_working_turn_no_longer_blocks_the_idle_end(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=0, idle_minutes=5) as (client, ctl, log):
            clock = [0.0]
            await collected(ctl, log, clock)
            clock[0] = 121
            return ctl.idle_expired(1000.0 + 6 * 60)

    assert run(go()) is True


# -- CAPS: hard limits on paid live time -----------------------------------------------------------


def ledger(tmp_path=None):
    path = talk.LEDGER_FILE
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def today():
    return talk.dt.date.today().isoformat()


def test_every_session_is_billed_at_least_15_s_and_no_more_once_past_it(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await created(ctl)
            fresh = ctl.billed_seconds()
            ctl.voice_marked_at -= 50  # the session has been open 50 s
            return ctl.opened, fresh, ctl.billed_seconds()

    opened, fresh, later = run(go())
    assert opened == 1 and fresh == 15  # a session just opened already costs its minimum
    assert 50 <= later < 51  # max(50, 15), not 50 + 15


def test_create_is_refused_at_the_per_call_cap_without_asking_openai(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, max_live_minutes=30) as (client, ctl, log):
            ctl.ws = None
            log.voice_seconds = ctl.voice_base = 30 * 60
            ctl.http = FakeHttp()
            status, body = await ctl.create("v=0")
            return status, body["error"], ctl.http.sent, ctl.capped

    status, error, sent, capped = run(go())
    assert status == 429 and sent == []
    assert error == ("Live-minute cap for this call reached (30 min, $1.50). End the call, or start a new one "
                     "with a higher --max-live-minutes.")
    assert capped == error


def test_create_is_refused_at_the_daily_cap(tmp_path):
    talk.LEDGER_FILE.write_text(json.dumps({"date": today(), "call": "earlier", "session": "s0",
                                            "seconds": 120 * 60 - 15, "floor_seconds": 15, "usd": 6.0}) + "\n"
                                + json.dumps({"date": "2000-01-01", "call": "old", "session": "s9",
                                              "seconds": 9999, "floor_seconds": 15, "usd": 8.33}) + "\n")

    async def go():
        async with running_app(tmp_path, dormant_after=45, daily_live_minutes=120) as (client, ctl, log):
            ctl.ws = None
            ctl.http = FakeHttp()
            status, body = await ctl.create("v=0")
            return status, body["error"], ctl.http.sent

    status, error, sent = run(go())
    assert status == 429 and sent == []
    assert error == ("Daily live-minute cap reached (120 min, $6.00 today). Today's sessions are listed in "
                     f"{talk.LEDGER_FILE}; a wrong entry there can be corrected by hand.")


def test_only_todays_ledger_lines_count_against_the_daily_cap(tmp_path):
    talk.LEDGER_FILE.write_text(json.dumps({"date": "2000-01-01", "seconds": 99999, "floor_seconds": 15}) + "\n"
                                + "not json\n")

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            status, _ = await created(ctl)
            return status

    assert run(go()) == 201


def cap_hit(ctl, log):
    live(ctl, log)
    ctl.voice_marked_at = None
    log.voice_seconds = 30 * 60  # exactly at the cap
    ctl.opened = 1


def test_the_per_call_cap_while_live_says_one_line_then_goes_dormant(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, max_live_minutes=30) as (client, ctl, log):
            cap_hit(ctl, log)
            log.last_learner_speech = time.time()  # not quiet: only the cap may close the session
            ctl.last_output = 0.0
            ctl.cap_speech_wait = 0.05
            ticker = asyncio.create_task(ctl.tick())
            for _ in range(40):
                await asyncio.sleep(0.1)
                if "session.close" in events_of(ctl):
                    break
            ticker.cancel()
            sent = events_of(ctl)
            told = [e["content"] for e in ctl.ws.events if e["type"] == "session.instructions.append"]
            await ctl.on_event({"type": "session.closed", "reason": "client_closed"})
            ctl.sideband_ended()
            refused = ctl.wake({"text": "one more question", "start": 0.0, "end": 1.0})
            state = await (await client.get("/api/state", headers={"X-Talk-Token": "test-token"})).json()
            return sent, told, ctl.state, ctl.done.is_set(), refused, state["cap"]

    sent, told, state, done, refused, cap = run(go())
    assert sent == ["session.instructions.append", "session.close"]
    assert len(told) == 1 and "cap" in told[0]
    assert (state, done, refused) == ("dormant", False, False)
    assert cap.startswith("Live-minute cap for this call reached (30 min, $1.50).")


def test_a_meeting_at_the_cap_goes_dormant_without_a_word(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting", wake="name") as (client, ctl, log):
            cap_hit(ctl, log)
            ctl.state = "live"
            ctl.last_exchange = time.time()  # just asked: only the cap may close the session
            ctl.cap_speech_wait = 0.05
            ticker = asyncio.create_task(ctl.tick())
            for _ in range(40):
                await asyncio.sleep(0.1)
                if "session.close" in events_of(ctl):
                    break
            ticker.cancel()
            return events_of(ctl)

    assert run(go()) == ["session.close"]


def test_without_dormancy_the_cap_ends_the_call(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=0) as (client, ctl, log):
            cap_hit(ctl, log)
            ticker = asyncio.create_task(ctl.tick())
            await asyncio.sleep(0.8)
            ticker.cancel()
            return ctl.closing, log.end_reason

    assert run(go()) == (True, "reached the 30 min live-minute cap")


def test_a_session_closed_by_sleep_is_written_to_the_ledger(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.opened = 1
            task = asyncio.create_task(ctl.sleep(wait=2))
            await asyncio.sleep(0)
            await ctl.on_event({"type": "session.closed", "reason": "client_closed", "usage": {"seconds": 42}})
            ctl.sideband_ended()
            await task
            return ledger()

    (entry,) = run(go())
    assert entry["date"] == today() and entry["call"] == "out" and entry["session"] == "s1"
    assert entry["seconds"] == 42 and entry["floor_seconds"] == 0  # past the minimum: nothing added
    assert entry["usd"] == talk.cost_usd_of(42)


def test_a_discarded_session_is_written_to_the_ledger(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ws = None
            ctl.http = FakeHttp(on_post=ctl.done.set)  # End pressed while the POST is in flight
            await ctl.create("v=0")
            return ledger()

    (entry,) = run(go())
    assert (entry["session"], entry["seconds"], entry["floor_seconds"]) == ("s2", 0, 15)


def test_a_session_still_open_at_the_end_is_written_to_the_ledger_once(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.opened = 1
            log.voice_seconds = 30.0
            ctl.close_books()
            ctl.close_books()
            return ledger()

    (entry,) = run(go())
    assert (entry["session"], entry["seconds"]) == ("s1", 30.0)


def test_the_cost_view_carries_todays_total(tmp_path):
    talk.LEDGER_FILE.write_text(json.dumps({"date": today(), "seconds": 45, "floor_seconds": 15}) + "\n")

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            state = await (await client.get("/api/state", headers={"X-Talk-Token": "test-token"})).json()
            return state["cost"]["today_usd"]

    assert run(go()) == 0.05


def test_the_doctor_prints_todays_total_and_both_caps(tmp_path):
    talk.LEDGER_FILE.write_text(json.dumps({"date": today(), "seconds": 585, "floor_seconds": 15}) + "\n")
    lines = talk.caps_doctor_lines(SimpleNamespace(max_live_minutes=30, daily_live_minutes=120))
    assert lines == [
        "[--] live-minute caps: 30 min per call ($1.50), 120 min per day ($6.00); "
        f"today so far 10.0 min ($0.50), ledger {talk.LEDGER_FILE}",
    ]


# -- S1: first-run honesty -------------------------------------------------------------------------

NO_CREDIT = "OpenAI account has no credit — add credit at https://platform.openai.com/settings/organization/billing"
QUOTA = {"error": {"message": "You exceeded your current quota, please check your plan and billing details.",
                   "type": "insufficient_quota", "code": "insufficient_quota"}}


async def refused(ctl, http, woken=False):
    ctl.ws = None
    ctl.http = http
    ctl.run_sideband = lambda: asyncio.sleep(0)
    if woken:
        ctl.state = "dormant"
    status, body = await ctl.create("v=0")
    return status, body["error"], ctl.state


def test_no_credit_says_so_with_the_billing_link(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            return await refused(ctl, FakeHttp(status=429, body=QUOTA)), log.last_error

    (status, error, state), last_error = run(go())
    assert (status, error, state) == (429, NO_CREDIT, "live")
    assert "insufficient_quota" in last_error  # OpenAI's own words stay in the transcript


def test_a_rejected_key_says_which_key(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            return await refused(ctl, FakeHttp(status=401, body={"error": {"message": "Incorrect API key"}}))

    status, error, _ = run(go())
    assert status == 401
    assert error.startswith("OpenAI rejected the API key (HTTP 401)") and "OPENAI_API_KEY" in error


def test_a_server_error_with_an_html_body_is_reported_not_raised(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            return await refused(ctl, FakeHttp(status=502, body="<html><body>Bad gateway</body></html>"), woken=True)

    status, error, state = run(go())
    assert status == 502
    assert error == "OpenAI had a server error (HTTP 502); try again in a moment."
    assert state == "dormant"  # a wake goes back to listening


def test_a_create_that_times_out_is_reported_and_a_wake_goes_back_to_dormant(tmp_path):
    class Hanging(FakeHttp):
        def post(self, url, headers=None, json=None, **kwargs):
            self.kwargs = kwargs
            raise asyncio.TimeoutError()

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            http = Hanging()
            result = await refused(ctl, http, woken=True)
            return result, http.kwargs

    (status, error, state), kwargs = run(go())
    assert status == 504 and state == "dormant"
    assert error == f"OpenAI did not answer the session create within {talk.CREATE_TIMEOUT_S:g} s; try again."
    assert kwargs["timeout"].total == talk.CREATE_CEILING_S  # the POST itself runs on, to this ceiling


def test_a_session_that_arrives_after_its_create_timed_out_is_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "CREATE_TIMEOUT_S", 0.05)

    class Late(FakeHttp):
        def post(self, url, headers=None, json=None, **kwargs):
            outer = super().post(url, headers, json, **kwargs)

            class Slow:
                async def __aenter__(self):
                    await asyncio.sleep(0.3)  # OpenAI answers, but after the page was told it timed out
                    return outer

                async def __aexit__(self, *exc):
                    return False

            return Slow()

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ws = None
            ctl.http = Late(body={"session": {"id": "s9"}, "transport": {"sdp": "v=0"}})
            ctl.run_sideband = lambda: asyncio.sleep(0)
            status, body = await ctl.create("v=0")
            early = list(ctl.http.attached)
            await asyncio.sleep(0.5)
            await ctl.settle_closes(timeout=2)
            return (status, early, ctl.session_id, ctl.opened,
                    [(url, [e["type"] for e in ws.events]) for url, ws in ctl.http.attached], ledger())

    status, early, session_id, opened, attached, entries = run(go())
    assert status == 504 and early == []
    assert session_id is None and opened == 1  # never attached to the call, but billed
    assert attached == [(f"{talk.OPENAI_API.replace('https://', 'wss://')}/live/sessions/s9/attach", ["session.close"])]
    assert [e["session"] for e in entries] == ["s9"]


def test_the_doctor_says_credit_is_not_checked():
    assert talk.openai_doctor_line(200) == (
        True, "gpt-live-1 access (credit not checked — see https://platform.openai.com/settings/organization/billing)")
    passed, label = talk.openai_doctor_line(401)
    assert not passed and "HTTP 401" in label


# -- S2: the end-of-call cost ----------------------------------------------------------------------


def test_the_footer_counts_the_live_estimate_and_the_15_s_floor_and_links_the_real_bill(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.opened = 1
            ctl.voice_marked_at = time.time() - 50  # 50 s live, and no usage report yet
            ctl.close_books()
            return log.finish()

    summary = run(go())
    assert 49 <= summary["voice_seconds"] < 52
    assert summary["billed_seconds"] == round(summary["voice_seconds"], 1)  # past the 15 s minimum
    assert summary["cost_usd"] == talk.cost_usd_of(summary["billed_seconds"])
    saved = json.loads((tmp_path / "out" / "session.json").read_text())
    assert saved["cost_usd"] == summary["cost_usd"] and saved["sessions"] == 1
    footer = (tmp_path / "out" / "transcript.md").read_text().splitlines()[-1]
    assert "0m 50s GPT-Live" in footer or "0m 49s GPT-Live" in footer or "0m 51s GPT-Live" in footer
    assert "(1 session, each billed at least 15 s)" in footer and "billed as" not in footer
    assert f"${summary['cost_usd']:.2f}" in footer
    assert "https://platform.openai.com/usage" in footer


def test_short_sessions_are_billed_up_to_the_minimum_and_the_footer_says_so(tmp_path):
    log = talk.SessionLog(tmp_path / "out", "Test topic", "test")
    log.voice_seconds, log.floor_seconds, log.sessions = 8.0, 22.0, 2  # sessions of 5 s and 3 s
    summary = log.finish()
    assert summary["billed_seconds"] == 30.0 and summary["cost_usd"] == talk.cost_usd_of(30)
    footer = log.transcript.read_text().splitlines()[-1]
    assert "0m 8s GPT-Live, billed as 0m 30s (2 sessions, each billed at least 15 s)" in footer


def test_the_page_cost_counts_the_minimum_of_every_session(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            log.voice_seconds = ctl.voice_base = 60.0  # two sessions: 5 s and 55 s
            ctl.opened = 2
            ctl.record_session("a", 5.0)
            ctl.record_session("b", 55.0)
            return ctl.cost_view()

    view = run(go())
    assert view["voice_seconds"] == 70 and view["cost_usd"] == talk.cost_usd_of(70)


# -- I2: a long tool call, and a reply that arrives while the call sleeps --------------------------


def tool(ctl, phase, tool_name="Bash"):
    ctl.record_activity({"doorbell": True, "session_id": "brain"})
    ctl.record_activity({"session_id": "brain", "label": "Running tests", "tool": tool_name, "phase": phase})


def test_a_tool_call_still_running_keeps_the_turn_present(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            clock = [0.0]
            await collected(ctl, log, clock)
            clock[0] = 10
            tool(ctl, "start")
            clock[0] = 300  # one long tool call, nothing else
            running = ctl.brain_absent()
            clock[0] = 320
            tool(ctl, "end")
            clock[0] = 441
            after_end = ctl.brain_absent()
            return running, after_end

    assert run(go()) == (False, True)


def test_a_tool_call_running_for_ten_minutes_no_longer_holds_the_session(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            clock = [0.0]
            await collected(ctl, log, clock)
            clock[0] = 10
            tool(ctl, "start")  # a permission prompt nobody answers looks like this
            clock[0] = 10 + talk.RUNNING_TOOL_MAX_S + 1
            return ctl.brain_absent()

    assert run(go()) is True


def test_a_turn_that_sent_a_status_is_allowed_300_s(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            clock = [0.0]
            await collected(ctl, log, clock)
            clock[0] = 10
            await ctl.answer("d1", status="checking the code")
            clock[0] = 250
            early = ctl.brain_absent()
            clock[0] = 311
            return early, ctl.brain_absent()

    assert run(go()) == (False, True)


async def asleep_with_a_turn(ctl, log, **kw):
    """A turn the brain collected; then the call went dormant before the answer came."""
    clock = [0.0]
    await collected(ctl, log, clock)
    ctl.state = "dormant"
    ctl.forget_session()
    ctl.ws = None


def test_a_reply_that_arrives_while_the_call_sleeps_wakes_it_to_say_it(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            result = await ctl.answer("d1", text="The retry limit is three.")
            state = ctl.state
            await created(ctl)
            config = ctl.http.sent[0]["session"]["instructions"]
            await ctl.greet()
            return result, state, config, [e["content"] for e in ctl.ws.events
                                           if e["type"] == "session.instructions.append"]

    result, state, config, told = run(go())
    assert result == "held:waking" and state == "waking"
    assert "The retry limit is three." not in config  # said once: by the line below, not the instructions too
    assert told == [talk.HELD_REPLY_LINE.format(asker="the learner", reply="The retry limit is three.")]
    assert told[0].startswith("You were about to say this")


def test_wake_words_after_a_held_reply_ride_in_the_same_line_and_cannot_cut_it_off(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.attached.set()
            ctl.sessions = 2
            ctl.held_reply = "The retry limit is three."
            ctl.woke_with = {"text": "and what about timeouts", "start": 0.0, "end": 1.0}
            await ctl.greet()
            return [e["content"] for e in ctl.ws.events if e["type"] == "session.instructions.append"]

    (told,) = run(go())  # one instruction, not the reply followed by WAKE_LINE's "say nothing"
    assert told.index("The retry limit is three.") < told.index("and what about timeouts")
    assert told.lower().index("say nothing") > told.index("and what about timeouts")  # only once it is said


def test_a_status_while_the_call_sleeps_is_not_spoken_and_does_not_wake_it(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            return await ctl.answer("d1", status="checking the code"), ctl.state

    assert run(go()) == ("ignored", "dormant")


def test_a_reply_the_call_cannot_wake_for_is_refused_not_reported_sent(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            ctl.capped = talk.call_cap_message(30)
            resp = await client.post("/api/reply", headers={"X-Talk-Token": "test-token"},
                                     json={"id": "d1", "text": "The retry limit is three."})
            return resp.status, (await resp.json())["error"]

    status, error = run(go())
    assert status == 423
    assert "not said" in error and "Live-minute cap" in error


def test_the_client_says_a_reply_was_held_for_a_waking_call(tmp_path):
    import os
    import sys
    from helpers import SKILL_DIR

    state_file = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            state_file.write_text(json.dumps({"port": client.server.port, "token": "test-token", "out": "/tmp",
                                              "pid": 1}))
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(SKILL_DIR / "talk_client.py"), "reply", "d1",
                env={**os.environ, "TALK_STATE": str(state_file)},
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(b"The retry limit is three."), 15)
            return proc.returncode, out.decode()

    code, out = run(go())
    assert code == 0 and out.startswith("held: ")


# -- minor (b): a daily cap lifts at midnight --------------------------------------------------------


def capped_on(ctl, message, day):
    ctl.set_cap(message)
    ctl.capped_day = day
    ctl.state = "dormant"


def test_a_daily_cap_from_yesterday_no_longer_refuses_a_wake(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            capped_on(ctl, talk.daily_cap_message(120), "2000-01-01")
            woke = ctl.wake({"text": "one more thing", "start": 0.0, "end": 1.0})
            return woke, ctl.capped

    assert run(go()) == (True, None)


def test_a_daily_cap_from_today_still_refuses(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            capped_on(ctl, talk.daily_cap_message(120), today())
            return ctl.wake({"text": "one more thing", "start": 0.0, "end": 1.0})

    assert run(go()) is False


def test_a_per_call_cap_does_not_lift_at_midnight(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            capped_on(ctl, talk.call_cap_message(30), "2000-01-01")
            state = await (await client.get("/api/state", headers={"X-Talk-Token": "test-token"})).json()
            return ctl.wake({"text": "one more thing", "start": 0.0, "end": 1.0}), state["cap"] is not None

    assert run(go()) == (False, True)


# -- minor (c): a bad cap in the environment ---------------------------------------------------------


import pytest  # noqa: E402


@pytest.mark.parametrize("env", ["TALK_MAX_LIVE_MINUTES", "TALK_DAILY_LIVE_MINUTES"])
@pytest.mark.parametrize("value", ["thirty", "0", "-5", "nan"])
def test_a_bad_cap_in_the_environment_is_a_clear_usage_error(env, value, monkeypatch, capsys):
    monkeypatch.setenv(env, value)
    with pytest.raises(SystemExit) as exit_:
        talk.build_parser().parse_args(["--topic", "x"])
    err = capsys.readouterr().err
    assert exit_.value.code == 2
    assert env in err and repr(value) in err and "Traceback" not in err


def test_a_good_cap_in_the_environment_is_used(monkeypatch):
    monkeypatch.setenv("TALK_MAX_LIVE_MINUTES", "12.5")
    args = talk.build_parser().parse_args(["--topic", "x"])
    assert (args.max_live_minutes, args.daily_live_minutes) == (12.5, 120)


# -- Round 3: a held reply must not wake the call in a loop -----------------------------------------


async def page_answers_wakes(ctl, fail, rounds=3):
    """Play the page: whenever the server is waking, POST a session (billed), then fail it as `fail` does."""
    for _ in range(rounds):
        if ctl.state != "waking":
            break
        await created(ctl)
        sid = ctl.session_id
        await fail(ctl)
        ctl.sideband_ended(sid)  # GPT-Live confirms the close; the sideband ends
        await settle(ctl)


def test_a_held_reply_whose_session_the_page_cannot_use_wakes_once_not_in_a_loop(tmp_path):
    async def unusable(ctl):
        ctl.wake_failed("setRemoteDescription failed")
        await asyncio.sleep(0.05)

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            await ctl.answer("d1", text="The retry limit is three.")
            await page_answers_wakes(ctl, unusable)
            kept = ctl.held_reply
            ctl.hear({"text": "so what was it", "start": 0.0, "end": 1.0})  # the user wakes it
            return ctl.opened, kept, ctl.state

    opened, kept, state = run(go())
    assert opened == 1
    assert kept == "The retry limit is three."  # kept for the next wake the user starts
    assert state == "waking"


def test_a_held_reply_whose_session_never_starts_wakes_once_not_in_a_loop(tmp_path):
    async def never_starts(ctl):
        await asyncio.sleep(0.2)  # the start watchdog fires

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.start_timeout = 0.05
            await asleep_with_a_turn(ctl, log)
            await ctl.answer("d1", text="The retry limit is three.")
            await page_answers_wakes(ctl, never_starts)
            return ctl.opened, ctl.state, ctl.held_reply

    assert run(go()) == (1, "dormant", "The retry limit is three.")


# -- Round 3, minor 3: what `held` says is true ----------------------------------------------------


async def held_message(client):
    resp = await client.post("/api/reply", headers={"X-Talk-Token": "test-token"},
                             json={"id": "d1", "text": "The retry limit is three."})
    return (await resp.json())["held"]


def test_held_says_waking_only_when_a_wake_started(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            return await held_message(client), ctl.state

    assert run(go()) == ("the call was asleep; it is waking to say this", "waking")


def test_held_says_kept_when_no_wake_started(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            ctl.held_reply, ctl.held_autowoke = "An earlier answer.", True  # its one wake already failed
            return await held_message(client), ctl.state

    assert run(go()) == ("no session can say it now; it is kept for the next wake or rejoin", "dormant")


def test_held_says_connecting_while_a_session_is_attaching(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            ctl.state, ctl.session_id = "live", "s2"
            return await held_message(client)

    assert run(go()) == "the voice is connecting; it says this as soon as it is on"


# -- Round 3, minor 1: a wrap-up that arrives while no session can say it --------------------------


def test_a_wrap_up_while_dormant_ends_the_call_and_says_so(tmp_path):
    import os
    import sys
    from helpers import SKILL_DIR

    state_file = tmp_path / "state.json"

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            state_file.write_text(json.dumps({"port": client.server.port, "token": "test-token", "out": "/tmp",
                                              "pid": 1}))
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(SKILL_DIR / "talk_client.py"), "reply", "d1", "--end",
                env={**os.environ, "TALK_STATE": str(state_file)},
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, _ = await asyncio.wait_for(proc.communicate(b"We covered retries. Good session."), 15)
            await asyncio.sleep(0.1)
            return proc.returncode, out.decode(), ctl.done.is_set(), ctl.held_reply

    code, out, done, held = run(go())
    assert code == 0
    assert out.startswith("ended: the call was asleep; the wrap-up is only in the transcript")
    assert done and held is None


def test_a_wrap_up_while_connecting_is_said_by_the_session_then_the_call_closes(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            ctl.state, ctl.session_id = "live", "s2"  # a session created; its sideband not attached yet
            result = await ctl.answer("d1", text="We covered retries. Good session.", end=True)
            ctl.ws = talk_socket()
            ctl.attached.set()
            await ctl.greet()
            await asyncio.sleep(0)  # the close is a task of its own
            told = [e["content"] for e in ctl.ws.events if e["type"] == "session.instructions.append"]
            return result, told, ctl.closing, ctl.done.is_set()

    result, told, closing, done = run(go())
    assert result == "held:connecting"
    assert len(told) == 1 and "We covered retries. Good session." in told[0]
    assert closing and not done  # it closes after the wrap-up is spoken


# -- Round 3, minor 5: shutdown waits for creates in flight, then closes the books --------------------


class Slow(FakeHttp):
    """OpenAI answers the create after `delay` s."""

    def __init__(self, delay, **kw):
        super().__init__(**kw)
        self.delay = delay

    def post(self, url, headers=None, json=None, **kwargs):
        outer, delay = super().post(url, headers, json, **kwargs), self.delay

        class Late:
            async def __aenter__(self):
                await asyncio.sleep(delay)
                return outer

            async def __aexit__(self, *exc):
                return False

        return Late()


def test_shutdown_waits_for_a_create_still_under_its_timeout_and_closes_what_it_brings(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ws = None
            ctl.http = Slow(0.3, body={"session": {"id": "s7"}, "transport": {"sdp": "v=0"}})
            ctl.run_sideband = lambda: asyncio.sleep(0)
            pending = asyncio.create_task(ctl.create("v=0"))
            await asyncio.sleep(0.05)
            ctl.done.set()  # the call ends while the POST is in flight, well under 30 s
            await ctl.wind_down()
            attached = [(url, [e["type"] for e in ws.events]) for url, ws in ctl.http.attached]
            await pending
            return attached, log.sessions

    attached, sessions = run(go())
    assert [events for _, events in attached] == [["session.close"]]
    assert sessions == 1


def test_a_late_session_is_counted_in_the_footer(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "CREATE_TIMEOUT_S", 0.05)

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ws = None
            ctl.http = Slow(0.3, body={"session": {"id": "s8"}, "transport": {"sdp": "v=0"}})
            status, _ = await ctl.create("v=0")  # 504 to the page; the POST runs on
            await ctl.wind_down()
            return status, log.sessions, log.floor_seconds

    assert run(go()) == (504, 1, 15.0)


def test_the_refusal_names_the_cap_as_a_sentence():
    assert talk.dropped_reply_message(None) == "the call is asleep and cannot wake: it has ended. The reply was not said."
    cap = talk.call_cap_message(30)
    assert talk.dropped_reply_message(cap) == f"the call is asleep and cannot wake: {cap} The reply was not said."


# -- Round 4: the wake hand-off backstop waits for a held reply to be said --------------------------


def wake_offers(ctl):
    return sorted(i for i in ctl.turns.offered_ids if i.startswith("wake"))


def test_the_backstop_waits_for_a_long_held_reply_then_offers_the_words_once(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.wake_handoff_s, ctl.handoff_idle_s = 0.3, 0.2  # 4 s and 1.2 s, scaled down
            await asleep_with_a_turn(ctl, log)
            await ctl.answer("d1", text="A long answer. " * 40)
            await created(ctl)
            ctl.woke_with = {"text": "and what about timeouts", "start": 0.0, "end": 1.0}
            await ctl.greet()
            for _ in range(10):  # the voice speaks the held reply for 1 s, well past the plain 0.3 s
                await asyncio.sleep(0.1)
                await ctl.on_event({"type": "session.output_transcript.delta", "delta": "a long answer "})
            while_speaking = wake_offers(ctl)
            await asyncio.sleep(0.2 + 0.3 + 0.3)  # idle, then the plain wait, then some
            return while_speaking, wake_offers(ctl)

    while_speaking, after = run(go())
    assert while_speaking == []
    assert len(after) == 1


def test_a_wake_with_no_held_reply_keeps_the_plain_backstop(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.wake_handoff_s = 0.2
            await created(ctl)
            ctl.woke_with = {"text": "Nova, what is two plus two", "start": 0.0, "end": 1.0}
            await ctl.greet()
            await asyncio.sleep(0.35)
            return wake_offers(ctl)

    assert len(run(go())) == 1


# -- Round 4, minor 2: a held goodbye does not outlive its wake -------------------------------------


def test_a_goodbye_whose_wake_failed_does_not_hang_up_on_the_next_question(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            ctl.state = "waking"  # a wake in flight
            await ctl.answer("d1", text="We covered retries. Bye.", end=True)
            ctl.wake_failed("NotAllowedError: mic")  # that wake fails before its POST
            ctl.hear({"text": "hey tutor, one more question", "start": 0.0, "end": 1.0})  # later, the user
            await created(ctl)
            await ctl.greet()
            await asyncio.sleep(0)
            told = " ".join(e["content"] for e in ctl.ws.events if e["type"] == "session.instructions.append")
            return ctl.closing, "Bye." in told, "We covered retries. Bye." in log.transcript.read_text()

    closing, said_goodbye, in_transcript = run(go())
    assert not closing and not said_goodbye
    assert in_transcript



def test_a_goodbye_whose_session_never_started_does_not_hang_up_on_the_next_question(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.start_timeout = 0.05
            await asleep_with_a_turn(ctl, log)
            ctl.state = "waking"
            await ctl.answer("d1", text="We covered retries. Bye.", end=True)
            await created(ctl)
            sid = ctl.session_id
            await asyncio.sleep(0.2)  # the start watchdog abandons it
            ctl.sideband_ended(sid)
            await settle(ctl)
            ctl.hear({"text": "hey tutor, one more question", "start": 0.0, "end": 1.0})
            await created(ctl)
            await ctl.greet()
            await asyncio.sleep(0)
            told = " ".join(e["content"] for e in ctl.ws.events if e["type"] == "session.instructions.append")
            return ctl.closing, "Bye." in told

    assert run(go()) == (False, False)


# -- Round 4, minor 3: a reply never said is flagged at the end -------------------------------------


def test_a_held_reply_never_said_is_flagged_in_the_footer_and_the_end(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            ctl.held_autowoke = True  # its one wake already failed: it waits for the user
            long = "The retry limit is three, and here is why. " * 20
            await ctl.answer("d1", text=long)
            await ctl.answer("d1", text="That is all for today.", end=True)  # a dormant --end drops nothing silently
            ctl.hand_over_end()
            end = await ctl.turns.next(timeout=1)
            summary = log.finish()
            return long, end, summary, log.transcript.read_text()

    long, end, summary, transcript = run(go())
    assert end["type"] == "end" and end["unsaid"] == talk.speakable(long)
    assert summary["reply_not_said"] == talk.speakable(long)
    line = next(l for l in transcript.splitlines() if "Reply not said:" in l)
    assert line.startswith("_Reply not said: The retry limit is three") and line.endswith("…_")
    assert len(line) < 260


def test_a_call_with_nothing_unsaid_has_no_flag(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.hand_over_end()
            end = await ctl.turns.next(timeout=1)
            return end, log.finish(), log.transcript.read_text()

    end, summary, transcript = run(go())
    assert "unsaid" not in end and summary["reply_not_said"] is None and "Reply not said" not in transcript


# -- Round 4, minor 5: shutdown writes the ledger first, and a second signal cuts the wait short ------


def test_open_sessions_are_in_the_ledger_before_the_settle_wait(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ctl.opened = 1
            ctl.http = Slow(0.5, body={"session": {"id": "s7"}, "transport": {"sdp": "v=0"}})
            ctl.run_sideband = lambda: asyncio.sleep(0)
            ctl.session_id, ctl.ws = None, None
            pending = asyncio.create_task(ctl.create("v=0"))  # a create in flight keeps the settle waiting
            await asyncio.sleep(0.05)
            ctl.session_id = "s1"  # and a session still open
            ctl.done.set()
            winding = asyncio.create_task(ctl.wind_down())
            await asyncio.sleep(0.1)
            during = [e["session"] for e in ledger()]
            await winding
            await pending
            return during, sorted(e["session"] for e in ledger())

    during, after = run(go())
    assert during == ["s1"]
    assert after == ["s1", "s7"]  # each once


def test_a_hurried_wind_down_returns_at_once(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ws = None
            ctl.http = Slow(30, body={"session": {"id": "s7"}, "transport": {"sdp": "v=0"}})
            pending = asyncio.create_task(ctl.create("v=0"))
            await asyncio.sleep(0.05)
            hurry = asyncio.Event()
            asyncio.get_running_loop().call_later(0.1, hurry.set)
            started = time.monotonic()
            await ctl.wind_down(hurry=hurry)
            took = time.monotonic() - started
            pending.cancel()
            return took

    assert run(go()) < 1.0


SIGNAL_SCRIPT = r"""
import asyncio, os, signal, sys, time
sys.path[:0] = [sys.argv[1], sys.argv[2]]
from pathlib import Path
from helpers import running_app, talk
from test_billing import Slow
talk.LEDGER_FILE = Path(sys.argv[3]) / "ledger.jsonl"

async def main():
    async with running_app(Path(sys.argv[3]), dormant_after=45) as (client, ctl, log):
        ctl.ws = None
        ctl.http = Slow(30, body={"session": {"id": "s7"}, "transport": {"sdp": "v=0"}})
        pending = asyncio.create_task(ctl.create("v=0"))
        await asyncio.sleep(0.05)
        hurry = talk.hurry_on_signals(asyncio.get_running_loop())
        asyncio.get_running_loop().call_later(0.2, os.kill, os.getpid(), signal.SIGTERM)
        started = time.monotonic()
        await ctl.wind_down(hurry=hurry)
        print(f"took {time.monotonic() - started:.2f}")
        pending.cancel()

asyncio.run(main())
"""


def test_a_second_signal_during_the_settle_wait_ends_it_promptly(tmp_path):
    import subprocess
    import sys
    from helpers import SKILL_DIR

    script = tmp_path / "signal_probe.py"
    script.write_text(SIGNAL_SCRIPT)
    out = subprocess.run([sys.executable, str(script), str(SKILL_DIR / "tests"), str(SKILL_DIR), str(tmp_path)],
                         capture_output=True, text=True, timeout=20,
                         env={**__import__("os").environ, "XDG_DATA_HOME": str(tmp_path)})
    assert out.returncode == 0, out.stderr[-500:]
    assert float(out.stdout.split()[-1]) < 1.5


def test_a_pending_goodbye_is_flagged_when_the_call_ends_another_way(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            await asleep_with_a_turn(ctl, log)
            ctl.held_autowoke = True
            await ctl.answer("d1", text="The retry limit is three.")  # held, waiting for a wake
            ctl.state = "waking"
            await ctl.answer("d1", text="We covered retries. Bye.", end=True)  # held for that wake
            ctl.hand_over_end()  # Ctrl-C, the time limit: the call ends before any session says either
            end = await ctl.turns.next(timeout=1)
            return end.get("unsaid"), log.unsaid

    unsaid, logged = run(go())
    assert unsaid == logged == "The retry limit is three. We covered retries. Bye."
