"""Confirmed delivery (a marker in the target's transcript), the SendMessage fallback, the documented sources for
liveness, the socket and the spawn id, and the canary. Sessions, ssh and `claude` are fakes; a fake session
writes what it receives into a fake transcript, or deliberately does not."""
import json
import os
import re
import sqlite3
import threading
import time

import pytest

from fleet_testkit import fleet, wait_for, world  # noqa: F401
from test_fleet_machines import duo
from test_fleet_messaging import msg_id, two

MARK = re.compile(r"fleet-ref-(\d+)-([0-9a-f]{8})")


def pair(world, writes=True):
    """alpha, and beta whose transcript is known (recorded at SessionStart) and gets what it receives."""
    a = world.session("alpha")
    b = world.session("beta", transcript=True)
    b.writes = writes
    b.record_start()
    assert world.member(a)[0] == 0 and world.member(b)[0] == 0
    return a, b


def row(world, mid):
    world.here_env()
    return fleet.db().execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()


def inbox_notes(world):
    world.here_env()
    return [r["body"] for r in fleet.db().execute("SELECT body FROM messages WHERE kind='notify' ORDER BY id")]


def calls(world):
    try:
        return [json.loads(x) for x in open(os.path.join(world.stub_dir, "calls.jsonl"))]
    except OSError:
        return []


# ---------------------------------------------------------------- the marker

def test_a_tell_carries_a_marker_and_is_confirmed_when_it_shows_in_the_target_transcript(world):
    a, b = pair(world)
    code, out, _ = world.run(a, "tell", "beta", "run the tests")
    assert code == 0, out
    mid = msg_id(out, "beta")
    assert "message %d to beta: delivered (confirmed in its transcript)" % mid in out
    [m] = b.messages()
    found = MARK.search(m["message"]["content"])
    assert found and int(found.group(1)) == mid
    r = row(world, mid)
    assert r["delivery"] == "confirmed" and r["confirmed_at"] and r["nonce"] == found.group(2)
    assert r["delivered_at"] and r["scan_from"] == 0


def test_two_identical_messages_get_different_markers(world):
    a, b = pair(world)
    world.run(a, "tell", "beta", "same")
    world.run(a, "tell", "beta", "same")
    marks = [MARK.search(m["message"]["content"]).group(0) for m in b.messages()]
    assert len(set(marks)) == 2  # Claude Code drops identical repeats; the nonce keeps each one apart


def test_a_member_with_no_known_transcript_is_delivered_but_not_checked(world):
    a, b = two(world)
    code, out, _ = world.run(a, "tell", "beta", "hi")
    mid = msg_id(out, "beta")
    assert out.strip().endswith("message %d to beta: delivered" % mid)
    assert row(world, mid)["delivery"] == "delivered"


def test_join_takes_the_transcript_path_from_the_history_row_or_the_hook_input(world):
    a, b = pair(world)
    world.here_env()
    assert fleet.db().execute("SELECT transcript_path FROM members WHERE name='beta'").fetchone()[0] == b.transcript
    c = world.session("gamma", transcript=True)
    stdin = json.dumps({"session_id": c.sid, "cwd": "/work/x", "transcript_path": c.transcript})
    from test_fleet_messaging import hook
    r = hook(world, "join.sh", stdin, {"FLEET_JOIN_NAME": "gamma", "CLAUDE_CODE_SESSION_ID": c.sid,
                                       "CLAUDE_CODE_MESSAGING_SOCKET": c.sock_path})
    assert r.returncode == 0, r.stderr
    assert fleet.db().execute("SELECT transcript_path FROM members WHERE name='gamma'").fetchone()[0] == c.transcript


def test_a_marker_that_lands_late_confirms_it_without_the_fallback(world):
    a, b = pair(world, writes=False)
    world.mp.setenv("FLEET_CONFIRM_WINDOW", "5")
    code, out, _ = world.run(a, "tell", "beta", "slow")
    mid = msg_id(out, "beta")
    assert "not seen in its transcript yet" in out and row(world, mid)["delivery"] == "unconfirmed"
    mark = MARK.search(b.messages()[0]["message"]["content"]).group(0)
    threading.Timer(0.6, lambda: b.append_transcript(mark)).start()
    assert world.run(a, "_confirm", str(mid))[0] == 0
    assert row(world, mid)["delivery"] == "confirmed"
    assert not [c for c in calls(world) if "-p" in c["argv"]]
    assert inbox_notes(world) == []


# ---------------------------------------------------------------- the fallback

