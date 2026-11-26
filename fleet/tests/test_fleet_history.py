"""`fleet history`: this machine's sessions as the session index holds them, written by the one recorder hook, and
the history verbs with a stub `claude`; and the page's write guards. Every session and transcript here is made up.
The per-machine `conversations` table is no source any more (phase 3): no test writes or reads it but to prove
that."""
import json
import os
import sqlite3
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request

import pytest

from fleet_testkit import fleet, index_row, world, ROOT  # noqa: F401
import fleet_history as hist
STUB = """#!%s
import json, os, sys
prompt = sys.stdin.read()
with open(os.path.join(os.environ["STUB_DIR"], "calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt, "no_record": os.environ.get("FLEET_NO_RECORD"),
                        "join": os.environ.get("FLEET_JOIN_NAME")}) + "\\n")
if os.environ.get("STUB_FAIL"):
    sys.stderr.write("stub failure\\n"); sys.exit(2)
if "They are looking for" in prompt:
    print('Here you go: [{"n": 2, "why": "it is about the billing export"}, {"n": 9, "why": "no such"}, {"n": 2, "why": "dup"}]')
elif "Question:" in prompt:
    print("ANSWER from transcript: " + prompt.split("Question:")[1].split("\\n")[0].strip())
else:
    print("This session was about " + prompt.split("Folder:")[1].split("\\n")[0].strip() + " and wrote a plan for the export job.")
"""


@pytest.fixture
def stub(world):
    d = os.path.join(world.base, "stub")
    os.makedirs(d)
    import sys
    path = os.path.join(d, "claude")
    with open(path, "w") as f:
        f.write(STUB % sys.executable)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    world.mp.setenv("FLEET_CLAUDE_BIN", path)
    world.mp.setenv("STUB_DIR", d)
    world.mp.setenv("FLEET_DESCRIBE_PAUSE", "0")
    world.mp.delenv("STUB_FAIL", raising=False)

    def calls():
        try:
            return [json.loads(x) for x in open(os.path.join(d, "calls.jsonl"))]
        except OSError:
            return []
    return calls


