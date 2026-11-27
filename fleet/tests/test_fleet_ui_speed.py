"""The page server never waits on a slow or sleeping machine twice: its answers are stale while they refresh, one
lock per endpoint, and a machine that did not answer is skipped for DOWN_TTL seconds."""
import threading
import time

import pytest

from fleet_testkit import fleet


def test_a_slow_endpoint_never_holds_another_one():
    cache, gate = fleet.Cache(ttl=60), threading.Event()
    slow = threading.Thread(target=cache.get, args=("/api/threads", lambda: gate.wait(10) and "threads"), daemon=True)
    slow.start()
    time.sleep(0.1)  # the slow fetch now holds its own lock
    t0 = time.time()
    assert cache.get("/api/machines", lambda: "machines") == "machines"
    assert time.time() - t0 < 1
    gate.set()
    slow.join(5)


def test_a_stale_answer_comes_back_at_once_and_is_refreshed_behind_it():
    cache, gate, asked = fleet.Cache(ttl=0.05), threading.Event(), []
    assert cache.get("/api/members", lambda: "old") == "old"
    time.sleep(0.1)

    def fresh():
        asked.append(1)
        gate.wait(10)
        return "new"
    t0 = time.time()
    assert cache.get("/api/members", fresh) == "old"
    assert cache.get("/api/members", fresh) == "old"
    assert time.time() - t0 < 1
    gate.set()
    deadline = time.time() + 5
    while cache.get("/api/members", lambda: "never") != "new" and time.time() < deadline:
        time.sleep(0.02)
    assert cache.items["/api/members"][1] == "new"
    assert asked == [1]  # one refresh at a time per endpoint


@pytest.fixture
def lat(monkeypatch):
    calls = []

    def unreachable(m, args, stdin, timeout):
        calls.append(m["ssh"])
        raise fleet.RemoteError("ssh: connect to host lat port 22: Operation timed out", unreachable=True)
    monkeypatch.setattr(fleet, "other_machines", lambda: {"lat": {"ssh": "lat", "fleet": "/x", "python": "python3"}})
    monkeypatch.setattr(fleet, "_run_remote", unreachable)
    fleet.remember_down()
    yield calls
    fleet.remember_down(False)


def test_a_machine_that_did_not_answer_is_skipped_until_down_ttl_passes(lat, monkeypatch):
    for _ in range(3):
        with pytest.raises(fleet.RemoteError) as e:
            fleet.run_remote("lat", ["ls"])
        assert e.value.unreachable
    assert lat == ["lat"]
    assert "Operation timed out, 0 s ago; asked again after 30 s" in str(e.value)
    monkeypatch.setattr(fleet, "DOWN_TTL", 0)
    with pytest.raises(fleet.RemoteError):
        fleet.run_remote("lat", ["ls"])
    assert lat == ["lat", "lat"]


def test_outside_the_page_server_every_call_asks_the_machine(lat):
    fleet.remember_down(False)
    for _ in range(2):
        with pytest.raises(fleet.RemoteError):
            fleet.run_remote("lat", ["ls"])
    assert lat == ["lat", "lat"]
