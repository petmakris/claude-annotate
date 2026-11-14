"""Across machines: a fake `ssh` on PATH runs the real CLI with another machine's FLEET_HOME and sessions dir."""
import json
import os
import stat

import pytest

from fleet_testkit import fleet, install_claude_stub, wait_for, world  # noqa: F401
from test_fleet_messaging import msg_id, thread_id

NASTY = "it's \"quoted\" $HOME `touch /tmp/x` $(id) \\ back\nsecond line;  two  spaces & | > <"


def duo(world, **kw):
    """alpha on `here`, beta on `bee`, both joined, linked by ssh."""
    bee = world.host("bee")
    world.link(bee, **kw)
    a, b = world.session("alpha"), bee.session("beta")
    assert world.member(a)[0] == 0 and world.member(b)[0] == 0
    return a, b, bee


def test_without_machines_json_ls_and_send_stay_single_machine(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    code, out, _ = world.run(a, "ls")
    assert "@" not in out and "unreachable" not in out and world.ssh_log() == []
    assert world.run(a, "tell", "nobody@bee", "x")[0] == 1
    assert world.ssh_log() == []


def test_ls_fans_out_and_reports_an_unreachable_machine(world):
    a, b, bee = duo(world, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    code, out, _ = world.run(a, "ls")
    assert code == 0
    assert "alpha " in out and "beta@bee" in out
    assert "machine gone: unreachable (ssh: connect to host no-such-host port 22: Operation timed out)" in out
    hosts = [h for h, _ in world.ssh_log()]
    assert sorted(hosts) == ["bee", "no-such-host"]
    assert all("--local" in c for _, c in world.ssh_log())  # a remote ls never fans out again


def test_ls_json_carries_the_machine_and_reports_unreachable_on_stderr(world):
    a, b, bee = duo(world, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    code, out, err = world.run(a, "ls", "--json")
    rows = {m["name"]: m["machine"] for m in json.loads(out)}
    assert rows == {"alpha": "here", "beta": "bee"}
    assert "machine gone: unreachable" in err
    out = world.run(a, "ls", "--local")[1]
    assert "beta" not in out


def test_the_local_machine_name_falls_back_to_the_hostname(world, monkeypatch):
    bee = world.host("bee")
    world.link(bee)
    path = os.path.join(world.here.home, "machines.json")
    conf = json.load(open(path))
    del conf["self"]
    json.dump(conf, open(path, "w"))
    monkeypatch.setattr(fleet.socket, "gethostname", lambda: "somebox.example.net")
    assert fleet.self_machine() == "somebox"
    assert fleet.other_machines().keys() == {"bee"}


def test_a_machine_that_is_also_this_one_is_not_asked_over_ssh(world):
    a, b, bee = duo(world)
    world.run(a, "tell", "beta@here", "x")  # `here` is this machine: nobody named beta locally
    assert world.ssh_log() == []


def test_ask_answer_and_wait_across_machines(world):
    a, b, bee = duo(world)
    code, out, _ = world.run(a, "ask", "beta@bee", "which session works on X?")
    assert code == 0 and "to beta@bee: delivered" in out
    th = thread_id(out)
    assert th.startswith("t") and not th.isdigit()
    # stored on the target's machine, posted to its socket there
    [row] = [dict(r) for r in bee.db().execute("SELECT * FROM messages")]
    assert row["thread"] == th and row["kind"] == "ask" and row["recipient"] == "beta"
    assert row["sender"] == "alpha@here" and row["machine"] == "here" and row["body"] == "which session works on X?"
    assert wait_for(lambda: b.messages()) and a.messages() == []
    wake = b.messages()[0]["message"]["content"]
    assert "Fleet ask %d from alpha@here: which session works on X?" % row["id"] in wake
    assert 'Reply once with `/fleet answer %d "YOUR ANSWER"`' % row["id"] in wake

    code, out, err = world.run(b, "answer", str(row["id"]), "me, on X")
    assert code == 0, err
    assert "asker: delivered" in out
    assert wait_for(lambda: a.messages())
    c = a.messages()[0]["message"]["content"]
    assert 'from-name="beta@bee"' in c and "me, on X" in c and th in c

    code, out, _ = world.run(a, "wait", th, "--timeout", "5")
    assert code == 0 and "answer beta@bee -> alpha" in out and "me, on X" in out and out.strip().endswith("all answered")
    # one thread id on both machines, each holding the whole conversation
    for who in (a, b):
        rows = json.loads(world.run(who, "thread", th, "--json")[1])
        assert [r["kind"] for r in rows] == ["ask", "answer"] and {r["thread"] for r in rows} == {th}
        assert [r["body"] for r in rows] == ["which session works on X?", "me, on X"]


def test_a_tell_across_machines_is_closed_by_an_ack_without_waking_the_sender(world):
    a, b, bee = duo(world)
    out = world.run(a, "tell", "beta@bee", "rebase")[1]
    th = thread_id(out)
    mid = [r["id"] for r in bee.db().execute("SELECT id FROM messages")][0]
    assert "Fleet tell %d from alpha@here" % mid in (wait_for(lambda: b.messages()) and b.messages()[0]["message"]["content"])
    code, out, _ = world.run(b, "ack", str(mid))
    assert code == 0 and "asker: stored" in out
    assert a.messages() == []
    code, out, _ = world.run(a, "wait", th, "--timeout", "5")
    assert code == 0 and "ack beta@bee -> alpha" in out


def test_wait_fetches_an_answer_the_push_back_could_not_deliver(world):
    # beta's machine does not list alpha's, so the answer cannot be pushed home and stays stored there
    a, b, bee = duo(world, only={"here": ["bee"], "bee": []})
    out = world.run(a, "ask", "beta@bee", "q?")[1]
    th = thread_id(out)
    mid = bee.db().execute("SELECT id FROM messages").fetchone()["id"]
    code, out, _ = world.run(b, "answer", str(mid), "found it")
    assert code == 0 and "asker: failed" in out and "fleet wait" in out
    assert a.messages() == []
    code, out, _ = world.run(a, "wait", th, "--timeout", "10")
    assert code == 0 and "found it" in out and out.strip().endswith("all answered")
    rows = json.loads(world.run(a, "thread", th, "--json")[1])
    assert [r["kind"] for r in rows] == ["ask", "answer"]  # fetched once, not twice


def test_a_pushed_answer_is_not_filed_twice_when_wait_also_fetches(world):
    a, b, bee = duo(world)
    out = world.run(a, "ask", "beta@bee", "q?")[1]
    th = thread_id(out)
    mid = bee.db().execute("SELECT id FROM messages").fetchone()["id"]
    world.run(b, "answer", str(mid), "once")
    fleet_con = fleet.db()
    con_rows = lambda: fleet_con.execute("SELECT kind FROM messages WHERE thread=?", (th,)).fetchall()
    world.run(a, "thread", th)
    world.run(a, "thread", th)
    assert [r["kind"] for r in con_rows()] == ["ask", "answer"]


def test_a_bare_name_is_looked_up_on_the_other_machines(world):
    a, b, bee = duo(world)
    code, out, _ = world.run(a, "tell", "beta", "hello")
    assert code == 0 and "to beta@bee: delivered" in out
    assert wait_for(lambda: b.messages())


def test_a_local_name_wins_over_the_same_name_elsewhere(world):
    a, b, bee = duo(world)
    c = world.session("beta")
    world.member(c)
    assert "to beta: delivered" in world.run(a, "tell", "beta", "local wins")[1]
    assert wait_for(lambda: c.messages()) and b.messages() == []


def test_a_bare_name_on_two_machines_must_be_qualified(world):
    a, b, bee = duo(world)
    cee = world.host("cee")
    world.link(bee, cee)
    world.member(cee.session("gamma")), world.member(bee.session("gamma"))
    code, _, err = world.run(a, "tell", "gamma", "x")
    assert code == 1 and "several machines (bee, cee)" in err and "name@machine" in err


def test_a_thread_id_is_never_all_digits(world, monkeypatch):
    # 8 hex digits that happen to be 0-9 read as a message id in `fleet thread`: it was a 1-in-50 flake
    class Digits:
        hex = "1234567890" + "ab" * 11
    monkeypatch.setattr(fleet.uuid, "uuid4", lambda: Digits())
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    out = world.run(a, "tell", "beta", "x")[1]
    th = thread_id(out)
    assert th == "t1234567890" and not th.isdigit()
    assert world.run(a, "thread", th, "--json")[0] == 0


def test_an_unknown_machine_or_member_is_an_error(world):
    a, b, bee = duo(world)
    assert "no machine named 'nowhere'" in world.run(a, "tell", "beta@nowhere", "x")[2]
    code, _, err = world.run(a, "tell", "nobody", "x")
    assert code == 1 and "no member named 'nobody'" in err
    code, out, _ = world.run(a, "tell", "nobody@bee", "x")
    assert "failed (fleet: no member named 'nobody' on bee.)" in out


def test_broadcast_reaches_every_machine_and_names_the_unreachable_one(world):
    a, b, bee = duo(world, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    c = world.session("gamma")
    world.member(c)
    code, out, _ = world.run(a, "ask", "*", "who works on X?")
    assert code == 0
    assert "message" in out and "to gamma: delivered" in out and "to beta@bee: delivered" in out
    assert "machine gone: unreachable" in out
    th = thread_id(out)
    assert wait_for(lambda: b.messages() and c.messages()) and a.messages() == []
    mid_b = bee.db().execute("SELECT id FROM messages").fetchone()["id"]
    mid_c = int([ln for ln in out.splitlines() if "to gamma:" in ln][0].split()[1])
    world.run(b, "answer", str(mid_b), "not me")
    world.run(c, "answer", str(mid_c), "me")
    code, out, _ = world.run(a, "wait", th, "--timeout", "5")
    assert code == 0 and "not me" in out and "me\n" in out


def test_broadcast_skips_a_job_on_another_machine(world):
    a, b, bee = duo(world)
    j = bee.session("job:remote-1")
    world.member(j, "job:remote-1")
    world.here_env()
    code, out, _ = world.run(a, "tell", "*", "heads up")
    assert code == 0 and "to beta@bee: delivered" in out
    assert "skipped 1 job (a broadcast never reaches a job; name it to reach it): job:remote-1@bee" in out
    assert wait_for(lambda: b.messages())
    assert j.messages() == []


def test_a_message_with_quotes_newlines_and_shell_characters_arrives_exactly(world):
    a, b, bee = duo(world)
    out = world.run(a, "ask", "beta@bee", NASTY)[1]
    th = thread_id(out)
    row = bee.db().execute("SELECT * FROM messages").fetchone()
    assert row["body"] == NASTY
    world.run(b, "answer", str(row["id"]), NASTY[::-1])
    rows = json.loads(world.run(a, "thread", th, "--json")[1])
    assert [r["body"] for r in rows] == [NASTY, NASTY[::-1]]


def test_a_machines_env_reaches_the_remote_command(world):
    out = os.path.join(world.base, "env.out")
    bee = world.host("bee")
    world.link(bee)
    conf = json.load(open(os.path.join(world.here.home, "machines.json")))
    conf["bee"]["env"] = {"FLEET_HOME": "~/my store"}
    json.dump(conf, open(os.path.join(world.here.home, "machines.json"), "w"))
    world.mp.setenv("HOME", world.base)
    fleet.run_remote("bee", ["ls", "--local"])
    # the store was made where the env said, under the remote HOME, not where the fake ssh would have put it
    assert os.path.exists(os.path.join(world.base, "my store", "fleet.db"))


def test_remote_arguments_are_quoted_for_the_remote_shell():
    m = {"python": "python3", "fleet": "/opt/my tools/fleet.py"}
    cmd = fleet.remote_command(m, ["spawn", "n", "/a b", NASTY])
    import shlex
    assert shlex.split(cmd) == ["python3", "/opt/my tools/fleet.py", "spawn", "n", "/a b", NASTY]
    home = fleet.remote_command({"python": "python3", "fleet": "~/.cache/my dir/fleet.py"}, ["ls"])
    assert home.startswith("python3 ~/'.cache/my dir/fleet.py' ")
    withenv = fleet.remote_command({"python": "python3", "fleet": "/f.py", "env": {"FLEET_HOME": "~/x y"}}, ["ls"])
    assert withenv == "env FLEET_HOME=\"$HOME\"/'x y' python3 /f.py ls"


@pytest.fixture
def stub(world):
    install_claude_stub(world)
    out = os.path.join(world.base, "stub.out")
    world.mp.setenv("STUB_OUT", out)
    work = os.path.join(world.base, "work dir")
    os.makedirs(work)
    return out, work


def test_spawn_on_runs_it_on_the_other_machine_with_the_prompt_intact(world, stub):
    out_file, work = stub
    a, b, bee = duo(world)
    code, out, err = world.run(a, "spawn", "--on", "bee", "builder", work, NASTY)
    assert code == 0, err
    assert "started builder (id ab12cd34)" in out
    args = open(out_file).read().split("\n")[:-1]
    assert args[:3] == ["--bg", "-n", "builder"]
    settings = json.loads(args[4])
    assert settings["env"]["FLEET_HOME"] == bee.home  # joins the fleet of the machine it runs on
    assert "\n".join(args[5:]) == NASTY
    assert world.run(a, "spawn", "--on", "bee", "builder", "/no/such", "x")[0] == 1


def test_spawn_on_an_unreachable_machine_is_a_clear_error(world, stub):
    a, b, bee = duo(world, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    code, _, err = world.run(a, "spawn", "--on", "gone", "n", stub[1], "p")
    assert code == 1 and "spawn on gone unreachable" in err


def test_todo_spawn_on_copies_the_todo_there_and_reserves_it_here(world, stub):
    out_file, work = stub
    a, b, bee = duo(world)
    world.run(a, "todo", "add", "fix it: 'now'", "--ref", "/r/x", "--notes", "a b")
    code, out, err = world.run(a, "todo", "spawn", "1", "--on", "bee", "--cwd", work)
    assert code == 0, err
    assert "started todo-1 on bee for to-do 1 (its copy there is to-do 1)" in out
    there = dict(bee.db().execute("SELECT * FROM todos").fetchone())
    assert there["title"] == "fix it: 'now'" and there["reserved_for"] == "todo-1" and there["notes"] == "a b"
    prompt = open(out_file).read()
    assert "/fleet todo claim 1" in prompt and "Reference: /r/x" in prompt
    here = json.loads(world.run(a, "todo", "ls", "--json")[1])
    assert here[0]["reserved_for"] == "todo-1@bee"


def test_a_failed_todo_spawn_on_releases_the_reservation_here(world, stub):
    a, b, bee = duo(world)
    world.run(a, "todo", "add", "x")
    code, _, err = world.run(a, "todo", "spawn", "1", "--on", "bee", "--cwd", "/no/such")
    assert code == 1
    assert json.loads(world.run(a, "todo", "ls", "--json")[1])[0]["reserved_for"] is None
