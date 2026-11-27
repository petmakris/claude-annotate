"""`fleet _deliver-session` and `fleet _session-state`: a local service (webcompanion) wakes the session that
opened a page by its session id, through the same delivery and redelivery as a tell."""
import io
import json

import pytest

from fleet_testkit import fleet, world  # noqa: F401
from test_fleet_control import rejoin_as
from test_fleet_messaging import two


def service(world, who, verb, payload=None, *argv):
    """Run an internal verb from outside any session (the daemon has none), JSON on stdin."""
    world.mp.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    world.mp.delenv("CLAUDE_CODE_MESSAGING_SOCKET", raising=False)
    world.mp.setattr("sys.stdin", io.StringIO(json.dumps(payload or {})))
    world.capsys.readouterr()
    code = fleet.main([verb] + list(argv))
    out = world.capsys.readouterr()
    return code, out.out, out.err


def test_a_service_wakes_a_member_by_its_session_id(world):
    a, b = two(world)
    code, out, err = service(world, None, "_deliver-session",
                             {"session": b.sid, "sender": "webcompanion",
                              "body": "WEBCOMPANION_EVENT skill=walkthrough sid=s1 event_id=e1"})
    assert code in (0, None), err
    res = json.loads(out)
    assert res["state"] == "delivered" and res["name"] == "beta"
    [line] = b.messages()
    content = line["message"]["content"]
    assert ("\nFleet tell %d from webcompanion: WEBCOMPANION_EVENT skill=walkthrough sid=s1 "
                              "event_id=e1" % res["id"]) in content
    assert "/fleet ack %d" % res["id"] in content
    assert a.messages() == []


def test_a_message_for_a_session_that_is_not_running_waits_and_reaches_it_when_it_joins_again(world):
    a, b = two(world)
    b.die()
    code, out, _ = service(world, None, "_deliver-session",
                           {"session": b.sid, "sender": "webcompanion", "body": "WEBCOMPANION_EVENT x"})
    res = json.loads(out)
    assert res["state"] == "waiting" and b.messages() == []
    new = rejoin_as(world, "beta")
    [line] = new.messages()
    assert "Fleet tell %d from webcompanion: WEBCOMPANION_EVENT x" % res["id"] in line["message"]["content"]


def test_a_session_that_never_joined_is_refused_with_how_to_fix_it(world):
    two(world)
    code, out, err = service(world, None, "_deliver-session",
                             {"session": "no-such-session", "sender": "webcompanion", "body": "x"})
    assert code not in (0, None) and "never joined the fleet" in err and "fleet join" in err


@pytest.mark.parametrize("sender", ["", "petros", "Web Companion", "a"])
def test_the_sender_must_be_a_service_name(world, sender):
    _, b = two(world)
    code, _, err = service(world, None, "_deliver-session", {"session": b.sid, "sender": sender, "body": "x"})
    assert code not in (0, None) and "service name" in err
    assert b.messages() == []


def test_session_state_says_whether_a_tell_would_reach_a_running_session(world):
    _, b = two(world)
    assert json.loads(service(world, None, "_session-state", None, b.sid)[1]) == \
        {"member": True, "name": "beta", "alive": True}
    b.die()
    assert json.loads(service(world, None, "_session-state", None, b.sid)[1])["alive"] is False
    assert json.loads(service(world, None, "_session-state", None, "nobody")[1]) == \
        {"member": False, "name": None, "alive": False}
