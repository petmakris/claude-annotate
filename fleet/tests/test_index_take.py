"""Take: the only call that changes owner and epoch, a compare-and-set on (sid, epoch) on the hub."""
import os

import pytest

from index_testkit import fixture, hub, index_env, sid  # noqa: F401

import fleet_index_store as store  # noqa: E402


def test_take_counts_epochs_1_2_3_across_mac_phone_lat_and_refuses_a_stale_epoch(hub):
    s = sid(1)
    assert hub.start("mac", s)["epoch"] == 1
    r1 = hub.take(s, "phone:prod", 1)
    r2 = hub.take(s, "lat", 2)
    assert [(r1["previous_owner"], r1["owner"], r1["epoch"]), (r2["previous_owner"], r2["owner"], r2["epoch"])] == [
        ("mac", "phone:prod", 2), ("phone:prod", "lat", 3)]
    row = hub.row(s)
    assert (row["owner"], row["epoch"], row["machine"]) == ("lat", 3, "lat")
    with pytest.raises(store.Refused) as e:
        hub.take(s, "mac", 2)
    assert e.value.code == "stale-epoch"
    assert e.value.line == "session %s moved meanwhile (epoch 3, expected 2); read it again" % s
    assert (hub.row(s)["owner"], hub.row(s)["epoch"]) == ("lat", 3)


def test_a_phone_owner_puts_the_row_on_the_hub_machine(hub):
    hub.start("mac", sid(2))
    hub.take(sid(2), "phone:prod", 1)
    assert hub.row(sid(2))["machine"] == "main"


def test_the_take_chain_scenario(hub):
    sc = fixture("scenarios", "take-chain.json")
    s = sc["row_1"]["sid"]
    hub.machines |= {"laptop", "spare"}
    hub.start("laptop", s)
    got = []
    for t in (sc["take_1"], sc["take_2"]):
        got.append(store.take(hub.con, t["sid"], t["to"], t["expect_epoch"], t["by"], hub="main",
                              machines=hub.machines)["epoch"])
    assert [1] + got == sc["expected"]["epochs"]
    with pytest.raises(store.Refused) as e:
        st = sc["stale_take"]
        store.take(hub.con, st["sid"], st["to"], st["expect_epoch"], st["by"], hub="main", machines=hub.machines)
    assert (e.value.code, e.value.line) == (sc["stale_reply"]["code"], sc["stale_reply"]["error"])


def test_take_to_the_owner_is_ok_and_changes_nothing(hub):
    hub.start("mac", sid(3))
    r = hub.take(sid(3), "mac", 1)
    assert (r["ok"], r["epoch"], hub.row(sid(3))["epoch"]) == (True, 1, 1)


@pytest.mark.parametrize("kind,code", [("job", "job"), ("worker", "job")])
def test_take_refuses_jobs_and_workers(hub, kind, code):
    hub.start("mac", sid(4), {"kind": kind})
    with pytest.raises(store.Refused) as e:
        hub.take(sid(4), "lat", 1)
    assert e.value.code == code
    assert e.value.line == "session %s is a %s: it can be read, never taken" % (sid(4), kind)


def test_take_refuses_a_work_row_a_missing_row_and_an_unknown_owner(hub):
    hub.start("mac", sid(5), {"work": True})
    for args, code in (((sid(5), "lat", 1), "work"), ((sid(6), "lat", 1), "no-session"),
                       ((sid(5), "nowhere", 1), "bad-request")):
        with pytest.raises(store.Refused) as e:
            hub.take(*args)
        assert e.value.code == code


def test_every_take_backs_the_store_up_and_keeps_the_20_newest(hub, index_env):
    hub.start("mac", sid(7))
    owners = ["lat", "mac"] * 11
    for i, o in enumerate(owners):
        hub.take(sid(7), o, i + 1)
    files = sorted(os.listdir(str(index_env / "backups")))
    assert len(files) == 20
    assert any(f.endswith("-0a1b2c3d-e23.db") for f in files)
    assert not any(f.endswith("-0a1b2c3d-e2.db") for f in files)
