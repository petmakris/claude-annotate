"""Manager control (stop, respawn, attach), redelivery when a member rejoins, the user's inbox (petros), notify,
and the page's writes. Sessions, ssh and `claude` are fakes."""
import json
import os
import stat
import sys
import threading
import urllib.error
import urllib.request

import pytest

from fleet_testkit import ROOT, fleet, install_claude_stub, world  # noqa: F401
from test_fleet_machines import duo
from test_fleet_messaging import hook, msg_id, thread_id, two
import fleet_history as hist

@pytest.fixture
def claude(world):
    d = install_claude_stub(world, "cafe0001")
    world.mp.delenv("FLEET_AS", raising=False)

    class C:
        def agents(self, *entries):
            with open(os.path.join(d, "agents.json"), "w") as f:
                json.dump([dict(kind="background", state="idle", **e) for e in entries], f)

        def calls(self):
            try:
                return [json.loads(x) for x in open(os.path.join(d, "calls.jsonl"))]
            except OSError:
                return []

        def bg(self, session, id="ab12cd34"):
            self.agents({"id": id, "sessionId": session.sid, "cwd": "/x", "name": session.name})
    c = C()
    c.agents()
    return c


def folder(world, name="proj"):
    p = os.path.join(world.base, name)
    os.makedirs(p, exist_ok=True)
    return p


def first_id(out):
    """The id in the first 'message N to ...' / 'notice N stored' line."""
    for ln in out.splitlines():
        if ln.startswith(("message ", "notice ")):
            return int(ln.split()[1])
    raise AssertionError(out)


# ---------------------------------------------------------------- redelivery

def rejoin_as(world, name, **kw):
    """A new session takes the name an earlier one had."""
    new = world.session(name + "2", **kw)
    new.info["name"] = name
    new.write_info()
    assert world.member(new, name)[0] == 0
    return new


def test_redelivery_of_an_undelivered_ask_to_the_member_that_rejoins(world):
    a, b = two(world)
    b.die()
    code, out, _ = world.run(a, "ask", "beta", "how far?")
    assert code == 0 and "waiting" in out
    mid = msg_id(out, "beta")
    new = rejoin_as(world, "beta")
    [line] = new.messages()
    assert "Fleet ask %d from alpha: how far?" % mid in line["message"]["content"]
    assert "Sent again" in line["message"]["content"]
    row = fleet.db().execute("SELECT recipient_session, delivered_at FROM messages WHERE id=?", (mid,)).fetchone()
    assert row["recipient_session"] == new.sid and row["delivered_at"] is not None
    assert world.run(new, "answer", str(mid), "far enough")[0] == 0
    assert "far enough" in world.run(a, "thread", str(mid))[1]


def test_redelivery_of_an_unanswered_tell_that_went_to_a_session_that_died(world):
    a, b = two(world)
    mid = msg_id(world.run(a, "tell", "beta", "rebase now")[1], "beta")
    assert len(b.messages()) == 1
    b.die()
    new = rejoin_as(world, "beta")
    assert len(new.messages()) == 1 and "rebase now" in new.messages()[0]["message"]["content"]
    assert fleet.db().execute("SELECT recipient_session FROM messages WHERE id=?", (mid,)).fetchone()[0] == new.sid
    assert len(b.messages()) == 1  # the dead one got nothing more


def test_redelivery_leaves_answered_messages_and_messages_to_a_live_session_alone(world):
    a, b = two(world)
    answered = msg_id(world.run(a, "ask", "beta", "one?")[1], "beta")
    world.run(b, "answer", str(answered), "yes")
    open_one = msg_id(world.run(a, "ask", "beta", "two?")[1], "beta")
    before = len(b.messages())
    code, out, _ = world.member(b, "beta")  # the same live session joins again
    assert code == 0 and "sent again" not in out and len(b.messages()) == before
    c = world.session("gamma")
    assert world.member(c, "gamma")[0] == 0  # another name: it owns nothing of beta's
    assert c.messages() == []
    assert fleet.db().execute("SELECT recipient_session FROM messages WHERE id=?", (open_one,)).fetchone()[0] == b.sid


