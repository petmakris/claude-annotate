"""The registry shim (fleet_registry_shim.py): registry files written on the hub as a view of the index, one writer
per field, and Claude Voice's own patches read back into the index when a file changes (contract section 12.2).

The store's callbacks are called by hand here (`after_change`, `ingest_phone_rows`), as the store would after a
change and before a read, so nothing global is left registered between tests.
"""
import json
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_index_import import IndexWorld, SID_A, SID_B, SID_C, record  # noqa: E402

PATCH = {"topic": {"host": "prod", "id": "kitchen"}, "live": True, "last_prompt": "and the fridge",
         "last_answer": "It fits too.", "updated": "2026-11-25T12:00:00+00:00"}


@pytest.fixture
def iw(tmp_path, monkeypatch):
    import fleet_index_import
    w = IndexWorld(str(tmp_path), monkeypatch)
    m = w["main"]
    m.put_record(record(SID_A, owner="main", epoch=1))
    m.put_record(record(SID_B, owner="phone:prod", epoch=2, topic={"host": "prod", "id": "kitchen"},
                        name="kitchen plans", last_prompt="what about the oven", last_answer="The oven fits."))
    assert fleet_index_import.main(["import", "--machine", "main", "--backup-dir", os.path.join(w.base, "bk")]) == 0
    yield w
    monkeypatch.undo()
    time.tzset()


def voice_patch(path, fields):
    """Claude Voice's Registry.patch: read the file, spread the fields over it, write by rename."""
    with open(path) as f:
        raw = json.load(f)
    raw.update(fields)
    tmp = path + ".%d.tmp" % os.getpid()
    with open(tmp, "w") as f:
        f.write(json.dumps(raw) + "\n")
    os.replace(tmp, path)


def read(iw, sid):
    with open(os.path.join(iw.hub.registry, sid + ".json")) as f:
        return json.load(f)


def change(iw, fn, *sids):
    import fleet_index_store
    import fleet_registry_shim as shim
    con = iw.con()
    try:
        fn(fleet_index_store, con)
        shim.after_change(con, list(sids))
    finally:
        con.close()


def test_a_voice_patch_on_a_phone_row_survives_the_next_shim_write(iw):
    voice_patch(os.path.join(iw.hub.registry, SID_B + ".json"), PATCH)
    change(iw, lambda store, con: store.rename(con, SID_B, "kitchen and fridge"), SID_B)
    got = read(iw, SID_B)
    assert {k: got[k] for k in PATCH} == PATCH
    assert (got["name"], got["owner"], got["epoch"]) == ("kitchen and fridge", "phone:prod", 2)
    row = iw.rows()[SID_B]
    assert (row["last_prompt"], row["last_answer"], row["topic"]) == \
        ("and the fridge", "It fits too.", {"host": "prod", "id": "kitchen"})


def test_a_voice_patch_is_read_before_a_list_and_only_when_the_file_changed(iw):
    import fleet_index_journal
    import fleet_registry_shim as shim
    voice_patch(os.path.join(iw.hub.registry, SID_B + ".json"), PATCH)
    con = iw.con()
    try:
        assert shim.ingest_phone_rows(con) == 1
        entries = fleet_index_journal.pending(iw.hub.home)
        assert shim.ingest_phone_rows(con) == 0  # the same file again: nothing read, nothing journaled
    finally:
        con.close()
    assert entries == []  # flushed in process: the hub applied it at once
    lines = open(os.path.join(iw.hub.home, "index", "journal.jsonl")).read().splitlines()
    e = json.loads(lines[-1])
    assert (len(lines), e["machine"], e["as"], e["sid"], e["epoch_seen"], e["event"]) == \
        (1, "main", "phone:prod", SID_B, 2, "stop")
    assert {k: v for k, v in e["fields"].items() if k != "observed"} == \
        {"last_prompt": "and the fridge", "last_answer": "It fits too."}
    assert iw.rows()[SID_B]["last_prompt"] == "and the fridge"
    assert {k: read(iw, SID_B)[k] for k in PATCH} == PATCH


def test_a_file_that_disagrees_on_the_owner_is_written_again(iw):
    path = os.path.join(iw.hub.registry, SID_B + ".json")
    voice_patch(path, dict(PATCH, owner="mac", epoch=7))
    import fleet_registry_shim as shim
    con = iw.con()
    try:
        shim.ingest_phone_rows(con)
    finally:
        con.close()
    got = read(iw, SID_B)
    assert (got["owner"], got["epoch"]) == ("phone:prod", 2)
    assert {k: got[k] for k in PATCH} == PATCH