def transcript(world, name, prompts=("Plan the billing export", "Now write the job"), names=(), cwd=None):
    """A made-up transcript where Claude Code keeps them ($CLAUDE_CONFIG_DIR/projects/<folder>/<name>.jsonl), so
    the verbs that read it on this machine find it by the session id; `names` are (record type, key, value)."""
    folder = os.path.join(os.environ["CLAUDE_CONFIG_DIR"], "projects", "-work")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name + ".jsonl")
    recs = []
    for i, p in enumerate(prompts):
        recs.append({"type": "user", "message": {"role": "user", "content": p}, "cwd": cwd})
        recs.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Reply to: " + p}]}})
    recs.insert(1, {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "noise"}]}})
    recs.insert(2, {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta noise"}})
    recs.insert(3, {"type": "user", "message": {"role": "user", "content": "<system-reminder>x</system-reminder>"}})
    for t, k, v in names:
        recs.append({"type": t, k: v})
    with open(path, "w") as f:
        f.write("\n".join(json.dumps(r) for r in recs) + "\n")
    return path


def hook_payload(event, sid, cwd, path, reason=None):
    d = {"hook_event_name": event, "session_id": sid, "cwd": cwd, "transcript_path": path}
    if reason:
        d["reason"] = reason
    return json.dumps(d)


def run_hook(world, payload, extra=None):
    env = dict(os.environ)
    for k in ("FLEET_NO_RECORD", "CLAUDE_DETACH_NAME", "FLEET_RC_NAME"):  # a made-up chat, not this job's session
        env.pop(k, None)
    env.update(FLEET_INDEX_FOREGROUND="1", **(extra or {}))  # no detached flush outlives the test
    return subprocess.run(["sh", os.path.join(ROOT, "hooks", "record.sh")], input=payload, capture_output=True,
                          text=True, env=env, timeout=30)


def row(world, sid):
    return index_row(world.here.home, sid)


def history_rows(world):
    """Rows of the old per-machine table, which nothing may write any more (read only: no store is made)."""
    path = os.path.join(world.here.home, "fleet.db")
    if not os.path.exists(path):
        return []
    con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    try:
        return con.execute("SELECT * FROM conversations").fetchall()
    except sqlite3.OperationalError:  # a store with no such table
        return []
    finally:
        con.close()


def cli(world, *argv):
    world.capsys.readouterr()
    code = fleet.main(list(argv))
    out = world.capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------- the hook

def test_a_session_start_writes_an_index_entry_and_no_history_row(world):
    path = transcript(world, "s-1", names=[("ai-title", "aiTitle", "Billing export plan")])
    r = run_hook(world, hook_payload("SessionStart", "s-1", "/work/shop", path))
    assert (r.returncode, r.stdout) == (0, "")
    got = row(world, "s-1")
    assert (got["cwd"], got["machine"], got["ended"]) == ("/work/shop", fleet.self_machine(), None)
    assert history_rows(world) == []
    run_hook(world, hook_payload("Stop", "s-1", "/work/shop", path))
    got = row(world, "s-1")
    assert (got["name"], got["name_source"], got["first_prompt"]) == ("Billing export plan", "ai", "Plan the billing export")
    run_hook(world, hook_payload("SessionEnd", "s-1", "/work/shop", path, "clear"))
    got = row(world, "s-1")
    assert got["ended"] >= got["started"] and got["end_reason"] == "clear"
    assert history_rows(world) == []  # the history table is never written again
    assert not os.path.exists(os.path.join(world.here.home, "fleet.db"))  # recording opens no fleet store


def test_sessions_lists_a_session_that_has_no_history_row(world):
    sid = "cccc0000-0000-4000-8000-000000000000"
    path = transcript(world, sid, names=[("custom-title", "customTitle", "export plan")])
    run_hook(world, hook_payload("SessionStart", sid, "/work/shop", path))
    run_hook(world, hook_payload("SessionEnd", sid, "/work/shop", path, "other"))
    assert history_rows(world) == []
    for argv in (["sessions", "--json", "--kind", "all"], ["sessions", "--local", "--json", "--kind", "all"]):
        code, out, err = cli(world, *argv)
        rows = {r["id"]: r for r in json.loads(out)["rows"]}
        assert code == 0 and sid in rows, (argv, err)
        assert (rows[sid]["name"], rows[sid]["folder"], rows[sid]["live_on"]) == ("export plan", "/work/shop", []), argv


def test_hook_exits_zero_and_prints_nothing_whatever_goes_wrong(world):
    for stdin in ("", "not json", "[]", json.dumps({"hook_event_name": "Stop"}),
                  hook_payload("Stop", "s-2", "/w", "/no/such/transcript.jsonl")):
        r = run_hook(world, stdin)
        assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    # a FLEET_HOME that is a file: nothing can be written, still exit 0, nothing printed
    bad = os.path.join(world.base, "afile")
    open(bad, "w").write("x")
    r = run_hook(world, hook_payload("Stop", "s-3", "/w", ""), {"FLEET_HOME": bad})
    assert (r.returncode, r.stdout) == (0, "")


def test_hook_skips_a_headless_call_of_its_own(world):
    r = run_hook(world, hook_payload("SessionStart", "s-4", "/w", ""), {"FLEET_NO_RECORD": "1"})
    assert r.returncode == 0 and not os.path.exists(os.path.join(world.here.home, "index", "journal.jsonl"))


def test_hook_is_fast_on_a_big_transcript(world):
    path = transcript(world, "s-5", prompts=())
    line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 2000}]}}) + "\n"
    with open(path, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "first ask"}}) + "\n")
        f.write(line * 25000)  # 50 MB
        f.write(json.dumps({"type": "custom-title", "customTitle": "late name"}) + "\n")
    run_hook(world, hook_payload("SessionStart", "s-5", "/w", path))
    t = time.time()
    run_hook(world, hook_payload("SessionEnd", "s-5", "/w", path))
    assert time.time() - t < 2.5  # process start and the hub's write included; the file is read at its two ends only
    assert (row(world, "s-5")["name"], row(world, "s-5")["first_prompt"]) == ("late name", "first ask")


