"""Each member's live state, worked out when read and never stored: activity from `claude agents --json`, held
to-dos and unanswered messages from the store, `free` only when every source answered, and the time it was read."""
import json
import os
import sqlite3
import time

from fleet_testkit import fleet, world  # noqa: F401


def say(world, **by_name):
    with open(os.path.join(world.stub_dir, "status.json"), "w") as f:
        json.dump(by_name, f)


def members(world, who, *extra):
    return {m["name"]: m for m in json.loads(world.run(who, "ls", "--json", *extra)[1])}


def test_activity_is_the_raw_agent_status_and_free_needs_idle_and_nothing_owed(world):
    a, b, c = world.session("alpha"), world.session("beta"), world.session("gamma")
    for s in (a, b, c):
        world.member(s)
    say(world, beta={"status": "busy"}, gamma={"status": "waiting", "state": "blocked"})
    before = time.time()
    m = members(world, a)
    assert (m["alpha"]["activity"], m["alpha"]["free"]) == ("idle", True)
    assert (m["beta"]["activity"], m["beta"]["free"]) == ("busy", False)
    assert (m["gamma"]["activity"], m["gamma"]["free"]) == ("waiting", False)
    assert before <= m["alpha"]["as_of"] <= time.time()
    out = world.run(a, "ls", "--state")[1]
    assert "gamma                waiting (a prompt is open)\n" in out
    assert "alpha                idle; free\n" in out
    assert out.startswith("as of ")


def test_a_member_that_holds_a_to_do_or_owes_an_answer_is_never_free(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    world.run(a, "todo", "add", "ship it")
    world.run(b, "todo", "claim", "1")
    out = world.run(a, "tell", "beta", "please rebase")[1]
    mid = int([ln for ln in out.splitlines() if ln.startswith("message")][0].split()[1])
    m = members(world, a)["beta"]
    assert m["activity"] == "idle" and m["free"] is False
    assert m["held"] == [{"id": 1, "title": "ship it"}]
    assert [(u["id"], u["kind"], u["sender"]) for u in m["unanswered"]] == [(mid, "tell", "alpha")]
    assert "beta                 idle; holds #1 ship it; unanswered: tell %d from alpha, 0 min\n" % mid \
        in world.run(a, "ls", "--state")[1]
    world.run(b, "ack", str(mid))
    world.run(b, "todo", "done", "1")
    assert members(world, a)["beta"]["free"] is True


def test_when_agents_cannot_answer_activity_is_unknown_and_nobody_is_free(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    world.mp.setenv("STUB_AGENTS_BROKEN", "1")
    m = members(world, a)
    assert (m["beta"]["activity"], m["beta"]["free"]) == ("unknown", False)


def test_a_dead_member_has_no_activity_and_still_shows_what_it_held(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    world.run(a, "todo", "add", "x")
    world.run(b, "todo", "claim", "1")
    b.die()
    m = members(world, a)["beta"]
    assert (m["status"], m["activity"], m["free"], m["held"]) == ("dead", None, False, [{"id": 1, "title": "x"}])
    assert "beta                 dead; holds #1 x\n" in world.run(a, "ls", "--state")[1]


def test_nothing_about_a_members_activity_is_written_to_the_store(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    say(world, beta={"status": "busy"})
    db = os.path.join(world.here.home, "fleet.db")
    con = sqlite3.connect(db)
    tables = {r[0]: con.execute("SELECT sql FROM sqlite_master WHERE name=?", (r[0],)).fetchone()[0]
              for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    before = {t: con.execute("SELECT * FROM %s" % t).fetchall() for t in tables if t != "sqlite_sequence"}
    con.close()
    world.run(a, "ls", "--state")
    con = sqlite3.connect(db)
    after = {t: con.execute("SELECT * FROM %s" % t).fetchall() for t in before}
    assert after == before
    assert all("activity" not in sql and "busy" not in sql for sql in tables.values())


def test_state_on_another_machine_carries_its_own_time_and_an_unreachable_one_says_unknown(world):
    bee = world.host("bee")
    world.link(bee, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    a, b = world.session("alpha"), bee.session("beta")
    world.member(a), world.member(b)
    world.here_env()
    m = {x["name"]: x for x in json.loads(world.run(a, "ls", "--json")[1])}
    assert m["beta"]["machine"] == "bee" and m["beta"]["activity"] == "idle" and m["beta"]["as_of"]
    out = world.run(a, "ls", "--state")[1]
    assert "as of " in out and " on bee\n" in out and " on here\n" in out
    assert "machine gone: unreachable" in out and "its members' state is unknown" in out
