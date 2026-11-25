"""Chains: a Claude Voice handover is one hub transaction; take and lists resolve to the head."""
import pytest

from index_testkit import fixture, hub, index_env, sid  # noqa: F401

import fleet_index_store as store  # noqa: E402


def voice(hub, s):
    return hub.start("main", s, {"kind": "voice", "name": "kitchen plans", "name_source": "topic",
                                 "topic": {"host": "prod", "id": "kitchen-plans"}}, writer="phone:prod")


def test_a_chain_is_one_transaction(hub, monkeypatch):
    voice(hub, sid(1))
    before = hub.row(sid(1))
    real = store._write_row
    calls = []

    def fail_on_second(con, row):
        calls.append(row["sid"])
        if len(calls) == 2:
            raise RuntimeError("the disk fell off")
        real(con, row)
    monkeypatch.setattr(store, "_write_row", fail_on_second)
    with pytest.raises(RuntimeError):
        store.chain(hub.con, sid(1), sid(2), "phone:prod", 1, {}, hub="main")
    monkeypatch.setattr(store, "_write_row", real)
    assert calls == [sid(1), sid(2)]
    assert hub.row(sid(1)) == before
    assert hub.row(sid(2)) is None


def test_take_refuses_a_superseded_sid_and_names_the_head(hub):
    voice(hub, sid(1))
    store.chain(hub.con, sid(1), sid(2), "phone:prod", 1, {"kind": "voice"}, hub="main")
    with pytest.raises(store.Refused) as e:
        hub.take(sid(1), "mac", 1, by="mac")
    assert e.value.code == "superseded"
    assert e.value.line == "session %s was continued as %s; take %s instead" % (sid(1), sid(2), sid(2))
    assert hub.take(sid(2), "mac", 1, by="mac")["epoch"] == 2


def test_the_handover_scenario(hub):
    sc = fixture("scenarios", "voice-handover-chain.json")
    req = sc[[k for k, v in sc["parts"].items() if v == "chain_request"][0]]
    voice(hub, req["old_sid"])
    reply = store.chain(hub.con, req["old_sid"], req["new_sid"], req["by"], req["expect_epoch"], req["fields"],
                        hub="main")
    old, new = reply["old"], reply["new"]
    assert (old["superseded_by"], old["end_reason"]) == (req["new_sid"], "handover")
    assert (new["continues"], new["conversation"], new["epoch"]) == (req["old_sid"], req["old_sid"], 1)
    assert store.head_of(hub.con, req["old_sid"]) == sc["expected"]["head"]
    assert new["conversation"] == sc["expected"]["conversation"]
    listed = store.list_rows(hub.con)
    assert [r["sid"] for r in listed] == sc["expected"]["rows_listed_by_default"]
    assert listed[0]["chain"] == [req["old_sid"], req["new_sid"]]
    assert {r["sid"] for r in store.list_rows(hub.con, chains="all")} == {req["old_sid"], req["new_sid"]}


def test_a_chain_links_a_new_row_its_journal_made_first_and_refuses_other_rows(hub):
    voice(hub, sid(3))
    voice(hub, sid(4))
    reply = store.chain(hub.con, sid(3), sid(4), "phone:prod", 1, {}, hub="main")
    assert reply["new"]["continues"] == sid(3)
    hub.start("mac", sid(5))
    voice(hub, sid(6))
    with pytest.raises(store.Refused) as e:
        store.chain(hub.con, sid(6), sid(5), "phone:prod", 1, {}, hub="main")
    assert e.value.code == "exists"
    for args, code in (((sid(3), sid(7), "phone:prod", 1), "superseded"), ((sid(6), sid(7), "mac", 1), "not-owner"),
                       ((sid(6), sid(7), "phone:prod", 2), "stale-epoch"), ((sid(9), sid(7), "phone:prod", 1),
                                                                            "no-session")):
        with pytest.raises(store.Refused) as e:
            store.chain(hub.con, *args, {}, hub="main")
        assert e.value.code == code