def test_a_take_moves_the_file_and_the_shim_then_writes_the_voice_fields(iw):
    voice_patch(os.path.join(iw.hub.registry, SID_B + ".json"), PATCH)
    change(iw, lambda store, con: store.take(con, SID_B, "mac", 2, "mac", hub="main",
                                             machines={"main", "mac", "lat"}, now=1795100000.0), SID_B)
    got = read(iw, SID_B)
    assert (got["owner"], got["epoch"], got["machine"]) == ("mac", 3, "mac")
    assert got["owner_since"] == "2026-11-19T14:53:20+00:00"
    # The patch was read in before the take's write, so a machine owner's file carries Voice's last words.
    assert (got["last_prompt"], got["last_answer"]) == ("and the fridge", "It fits too.")


def test_env_fields_the_index_did_not_change_are_left_alone(iw):
    path = os.path.join(iw.hub.registry, SID_A + ".json")
    voice_patch(path, {"last_prompt": "written by env on the hub", "account": "me"})
    change(iw, lambda store, con: store.rename(con, SID_A, "build fix"), SID_A)
    got = read(iw, SID_A)
    assert (got["name"], got["last_prompt"]) == ("build fix", "written by env on the hub")


@pytest.mark.parametrize("what,fields", [
    ("work", {"work": True, "cwd": None, "account": None, "first_prompt": None, "last_prompt": None,
              "last_answer": None, "name": "", "name_source": ""}),
    ("dev", {"env": "dev:x", "owner": "phone:dev:x"}),
    ("worker", {"kind": "worker"}),
    ("voice", {"kind": "voice"}),
    ("superseded", {"superseded_by": SID_A}),
    ("nameless", {"name": "", "name_source": ""}),
])
def test_the_shim_writes_no_file_for_a_row_the_registry_never_held(iw, what, fields):
    import fleet_index_store
    import fleet_registry_shim as shim
    if not hasattr(fleet_index_store, "_put"):
        pytest.skip("the real store has no test writer")
    row = dict(iw.rows()[SID_A], sid=SID_C, conversation=SID_C, **fields)
    con = iw.con()
    try:
        fleet_index_store._put(con, row)
        shim.after_change(con, [SID_C])
    finally:
        con.close()
    assert not os.path.exists(os.path.join(iw.hub.registry, SID_C + ".json"))


def test_a_new_file_is_whole_and_named_by_its_first_prompt(iw):
    import fleet_index_store
    import fleet_registry_shim as shim
    if not hasattr(fleet_index_store, "_put"):
        pytest.skip("the real store has no test writer")
    row = dict(iw.rows()[SID_A], sid=SID_C, conversation=SID_C, name="Tidy the notes", name_source="ai",
               first_prompt="please tidy up all of my notes folder and drop the stale drafts from last year too",
               ended=None, updated=1795000000.0, owner_since=1794990000.0)
    con = iw.con()
    try:
        fleet_index_store._put(con, row)
        shim.after_change(con, [SID_C])
    finally:
        con.close()
    assert read(iw, SID_C) == {
        "version": 1, "sid": SID_C, "name": "please tidy up all of my notes folder and drop the stale dr…",
        "machine": "main", "account": "me", "cwd": "/home/me/projects/app", "last_prompt": "run the tests",
        "last_answer": "All green.", "updated": "2026-11-18T11:06:40+00:00", "live": True, "owner": "main",
        "owner_since": "2026-11-18T08:20:00+00:00", "epoch": 1, "kind": "chat", "topic": None}
    assert set(json.load(open(os.path.join(iw.hub.home, "index", "shim-state.json")))["files"]) >= {SID_C}


def test_a_second_import_does_not_hide_a_voice_patch_made_since_the_first(iw):
    import fleet_index_import
    import fleet_registry_shim as shim
    voice_patch(os.path.join(iw.hub.registry, SID_B + ".json"), PATCH)
    assert fleet_index_import.main(["import", "--machine", "main", "--backup-dir", os.path.join(iw.base, "bk2")]) == 0
    con = iw.con()
    try:
        assert shim.ingest_phone_rows(con) == 1
    finally:
        con.close()
    assert iw.rows()[SID_B]["last_prompt"] == "and the fridge"