def test_the_session_start_hook_redelivers_too(world):
    a, b = two(world)
    b.die()
    mid = msg_id(world.run(a, "tell", "beta", "pick up the notes")[1], "beta")
    new = world.session("beta2")
    r = hook(world, "join.sh", json.dumps({"session_id": new.sid, "cwd": "/work/x"}), {"FLEET_JOIN_NAME": "beta"})
    assert r.returncode == 0, r.stderr
    [line] = new.messages()
    assert "Fleet tell %d from alpha: pick up the notes" % mid in line["message"]["content"]


# ---------------------------------------------------------------- petros

def test_nobody_can_join_as_petros(world, claude):
    a = world.session("alpha")
    for name in ("petros", "Petros"):
        code, _, err = world.member(a, name)
        assert code == 1 and "reserved" in err
    assert fleet.main(["spawn", "petros", folder(world), "p"]) == 1


def test_a_session_outside_the_fleet_sends_as_petros(world):
    a = world.session("alpha")
    world.member(a)
    voice = world.session("voice")  # not joined
    code, out, err = world.run(voice, "tell", "alpha", "ship", "it", "--as", "petros")
    assert code == 0, err
    [line] = a.messages()
    assert line["message"]["content"].startswith('<cross-session-message from="fleet:petros" from-name="petros">')
    assert "Fleet tell %d from petros: ship it" % msg_id(out, "alpha") in line["message"]["content"]
    world.mp.setenv("FLEET_AS", "petros")
    assert world.run(voice, "ask", "alpha", "status?")[0] == 0
    world.mp.delenv("FLEET_AS")
    assert world.run(voice, "tell", "alpha", "no identity")[0] == 1  # not a member and not petros


def test_a_member_cannot_send_as_petros_and_no_other_name_works_for_as(world):
    a, b = two(world)
    code, _, err = world.run(a, "tell", "beta", "x", "--as", "petros")
    assert code == 1 and "speaks as itself" in err and b.messages() == []
    voice = world.session("voice")
    assert world.run(voice, "tell", "beta", "x", "--as", "alpha")[0] == 1


def test_a_message_to_petros_is_stored_not_posted_and_listed(world):
    a, b = two(world)
    code, out, _ = world.run(a, "ask", "petros", "may", "I", "drop", "the", "table?")
    assert code == 0 and "stored in his inbox" in out
    world.run(b, "notify", "tests", "are", "green")
    assert a.messages() == [] and b.messages() == []
    items = json.loads(world.run(a, "inbox", "--json")[1])
    assert [(i["kind"], i["sender"], i["body"], i["machine"], i["ref"]) for i in items] == [
        ("notify", "beta", "tests are green", fleet.self_machine(), "2"),
        ("ask", "alpha", "may I drop the table?", fleet.self_machine(), "1")]
    assert "[1] ask from alpha" in world.run(a, "inbox")[1]
    assert world.run(a, "tell", "*", "all")[0] == 0
    assert fleet.db().execute("SELECT count(*) FROM messages WHERE recipient='petros'").fetchone()[0] == 2


def test_petros_answers_and_the_asker_is_woken_with_the_answer(world):
    a, b = two(world)
    mid = first_id(world.run(a, "ask", "petros", "may I?")[1])
    voice = world.session("voice")
    code, out, err = world.run(voice, "answer", str(mid), "yes, go", "--as", "petros")
    assert code == 0, err
    assert "asker: delivered" in out
    [line] = a.messages()
    text = line["message"]["content"]
    assert "Fleet answer" in text and "yes, go" in text and "from petros" in text
    assert world.run(a, "inbox")[1].strip() == "nothing for petros"
    items = json.loads(world.run(a, "inbox", "--json", "--all")[1])
    assert [(i["reply"], i["answered_at"] is not None) for i in items] == [("yes, go", True)]
    assert world.run(voice, "answer", str(mid), "again", "--as", "petros")[0] == 1
    assert world.run(voice, "answer", "99", "x", "--as", "petros")[0] == 1