def test_unconfirmed_after_the_window_falls_back_to_send_message_and_confirms_again(world):
    a, b = pair(world, writes=False)
    world.mp.setenv("FLEET_CONFIRM_WINDOW", "0.3")
    world.mp.setenv("FLEET_FALLBACK_WINDOW", "3")
    world.mp.setenv("STUB_TRANSCRIPT", b.transcript)  # the headless claude's SendMessage reaches beta
    mid = msg_id(world.run(a, "tell", "beta", "rebase now")[1], "beta")
    assert world.run(a, "_confirm", str(mid))[0] == 0
    assert row(world, mid)["delivery"] == "confirmed"
    [call] = [c for c in calls(world) if "-p" in c["argv"]]
    assert call["no_record"] == "1" and call["session_env"] is None
    assert "--allowedTools" in call["argv"] and "SendMessage,ListAgents" in call["argv"]
    asked = open(os.path.join(world.stub_dir, "headless.txt")).read()
    assert "SendMessage" in asked and "'beta'" in asked and b.sid in asked
    assert "Fleet tell %d from alpha: rebase now" % mid in asked  # the same text, with a new marker
    assert len(set(MARK.findall(asked))) == 1 and MARK.search(asked).group(2) != row(world, mid)["nonce"]
    assert inbox_notes(world) == []


def test_still_unconfirmed_after_the_fallback_is_failed_and_the_user_is_told_in_one_line(world):
    a, b = pair(world, writes=False)
    world.mp.setenv("FLEET_CONFIRM_WINDOW", "0.3")
    world.mp.setenv("FLEET_FALLBACK_WINDOW", "0.3")
    mid = msg_id(world.run(a, "tell", "beta", "lost")[1], "beta")
    assert world.run(a, "_confirm", str(mid))[0] == 0
    assert row(world, mid)["delivery"] == "failed"
    [note] = inbox_notes(world)
    assert "\n" not in note and "Message %d to beta was not delivered" % mid in note
    code, out, _ = world.run(a, "thread", str(mid), "--json")
    assert json.loads(out)[0]["delivery"] == "failed"
    log = open(os.path.join(world.here.home, "hooks.log")).read()
    assert "message %d to beta: failed" % mid in log


def test_a_failing_headless_call_fails_the_message_with_its_reason(world):
    a, b = pair(world, writes=False)
    world.mp.setenv("FLEET_CONFIRM_WINDOW", "0.2")
    world.mp.setenv("STUB_HEADLESS_FAIL", "1")
    mid = msg_id(world.run(a, "tell", "beta", "x")[1], "beta")
    world.run(a, "_confirm", str(mid))
    assert row(world, mid)["delivery"] == "failed" and "claude -p failed" in inbox_notes(world)[0]


def test_confirm_does_nothing_for_a_message_that_is_not_unconfirmed(world):
    a, b = pair(world)
    mid = msg_id(world.run(a, "tell", "beta", "x")[1], "beta")
    assert row(world, mid)["delivery"] == "confirmed"
    assert world.run(a, "_confirm", str(mid))[0] == 0
    assert not [c for c in calls(world) if "-p" in c["argv"]]


def test_the_follow_up_is_started_detached_so_the_sender_returns_at_once(world, monkeypatch):
    a, b = pair(world, writes=False)
    monkeypatch.setenv("FLEET_CONFIRM_DETACH", "1")
    started = []
    real = fleet.subprocess.Popen

    def popen(cmd, **kw):
        if "_confirm" not in cmd:
            return real(cmd, **kw)
        started.append((cmd, kw))
    monkeypatch.setattr(fleet.subprocess, "Popen", popen)
    t0 = time.time()
    code, out, _ = world.run(a, "tell", "beta", "x")
    assert code == 0 and time.time() - t0 < 3
    [(cmd, kw)] = started
    assert cmd[1].endswith("fleet.py") and cmd[2] == "_confirm" and kw["start_new_session"] is True


def test_across_machines_the_target_machine_confirms_and_says_so(world):
    a, b, bee = duo(world)
    c = bee.session("gamma", transcript=True)
    c.record_start()
    assert world.member(c)[0] == 0
    world.here_env()
    code, out, err = world.run(a, "tell", "gamma@bee", "hello")
    assert code == 0, err
    assert "delivered (confirmed in its transcript)" in out
    assert MARK.search(c.messages()[0]["message"]["content"])


# ---------------------------------------------------------------- the socket

