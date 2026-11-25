"""The journal: entries applied per sid in seq order, deduped on (machine, seq), dropped when stale or not the owner;
the writer's side appends first, sends after, and replays what the hub did not take on the next write."""
import json
import os

from index_testkit import cluster, fixture, hub, index_env, sid, transcript  # noqa: F401

import fleet_index_cache as cache  # noqa: E402
import fleet_index_journal as journal  # noqa: E402
import fleet_index_store as store  # noqa: E402


def test_a_replayed_journal_entry_at_an_old_epoch_changes_nothing(hub):
    sc = fixture("scenarios", "replayed-stale-entry.json")
    hub.machines.add("laptop")
    store.import_row(hub.con, sc["row_before"], origin="test")
    before = hub.row(sc["row_before"]["sid"])
    reply = store.apply_batch(hub.con, sc["batch"], hub="main", machines=hub.machines)
    assert [(r["seq"], r["outcome"]) for r in reply["results"]] == [(12, "stale-epoch")] == [
        (r["seq"], r["outcome"]) for r in sc["reply"]["results"]]
    assert reply["rows"] == sc["reply"]["rows"]
    assert hub.row(sc["row_before"]["sid"]) == before
    assert (before["name"], before["last_prompt"]) == (sc["row_after"]["name"], sc["row_after"]["last_prompt"])


def test_a_replayed_entry_after_takes_changes_nothing(hub):
    s = sid(1)
    hub.start("mac", s)
    old = hub.entry("mac", s, "prompt", {"last_prompt": "an old prompt", "name": "an old name", "name_source": "manual"})
    hub.take(s, "lat", 1)
    hub.take(s, "mac", 2)
    before = hub.row(s)
    reply = hub.apply("mac", old)
    assert reply["results"] == [{"seq": 2, "outcome": "stale-epoch", "reason": "epoch 3, the entry saw 1"}]
    assert hub.row(s) == before


def test_a_resent_seq_is_a_duplicate_and_entries_apply_in_seq_order(hub):
    s = sid(2)
    hub.start("mac", s)
    a = hub.entry("mac", s, "prompt", {"last_prompt": "first", "last_answer": ""})
    b = hub.entry("mac", s, "stop", {"last_prompt": "first", "last_answer": "second"})
    reply = hub.apply("mac", b, a)
    assert [r["outcome"] for r in reply["results"]] == ["applied", "applied"]
    assert (hub.row(s)["last_answer"], store.high_seq(hub.con, "mac")) == ("second", 3)
    again = hub.apply("mac", a, b)
    assert [r["outcome"] for r in again["results"]] == ["duplicate", "duplicate"]


def test_an_entry_from_a_machine_that_is_not_the_owner_is_dropped(hub):
    s = sid(3)
    hub.start("mac", s)
    reply = hub.apply("lat", hub.entry("lat", s, "prompt", {"last_prompt": "not mine"}))
    assert reply["results"][0]["outcome"] == "not-owner"
    assert hub.row(s)["last_prompt"] is None


def test_an_entry_that_writes_the_owner_or_an_unknown_machine_is_invalid(hub):
    bad = hub.entry("mac", sid(4), "start", {"name": "x", "name_source": "custom"})
    bad["fields"]["owner"] = "lat"
    unknown = hub.entry("nowhere", sid(5), "start", {})
    assert hub.apply("mac", bad)["results"][0]["outcome"] == "invalid"
    assert hub.apply("nowhere", unknown)["results"][0]["outcome"] == "invalid"
    assert hub.row(sid(4)) is None and hub.row(sid(5)) is None


def test_names_follow_the_rank(hub):
    s = sid(6)
    hub.start("mac", s, {"name": "from the prompt", "name_source": "prompt"})
    hub.apply("mac", hub.entry("mac", s, "stop", {"name": "an ai title", "name_source": "ai"}))
    hub.apply("mac", hub.entry("mac", s, "stop", {"name": "a later prompt name", "name_source": "prompt"}))
    assert (hub.row(s)["name"], hub.row(s)["name_source"]) == ("an ai title", "ai")
    store.rename(hub.con, s, "mine")
    hub.apply("mac", hub.entry("mac", s, "stop", {"name": "renamed in claude", "name_source": "custom"}))
    assert (hub.row(s)["name"], hub.row(s)["name_source"]) == ("mine", "manual")
    store.rename(hub.con, s, "")
    hub.apply("mac", hub.entry("mac", s, "stop", {"name": "an agent", "name_source": "agent"}))
    assert (hub.row(s)["name"], hub.row(s)["name_source"]) == ("an agent", "agent")


def test_end_sets_ended_and_a_later_prompt_opens_the_row_again(hub):
    s = sid(7)
    hub.start("mac", s)
    hub.apply("mac", hub.entry("mac", s, "end", {"end_reason": "logout"}))
    assert hub.row(s)["end_reason"] == "logout" and hub.row(s)["ended"]
    hub.apply("mac", hub.entry("mac", s, "prompt", {"last_prompt": "back"}))
    assert (hub.row(s)["ended"], hub.row(s)["end_reason"]) == (None, None)