def test_dismissing_an_ask_releases_the_asker_and_a_notice_just_clears(world):
    a, b = two(world)
    th = thread_id(world.run(a, "ask", "petros", "ready?")[1])
    ask_id = first_id(world.run(a, "inbox")[1].replace("[", "message ").replace("]", " "))
    nid = first_id(world.run(b, "notify", "done")[1])
    voice = world.session("voice")
    assert world.run(voice, "dismiss", str(ask_id), "--as", "petros")[0] == 0
    assert world.run(voice, "dismiss", str(nid), "--as", "petros")[0] == 0
    assert world.run(a, "inbox")[1].strip() == "nothing for petros"
    code, out, _ = world.run(a, "wait", th, "--timeout", "5")
    assert code == 0 and "dismissed this without answering" in out
    assert world.run(voice, "dismiss", str(nid), "--as", "petros")[0] == 1


def test_notify_needs_a_member_and_statusline_counts_the_inbox(world):
    a, b = two(world)
    assert world.run(world.session("loner"), "notify", "hello")[0] == 1
    world.run(a, "notify", "blocked on a decision")
    world.run(b, "ask", "petros", "which?")
    world.capsys.readouterr()
    fleet.main(["statusline", a.sid])
    assert json.loads(world.capsys.readouterr().out)["for_petros"] == 2
    ref = json.loads(world.run(a, "inbox", "--json")[1])[0]["ref"]
    assert world.run(world.session("voice"), "dismiss", ref, "--as", "petros")[0] == 0
    fleet.main(["statusline", "x"])
    assert json.loads(world.capsys.readouterr().out)["for_petros"] == 1


def test_the_inbox_fans_out_and_a_remote_item_is_answered_by_its_ref(world):
    a, b, bee = duo(world, extra={"gone": {"ssh": "no-such-host", "fleet": "/x/fleet.py"}})
    world.run(a, "notify", "here note")
    mid = first_id(world.run(b, "ask", "petros", "remote question?")[1])
    code, out, _ = world.run(a, "inbox")
    assert "[%d@bee] ask from beta" % mid in out and "[1] notify from alpha" in out
    assert "machine gone: unreachable" in out
    voice = world.session("voice")
    code, out, err = world.run(voice, "answer", "%d@bee" % mid, "do it", "--as", "petros")
    assert code == 0, err
    [line] = b.messages()
    assert "do it" in line["message"]["content"] and "from petros" in line["message"]["content"]
    world.here_env()
    assert [i["ref"] for i in json.loads(world.run(a, "inbox", "--json")[1])] == ["1"]


# ---------------------------------------------------------------- stop, respawn, attach

def test_stop_a_background_member_with_claude_stop(world, claude):
    a, b = two(world)
    claude.bg(b, id="bb22cc33")
    code, out, err = world.run(a, "stop", "beta")
    assert code == 0, err
    assert "stopped beta" in out and "bb22cc33" in out
    assert ["stop", "bb22cc33"] in [c["argv"] for c in claude.calls()]
    assert b.messages() == []  # a background member is stopped, not asked


def test_stop_never_kills_an_interactive_member_it_asks_it_to_leave(world, claude):
    a, b = two(world)
    claude.agents()  # beta is not among the background sessions
    code, out, err = world.run(a, "stop", "beta")
    assert code == 0, err
    assert "interactive" in out and "never killed" in out
    assert not [c for c in claude.calls() if c["argv"][:1] == ["stop"]]
    [line] = b.messages()
    assert "wrap up" in line["message"]["content"] and "leave the fleet" in line["message"]["content"]


