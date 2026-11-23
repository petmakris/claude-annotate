import json
import os
import stat
import subprocess
import sys

import pytest

from fleet_testkit import ROOT, fleet, install_claude_stub, world  # noqa: F401

@pytest.fixture
def stub(world):
    install_claude_stub(world)
    out = os.path.join(world.base, "stub.out")
    world.mp.setenv("STUB_OUT", out)
    world.mp.setenv("STUB_PWD", "1")
    work = os.path.join(world.base, "work")
    os.makedirs(work)

    class S:
        args = lambda self: open(out).read().splitlines()
        cwd = work
    return S()


def runner(world, who=None):
    def run(*argv):
        if who:
            who.env(world.mp)
        else:
            world.mp.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
            world.mp.delenv("CLAUDE_CODE_MESSAGING_SOCKET", raising=False)
        world.capsys.readouterr()
        code = fleet.main(list(argv))
        o = world.capsys.readouterr()
        return code, o.out, o.err
    return run


def test_spawn_command_line_settings_and_output(world, stub):
    code, out, err = runner(world)("spawn", "builder", stub.cwd, "do", "the", "thing")
    assert code == 0, err
    a = stub.args()
    assert a[:3] == ["--bg", "-n", "builder"] and a[3] == "--settings"
    assert json.loads(a[4]) == {"env": {"FLEET_JOIN_NAME": "builder", "FLEET_HOME": os.path.join(world.base, "home")},
                                "crossSessionInbound": "accept"}
    assert a[5] == "do the thing" and os.path.realpath(a[6]) == os.path.realpath(stub.cwd)
    assert "id ab12cd34" in out and "claude attach builder" in out


def test_spawn_json_and_extra_args(world, stub):
    world.mp.setenv("FLEET_CLAUDE_ARGS", "--plugin-dir '/x y'")
    code, out, _ = runner(world)("spawn", "b", stub.cwd, "p", "--json")
    assert json.loads(out) == {"name": "b", "id": "ab12cd34", "cwd": stub.cwd, "attach": "claude attach b"}
    assert stub.args()[5:7] == ["--plugin-dir", "/x y"]


def test_spawn_refuses_a_live_name_and_a_missing_folder(world, stub):
    a = world.session("alpha")
    world.member(a)
    code, _, err = runner(world)("spawn", "alpha", stub.cwd, "p")
    assert code == 1 and "'alpha' is taken by a live member" in err
    assert not os.path.exists(os.path.join(world.base, "stub.out"))
    code, _, err = runner(world)("spawn", "zed", "/nonexistent-dir", "p")
    assert code == 1 and "is not a folder" in err


def test_spawn_untrusted_folder_prints_the_fix(world, stub):
    world.mp.setenv("STUB_FAIL", "This folder is not trusted: run claude here and accept the trust dialog")
    code, _, err = runner(world)("spawn", "b", stub.cwd, "p")
    assert code == 1 and "does not trust" in err and "accept the trust prompt" in err


def test_spawn_other_failure_is_reported(world, stub):
    world.mp.setenv("STUB_FAIL", "boom")
    code, _, err = runner(world)("spawn", "b", stub.cwd, "p")
    assert code == 1 and "failed (exit 1): boom" in err


