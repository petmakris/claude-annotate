"""Hub recovery: every machine's cache rebuilds the index, the highest epoch winning."""
import json
import os

from index_testkit import cluster, hub, index_env, sid, transcript  # noqa: F401

import fleet_index_store as store  # noqa: E402


def row(s, owner, epoch, **kw):
    r = {"sid": s, "conversation": s, "owner": owner, "epoch": epoch, "owner_since": 1.0, "name": "n",
         "name_source": "custom", "kind": "chat", "env": "prod", "machine": owner, "work": False,
         "superseded_by": None}
    r.update(kw)
    return r


def test_rebuild_keeps_the_highest_epoch_and_on_a_tie_the_owners_copy(hub):
    dumps = {"mac": {"rows": [row(sid(1), "mac", 1), row(sid(2), "lat", 2, name="mac's copy")], "acked_seq": 7},
             "lat": {"rows": [row(sid(1), "lat", 2), row(sid(2), "lat", 2, name="lat's copy")], "acked_seq": 3}}
    assert store.rebuild(hub.con, dumps, dry_run=True)["written"] == 2
    assert hub.row(sid(1)) is None
    report = store.rebuild(hub.con, dumps)
    assert (report["rows"], report["written"], report["conflicts"]) == (2, 2, 2)
    assert (hub.row(sid(1))["owner"], hub.row(sid(1))["epoch"]) == ("lat", 2)
    assert hub.row(sid(2))["name"] == "lat's copy"
    assert (store.high_seq(hub.con, "mac"), store.high_seq(hub.con, "lat")) == (7, 3)
    assert report["backup"] and os.path.basename(report["backup"]).endswith("-rebuild.db")


def test_fleet_session_rebuild_reads_every_machines_cache_over_ssh(cluster):
    mac, lat, main = cluster["mac"], cluster["lat"], cluster["main"]
    s = sid(3)
    p = transcript(mac.file("t.jsonl"), ["hello"], ["hi"])
    assert mac.hook({"session_id": s, "hook_event_name": "SessionStart", "transcript_path": p, "cwd": "/a"}).returncode == 0
    r = mac.cli("take", s, "--to", "lat", "--expect-epoch", "1", "--json")
    assert r.returncode == 0, r.stderr
    assert (mac.cache(s)["owner"], lat.cache(s)["owner"], lat.cache(s)["epoch"]) == ("lat", "lat", 2)
    os.rename(main.file("index", "hub.db"), main.file("index", "lost.db"))
    for suffix in ("-wal", "-shm"):
        if os.path.exists(main.file("index", "hub.db" + suffix)):
            os.rename(main.file("index", "hub.db" + suffix), main.file("index", "lost.db" + suffix))
    out = main.cli("rebuild")
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout)
    assert (report["machines"]["mac"]["rows"], report["machines"]["lat"]["rows"], report["unreachable"]) == (1, 1, {})
    got = main.hub_row(s)
    assert (got["owner"], got["epoch"]) == ("lat", 2)