def test_stop_refuses_a_dead_member_and_an_unknown_name(world, claude):
    a, b = two(world)
    b.die()
    code, _, err = world.run(a, "stop", "beta")
    assert code == 1 and "dead" in err and "fleet respawn beta" in err
    assert world.run(a, "stop", "nobody")[0] == 1


def test_respawn_starts_a_dead_member_in_the_background_with_its_conversation(world, claude):
    work = folder(world)
    a, b = world.session("alpha"), world.session("beta", cwd=work)
    world.member(a), world.member(b)
    code, _, err = world.run(a, "respawn", "beta")
    assert code == 1 and "alive" in err  # a live member is refused
    b.die()
    code, out, err = world.run(a, "respawn", "beta")
    assert code == 0, err
    assert "cafe0001" in out and "claude attach beta" in out
    [call] = [c for c in claude.calls() if "--bg" in c["argv"]]
    argv = call["argv"]
    assert argv[:6] == ["--bg", "--resume", b.sid, "-n", "beta", "--settings"]
    assert json.loads(argv[6]) == {"env": {"FLEET_JOIN_NAME": "beta", "FLEET_HOME": world.here.home},
                                   "crossSessionInbound": "accept"}
    assert os.path.realpath(call["cwd"]) == os.path.realpath(work) and len(argv) == 7


def test_respawn_of_a_background_member_is_claude_respawn_and_rebuilds_nothing(world, claude):
    work = folder(world)
    a, b = world.session("alpha"), world.session("beta", cwd=work)
    world.member(a), world.member(b)
    started = os.path.join(world.stub_dir, "started.json")
    json.dump([{"id": b.sid[:8], "sessionId": b.sid, "name": "beta", "cwd": work, "kind": "background",
                "state": "done", "startedAt": 1}], open(started, "w"))
    b.die()
    code, out, err = world.run(a, "respawn", "beta")
    assert code == 0, err
    assert "started beta again in the background (id %s)" % b.sid[:8] in out
    argvs = [c["argv"] for c in claude.calls()]
    assert ["respawn", b.sid[:8]] in argvs
    assert not [x for x in argvs if "--bg" in x or "--resume" in x]  # nothing rebuilt by hand


def test_respawn_falls_back_to_resume_when_claude_has_no_such_background_job(world, claude):
    work = folder(world)
    a, b = world.session("alpha"), world.session("beta", cwd=work)  # beta ran in a terminal: no daemon record
    world.member(a), world.member(b)
    b.die()
    assert world.run(a, "respawn", "beta")[0] == 0
    argvs = [c["argv"] for c in claude.calls()]
    assert ["respawn", b.sid[:8]] in argvs  # tried first
    assert [x for x in argvs if x[:3] == ["--bg", "--resume", b.sid]]


def test_respawn_a_member_that_left_and_a_vanished_folder(world, claude):
    work = folder(world)
    a, b = world.session("alpha"), world.session("beta", cwd=work)
    world.member(a), world.member(b)
    world.run(b, "leave")
    assert world.run(a, "respawn", "beta")[0] == 0
    c = world.session("gamma", cwd="/no/such/folder")
    world.member(c)
    c.die()
    code, _, err = world.run(a, "respawn", "gamma")
    assert code == 1 and "folder" in err and "gone" in err


def test_attach_prints_the_command_for_each_kind_of_member(world, claude):
    a, b = two(world)
    claude.bg(b, id="bb22cc33")
    assert world.run(a, "attach", "beta")[1].strip() == "claude attach bb22cc33"
    claude.agents()
    lines = world.run(a, "attach", "beta")[1].splitlines()
    assert "terminal" in lines[0] and "cannot be attached" in lines[0]
    assert lines[1] == "cd /work/x && claude --resume %s -n beta" % b.sid
    b.die()
    out = world.run(a, "attach", "beta")[1]
    assert "is dead" in out and "fleet respawn beta" in out and b.sid in out


