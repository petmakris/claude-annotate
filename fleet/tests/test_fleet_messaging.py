import json
import os
import subprocess
import sys
import threading
import time

import pytest

from fleet_testkit import ROOT, fleet, wait_for, world  # noqa: F401


def thread_id(out):
    return out.splitlines()[0].split()[1]


def msg_id(out, name):
    for ln in out.splitlines():
        if ln.startswith("message ") and " to %s:" % name in ln:
            return int(ln.split()[1])
    raise AssertionError(out)


def two(world):
    a, b = world.session("alpha"), world.session("beta")
    assert world.member(a)[0] == 0 and world.member(b)[0] == 0
    return a, b


def test_join_uses_the_session_name_and_records_the_respawn_command(world):
    a = world.session("alpha", cwd="/work/some dir")
    code, out, err = world.member(a)
    assert code == 0 and out.strip() == "joined the fleet as alpha"
    code, out, _ = world.run(a, "ls", "--json")
    [m] = json.loads(out)
    assert m["name"] == "alpha" and m["status"] == "alive" and m["session_id"] == a.sid
    assert m["respawn"] == "cd '/work/some dir' && claude --resume %s -n alpha" % a.sid


def test_join_with_an_explicit_name_and_a_folder_default(world):
    a = world.session("alpha", cwd="/work/proj")
    a.info["name"] = None
    a.write_info()
    assert world.member(a)[1].strip().endswith("as proj")
    assert world.member(a, "other")[1].strip().endswith("as other")
    [m] = json.loads(world.run(a, "ls", "--json")[1])
    assert m["name"] == "other"


def test_join_refuses_a_name_held_by_a_live_member(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a)
    code, out, err = world.member(b, "alpha")
    assert code == 1 and "'alpha' is taken by a live member" in err and a.sid in err


def test_join_takes_a_name_from_a_dead_holder(world):
    a, b = world.session("alpha"), world.session("beta")
    world.member(a)
    a.die()
    assert world.member(b, "alpha")[0] == 0
    names = [(m["name"], m["status"]) for m in json.loads(world.run(b, "ls", "--json")[1])]
    assert names == [("alpha", "alive")]


def test_ls_reports_dead_and_left_members(world):
    a, b = two(world)
    b.die()
    rows = {m["name"]: m["status"] for m in json.loads(world.run(a, "ls", "--json")[1])}
    assert rows == {"alpha": "alive", "beta": "dead"}
    world.run(a, "leave")
    rows = {m["name"]: m["status"] for m in json.loads(world.run(a, "ls", "--json", "--all")[1])}
    assert rows == {"alpha": "left", "beta": "dead"}


def test_a_session_that_claude_agents_does_not_list_is_dead(world):
    a, b = two(world)
    world.mp.setenv("STUB_HIDE", "beta")  # its process runs, but `claude agents --json` does not list it
    rows = {m["name"]: m["status"] for m in json.loads(world.run(a, "ls", "--json")[1])}
    assert rows == {"alpha": "alive", "beta": "dead"}


def test_without_claude_agents_a_reused_pid_with_another_start_time_is_dead(world):
    a, b = two(world)
    world.mp.setenv("STUB_AGENTS_BROKEN", "1")  # the fallback: the pid and start time recorded at join
    rows = {m["name"]: m["status"] for m in json.loads(world.run(a, "ls", "--json")[1])}
    assert rows == {"alpha": "alive", "beta": "alive"}
    b.info["procStart"] = "a different process"
    b.write_info()
    rows = {m["name"]: m["status"] for m in json.loads(world.run(a, "ls", "--json")[1])}
    assert rows["beta"] == "dead"


def test_tell_posts_the_exact_wire_format(world):
    a, b = two(world)
    code, out, _ = world.run(a, "tell", "beta", "run the tests")
    assert code == 0 and "delivered" in out
    mid = msg_id(out, "beta")
    assert wait_for(lambda: b.messages())
    assert b.auths() == []  # the auth line is optional on macOS and Linux (documented), so none is sent
    [m] = b.messages()
    assert m["msgV"] == 1 and m["type"] == "user" and m["priority"] == "next" and m["msg_id"]
    assert m["from"] == "uds:" + a.sock_path
    c = m["message"]["content"]
    assert m["message"]["role"] == "user"
    assert c.startswith('<cross-session-message from="uds:%s" from-name="alpha">\n' % a.sock_path)
    assert c.endswith("\n</cross-session-message>")
    assert "Fleet tell %d from alpha: run the tests" % mid in c
    assert "`/fleet ack %d`" % mid in c


