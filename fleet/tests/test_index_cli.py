"""`fleet session <verb>` across machines: take from another machine, the caches it writes, lists on and off
the hub, the owner guard's call and the bin/fleet dispatch."""
import json
import os
import subprocess
import sys

from index_testkit import ROOT, cluster, index_env, sid, transcript  # noqa: F401


def start(m, s, prompt="hello"):
    p = transcript(m.file("t", s + ".jsonl"), [prompt], ["hi"])
    r = m.hook({"session_id": s, "hook_event_name": "SessionStart", "transcript_path": p, "cwd": "/home/me/app"})
    assert r.returncode == 0
    return p


def test_a_take_from_another_machine_runs_on_the_hub_and_writes_both_caches(cluster):
    mac, lat, main = cluster["mac"], cluster["lat"], cluster["main"]
    s = sid(1)
    start(mac, s)
    r = lat.cli("take", s, "--to", "lat", "--expect-epoch", "1", "--release", "stopped", "--json")
    assert r.returncode == 0, r.stderr
    reply = json.loads(r.stdout)
    assert (reply["owner"], reply["epoch"], reply["previous_owner"]) == ("lat", 2, "mac")
    assert (mac.cache(s)["owner"], lat.cache(s)["owner"], main.hub_row(s)["machine"]) == ("lat", "lat", "lat")
    r = mac.cli("take", s, "--to", "mac", "--expect-epoch", "1", "--json")
    assert (r.returncode, r.stderr) == (2, "session %s moved meanwhile (epoch 2, expected 1); read it again\n" % s)
    assert json.loads(r.stdout)["code"] == "stale-epoch"
    r = mac.cli("owner", s, "--json")
    assert json.loads(r.stdout) == {"sid": s, "owner": "lat", "epoch": 2, "head": s, "source": "hub", "stale": False}


def test_a_take_on_the_hub_changes_the_index_and_writes_no_registry_file(cluster, tmp_path):
    main = cluster["main"]
    registry = tmp_path / "claude-sessions"
    registry.mkdir()
    s = sid(9)
    start(main, s)
    r = main.cli("take", s, "--to", "mac", "--expect-epoch", "1", "--json", CLAUDE_SESSIONS_DIR=str(registry))
    assert r.returncode == 0, r.stderr
    assert (main.hub_row(s)["owner"], main.hub_row(s)["epoch"]) == ("mac", 2)
    assert sorted(os.listdir(str(registry))) == []
    r = main.cli("rename", s, "a new name", CLAUDE_SESSIONS_DIR=str(registry))
    assert r.returncode == 0, r.stderr
    assert main.hub_row(s)["name"] == "a new name"
    assert sorted(os.listdir(str(registry))) == []
    assert not os.path.exists(main.file("index", "shim-state.json"))


def test_a_list_off_the_hub_asks_the_hub_and_serves_its_last_copy_with_its_own_rows_when_the_hub_is_down(cluster):
    mac, lat = cluster["mac"], cluster["lat"]
    start(mac, sid(2), "first session")
    start(lat, sid(3), "second session")
    up = json.loads(lat.cli("list", "--json").stdout)
    assert (up["index"], {r["sid"] for r in up["rows"]}) == ("up", {sid(2), sid(3)})
    cluster.down("main")
    start(lat, sid(4), "made while the hub is down")
    down = json.loads(lat.cli("list", "--json").stdout)
    assert down["index"] == "down" and down["reason"]
    assert {r["sid"] for r in down["rows"]} == {sid(2), sid(3), sid(4)}


def test_tail_reads_the_transcript_on_the_rows_machine(cluster):
    mac, lat = cluster["mac"], cluster["lat"]
    s = sid(5)
    p = start(mac, s, "show me the logs")
    os.makedirs(os.path.join(os.environ["HOME"], ".claude", "projects", "-a"), exist_ok=True)
    os.link(p, os.path.join(os.environ["HOME"], ".claude", "projects", "-a", s + ".jsonl"))
    r = lat.cli("tail", s, "--json", "--turns", "5")
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert (got["machine"], [t["text"] for t in got["turns"]]) == ("mac", ["show me the logs", "hi"])


def test_note_journals_a_masked_work_entry_and_bin_fleet_sends_session_to_the_index_cli(index_env):
    env = dict(os.environ)
    note = {"sid": sid(6), "event": "start", "fields": {"work": True, "last_prompt": "secret", "kind": "chat"}}
    r = subprocess.run([os.path.join(ROOT, "bin", "fleet"), "session", "note"], input=json.dumps(note),
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    entry = json.loads(r.stdout)
    assert entry["fields"] == {"kind": "chat", "work": True}
    r = subprocess.run([os.path.join(ROOT, "bin", "fleet"), "session", "show", sid(6), "--json"], capture_output=True,
                       text=True, env=env, timeout=60)
    assert (r.returncode, json.loads(r.stdout)["work"]) == (0, True)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "fleet_index_cli.py"), "import", "--dry-run"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode in (0, 1)


def test_the_stored_rows_come_from_the_hub_without_asking_any_machine_what_runs(cluster):
    mac, lat, main = cluster["mac"], cluster["lat"], cluster["main"]
    start(mac, sid(6), "first")
    start(lat, sid(7), "second")
    observed = main.file("index", "observed")
    r = main.cli("list", "--json", "--stored", "--env", "all", "--chains", "all")
    assert r.returncode == 0, r.stderr
    assert {x["sid"] for x in json.loads(r.stdout)["rows"]} == {sid(6), sid(7)}
    assert not os.path.exists(observed)
    # history ls off the hub reads the stored rows through the same verb: main asks no machine for it
    r = subprocess.run([sys.executable, os.path.join(ROOT, "fleet.py"), "history", "ls", "--json"],
                       capture_output=True, text=True, env=mac.env(), timeout=60)
    assert r.returncode == 0, r.stderr
    assert not os.path.exists(observed)