def test_a_resumed_session_is_open_again(world):
    run_hook(world, hook_payload("SessionStart", "s-6", "/w", ""))
    run_hook(world, hook_payload("SessionEnd", "s-6", "/w", "", "logout"))
    assert row(world, "s-6")["ended"] is not None
    run_hook(world, hook_payload("SessionStart", "s-6", "/w", ""))
    assert (row(world, "s-6")["ended"], row(world, "s-6")["end_reason"]) == (None, None)


# ---------------------------------------------------------------- names

def test_the_newest_name_wins_and_a_blank_one_is_no_name():
    recs = [{"type": "ai-title", "aiTitle": "first"}, {"type": "custom-title", "customTitle": "old"},
            {"type": "custom-title", "customTitle": "newest"}, {"type": "custom-title", "customTitle": "   "},
            {"type": "ai-title", "aiTitle": "ai newest"}, {"type": "agent-name", "agentName": "worker"}]
    assert hist.newest_names(recs) == {"name_ai": "ai newest", "name_custom": "newest", "name_agent": "worker"}


def test_a_history_rename_is_the_index_s_name_and_becomes_the_claude_name(world):
    path = transcript(world, "s-7", names=[("ai-title", "aiTitle", "generated"), ("custom-title", "customTitle", "slug-one"),
                                           ("custom-title", "customTitle", "typed-later")])
    run_hook(world, hook_payload("SessionStart", "s-7", "/w", path))
    run_hook(world, hook_payload("SessionEnd", "s-7", "/w", path, "other"))
    assert row(world, "s-7")["name"] == "typed-later"
    code, out, err = cli(world, "history", "rename", "s-7", "My", "own name")
    assert code == 0 and out.strip() == "s-7 is now My own name", err
    assert (row(world, "s-7")["name"], row(world, "s-7")["name_source"]) == ("My own name", "manual")
    last = json.loads(open(path).read().splitlines()[-1])
    assert last == {"type": "custom-title", "customTitle": "My own name", "sessionId": "s-7"}  # one name: Claude's
    run_hook(world, hook_payload("Stop", "s-7", "/w", path))  # the next turn restates the transcript names
    assert row(world, "s-7")["name"] == "My own name"
    assert history_rows(world) == []


def test_an_empty_history_rename_clears_the_name_the_user_gave(world):
    path = transcript(world, "s-9", names=[("custom-title", "customTitle", "claude-name")])
    run_hook(world, hook_payload("SessionStart", "s-9", "/w", path))
    assert cli(world, "history", "rename", "s-9", "old label")[0] == 0
    assert row(world, "s-9")["name_source"] == "manual"
    with open(path, "w") as f:  # the transcript as it was, without the title the rename wrote
        f.write(json.dumps({"type": "custom-title", "customTitle": "claude-name"}) + "\n")
    assert cli(world, "history", "rename", "s-9", "")[0] == 0
    assert (row(world, "s-9")["name"], row(world, "s-9")["name_source"]) == ("", "")
    run_hook(world, hook_payload("Stop", "s-9", "/w", path))  # the next journal name fills it again
    assert (row(world, "s-9")["name"], row(world, "s-9")["name_source"]) == ("claude-name", "custom")


# ---------------------------------------------------------------- the verbs

def seed(world, n=3):
    ids = []
    for i in range(n):
        sid = "aaaa000%d-0000-4000-8000-00000000000%d" % (i, i)
        path = transcript(world, sid, prompts=("Plan the billing export %d" % i, "Now write the job"),
                          names=[("custom-title", "customTitle", "name-%d" % i)] if i != 1 else [])
        cwd = ("/work/shop" if i < 2 else "/work/blog/posts")
        run_hook(world, hook_payload("SessionStart", sid, cwd, path))
        run_hook(world, hook_payload("SessionEnd", sid, cwd, path, "other"))
        ids.append((sid, path))
    return ids


