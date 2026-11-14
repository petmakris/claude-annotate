"""Lungo's needs-you items, read live into `fleet inbox` and the page's For you, never copied into the store. The
command comes from $FLEET_HOME/lungo.json; a fake one prints a brief here."""
import json
import os
import sqlite3
import sys

from fleet_testkit import fleet, world  # noqa: F401

BRIEF = {"ok": True, "error": None, "data": {
    "schema": "lungo.brief/1", "as_of": "2026-11-14T15:50:29+01:00", "counts": {"needs_petros": 2, "running": 1},
    "jobs": [
        {"machine": "main", "name": "watch-sync-check", "say": "The watch sync", "state": "done", "attention": "hands",
         "kind": "action", "step": "Plug the watch into the Mac.", "asked": "2026-11-14T15:41:50+01:00"},
        {"machine": "main", "name": "ops-f1", "say": "Ops dashboard", "state": "blocked", "attention": "blocked",
         "question": "Which vendor first?", "ended": "2026-11-10T19:56:59+01:00"},
        {"machine": "main", "name": "busy-job", "say": "Something running", "state": "running"}]}}


def fake_lungo(world, doc=None, raw=None, code=0):
    """A command that prints `doc` (or `raw`) and exits with `code`; lungo.json points at it."""
    path = os.path.join(world.base, "brief.json")
    with open(path, "w") as f:
        f.write(raw if raw is not None else "Welcome to main\n" + json.dumps(doc or BRIEF))
    os.makedirs(world.here.home, exist_ok=True)
    cmd = [sys.executable, "-c", "import sys; sys.stdout.write(open(sys.argv[1]).read()); sys.exit(%d)" % code, path]
    with open(os.path.join(world.here.home, "lungo.json"), "w") as f:
        json.dump({"command": cmd, "ttl": 0}, f)
    fleet._LUNGO.update(at=0.0, val=None, key=None)


def user(world, *argv):
    world.mp.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    world.mp.delenv("CLAUDE_CODE_MESSAGING_SOCKET", raising=False)
    world.capsys.readouterr()
    code = fleet.main(list(argv))
    o = world.capsys.readouterr()
    return code, o.out, o.err


def test_without_lungo_json_the_inbox_is_unchanged(world):
    assert user(world, "inbox")[1] == "nothing for petros\n"


def test_the_needs_you_rows_are_listed_with_lungos_time_and_the_running_row_is_not(world):
    fake_lungo(world)
    code, out, _ = user(world, "inbox")
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "nothing for petros in the fleet"
    assert lines[1].startswith("Lungo, as of ") and lines[1].endswith(": 2 need you")
    assert lines[2].startswith("[lungo:main/watch-sync-check] action, ") and lines[2].endswith(
        ": The watch sync: Plug the watch into the Mac.")
    assert lines[3].startswith("[lungo:main/ops-f1] blocked, ") and lines[3].endswith(": Ops dashboard: Which vendor first?")
    assert "busy-job" not in out
    items = json.loads(user(world, "inbox", "--json")[1])
    assert [(i["ref"], i["kind"], i["answered_at"]) for i in items] == [
        ("lungo:main/watch-sync-check", "lungo", None), ("lungo:main/ops-f1", "lungo", None)]


def test_two_items_of_one_job_get_their_own_address_from_lungos_item_id(world):
    doc = json.loads(json.dumps(BRIEF))
    doc["data"]["jobs"][0]["id"] = "a7fe91aad2b0"
    doc["data"]["jobs"][1].update(name="watch-sync-check", id="06ef4c7c35ce")
    fake_lungo(world, doc)
    items = json.loads(user(world, "inbox", "--json")[1])
    assert sorted(i["ref"] for i in items) == ["lungo:main/watch-sync-check#06ef4c7c35ce",
                                               "lungo:main/watch-sync-check#a7fe91aad2b0"]


def test_an_unreachable_lungo_is_said_and_never_shown_as_nothing(world):
    fake_lungo(world, raw="", code=255)
    out = user(world, "inbox")[1]
    assert out.startswith("nothing for petros in the fleet\nLungo: unreachable (exit 255")
    assert "what it needs from you is not shown" in out
    code, out, err = user(world, "inbox", "--json")
    assert json.loads(out) == [] and "Lungo: unreachable" in err


def test_a_brief_of_another_shape_is_refused_not_misread(world):
    doc = json.loads(json.dumps(BRIEF))
    doc["data"]["schema"] = "lungo.brief/2"
    fake_lungo(world, doc)
    assert "Lungo: unreachable (its brief has schema 'lungo.brief/2', not lungo.brief/1)" in user(world, "inbox")[1]
    doc = json.loads(json.dumps(BRIEF))
    del doc["data"]["jobs"][0]["attention"]
    fake_lungo(world, doc)
    assert "a needs-you row of its brief has no attention" in user(world, "inbox")[1]


def test_a_lungo_item_cannot_be_answered_or_dismissed_from_the_fleet(world):
    fake_lungo(world)
    code, _, err = user(world, "answer", "lungo:main/ops-f1", "yes", "--as", "petros")
    assert code == 1 and "is Lungo's; the fleet only shows it. Act on it in Lungo." in err
    code, _, err = user(world, "dismiss", "lungo:main/ops-f1", "--as", "petros")
    assert code == 1 and "Act on it in Lungo" in err


def test_nothing_from_lungo_is_written_to_the_store(world):
    fake_lungo(world)
    user(world, "inbox")
    con = sqlite3.connect(os.path.join(world.here.home, "fleet.db"))
    assert con.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
    assert not [r for r in con.execute("SELECT name FROM sqlite_master WHERE name LIKE '%lungo%'")]


def test_another_machine_is_asked_for_its_fleet_inbox_only(world):
    bee = world.host("bee")
    world.link(bee)
    fake_lungo(world)
    with open(os.path.join(bee.home, "lungo.json"), "w") as f:  # bee has its own: a fan-out must not read it
        json.dump({"command": ["false"]}, f)
    out = user(world, "inbox")[1]
    assert out.count("Lungo") == 1 and "unreachable" not in out


def test_the_page_shows_lungo_items_and_its_line(world):
    fake_lungo(world)
    data = fleet.ui_inbox()
    assert data["open"] == 2 and data["lungo"]["ok"] is True and data["lungo"]["line"].endswith("2 need you")
    fake_lungo(world, raw="", code=1)
    data = fleet.ui_inbox()
    assert data["open"] == 0 and data["lungo"]["ok"] is False and "unreachable" in data["lungo"]["line"]
