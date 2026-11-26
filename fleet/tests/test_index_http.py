"""The service routes: loopback, a loopback Host, a Bearer token and a JSON body, never a cookie."""
import json

from index_testkit import hub, index_env, sid  # noqa: F401

import fleet_index_http as http  # noqa: E402
import fleet_index_store as store  # noqa: E402

TOKEN = "t" * 32
OK = {"Host": "127.0.0.1:8797", "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"}


def call(method, path, body=None, headers=OK, bound="127.0.0.1", query=None):
    raw = json.dumps(body).encode() if body is not None else b""
    return http.handle(method, path, query or {}, raw, headers, bound, TOKEN)


def test_the_guard_refuses_a_wide_bind_a_foreign_host_a_cookie_and_a_wrong_token(index_env):
    assert call("POST", "/api/session/take", {}, bound="0.0.0.0")[0] == 403
    assert call("POST", "/api/session/take", {}, headers=dict(OK, Host="evil.example"))[0] == 403
    cookie = {"Host": "127.0.0.1", "Cookie": "fleet_ui=" + TOKEN, "Content-Type": "application/json"}
    assert call("POST", "/api/session/take", {}, headers=cookie)[0] == 401
    assert call("POST", "/api/session/take", {}, headers=dict(OK, Authorization="Bearer nope"))[0] == 401
    assert call("POST", "/api/session/take", {}, headers=dict(OK, **{"Content-Type": "text/plain"}))[0] == 415


def test_take_owner_journal_and_end_host_through_the_routes(hub, index_env):
    status, reply = call("POST", "/api/session/journal", {"sid": sid(1), "event": "start", "as": "phone:prod",
                                                          "fields": {"kind": "voice", "name": "kitchen",
                                                                     "name_source": "topic"}})
    assert (status, reply["result"]["outcome"], reply["row"]["owner"]) == (200, "applied", "phone:prod")
    status, reply = call("GET", "/api/session/owner", query={"sid": [sid(1)]})
    assert (status, reply) == (200, {"sid": sid(1), "owner": "phone:prod", "epoch": 1, "head": sid(1),
                                     "source": "hub", "stale": False})
    status, reply = call("POST", "/api/session/take", {"sid": sid(1), "to": "phone:dev:demo", "expect_epoch": 1,
                                                       "by": "phone:dev:demo"})
    assert (status, reply["code"]) == (409, "dev-refused")
    status, reply = call("POST", "/api/session/journal", {"sid": sid(2), "event": "start", "as": "phone:dev:demo",
                                                          "fields": {}})
    assert status == 200
    status, reply = call("POST", "/api/session/end-host", {"owner": "phone:dev:demo"})
    assert (status, reply["ended"]) == (200, [sid(2)])
    assert call("POST", "/api/session/journal", {"sid": sid(3), "event": "start", "as": "lat", "fields": {}})[0] == 400
    assert store.get_row(hub.con, sid(3)) is None