def test_ask_wake_line_says_how_to_answer_and_long_bodies_are_cut(world):
    a, b = two(world)
    long = "word " * 200
    code, out, _ = world.run(a, "ask", "beta", long)
    mid = msg_id(out, "beta")
    assert wait_for(lambda: b.messages())
    c = b.messages()[0]["message"]["content"]
    assert 'Reply once with `/fleet answer %d "YOUR ANSWER"`' % mid in c
    assert "cut; the full text is in `fleet thread`" in c
    assert long.strip() not in c
    body = json.loads(world.run(a, "thread", thread_id(out), "--json")[1])[0]["body"]
    assert body == long


def test_ask_answer_wait_round_trip(world):
    a, b = two(world)
    _, out, _ = world.run(a, "ask", "beta", "which session works on X?")
    th, mid = thread_id(out), msg_id(out, "beta")
    code, out, err = world.run(b, "answer", str(mid), "me, on X")
    assert code == 0 and "asker: delivered" in out
    assert wait_for(lambda: a.messages())
    c = a.messages()[0]["message"]["content"]
    assert 'from-name="beta"' in c and "Fleet answer" in c and "me, on X" in c and th in c
    code, out, _ = world.run(a, "wait", th, "--timeout", "5")
    assert code == 0 and "me, on X" in out and out.strip().endswith("all answered")


def test_answering_twice_or_the_wrong_message_is_refused(world):
    a, b = two(world)
    c = world.session("gamma")
    world.member(c)
    mid = msg_id(world.run(a, "ask", "beta", "q?")[1], "beta")
    assert world.run(c, "answer", str(mid), "x")[0] == 1
    assert world.run(b, "answer", str(mid), "once")[0] == 0
    code, _, err = world.run(b, "answer", str(mid), "twice")
    assert code == 1 and "already answered" in err
    tid = msg_id(world.run(a, "tell", "beta", "do")[1], "beta")
    assert world.run(b, "answer", str(tid), "x")[0] == 1


def test_tell_is_closed_by_an_ack(world):
    a, b = two(world)
    out = world.run(a, "tell", "beta", "rebase")[1]
    th, mid = thread_id(out), msg_id(out, "beta")
    code, out, _ = world.run(b, "ack", str(mid))
    assert code == 0
    assert a.messages() == []  # an ack stores; it does not wake the sender
    code, out, _ = world.run(a, "wait", th, "--timeout", "5")
    assert code == 0 and "ack beta -> alpha" in out


def test_broadcast_fans_out_to_every_live_member_but_the_sender(world):
    a, b = two(world)
    c, d = world.session("gamma"), world.session("delta")
    world.member(c), world.member(d)
    d.die()
    code, out, _ = world.run(a, "ask", "*", "who works on X?")
    assert code == 0
    lines = [ln for ln in out.splitlines() if ln.startswith("message")]
    assert sorted(ln.split()[3].rstrip(":") for ln in lines) == ["beta", "gamma"]
    assert wait_for(lambda: b.messages() and c.messages())
    assert a.messages() == [] and d.messages() == []
    th = thread_id(out)
    rows = json.loads(world.run(a, "thread", th, "--json")[1])
    assert len(rows) == 2 and {r["thread"] for r in rows} == {th}


def test_broadcast_wait_collects_every_answer(world):
    a, b = two(world)
    c = world.session("gamma")
    world.member(c)
    out = world.run(a, "ask", "*", "who?")[1]
    th = thread_id(out)
    world.run(b, "answer", str(msg_id(out, "beta")), "not me")
    world.run(c, "answer", str(msg_id(out, "gamma")), "me")
    code, out, _ = world.run(a, "wait", th, "--timeout", "5")
    assert code == 0 and "not me" in out and "me\n" in out


def test_wait_times_out_and_names_who_is_missing(world):
    a, b = two(world)
    th = thread_id(world.run(a, "ask", "beta", "anyone?")[1])
    t0 = time.time()
    code, out, _ = world.run(a, "wait", th, "--timeout", "0.5")
    assert code == 3 and "timed out; no answer from: beta" in out
    assert time.time() - t0 < 3


def test_wait_returns_as_soon_as_a_late_answer_lands(world):
    a, b = two(world)
    out = world.run(a, "ask", "beta", "q?")[1]
    th, mid = thread_id(out), msg_id(out, "beta")

    def late():
        time.sleep(0.6)
        con = fleet.db()
        con.execute("UPDATE messages SET answered_at=1 WHERE id=?", (mid,))

    t = threading.Thread(target=late)
    t.start()
    t0 = time.time()
    code, _, _ = world.run(a, "wait", th, "--timeout", "10")
    t.join()
    assert code == 0 and 0.4 < time.time() - t0 < 5


def test_a_message_to_a_dead_member_is_stored_and_waits(world):
    a, b = two(world)
    b.die()
    code, out, _ = world.run(a, "tell", "beta", "later")
    assert code == 0 and "beta: waiting (dead; it will wait)" in out
    rows = json.loads(world.run(a, "thread", thread_id(out), "--json")[1])
    assert rows[0]["delivered_at"] is None and rows[0]["body"] == "later"