def test_an_error_reply_from_the_socket_is_a_failed_delivery_with_its_reason(world):
    a, b = pair(world)
    b.reply = b'{"type":"error","message":"inbox full"}\n'
    code, out, err = world.run(a, "tell", "beta", "x")
    mid = msg_id(out, "beta")
    assert "message %d to beta: failed" % mid in out and "inbox full" in err
    assert row(world, mid)["delivery"] == "failed" and row(world, mid)["delivered_at"] is None


@pytest.mark.parametrize("reply,problem", [
    (b'{"error":"refused"}\n', "refused"),
    (b'{"ok":false,"reason":"held"}\n', "held"),
    (b'{"type":"ack"}\n', None),
    (b"", None),
    (b"plain text\n", None),
])
def test_reply_problem_reads_only_explicit_refusals(reply, problem):
    assert fleet.reply_problem(reply) == problem


def test_the_socket_comes_from_the_environment_at_join_not_from_the_sessions_file(world):
    a, b = two(world)
    b.info["messagingSocketPath"] = "/nonexistent/other.sock"  # the undocumented file now disagrees
    b.write_info()
    code, out, _ = world.run(a, "tell", "beta", "still arrives")
    assert code == 0 and "delivered" in out
    assert wait_for(lambda: b.messages())


def test_a_peer_token_file_is_never_read(world):
    a, b = two(world)
    with open(os.path.join(b.dir, "%d.abc.key" % b.pid), "w") as f:
        json.dump({"peerToken": "secret"}, f)
    world.run(a, "tell", "beta", "x")
    assert wait_for(lambda: b.messages()) and b.auths() == []
    assert not hasattr(fleet, "peer_token")


def test_join_finds_the_session_by_claude_agents_even_with_no_sessions_file(world):
    a = world.session("alpha")
    os.unlink(os.path.join(a.dir, "%d.json" % a.pid))
    with open(os.path.join(world.stub_dir, "agents.json"), "w") as f:
        json.dump([{"pid": a.pid, "sessionId": a.sid, "cwd": "/work/x", "name": "alpha", "kind": "interactive"}], f)
    code, out, err = world.member(a, "alpha")
    assert code == 0, err
    world.here_env()
    row = fleet.db().execute("SELECT pid, socket, cwd FROM members WHERE name='alpha'").fetchone()
    assert (row["pid"], row["socket"], row["cwd"]) == (a.pid, a.sock_path, "/work/x")


# ---------------------------------------------------------------- spawn

def test_spawn_takes_the_id_from_claude_agents_by_name(world):
    from test_fleet_spawn_backlog import runner, stub  # noqa: F401
    work = os.path.join(world.base, "w")
    os.makedirs(work)
    world.mp.setenv("STUB_BG_ID", "9f8e7d6c")
    world.mp.setenv("STUB_PRINT_ID", "deadbeef")  # what --bg prints is not what the id is read from
    code, out, err = runner(world)("spawn", "builder", work, "go", "--json")
    assert code == 0, err
    assert json.loads(out)["id"] == "9f8e7d6c"


def test_spawn_says_so_when_the_started_session_is_never_listed(world):
    work = os.path.join(world.base, "w")
    os.makedirs(work)
    world.mp.setenv("STUB_START_UNLISTED", "1")
    world.mp.setenv("FLEET_FIND_WAIT", "0.5")
    code, out, err = world.run(world.session("alpha"), "spawn", "builder", work, "go")
    assert code == 1 and "does not list it" in err


# ---------------------------------------------------------------- canary

@pytest.fixture
def canary_world(world, monkeypatch):
    """`claude --bg` starts nothing real: the wrapper gives the scratch session a fake process, joins it as the
    plugin's hook would, and records its transcript."""
    monkeypatch.setenv("FLEET_CANARY_DIR", os.path.join(world.base, "canary"))
    monkeypatch.setenv("FLEET_CANARY_JOIN_WAIT", "2")
    monkeypatch.setenv("FLEET_CONFIRM_WINDOW", "0.3")
    monkeypatch.setenv("FLEET_FALLBACK_WINDOW", "0.3")
    state = {"session": None, "joins": True, "writes": True}
    real = fleet.start_background

    def start(args, cwd, name, prompt=None):
        assert os.path.isdir(cwd) and os.path.dirname(cwd) == os.path.join(world.base, "canary")
        open(os.path.join(cwd, "scratch.txt"), "w").write("x")
        out = real(args, cwd, name, prompt)
        if state["joins"]:
            s = world.session(name, transcript=True)
            s.writes = state["writes"]
            s.record_start()
            assert world.member(s, name)[0] == 0
            state["session"] = s
        return out
    monkeypatch.setattr(fleet, "start_background", start)
    world.canary = state
    return world


