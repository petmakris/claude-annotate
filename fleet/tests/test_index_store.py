"""The hub's store: lists, the legacy note, imports, deletes and the file's own protection."""
import os

import pytest

from index_testkit import hub, index_env, sid  # noqa: F401

import fleet_index_store as store  # noqa: E402


def test_the_store_is_private(hub, index_env):
    d = str(index_env / "fleet" / "index")
    assert os.stat(d).st_mode & 0o777 == 0o700
    assert os.stat(os.path.join(d, "hub.db")).st_mode & 0o777 == 0o600


def test_list_filters_by_words_kind_machine_and_owner_and_keeps_live_rows_past_the_limit(hub):
    hub.start("mac", sid(1), {"name": "fix the build"})
    hub.start("lat", sid(2), {"name": "plan the trip", "kind": "job"})
    hub.start("mac", sid(3), {"name": "old notes"})
    hub.apply("mac", hub.entry("mac", sid(1), "prompt", {"last_prompt": "run the tests",
                                                         "observed": {"live": True, "observed_at": 1.0}}))
    hub.apply("mac", hub.entry("mac", sid(3), "end", {"observed": {"live": False, "observed_at": 1.0}}))
    assert [r["sid"] for r in store.list_rows(hub.con, q="BUILD tests")] == [sid(1)]
    assert [r["sid"] for r in store.list_rows(hub.con, kinds=["job"])] == [sid(2)]
    assert {r["sid"] for r in store.list_rows(hub.con, machine="mac")} == {sid(1), sid(3)}
    assert [r["sid"] for r in store.list_rows(hub.con, owner="lat")] == [sid(2)]
    rows = store.list_rows(hub.con, limit=1)
    assert [r["sid"] for r in rows] == [sid(3), sid(1)]
    r = rows[1]
    assert (r["key"], r["head"], r["chain"], r["observed"]["source"], r["observed"]["stale"]) == (
        "mac:" + sid(1), True, [sid(1)], "journal", True)


def test_a_phone_writers_observed_values_never_turn_stale(hub):
    hub.start("main", sid(4), {"kind": "voice", "observed": {"live": True, "state": "idle", "observed_at": 1.0}},
              writer="phone:prod")
    assert store.list_rows(hub.con)[0]["observed"]["stale"] is False


def test_the_legacy_note_makes_a_row_writes_only_as_the_owner_and_keeps_a_name(hub):
    note = {"sid": sid(5), "machine": "mac", "name": "from the note", "last_prompt": "p", "last_answer": "a",
            "live": True, "kind": "chat"}
    row = store.apply_legacy_note(hub.con, note, machines=hub.machines)
    assert (row["owner"], row["epoch"], row["name"], row["name_source"]) == ("mac", 1, "from the note", "prompt")
    assert store.apply_legacy_note(hub.con, dict(note, machine="lat", last_prompt="no"), machines=hub.machines) is None
    store.apply_legacy_note(hub.con, dict(note, name="other", last_prompt="q"), machines=hub.machines)
    assert (hub.row(sid(5))["name"], hub.row(sid(5))["last_prompt"]) == ("from the note", "q")


def test_import_keeps_the_higher_epoch(hub):
    hub.start("mac", sid(6))
    hub.take(sid(6), "lat", 1)
    row = dict(hub.row(sid(6)))
    assert store.import_row(hub.con, dict(row, epoch=1, owner="mac"), origin="t") == "conflict-kept"
    assert store.import_row(hub.con, row, origin="t") == "same"
    assert store.import_row(hub.con, dict(row, epoch=3, owner="mac"), origin="t") == "updated"
    assert hub.row(sid(6))["owner"] == "mac"
    assert store.import_row(hub.con, dict(row, sid=sid(7)), origin="t") == "new"


def test_delete_refuses_a_conversation_that_has_not_ended(hub):
    hub.start("mac", sid(8))
    with pytest.raises(store.Refused) as e:
        store.delete_conversation(hub.con, sid(8))
    assert e.value.code == "not-ended"
    hub.apply("mac", hub.entry("mac", sid(8), "end", {}))
    assert store.delete_conversation(hub.con, sid(8)) == [sid(8)]
    assert hub.row(sid(8)) is None


def test_a_take_runs_in_one_transaction_against_a_second_connection(hub, index_env):
    hub.start("mac", sid(9))
    other = store.connect(str(index_env / "fleet" / "index" / "hub.db"))
    store.take(other, sid(9), "lat", 1, "lat", hub="main", machines=hub.machines)
    with pytest.raises(store.Refused) as e:
        hub.take(sid(9), "mac", 1)
    assert e.value.code == "stale-epoch"
    other.close()