def test_a_dead_socket_is_reported_failed_not_fatal(world):
    a, b = two(world)
    b.srv.close()
    os.unlink(b.sock_path)
    code, out, _ = world.run(a, "tell", "beta", "hi")
    assert code == 0 and "beta: failed" in out


def test_errors_unknown_target_self_target_and_not_joined(world):
    a = world.session("alpha")
    code, _, err = world.run(a, "tell", "beta", "x")
    assert code == 1 and "has not joined" in err
    world.member(a)
    code, _, err = world.run(a, "tell", "nobody", "x")
    assert code == 1 and "no member named 'nobody'" in err
    assert "is this session" in world.run(a, "tell", "alpha", "x")[2]
    assert "no other live member" in world.run(a, "tell", "*", "x")[2]


def test_unknown_session_is_an_error(world, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "nope")
    monkeypatch.delenv("CLAUDE_CODE_MESSAGING_SOCKET", raising=False)
    assert fleet.main(["join"]) == 1


def test_identity_falls_back_to_the_socket(world, monkeypatch):
    a = world.session("alpha")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_SOCKET", a.sock_path)
    assert fleet.main(["join"]) == 0


def test_thread_accepts_a_message_id(world):
    a, b = two(world)
    out = world.run(a, "tell", "beta", "hello there")[1]
    code, shown, _ = world.run(a, "thread", str(msg_id(out, "beta")))
    assert code == 0 and "tell alpha -> beta" in shown and "hello there" in shown
    assert world.run(a, "thread", "ffffffff")[0] == 1


def hook(world, script, stdin, env):
    e = dict(os.environ, FLEET_HOME=os.path.join(world.base, "home"), FLEET_SESSIONS_DIR=os.path.join(world.base, "sessions"))
    for k in ("FLEET_JOIN_NAME", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET"):
        e.pop(k, None)
    e.update(env)
    return subprocess.run(["sh", os.path.join(ROOT, "hooks", script)], input=stdin, capture_output=True, text=True, env=e, timeout=30)


def test_session_start_hook_joins_only_when_fleet_join_name_is_set(world):
    a = world.session("alpha")
    stdin = json.dumps({"session_id": a.sid, "cwd": "/work/x"})
    r = hook(world, "join.sh", stdin, {})
    assert r.returncode == 0 and r.stdout == "" and not os.path.exists(os.path.join(world.base, "home", "fleet.db"))
    r = hook(world, "join.sh", stdin, {"FLEET_JOIN_NAME": "job:one"})
    assert r.returncode == 0, r.stderr
    [m] = json.loads(world.run(a, "ls", "--json")[1])
    assert m["name"] == "job:one" and m["status"] == "alive"


def test_session_end_hook_leaves_and_is_silent_for_a_never_joined_session(world):
    a = world.session("alpha")
    stdin = json.dumps({"session_id": a.sid})
    r = hook(world, "leave.sh", stdin, {})
    assert r.returncode == 0 and r.stdout == "" and not os.path.exists(os.path.join(world.base, "home"))
    hook(world, "join.sh", stdin, {"FLEET_JOIN_NAME": "w"})
    assert hook(world, "leave.sh", stdin, {}).returncode == 0
    assert json.loads(world.run(a, "ls", "--json")[1]) == []


def test_hooks_json_declares_only_the_fleet_hooks_and_the_marketplace_points_at_the_plugin():
    h = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))
    assert set(h["hooks"]) == {"SessionStart", "SessionEnd", "Stop"}
    m = json.load(open(os.path.join(ROOT, "..", ".claude-plugin", "marketplace.json")))
    [p] = [p for p in m["plugins"] if p["name"] == "fleet"]
    assert p["source"] == "./fleet"
    assert json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))["name"] == "fleet"


def test_forget_removes_matching_members_and_keeps_live_ones_unless_asked(world):
    a, b, c = world.session("alpha"), world.session("beta"), world.session("gamma")
    world.member(a, "job:one"); world.member(b, "job:two"); world.member(c, "keeper")
    world.run(a, "leave")
    code, out, _ = world.run(c, "forget", "job:*")
    assert code == 0 and out == "forgot 1 member: job:one\nkept 1 live member (add --live to forget it too): job:two\n"
    assert [m["name"] for m in json.loads(world.run(c, "ls", "--json", "--all")[1])] == ["job:two", "keeper"]
    code, out, _ = world.run(c, "forget", "job:*", "--live")
    assert code == 0 and out == "forgot 1 member: job:two\n"
    assert [m["name"] for m in json.loads(world.run(c, "ls", "--json", "--all")[1])] == ["keeper"]
    assert world.run(c, "forget", "nobody")[1] == "no member matches nobody\n"
