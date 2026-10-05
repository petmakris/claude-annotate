import asyncio

import aiohttp
import pytest

from helpers import AUTH, TOKEN, FakeEar, running_app, talk


def run(coro):
    return asyncio.run(coro)


EAR = f"/api/ear?token={TOKEN}"


async def refused(client, path):
    with pytest.raises(aiohttp.WSServerHandshakeError) as err:
        await client.ws_connect(path)
    return err.value.status


def test_the_ear_needs_the_call_token(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ear, ctl.state = FakeEar(), "dormant"
            return await refused(client, "/api/ear"), await refused(client, "/api/ear?token=wrong")

    assert run(go()) == (403, 403)


def test_the_ear_is_refused_while_the_call_is_live(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ear = FakeEar()
            return await refused(client, EAR)

    assert run(go()) == 409


def test_the_ear_is_404_when_dormancy_is_off(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.state = "dormant"
            return await refused(client, EAR)

    assert run(go()) == 404


def test_frames_reach_the_ear_and_start_a_dormant_period(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            never_before = ctl.never_started
            ws = await client.ws_connect(EAR)
            await ws.send_bytes(b"\x01\x00" * 320)
            await ws.send_bytes(b"\x02\x00" * 320)
            for _ in range(50):
                if len(ctl.ear.frames) == 2:
                    break
                await asyncio.sleep(0.01)
            await ws.close()
            await asyncio.sleep(0.05)
            return never_before, ctl.never_started, ctl.ear.begun, ctl.ear.frames, ctl.ear.ended

    never_before, never_after, begun, frames, ended = run(go())
    assert (never_before, never_after, begun, ended) == (True, False, 1, 1)
    assert frames == [b"\x01\x00" * 320, b"\x02\x00" * 320]


def test_a_second_page_replaces_the_first_socket(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            first = await client.ws_connect(EAR)
            second = await client.ws_connect(EAR)
            msg = await asyncio.wait_for(first.receive(), 2)
            await second.send_bytes(b"\x05\x00" * 10)
            await asyncio.sleep(0.05)
            await second.close()
            return (msg.type, msg.data), ctl.ear.frames

    kind, frames = run(go())
    assert kind == (aiohttp.WSMsgType.CLOSE, talk.EAR_REPLACED)
    assert frames == [b"\x05\x00" * 10]


def test_a_wake_is_pushed_to_the_page_over_its_socket(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting", wake="name") as (client, ctl, log):
            ctl.ear = FakeEar()
            ws = await client.ws_connect(EAR)
            await asyncio.sleep(0.05)
            ctl.hear({"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
            msg = await asyncio.wait_for(ws.receive_json(), 2)
            await ws.close()
            return msg

    assert run(go()) == {"state": "waking"}


def test_a_page_that_closes_while_dormant_ends_the_call_after_the_rejoin_window(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "REJOIN_SECONDS", 0.05)

    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            ws = await client.ws_connect(EAR)
            await ws.close()
            await asyncio.wait_for(ctl.done.wait(), 2)
            return log.end_reason

    assert run(go()) == "page closed while dormant"


def test_a_page_that_comes_back_in_time_keeps_the_call(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "REJOIN_SECONDS", 0.2)

    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            await (await client.ws_connect(EAR)).close()
            await asyncio.sleep(0.05)
            again = await client.ws_connect(EAR)
            await asyncio.sleep(0.3)
            done = ctl.done.is_set()
            await again.close()
            return done

    assert run(go()) is False


def test_state_tells_the_page_the_dormant_state_and_what_was_heard(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting", wake="name") as (client, ctl, log):
            ctl.ear = FakeEar()
            ctl.hear({"text": "we should lower it", "start": 0.0, "end": 1.0})
            return await (await client.get("/api/state", headers=AUTH)).json()

    state = run(go())
    assert (state["state"], state["heard"], state["ear"], state["wake_name"]) == (
        "dormant", ["we should lower it"], "ready", "Nova")


def test_the_state_carries_why_local_listening_failed(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting", wake="name") as (client, ctl, log):
            ctl.ear = FakeEar()
            ctl.ear.status, ctl.ear.error = "failed", "no metal device"
            return await (await client.get("/api/state", headers=AUTH)).json()

    state = run(go())
    assert (state["ear"], state["ear_error"]) == ("failed", "no metal device")
