"""To-dos with an owner and an order (`--owner`, `--after`): every change is one locked write that refuses an
unknown id, a to-do waiting on itself and a loop; ready and owner gone are worked out on read."""
import json
import sqlite3
import threading

from fleet_testkit import fleet, world  # noqa: F401


def user(world, *argv):
    world.mp.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    world.mp.delenv("CLAUDE_CODE_MESSAGING_SOCKET", raising=False)
    world.capsys.readouterr()
    code = fleet.main(list(argv))
    o = world.capsys.readouterr()
    return code, o.out, o.err


def rows(world):
    return {r["id"]: r for r in json.loads(user(world, "todo", "ls", "--json", "--all")[1])}


def test_order_is_stored_and_ready_is_worked_out_on_read(world):
    a = world.session("alpha")
    world.member(a)
    assert user(world, "todo", "add", "schema")[1] == "todo 1 added\n"
    assert user(world, "todo", "add", "api", "--after", "1", "--owner", "alpha")[1] == "todo 2 added\n"
    assert user(world, "todo", "add", "page", "--after", "#1, #2")[1] == "todo 3 added\n"
    r = rows(world)
    assert (r[2]["after"], r[2]["waits_on"], r[2]["ready"], r[2]["owner"], r[2]["owner_gone"]) == ([1], [1], False, "alpha", False)
    assert (r[3]["after"], r[3]["waits_on"], r[3]["ready"]) == ([1, 2], [1, 2], False)
    assert r[1]["ready"] is True
    out = user(world, "todo", "ls")[1]
    assert "2    open     api  {for alpha; waits on #1}\n" in out
    world.run(a, "todo", "claim", "1")
    world.run(a, "todo", "done", "1")
    r = rows(world)
    assert (r[2]["waits_on"], r[2]["ready"]) == ([], True)
    assert r[3]["waits_on"] == [2]
    assert "2    open     api  {for alpha; ready}\n" in user(world, "todo", "ls")[1]


def test_unknown_ids_self_and_loops_are_refused_and_nothing_is_stored(world):
    user(world, "todo", "add", "one")
    user(world, "todo", "add", "two", "--after", "1")
    code, _, err = user(world, "todo", "add", "three", "--after", "9")
    assert code == 1 and err == "fleet: no to-do 9. `fleet todo ls --all` lists them.\n"
    assert sorted(rows(world)) == [1, 2]  # the refused add left no row behind
    code, _, err = user(world, "todo", "set", "1", "--after", "2")
    assert code == 1 and err == "fleet: to-do 1 cannot wait on #2: that would make a loop.\n"
    code, _, err = user(world, "todo", "set", "1", "--after", "1")
    assert code == 1 and err == "fleet: to-do 1 cannot wait on itself.\n"
    code, _, err = user(world, "todo", "set", "1", "--after", "3@bee")
    assert code == 1 and "a to-do on another machine" in err
    assert rows(world)[1]["after"] == []
    assert user(world, "todo", "set", "2", "--after", "")[1] == "todo 2: no owner, waits on nothing\n"
    assert rows(world)[2]["after"] == []


def test_claim_keeps_the_order_and_the_owner(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    user(world, "todo", "add", "first")
    user(world, "todo", "add", "second", "--after", "1", "--owner", "beta")
    code, _, err = world.run(b, "todo", "claim", "2")
    assert code == 1 and err == "fleet: to-do 2 waits on #1, not done yet.\n"
    world.run(a, "todo", "claim", "1")
    world.run(a, "todo", "done", "1")
    code, _, err = world.run(a, "todo", "claim", "2")
    assert code == 1 and err == "fleet: to-do 2 is for beta.\n"
    code, out, _ = world.run(b, "todo", "claim", "2")
    assert code == 0 and out.startswith("claimed todo 2: second")
    code, _, err = user(world, "todo", "set", "2", "--owner", "alpha")
    assert code == 1 and "claimed by beta" in err


def test_owner_gone_is_worked_out_from_who_is_alive(world):
    a = world.session("alpha")
    world.member(a)
    user(world, "todo", "add", "x", "--owner", "alpha")
    user(world, "todo", "add", "y", "--owner", "beta@bee")
    user(world, "todo", "add", "z", "--owner", "petros")
    assert rows(world)[1]["owner_gone"] is False
    a.die()
    r = rows(world)
    assert (r[1]["owner_gone"], r[2]["owner_gone"], r[3]["owner_gone"]) == (True, None, None)
    assert "{for alpha (gone)}" in user(world, "todo", "ls")[1]


def test_a_store_from_before_the_order_gains_the_columns(world):
    home = world.here.home
    import os
    os.makedirs(home, exist_ok=True)
    con = sqlite3.connect(os.path.join(home, "fleet.db"))
    con.execute("CREATE TABLE todos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, ref TEXT, notes TEXT,"
                " created_by TEXT, state TEXT NOT NULL DEFAULT 'open', claimed_by TEXT, claimed_session TEXT,"
                " reserved_for TEXT, created_at REAL, claimed_at REAL, done_at REAL)")
    con.execute("INSERT INTO todos (title) VALUES ('old one')")
    con.commit()
    con.close()
    r = rows(world)
    assert (r[1]["title"], r[1]["owner"], r[1]["after"], r[1]["ready"]) == ("old one", None, [], True)


def test_two_writers_at_once_cannot_make_a_loop(world):
    user(world, "todo", "add", "one")
    user(world, "todo", "add", "two")
    errors = []

    def setter(tid, after):
        try:
            fleet.todo_set(tid, after=after)
        except fleet.FleetError as e:
            errors.append(str(e))
    ts = [threading.Thread(target=setter, args=(1, "2")), threading.Thread(target=setter, args=(2, "1"))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    r = rows(world)
    assert len(errors) == 1 and "loop" in errors[0]
    assert sorted([r[1]["after"], r[2]["after"]]) == [[], [1]] or sorted([r[1]["after"], r[2]["after"]]) == [[], [2]]


def test_todo_spawn_of_an_owned_to_do_starts_its_owner_and_waits_for_its_order(world):
    from fleet_testkit import install_claude_stub
    install_claude_stub(world)
    import os
    work = os.path.join(world.base, "work")
    os.makedirs(work)
    user(world, "todo", "add", "first")
    user(world, "todo", "add", "second", "--after", "1", "--owner", "builder")
    code, _, err = user(world, "todo", "spawn", "2", "--cwd", work)
    assert code == 1 and err == "fleet: to-do 2 waits on #1, not done yet.\n"
    assert rows(world)[2]["reserved_for"] is None
    code, _, err = user(world, "todo", "spawn", "2", "--name", "other", "--cwd", work)
    assert code == 1 and "is for builder" in err
    con = sqlite3.connect(os.path.join(world.here.home, "fleet.db"))
    con.execute("UPDATE todos SET state='done' WHERE id=1")
    con.commit()
    code, out, err = user(world, "todo", "spawn", "2", "--cwd", work)
    assert code == 0, err
    assert "started builder" in out and rows(world)[2]["reserved_for"] == "builder"