def run_canary(world, *extra):
    world.here_env()
    for k in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_MESSAGING_SOCKET"):
        world.mp.delenv(k, raising=False)
    world.capsys.readouterr()
    code = fleet.main(["canary", *extra])
    o = world.capsys.readouterr()
    return code, o.out, o.err


def stopped_and_removed(world, sid="ab12cd34"):
    argvs = [c["argv"] for c in calls(world)]
    return ["stop", sid] in argvs and ["rm", sid] in argvs


def test_canary_passes_when_the_message_is_confirmed_and_leaves_nothing_behind(canary_world):
    w = canary_world
    code, out, err = run_canary(w)
    assert code == 0 and out.startswith("fleet canary ok: message ") and err == "", (out, err)
    assert stopped_and_removed(w)
    assert os.listdir(os.path.join(w.base, "canary")) == []  # its folder and what it held are gone
    s = w.canary["session"]
    assert not os.path.exists(s.transcript)  # its own transcript, by exact name
    w.here_env()
    con = fleet.db()
    assert con.execute("SELECT COUNT(*) FROM members WHERE session_id=?", (s.sid,)).fetchone()[0] == 0  # the row is gone
    assert con.execute("SELECT COUNT(*) FROM conversations WHERE session_id=?", (s.sid,)).fetchone()[0] == 0
    assert inbox_notes(w) == []
    [spawn_call] = [c for c in calls(w) if "--bg" in c["argv"]]
    assert "--model" in spawn_call["argv"] and spawn_call["argv"][spawn_call["argv"].index("-n") + 1].startswith("fleet-canary-")
    assert os.path.realpath(spawn_call["cwd"]).startswith(os.path.realpath(os.path.join(w.base, "canary")))


def test_canary_json_reports_the_steps(canary_world):
    code, out, _ = run_canary(canary_world, "--json")
    d = json.loads(out)
    assert code == 0 and d["ok"] is True and d["reason"] == "" and d["delivery"] == "confirmed"
    assert d["id"] == "ab12cd34" and d["message"] and any("joined as fleet-canary-" in s for s in d["steps"])


def test_canary_fails_with_one_line_and_tells_the_user_when_nothing_gets_delivered(canary_world):
    w = canary_world
    w.canary["writes"] = False
    code, out, err = run_canary(w)
    assert code == 1 and out == "" and err.startswith("fleet canary FAILED: the message was not delivered: failed")
    assert len(err.strip().splitlines()) == 1
    assert stopped_and_removed(w)
    assert os.listdir(os.path.join(w.base, "canary")) == []
    notes = inbox_notes(w)
    assert any(n.startswith("fleet canary failed: the message was not delivered") for n in notes)


def test_canary_flags_a_direct_post_that_only_the_fallback_delivered(canary_world):
    w = canary_world
    w.canary["writes"] = False

    real = fleet.fallback_send

    def send_through(name, sid, text):
        w.canary["session"].append_transcript(text)  # SendMessage reaches the session; the socket post did not
        return real(name, sid, text)
    w.mp.setattr(fleet, "fallback_send", send_through)
    code, _, err = run_canary(w)
    assert code == 1 and "only the SendMessage fallback delivered" in err
    assert any("fleet canary failed" in n for n in inbox_notes(w))


def test_canary_fails_when_the_scratch_session_never_joins(canary_world):
    w = canary_world
    w.canary["joins"] = False
    code, _, err = run_canary(w)
    assert code == 1 and "did not join the fleet in time" in err
    assert stopped_and_removed(w)
    assert os.listdir(os.path.join(w.base, "canary")) == []
    assert any("did not join" in n for n in inbox_notes(w))


def test_canary_fails_when_the_session_cannot_be_started(canary_world):
    w = canary_world
    w.mp.setenv("STUB_FAIL", "This folder is not trusted")
    code, _, err = run_canary(w)
    assert code == 1 and "could not start the scratch session" in err and "trust" in err
    assert os.listdir(os.path.join(w.base, "canary")) == []
    assert any("could not start" in n for n in inbox_notes(w))


def test_canary_cleans_up_a_session_that_was_started_but_whose_id_was_never_reported(canary_world):
    w = canary_world

    def start_then_break(name, cwd, prompt, as_json=False, on=None, extra=()):
        fleet.start_background(["--bg", "-n", name], cwd, name)  # the session exists now ...
        raise fleet.FleetError("boom")  # ... but spawn dies before it can report its id
    w.mp.setattr(fleet, "spawn", start_then_break)
    code, _, err = run_canary(w)
    assert code == 1 and "boom" in err
    assert stopped_and_removed(w)  # found by name in `claude agents --json`
    s = w.canary["session"]
    w.here_env()
    con = fleet.db()
    assert con.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM conversations WHERE session_id=?", (s.sid,)).fetchone()[0] == 0
    assert os.listdir(os.path.join(w.base, "canary")) == []