# ---------------------------------------------------------------- the writer's side

def send_to(hub_store, machine="mac"):
    def send(batch):
        return store.apply_batch(hub_store.con, batch, hub="main", machines=hub_store.machines)
    return send


def down(batch):
    raise journal.HubDown("no answer")


def test_append_writes_first_and_a_flush_with_the_hub_down_keeps_the_entries(hub, index_env):
    fh = str(index_env / "mac")
    e = journal.append(fh, "mac", sid(8), "start", {"name": "n", "name_source": "custom", "work": False})
    assert (e["seq"], e["epoch_seen"]) == (1, 1)
    assert cache.read(fh, sid(8))["owner"] == "mac"
    assert journal.flush(fh, "mac", down) is None
    assert [x["seq"] for x in journal.pending(fh)] == [1]
    journal.append(fh, "mac", sid(8), "prompt", {"last_prompt": "go", "last_answer": ""})
    reply = journal.flush(fh, "mac", send_to(hub))
    assert [r["outcome"] for r in reply["results"]] == ["applied", "applied"]
    assert journal.pending(fh) == []
    assert hub.row(sid(8))["last_prompt"] == "go"
    assert cache.read(fh, sid(8))["source"] == "hub"
    for name in ("journal.jsonl", "journal.state.json"):
        assert os.stat(os.path.join(fh, "index", name)).st_mode & 0o777 == 0o600


def test_a_lost_state_file_renumbers_the_unsent_entries_above_the_hubs_high_mark(hub, index_env):
    fh = str(index_env / "mac")
    journal.append(fh, "mac", sid(9), "start", {"name": "n", "name_source": "custom"})
    journal.flush(fh, "mac", send_to(hub))
    for i in range(4):
        hub.apply("mac", hub.entry("mac", sid(10), "observe", {"observed": {"live": True, "observed_at": 1.0}},
                                   epoch_seen=0, seq=i + 2))
    assert store.high_seq(hub.con, "mac") == 5
    os.unlink(os.path.join(fh, "index", "journal.state.json"))
    journal.append(fh, "mac", sid(9), "prompt", {"last_prompt": "after the loss"})
    journal.flush(fh, "mac", send_to(hub))
    assert hub.row(sid(9))["last_prompt"] == "after the loss"
    assert store.high_seq(hub.con, "mac") == 7
    assert json.load(open(os.path.join(fh, "index", "journal.state.json"))) == {"next_seq": 8, "acked_seq": 7}


def test_compact_drops_acknowledged_entries_past_the_limit(hub, index_env):
    fh = str(index_env / "mac")
    for i in range(3):
        journal.append(fh, "mac", sid(11), "start" if i == 0 else "prompt", {"last_prompt": "p%d" % i})
    journal.flush(fh, "mac", send_to(hub))
    journal.append(fh, "mac", sid(11), "prompt", {"last_prompt": "unsent"})
    journal.compact(fh, max_bytes=10)
    assert [e["seq"] for e in journal._entries(fh)] == [4]


def test_with_the_hub_down_a_mac_session_records_its_cache_shows_its_owner_and_the_journal_replays(cluster):
    mac, main = cluster["mac"], cluster["main"]
    s = sid(12)
    path = transcript(mac.file("t", s + ".jsonl"), ["fix the build"], ["Done: the build passes."])
    cluster.down("main")
    base = {"session_id": s, "transcript_path": path, "cwd": "/home/me/app"}
    assert mac.hook(dict(base, hook_event_name="SessionStart", source="startup")).returncode == 0
    assert mac.hook(dict(base, hook_event_name="UserPromptSubmit", prompt="fix the build")).returncode == 0
    assert [(e["seq"], e["event"]) for e in mac.journal()] == [(1, "start"), (2, "prompt")]
    assert mac.state() == {"next_seq": 3, "acked_seq": 0}
    assert (mac.cache(s)["owner"], mac.cache(s)["epoch"], mac.cache(s)["source"]) == ("mac", 1, "local")
    r = mac.cli("owner", s, "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["owner"] == "mac" and json.loads(r.stdout)["source"] == "cache"
    r = mac.cli("take", s, "--to", "lat", "--expect-epoch", "1", "--json")
    assert (r.returncode, r.stderr) == (3, "ownership cannot change while the hub is down\n")
    assert not os.path.exists(main.file("index", "hub.db")) or main.hub_row(s) is None
    cluster.up("main")
    assert mac.hook(dict(base, hook_event_name="Stop")).returncode == 0
    row = main.hub_row(s)
    assert (row["owner"], row["epoch"], row["machine"], row["last_prompt"], row["last_answer"]) == (
        "mac", 1, "mac", "fix the build", "Done: the build passes.")
    assert mac.state() == {"next_seq": 4, "acked_seq": 3}
    assert mac.cache(s)["source"] == "hub"
