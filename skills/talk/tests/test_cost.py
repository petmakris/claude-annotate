"""What a call costs: GPT-Live seconds are billed, dormant time is free, and the brain (in
--llm session mode) runs on the user's Claude subscription. See talk-10-brief for the rules."""
import asyncio
import json

from helpers import AUTH, running_app, talk
from test_dormant import FakeHttp, live, sleep_through


def run(coro):
    return asyncio.run(coro)


class Clock:
    """A controllable stand-in for time.time(), so cost math can be tested without real waits."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def tick(self, seconds):
        self.now += seconds


def test_a_live_session_reported_at_60s_costs_a_nickel(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await ctl.on_event({"type": "session.usage.updated", "usage": {"seconds": 60}})
            return ctl.cost_view()

    view = run(go())
    assert view["voice_seconds"] >= 60
    assert view["cost_usd"] == 0.05


def test_the_estimate_grows_with_the_clock_and_a_lower_report_never_drops_it(tmp_path, monkeypatch):
    clock = Clock(1000.0)
    monkeypatch.setattr(talk.time, "time", clock)

    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await ctl.on_event({"type": "session.usage.updated", "usage": {"seconds": 60}})
            first = ctl.cost_view()["voice_seconds"]
            clock.tick(10)
            grown = ctl.cost_view()["voice_seconds"]
            # A report that arrives lower than the running estimate (65 < 70) must not pull it back down.
            await ctl.on_event({"type": "session.usage.updated", "usage": {"seconds": 65}})
            after_low_report = ctl.cost_view()["voice_seconds"]
            return first, grown, after_low_report

    first, grown, after_low_report = run(go())
    assert first == 60
    assert grown == 70
    assert after_low_report == 70


def test_dormant_time_accumulates_between_rest_and_wake_while_voice_seconds_holds_still(tmp_path, monkeypatch):
    clock = Clock(1000.0)
    monkeypatch.setattr(talk.time, "time", clock)

    async def go():
        async with running_app(tmp_path, dormant_after=45, wake="name") as (client, ctl, log):
            live(ctl, log)
            log.voice_seconds = 42.0
            await sleep_through(ctl)  # live -> dormant, via rest()
            before_voice = ctl.cost_view()["voice_seconds"]
            clock.tick(30)
            ctl.wake()  # dormant -> waking
            return ctl.dormant_seconds_total(), before_voice, ctl.cost_view()["voice_seconds"]

    dormant_seconds, before_voice, after_voice = run(go())
    assert dormant_seconds == 30
    assert before_voice == 42.0
    assert after_voice == 42.0


def test_a_meeting_counts_its_opening_dormant_stretch(tmp_path, monkeypatch):
    clock = Clock(1000.0)
    monkeypatch.setattr(talk.time, "time", clock)

    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting", wake="name") as (client, ctl, log):
            start_state = ctl.state
            clock.tick(15)
            return start_state, ctl.dormant_seconds_total()

    state, dormant_seconds = run(go())
    assert state == "dormant"
    assert dormant_seconds == 15


def test_api_state_includes_the_cost_view_with_its_four_keys(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            state = await (await client.get("/api/state", headers=AUTH)).json()
            return state["cost"]

    cost = run(go())
    assert set(cost) == {"voice_seconds", "dormant_seconds", "cost_usd", "today_usd"}


def test_finish_writes_cost_and_dormant_into_the_summary_and_footer(tmp_path):
    log = talk.SessionLog(tmp_path / "out", "Test topic", "test")
    log.voice_seconds = 192.0  # 3m 12s
    log.dormant_seconds = 840.0  # 14m

    summary = log.finish()

    assert summary["cost_usd"] == 0.16
    assert summary["dormant_seconds"] == 840.0
    saved = json.loads((tmp_path / "out" / "session.json").read_text())
    assert saved["cost_usd"] == 0.16
    assert saved["dormant_seconds"] == 840.0
    footer = log.transcript.read_text()
    assert "3m 12s GPT-Live" in footer
    assert "$0.16" in footer
    assert "14m asleep (free)" in footer


def test_finish_hides_the_asleep_clause_below_a_whole_minute(tmp_path):
    log = talk.SessionLog(tmp_path / "out", "Test topic", "test")
    log.voice_seconds = 10.0
    log.dormant_seconds = 45.0  # under a minute: never "asleep 0m"

    log.finish()

    assert "asleep" not in log.transcript.read_text()


def test_wake_now_stops_the_dormant_clock_the_moment_create_succeeds_not_at_a_later_wake(tmp_path, monkeypatch):
    """"Wake now" can call create() straight from a dormant call, with no wake() in between (it does not
    go through wake() at all: see test_wake_now_is_a_visible_button_that_starts_a_wake in test_browser_dormant)."""
    clock = Clock(1000.0)
    monkeypatch.setattr(talk.time, "time", clock)

    async def go():
        async with running_app(tmp_path, dormant_after=45, wake="name") as (client, ctl, log):
            ctl.state = "dormant"
            ctl.dormant_started = clock.now  # a stretch already open, as rest() or a meeting's start left it
            ctl.http = FakeHttp()
            ctl.run_sideband = lambda: asyncio.sleep(0)
            clock.tick(12)  # dormant time passes before "Wake now" is pressed
            status, _ = await ctl.create("v=0")
            at_create = ctl.dormant_seconds_total()
            clock.tick(20)  # time passes after the call is live
            return status, at_create, ctl.dormant_seconds_total()

    status, at_create, later = run(go())
    assert status == 201
    assert at_create == 12
    assert later == 12  # the clock stopped counting the moment create() went live


def test_a_failed_create_from_dormant_leaves_the_stretch_running(tmp_path, monkeypatch):
    clock = Clock(1000.0)
    monkeypatch.setattr(talk.time, "time", clock)

    async def go():
        async with running_app(tmp_path, dormant_after=45, wake="name") as (client, ctl, log):
            ctl.state = "dormant"
            ctl.dormant_started = clock.now
            ctl.http = FakeHttp(status=429, body={"error": {"message": "insufficient_quota"}})
            ctl.run_sideband = lambda: asyncio.sleep(0)
            clock.tick(8)
            status, _ = await ctl.create("v=0")
            clock.tick(5)  # still dormant: the stretch was never interrupted
            return status, ctl.state, ctl.dormant_seconds_total()

    status, state, dormant_seconds = run(go())
    assert status == 429
    assert state == "dormant"
    assert dormant_seconds == 13