def test_ls_show_folder_and_json_read_the_index(world):
    seed(world)
    code, out, _ = cli(world, "history", "ls", "--json")
    data = json.loads(out)
    assert code == 0 and len(data) == 3
    assert {d["name"] for d in data} == {"name-0", "Plan the billing export 1", "name-2"}  # no title: the first prompt
    assert [d["id"] for d in data if d["folder"] == "/work/blog/posts"] == ["aaaa0002-0000-4000-8000-000000000002"]
    code, out, _ = cli(world, "history", "ls", "--folder", "/work/shop", "--json")
    assert len(json.loads(out)) == 2
    code, out, _ = cli(world, "history", "ls", "--folder", "/work/sh", "--json")
    assert json.loads(out) == []  # a folder, not a string prefix
    code, out, _ = cli(world, "history", "show", "aaaa0000")
    assert "name-0" in out and "claude --resume aaaa0000-0000-4000-8000-000000000000" in out and "Plan the billing export 0" in out
    code, out, err = cli(world, "history", "show", "aaaa")
    assert code == 1 and "matches 3 sessions" in err
    code, out, err = cli(world, "history", "show", "zzzz")
    assert code == 1 and "no session" in err
    code, out, _ = cli(world, "history", "resume", "aaaa0002")
    assert out.strip() == "cd /work/blog/posts && claude --resume aaaa0002-0000-4000-8000-000000000002"
    assert history_rows(world) == []


def test_ls_lists_only_this_machine_s_sessions(world):
    seed(world, 1)
    import fleet_index_store as store
    con = store.connect(store.hub_db_path(world.here.home))
    try:  # a session of another machine, as its journal would have put it
        reply = store.apply_batch(con, {"machine": "elsewhere", "entries": [
            {"v": 1, "machine": "elsewhere", "seq": 1, "as": "elsewhere", "sid": "bbbb0000-0000-4000-8000-000000000000",
             "epoch_seen": 1, "event": "start", "at": time.time(),
             "fields": {"name": "theirs", "name_source": "custom", "kind": "chat", "cwd": "/x", "work": False}}]},
            hub=fleet.self_machine(), machines={fleet.self_machine(), "elsewhere"})
        assert reply["results"][-1]["outcome"] == "applied", reply
    finally:
        con.close()
    assert index_row(world.here.home, "bbbb0000-0000-4000-8000-000000000000")["machine"] == "elsewhere"
    code, out, _ = cli(world, "history", "ls", "--json")
    assert [d["id"] for d in json.loads(out)] == ["aaaa0000-0000-4000-8000-000000000000"]


def test_delete_removes_the_index_row_and_never_the_transcript(world):
    (sid, path), *_ = seed(world)
    code, out, err = cli(world, "history", "delete", sid[:8])
    assert code == 0 and row(world, sid) is None, err
    assert len(json.loads(cli(world, "history", "ls", "--json")[1])) == 2
    assert os.path.exists(path)


def test_delete_refuses_a_session_that_has_not_ended(world):
    path = transcript(world, "open-1")
    run_hook(world, hook_payload("SessionStart", "open-1", "/w", path))
    code, _, err = cli(world, "history", "delete", "open-1")
    assert code == 1 and "has not ended" in err and row(world, "open-1") is not None


def test_ask_answers_from_the_transcript_with_one_headless_call(world, stub):
    (sid, path), *_ = seed(world)
    code, out, err = cli(world, "history", "ask", sid[:8], "what", "was", "built?")
    assert code == 0 and out.strip() == "ANSWER from transcript: what was built?", err
    (call,) = stub()
    assert "person: Plan the billing export 0" in call["prompt"] and "claude: Reply to: Now write the job" in call["prompt"]
    assert "(folder: /work/shop)" in call["prompt"]
    assert "noise" not in call["prompt"] and "meta noise" not in call["prompt"]
    assert call["argv"][:7] == ["-p", "--model", "sonnet", "--no-session-persistence", "--tools", "", "--strict-mcp-config"]  # no tools
    assert (call["no_record"], call["join"]) == ("1", None)


