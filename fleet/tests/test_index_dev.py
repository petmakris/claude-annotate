"""Dev isolation: a sandbox's Claude Voice server takes only the sessions it made, and its rows hide by default."""
import pytest

from index_testkit import fixture, hub, index_env, sid  # noqa: F401

import fleet_index_store as store  # noqa: E402


def test_a_dev_hosts_take_of_a_prod_sid_is_refused(hub):
    sc = fixture("scenarios", "dev-take-prod.json")
    hub.start("mac", sid(1))
    before = hub.row(sid(1))
    for to, by in (("phone:dev:demo", "phone:dev:demo"), ("mac", "phone:dev:demo")):
        with pytest.raises(store.Refused) as e:
            store.take(hub.con, sid(1), to, 1, by, hub="main", machines=hub.machines)
        assert e.value.code == sc["expected"]["code"] == "dev-refused"
        assert e.value.line == "a Claude Voice sandbox takes only the sessions it made, and never gives one to phone:prod"
    assert hub.row(sid(1)) == before


def test_a_dev_row_is_never_given_to_phone_prod_and_its_own_server_may_take_it_back(hub):
    hub.start("main", sid(2), {"kind": "voice"}, writer="phone:dev:demo")
    assert (hub.row(sid(2))["env"], hub.row(sid(2))["kind"]) == ("dev:demo", "voice")
    hub.take(sid(2), "mac", 1, by="mac")
    with pytest.raises(store.Refused) as e:
        hub.take(sid(2), "phone:prod", 2, by="mac")
    assert e.value.code == "dev-refused"
    assert hub.take(sid(2), "phone:dev:demo", 2)["epoch"] == 3
    with pytest.raises(store.Refused):
        hub.take(sid(2), "mac", 3, by="phone:dev:other")


def test_dev_rows_hide_from_default_lists(hub):
    hub.start("main", sid(3), writer="phone:dev:demo")
    hub.start("mac", sid(4))
    assert [r["sid"] for r in store.list_rows(hub.con)] == [sid(4)]
    assert {r["sid"] for r in store.list_rows(hub.con, env="all")} == {sid(3), sid(4)}
    assert [r["sid"] for r in store.list_rows(hub.con, env="dev:demo")] == [sid(3)]


def test_a_phone_writer_off_the_hub_machine_is_invalid(hub):
    e = hub.entry("mac", sid(5), "start", {"kind": "voice"}, writer="phone:prod")
    assert hub.apply("mac", e)["results"][0]["outcome"] == "invalid"
    assert hub.row(sid(5)) is None


def test_end_host_ends_a_sandboxs_rows_and_refuses_prod_and_machines(hub):
    hub.start("main", sid(6), writer="phone:dev:demo")
    assert store.end_host(hub.con, "phone:dev:demo") == [sid(6)]
    assert (hub.row(sid(6))["end_reason"], hub.row(sid(6))["ended"] is not None) == ("sandbox-down", True)
    for owner in ("phone:prod", "mac"):
        with pytest.raises(store.Refused):
            store.end_host(hub.con, owner)
