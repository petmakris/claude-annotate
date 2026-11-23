import json
import os

from fleet_testkit import fleet, world  # noqa: F401


def line(world, sid):
    world.capsys.readouterr()
    fleet.main(["statusline", sid])
    return json.loads(world.capsys.readouterr().out)


def test_no_store_prints_an_empty_object(world):
    world.mp.setenv("FLEET_HOME", os.path.join(world.base, "nowhere"))
    assert line(world, "anything") == {}
    assert not os.path.exists(os.path.join(world.base, "nowhere"))


def test_a_session_outside_the_fleet_sees_only_the_count(world):
    a = world.session("alpha")
    assert world.member(a, "alpha")[0] == 0
    assert line(world, "not-a-member") == {"members": 1, "name": None, "open_todos": 0, "for_petros": 0}


def test_a_member_sees_its_name_its_knock_and_what_it_waits_for(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a, "alpha")
    world.member(b, "beta")
    assert world.run(a, "ask", "beta", "how", "far?")[0] == 0
    assert world.run(a, "todo", "add", "write the notes")[0] == 0
    got = line(world, b.sid)
    assert got == {"members": 2, "name": "beta", "open_todos": 1, "inbox": 1, "knock": True,
                   "knock_from": "alpha", "waiting": 0, "todos": 0, "for_petros": 0}
    mine = line(world, a.sid)
    assert (mine["name"], mine["inbox"], mine["waiting"]) == ("alpha", 0, 1)


def test_an_answered_ask_leaves_the_inbox_and_an_old_one_stops_knocking(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a, "alpha")
    world.member(b, "beta")
    world.run(a, "ask", "beta", "first?")
    world.run(a, "ask", "beta", "second?")
    con = fleet.db()
    con.execute("UPDATE messages SET created_at = created_at - 600")
    got = line(world, b.sid)
    assert (got["inbox"], got["knock"]) == (2, False)
    first = con.execute("SELECT id FROM messages WHERE kind='ask' ORDER BY id LIMIT 1").fetchone()[0]
    assert world.run(b, "answer", str(first), "yes")[0] == 0
    assert line(world, b.sid)["inbox"] == 1
    assert line(world, a.sid)["waiting"] == 1


def test_a_dead_member_is_not_counted(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a, "alpha")
    world.member(b, "beta")
    b.die()
    assert line(world, a.sid)["members"] == 1


def test_the_fleet_version_is_declared_once_in_plugin_json_and_not_in_the_marketplace_entry():
    """The marketplace docs say not to set `version` in both: plugin.json wins without a warning, and
    `claude plugin validate` reports a mismatch."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    plugin = json.load(open(os.path.join(root, "fleet", ".claude-plugin", "plugin.json")))
    market = json.load(open(os.path.join(root, ".claude-plugin", "marketplace.json")))
    entry = next(p for p in market["plugins"] if p["name"] == "fleet")
    assert plugin["version"] and "version" not in entry