def test_ask_says_so_when_the_transcript_is_gone_or_claude_fails(world, stub):
    (sid, path), (sid2, _), _ = seed(world)
    os.unlink(path)
    code, _, err = cli(world, "history", "ask", sid[:8], "anything")
    assert code == 1 and "transcript is not on this machine" in err
    world.mp.setenv("STUB_FAIL", "1")
    code, _, err = cli(world, "history", "ask", sid2[:8], "anything")
    assert code == 1 and "stub failure" in err


def test_describe_fills_missing_descriptions_in_a_limited_paced_batch(world, stub):
    seed(world, 3)
    naps = []
    real_sleep = time.sleep
    # subprocess's own wait loop sleeps too, in steps of a few milliseconds: only the pause between calls counts.
    world.mp.setattr(time, "sleep", lambda s: naps.append(s) if s >= 1 else real_sleep(s))
    world.mp.setenv("FLEET_DESCRIBE_PAUSE", "2")
    code, out, err = cli(world, "history", "describe", "--limit", "2")
    assert code == 0 and "described 2, failed 0, 1 still waiting" in out, err
    assert len(stub()) == 2 and naps == [2.0]  # paced between calls, not before the first
    rows = json.loads(cli(world, "history", "ls", "--json")[1])
    assert sum(1 for r in rows if r["description"]) == 2
    assert [r["description"] for r in rows if r["description"]][0].startswith("This session was about /work/")
    cli(world, "history", "describe")
    assert len(stub()) == 3  # only the missing one
    code, out, _ = cli(world, "history", "describe")
    assert "every session that can be described has a description" in out and len(stub()) == 3
    assert history_rows(world) == []


def test_describe_skips_a_session_that_is_live_and_busy_just_now(world, stub):
    path = transcript(world, "live-1")
    run_hook(world, hook_payload("SessionStart", "live-1", "/w", path))
    run_hook(world, hook_payload("Stop", "live-1", "/w", path))  # not ended, written just now
    code, out, _ = cli(world, "history", "describe")
    assert "every session that can be described has a description" in out and stub() == []


def test_recording_never_calls_a_model(world, stub):
    seed(world)
    assert stub() == []


def test_search_reads_every_description_and_keeps_the_valid_matches(world, stub):
    ids = seed(world)
    cli(world, "history", "describe")
    code, out, _ = cli(world, "history", "search", "the", "billing", "thing", "--json")
    res = json.loads(out)
    assert code == 0 and (res["described"], res["total"]) == (3, 3)
    assert len(res["hits"]) == 1 and res["hits"][0]["why"] == "it is about the billing export"  # 9 unknown, 2 once
    last = stub()[-1]
    assert last["prompt"].count("\n[") == 3 and "They are looking for: the billing thing" in last["prompt"]
    assert res["hits"][0]["id"] in {sid for sid, _ in ids}
    code, _, err = cli(world, "history", "search", "  ")
    assert code == 1


def test_search_with_no_descriptions_makes_no_call(world, stub):
    seed(world)
    code, out, _ = cli(world, "history", "search", "billing")
    assert "0 of 3 sessions have a description" in out and stub() == []


def test_history_import_is_gone(world):
    with pytest.raises(SystemExit):
        fleet.main(["history", "import", os.path.join(world.base, "old.db")])


# ---------------------------------------------------------------- the page's write surface