def test_control_works_across_machines_over_ssh(world, claude):
    a, b, bee = duo(world)
    claude.bg(b, id="bb22cc33")
    assert world.run(a, "attach", "beta")[1].strip() == "ssh -t bee 'claude attach bb22cc33'"
    code, out, err = world.run(a, "stop", "beta@bee")
    assert code == 0, err
    assert "stopped beta" in out and ["stop", "bb22cc33"] in [c["argv"] for c in claude.calls()]
    claude.agents()
    out = world.run(a, "attach", "beta")[1]
    assert out.splitlines()[1].startswith("ssh -t bee 'cd /work/x && claude --resume")
    b.die()
    assert world.run(a, "stop", "beta")[0] == 1
    assert any("_control" in cmd for _, cmd in world.ssh_log())


def test_stopping_an_interactive_member_on_another_machine_tells_it(world, claude):
    a, b, bee = duo(world)
    claude.agents()
    code, out, err = world.run(a, "stop", "beta")
    assert code == 0, err
    assert any("wrap up" in m["message"]["content"] for m in b.messages())


# ---------------------------------------------------------------- history shows the fleet name

def test_history_shows_the_fleet_name_when_a_session_has_no_other_name(world):
    a = world.session("alpha")
    world.member(a, "builder")
    con = fleet.db()
    hist.record(con, {"hook_event_name": "SessionStart", "session_id": a.sid, "cwd": "/work/x"})
    hist.record(con, {"hook_event_name": "SessionStart", "session_id": "other-sid", "cwd": "/work/y"})
    rows = {r["id"]: r for r in json.loads(world.run(a, "history", "ls", "--json")[1])}
    assert (rows[a.sid]["name"], rows[a.sid]["fleet_name"], rows[a.sid]["renamed"]) == ("builder", "builder", False)
    assert (rows["other-sid"]["name"], rows["other-sid"]["fleet_name"]) == ("", "")
    con.execute("UPDATE conversations SET name_ai='Fix billing' WHERE session_id=?", (a.sid,))
    assert json.loads(world.run(a, "history", "show", a.sid, "--json")[1])["name"] == "Fix billing"
    world.run(a, "history", "rename", a.sid[:12], "mine")
    assert json.loads(world.run(a, "history", "show", a.sid, "--json")[1])["name"] == "mine"


# ---------------------------------------------------------------- the page's writes