def test_canary_deletes_the_history_row_only_after_the_session_has_ended(canary_world):
    w = canary_world
    real = fleet.listed
    state = {"calls": 0}

    def listed_once_more(name, sid):
        state["calls"] += 1
        if state["calls"] == 1:  # the stopping session's SessionEnd hook writes its history row again
            w.canary["session"].record_start()
            return True
        return real(name, sid)
    w.mp.setattr(fleet, "listed", listed_once_more)
    code, out, err = run_canary(w)
    assert code == 0, (out, err)
    s = w.canary["session"]
    w.here_env()
    assert state["calls"] >= 2
    assert fleet.db().execute("SELECT COUNT(*) FROM conversations WHERE session_id=?", (s.sid,)).fetchone()[0] == 0


def test_canary_reports_a_session_that_never_leaves_the_agents_list(canary_world):
    w = canary_world
    w.mp.setenv("FLEET_CANARY_END_WAIT", "0.4")
    w.mp.setattr(fleet, "listed", lambda name, sid: True)
    code, _, err = run_canary(w)
    assert code == 1 and "is still listed by `claude agents --json`" in err


# ---------------------------------------------------------------- no second copy to a busy session

def set_status(world, session, status):
    """What `claude agents --json` says about the session's turn (the stub adds agents.json to its list)."""
    path = os.path.join(world.stub_dir, "agents.json")
    if status is None:
        if os.path.exists(path):
            os.unlink(path)
        return
    with open(path, "w") as f:
        json.dump([{"sessionId": session.sid, "name": session.name, "kind": "interactive", "status": status}], f)


def test_a_busy_session_is_not_sent_a_second_copy_while_its_turn_runs(world):
    a, b = pair(world, writes=False)
    world.mp.setenv("FLEET_CONFIRM_WINDOW", "0.3")
    world.mp.setenv("FLEET_BUSY_WINDOW", "10")
    world.mp.setenv("FLEET_BUSY_STEP", "0.5")
    mid = msg_id(world.run(a, "tell", "beta", "queued behind a long turn")[1], "beta")
    set_status(world, b, "busy")
    mark = MARK.search(b.messages()[0]["message"]["content"]).group(0)
    threading.Timer(1.2, lambda: b.append_transcript(mark)).start()  # the turn ends, the queued message is read
    assert world.run(a, "_confirm", str(mid))[0] == 0
    assert row(world, mid)["delivery"] == "confirmed"
    assert not [c for c in calls(world) if "-p" in c["argv"]]  # no SendMessage fallback
    assert inbox_notes(world) == []


def test_an_idle_session_that_stays_silent_still_gets_the_fallback_after_a_busy_spell(world):
    a, b = pair(world, writes=False)
    world.mp.setenv("FLEET_CONFIRM_WINDOW", "0.3")
    world.mp.setenv("FLEET_FALLBACK_WINDOW", "0.3")
    world.mp.setenv("FLEET_BUSY_WINDOW", "10")
    world.mp.setenv("FLEET_BUSY_STEP", "0.5")
    mid = msg_id(world.run(a, "tell", "beta", "lost")[1], "beta")
    set_status(world, b, "busy")
    threading.Timer(1.0, lambda: set_status(world, b, None)).start()
    assert world.run(a, "_confirm", str(mid))[0] == 0
    assert row(world, mid)["delivery"] == "failed"
    assert len([c for c in calls(world) if "-p" in c["argv"]]) == 1


def test_either_marker_confirms_a_message_the_fallback_was_sent_for(world):
    a, b = pair(world, writes=False)
    world.mp.setenv("FLEET_CONFIRM_WINDOW", "0.3")
    world.mp.setenv("FLEET_FALLBACK_WINDOW", "3")
    mid = msg_id(world.run(a, "tell", "beta", "slow but not lost")[1], "beta")
    mark = MARK.search(b.messages()[0]["message"]["content"]).group(0)  # the ORIGINAL marker lands late
    threading.Timer(0.8, lambda: b.append_transcript(mark)).start()
    assert world.run(a, "_confirm", str(mid))[0] == 0
    assert row(world, mid)["delivery"] == "confirmed" and inbox_notes(world) == []