@pytest.fixture
def page(world, stub):
    srv = fleet.make_ui_server(port=0, ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    host = "127.0.0.1:%d" % port

    def call(method, path, body=None, headers=None):
        h = {"Host": host, "Authorization": "Bearer " + srv.fleet_token}
        if method == "POST":
            h.update({"Origin": "http://" + host, "Content-Type": "application/json"})
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        req = urllib.request.Request("http://" + host + path, data=json.dumps(body).encode() if body is not None else None,
                                     method=method, headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=30)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    call.srv, call.host = srv, host
    yield call
    srv.shutdown()
    srv.server_close()


def key(sid):
    return "%s:%s" % (fleet.self_machine(), sid)


def test_the_history_routes_are_gone_and_the_sessions_tab_writes_on_index_rows(world, page):
    ids = seed(world)
    assert page("GET", "/api/history")[0] == 404
    assert page("POST", "/api/history/rename", {"id": ids[0][0], "name": "x"})[0] == 404
    code, data = page("GET", "/api/sessions?fresh=1")
    assert code == 200 and {r["sid"] for r in data["rows"]} == {sid for sid, _ in ids}
    sid = ids[0][0]
    code, d = page("POST", "/api/sessions/rename", {"key": key(sid), "name": "Shop work"})
    assert code == 200 and row(world, sid)["name"] == "Shop work", d
    code, d = page("POST", "/api/sessions/ask", {"key": key(sid), "question": "what happened?"})
    assert code == 200 and d["answer"] == "ANSWER from transcript: what happened?"
    code, d = page("POST", "/api/sessions/delete", {"key": key(sid)})
    assert code == 200 and row(world, sid) is None and os.path.exists(ids[0][1])
    code, d = page("POST", "/api/sessions/delete", {"key": key("aaaa9999-0000-4000-8000-000000000009")})
    assert code == 400 and "no session" in d["error"]
    code, d = page("POST", "/api/sessions/search", {"query": "  "})
    assert code == 400
    assert history_rows(world) == []


def test_a_write_must_come_from_the_page_itself(world, page, stub):
    sid = seed(world)[0][0]
    body = {"key": key(sid), "name": "hijacked"}
    w = "/api/sessions/rename"
    refused = [
        page("POST", w, body, {"Origin": None}),                          # no Origin: not a browser page
        page("POST", w, body, {"Origin": "http://evil.example"}),         # another site
        page("POST", w, body, {"Origin": "http://127.0.0.1:1"}),          # same host, another port
        page("POST", w, body, {"Sec-Fetch-Site": "cross-site"}),
        page("POST", w, body, {"Content-Type": "text/plain"}),            # what a plain cross-site form sends
        page("POST", w, body, {"Content-Type": "application/x-www-form-urlencoded"}),
        page("POST", w, body, {"Host": "evil.example:80", "Origin": "http://evil.example:80"}),  # DNS rebinding
    ]
    assert [c for c, _ in refused] == [403] * 7
    assert row(world, sid)["name"] == "name-0" and stub() == []
    code, _ = page("GET", "/api/sessions", headers={"Host": "evil.example"})
    assert code == 403  # rebinding cannot read it either
    code, _ = page("POST", w, body, {"Sec-Fetch-Site": "same-origin"})
    assert code == 200 and row(world, sid)["name"] == "hijacked"


def test_a_proxy_name_works_only_when_ui_json_lists_it(world, page):
    seed(world)
    h = {"Host": "fleet.proxy.example"}
    assert page("GET", "/api/sessions", headers=h)[0] == 403
    with open(os.path.join(world.here.home, "ui.json"), "w") as f:
        json.dump({"hosts": ["fleet.proxy.example"]}, f)
    assert page("GET", "/api/sessions", headers=h)[0] == 200
    assert page("POST", "/api/sessions/search", {"query": "x"}, {"Host": "fleet.proxy.example", "Origin": "http://fleet.proxy.example"})[0] == 200


def test_sessions_are_not_served_when_the_page_listens_beyond_loopback(world):
    seed(world)
    srv = fleet.make_ui_server(port=0, host="0.0.0.0", ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        host = "127.0.0.1:%d" % srv.server_address[1]
        req = urllib.request.Request("http://" + host + "/api/sessions", headers={"Host": host, "Authorization": "Bearer " + srv.fleet_token})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 403 and b"loopback" in e.value.read()
        assert urllib.request.urlopen(urllib.request.Request("http://" + host + "/api/members", headers={"Host": host, "Authorization": "Bearer " + srv.fleet_token}), timeout=10).status == 200  # the read-only views stay
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_post_body_over_the_limit_or_not_json_is_refused(world, page):
    seed(world)
    host = page.host
    for data in (b"{not json", b"[]", b"x" * 70000):
        req = urllib.request.Request("http://%s/api/sessions/search" % host, data=data, method="POST",
                                     headers={"Host": host, "Origin": "http://" + host, "Content-Type": "application/json",
                                              "Authorization": "Bearer " + page.srv.fleet_token})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 400