def test_todo_lifecycle(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    ra, rb = runner(world, a), runner(world, b)
    assert ra("todo", "add", "Fix the thing", "--ref", "/p/README.md", "--notes", "soon")[1].strip() == "todo 1 added"
    [t] = json.loads(ra("todo", "ls", "--json")[1])
    assert (t["title"], t["ref"], t["notes"], t["state"], t["created_by"]) == (
        "Fix the thing", "/p/README.md", "soon", "open", "alpha")
    code, out, _ = rb("todo", "claim", "1")
    assert code == 0 and "claimed todo 1: Fix the thing" in out and "ref: /p/README.md" in out
    code, _, err = ra("todo", "claim", "1")
    assert code == 1 and "is claimed by beta" in err
    code, _, err = ra("todo", "done", "1")
    assert code == 1 and "only the member holding it" in err
    assert "[beta]" in ra("todo", "ls")[1]
    assert rb("todo", "release", "1")[0] == 0
    assert json.loads(ra("todo", "ls", "--json")[1])[0]["state"] == "open"
    assert ra("todo", "claim", "1")[0] == 0 and ra("todo", "done", "1")[0] == 0
    assert "no to-dos" in ra("todo", "ls")[1]
    [t] = json.loads(ra("todo", "ls", "--all", "--json")[1])
    assert t["state"] == "done" and t["claimed_by"] == "alpha"
    assert "is done" in ra("todo", "claim", "1")[2]
    assert "no to-do 9" in ra("todo", "claim", "9")[2]


def test_todo_add_works_without_joining_and_claim_needs_a_member(world):
    code, out, _ = runner(world)("todo", "add", "x")
    assert code == 0
    assert json.loads(runner(world)("todo", "ls", "--json")[1])[0]["created_by"] == "user"
    a = world.session("alpha")
    code, _, err = runner(world, a)("todo", "claim", "1")
    assert code == 1 and "has not joined" in err


def test_claim_race_between_two_processes(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    n = 8
    for i in range(n):
        runner(world, a)("todo", "add", "t%d" % i)
    script = os.path.join(world.base, "race.py")
    with open(script, "w") as f:
        f.write("import sys, time, os\nsys.path.insert(0, %r)\nimport fleet\n"
                "go = float(sys.argv[1])\nwon = []\n"
                "while time.time() < go: pass\n"
                "for i in range(1, %d + 1):\n"
                "    try:\n        fleet.todo_claim(i); won.append(i)\n"
                "    except fleet.FleetError: pass\n"
                "print('WON', won)\n" % (os.path.join(ROOT), n + 1))
    import time
    go = str(time.time() + 1.5)
    procs = []
    for s in (a, b):
        env = dict(os.environ, CLAUDE_CODE_SESSION_ID=s.sid, CLAUDE_CODE_MESSAGING_SOCKET=s.sock_path)
        procs.append(subprocess.Popen([sys.executable, script, go], env=env, stdout=subprocess.PIPE, text=True,
                                      stderr=subprocess.DEVNULL))
    wins = [json.loads(p.communicate()[0].splitlines()[-1].split(" ", 1)[1]) for p in procs]
    assert sorted(wins[0] + wins[1]) == list(range(1, n + 1)), wins  # each to-do has exactly one holder
    assert not set(wins[0]) & set(wins[1])
    holders = {t["id"]: t["claimed_by"] for t in json.loads(runner(world, a)("todo", "ls", "--json")[1])}
    assert all(holders[i] == "alpha" for i in wins[0]) and all(holders[i] == "beta" for i in wins[1])


def test_todo_spawn_reserves_prompts_and_only_the_spawned_name_claims(world, stub):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a), world.member(b)
    ra, rb = runner(world, a), runner(world, b)
    ra("todo", "add", "Tidy the docs", "--ref", "docs/README.md", "--notes", "keep it short")
    code, out, err = ra("todo", "spawn", "1", "--cwd", stub.cwd)
    assert code == 0, err
    a_ = stub.args()
    assert a_[2] == "todo-1" and json.loads(a_[4])["env"]["FLEET_JOIN_NAME"] == "todo-1"
    prompt = "\n".join(a_[5:-1])
    assert prompt.splitlines()[0] == "/fleet todo claim 1"
    assert "Tidy the docs" in prompt and "docs/README.md" in prompt and "keep it short" in prompt
    assert "fleet todo done 1" in prompt
    assert "reserved for todo-1" in rb("todo", "claim", "1")[2]
    assert "reserved for todo-1" in ra("todo", "spawn", "1")[2]
    # the spawned session, once joined, claims it
    c = world.session("todo-1")
    world.member(c, "todo-1")
    assert runner(world, c)("todo", "claim", "1")[0] == 0
    assert "[todo-1]" in ra("todo", "ls")[1]


def test_todo_spawn_failure_unreserves(world, stub):
    a = world.session("alpha")
    world.member(a)
    ra = runner(world, a)
    ra("todo", "add", "x")
    world.mp.setenv("STUB_FAIL", "boom")
    assert ra("todo", "spawn", "1", "--name", "w", "--cwd", stub.cwd)[0] == 1
    world.mp.delenv("STUB_FAIL")
    assert ra("todo", "claim", "1")[0] == 0