@pytest.fixture
def page(world):
    srv = fleet.make_ui_server(port=0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = "127.0.0.1:%d" % srv.server_address[1]

    def call(method, path, body=None, headers=None):
        h = {"Host": host, "Authorization": "Bearer " + srv.fleet_token}
        if method == "POST":
            h.update({"Origin": "http://" + host, "Content-Type": "application/json"})
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        world.here_env()
        req = urllib.request.Request("http://" + host + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=30)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield call
    srv.shutdown()
    srv.server_close()


def test_page_adds_a_todo_and_tells_or_asks_a_member_as_petros(world, page, claude):
    a, b = two(world)
    code, d = page("POST", "/api/todos/add", {"title": "write docs", "ref": "T-9", "notes": "short"})
    assert code == 200
    [t] = json.loads(world.run(a, "todo", "ls", "--json")[1])
    assert (t["title"], t["ref"], t["notes"], t["created_by"]) == ("write docs", "T-9", "short", "petros")
    code, d = page("POST", "/api/tell", {"target": "beta", "text": "hello", "kind": "ask"})
    assert code == 200 and d["thread"].startswith("t")
    text = b.messages()[0]["message"]["content"]
    assert "Fleet ask" in text and "from petros" in text
    assert page("POST", "/api/tell", {"target": "beta", "text": "x", "kind": "shout"})[0] == 400
    assert page("POST", "/api/tell", {"target": "nobody", "text": "x", "kind": "tell"})[0] == 400
    assert page("POST", "/api/tell", {"target": "beta", "text": "", "kind": "tell"})[0] == 400


def test_page_works_as_petros_even_when_its_server_runs_inside_a_member_session(world, page):
    a, b = two(world)
    a.env(world.mp)  # the server's environment is a member's session
    page_call = page("POST", "/api/tell", {"target": "beta", "text": "from the page", "kind": "tell"})
    assert page_call[0] == 200 and "from petros" in b.messages()[0]["message"]["content"]


def test_page_inbox_answer_and_dismiss(world, page):
    a, b = two(world)
    world.run(a, "ask", "petros", "q1?")
    world.run(b, "notify", "n1")
    code, d = page("GET", "/api/inbox")
    assert code == 200 and d["open"] == 2 and d["machine"] == fleet.self_machine()
    refs = {i["body"]: i["ref"] for i in d["items"]}
    assert page("POST", "/api/inbox/answer", {"ref": refs["q1?"], "text": "yes"})[0] == 200
    assert "yes" in a.messages()[0]["message"]["content"]
    assert page("POST", "/api/inbox/dismiss", {"ref": refs["n1"]})[0] == 200
    d = page("GET", "/api/inbox")[1]
    assert d["open"] == 0 and [i["reply"] for i in d["items"] if i["body"] == "q1?"] == ["yes"]
    assert page("POST", "/api/inbox/dismiss", {"ref": refs["n1"]})[0] == 400


def test_page_stop_respawn_and_attach(world, page, claude):
    work = folder(world)
    a, b = world.session("alpha"), world.session("beta", cwd=work)
    world.member(a), world.member(b)
    claude.bg(b, id="bb22cc33")
    assert page("POST", "/api/members/attach", {"target": "beta"})[1]["command"] == "claude attach bb22cc33"
    code, d = page("POST", "/api/members/stop", {"target": "beta"})
    assert code == 200 and d["action"] == "stopped"
    b.die()
    code, d = page("POST", "/api/members/respawn", {"target": "beta"})
    assert code == 200 and d["id"] == "cafe0001"
    assert page("POST", "/api/members/stop", {"target": "alpha@nowhere"})[0] == 400


def test_page_writes_are_refused_unless_they_come_from_the_page(world, page, claude):
    a, b = two(world)
    body = {"target": "beta", "text": "hijack", "kind": "tell"}
    refused = [page("POST", "/api/tell", body, {"Origin": None}),
               page("POST", "/api/tell", body, {"Origin": "http://evil.example"}),
               page("POST", "/api/tell", body, {"Content-Type": "text/plain"}),
               page("POST", "/api/tell", body, {"Host": "evil.example:80", "Origin": "http://evil.example:80"}),
               page("POST", "/api/todos/add", {"title": "x"}, {"Sec-Fetch-Site": "cross-site"}),
               page("POST", "/api/members/stop", {"target": "beta"}, {"Origin": None}),
               page("GET", "/api/inbox", None, {"Host": "evil.example"})]
    assert [c for c, _ in refused] == [403] * 7
    assert b.messages() == [] and json.loads(world.run(a, "todo", "ls", "--json")[1]) == []


def test_the_page_has_the_for_you_view_and_member_buttons():
    d = os.path.join(ROOT, "ui")
    js, html = open(os.path.join(d, "app.js")).read(), open(os.path.join(d, "index.html")).read()
    assert "For you" in js and 'data-view="foryou"' in html
    for word in ("Stop", "Respawn", "Copy attach", "/api/members/stop", "/api/inbox/answer", "/api/todos/add"):
        assert word in js
    # every action is an icon button named by aria-label and title, built from the vendored Lucide map
    assert "createElementNS" in js and "Lucide" in js and "innerHTML" not in js
    for label in ("Tell", "Ask", "Stop", "Respawn", "Copy attach", "Rename", "Copy resume", "Delete", "Dismiss"):
        assert 'ibtn(' in js and '"%s"' % label in js
    assert "const mk = ibtn" in js and '"aria-label": label, title: label' in js
