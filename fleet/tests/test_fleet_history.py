"""Session history: the recording hook, names, import, the history verbs with a stub `claude`, and the page's
write surface. Every session, transcript and old store here is made up."""
import hashlib
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

from fleet_testkit import fleet, world, ROOT  # noqa: F401
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
    """A made-up transcript file; `names` are (record type, key, value) in order."""
    path = os.path.join(world.base, name + ".jsonl")
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
    env = dict(os.environ, **(extra or {}))
    return subprocess.run(["sh", os.path.join(ROOT, "hooks", "record.sh")], input=payload, capture_output=True,
                          text=True, env=env, timeout=30)


def rows(world):
    return {r["session_id"]: r for r in world.here.db().execute("SELECT * FROM conversations")}


def cli(world, *argv):
    world.capsys.readouterr()
    code = fleet.main(list(argv))
    out = world.capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------- the hook

def test_hook_records_every_session_not_only_joined_ones(world):
    path = transcript(world, "a", names=[("ai-title", "aiTitle", "Billing export plan")])
    r = run_hook(world, hook_payload("SessionStart", "s-1", "/work/shop", path))
    assert (r.returncode, r.stdout) == (0, "")
    assert rows(world)["s-1"]["cwd"] == "/work/shop" and rows(world)["s-1"]["ended_at"] is None
    run_hook(world, hook_payload("Stop", "s-1", "/work/shop", path))
    row = rows(world)["s-1"]
    assert (row["name_ai"], row["first_prompt"], row["transcript_path"]) == ("Billing export plan", "Plan the billing export", path)
    run_hook(world, hook_payload("SessionEnd", "s-1", "/work/shop", path, "clear"))
    row = rows(world)["s-1"]
    assert row["ended_at"] >= row["started_at"] and row["end_reason"] == "clear"
    assert world.here.db().execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0  # recording is not joining


def test_hook_exits_zero_and_prints_nothing_whatever_goes_wrong(world):
    for stdin in ("", "not json", "[]", json.dumps({"hook_event_name": "Stop"}),
                  hook_payload("Stop", "s-2", "/w", "/no/such/transcript.jsonl")):
        r = run_hook(world, stdin)
        assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    # a FLEET_HOME that is a file: the store cannot open, still exit 0, nothing printed
    bad = os.path.join(world.base, "afile")
    open(bad, "w").write("x")
    r = run_hook(world, hook_payload("Stop", "s-3", "/w", ""), {"FLEET_HOME": bad})
    assert (r.returncode, r.stdout) == (0, "")


def test_hook_skips_a_headless_call_of_its_own(world):
    r = run_hook(world, hook_payload("SessionStart", "s-4", "/w", ""), {"FLEET_NO_RECORD": "1"})
    assert r.returncode == 0 and not os.path.exists(os.path.join(world.here.home, "fleet.db"))


def test_hook_is_fast_on_a_big_transcript(world):
    path = os.path.join(world.base, "big.jsonl")
    line = json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x" * 2000}]}}) + "\n"
    with open(path, "w") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "first ask"}}) + "\n")
        f.write(line * 25000)  # 50 MB
        f.write(json.dumps({"type": "custom-title", "customTitle": "late name"}) + "\n")
    run_hook(world, hook_payload("SessionStart", "s-5", "/w", path))
    t = time.time()
    run_hook(world, hook_payload("SessionEnd", "s-5", "/w", path))
    assert time.time() - t < 1.5  # process start included; the file is read at its two ends only
    assert (rows(world)["s-5"]["name_custom"], rows(world)["s-5"]["first_prompt"]) == ("late name", "first ask")


def test_a_resumed_session_is_open_again(world):
    run_hook(world, hook_payload("SessionStart", "s-6", "/w", ""))
    run_hook(world, hook_payload("SessionEnd", "s-6", "/w", "", "logout"))
    assert rows(world)["s-6"]["ended_at"] is not None
    run_hook(world, hook_payload("SessionStart", "s-6", "/w", ""))
    assert (rows(world)["s-6"]["ended_at"], rows(world)["s-6"]["end_reason"]) == (None, None)


# ---------------------------------------------------------------- names

def test_the_newest_name_wins_and_a_blank_one_is_no_name():
    recs = [{"type": "ai-title", "aiTitle": "first"}, {"type": "custom-title", "customTitle": "old"},
            {"type": "custom-title", "customTitle": "newest"}, {"type": "custom-title", "customTitle": "   "},
            {"type": "ai-title", "aiTitle": "ai newest"}, {"type": "agent-name", "agentName": "worker"}]
    assert hist.newest_names(recs) == {"name_ai": "ai newest", "name_custom": "newest", "name_agent": "worker"}


def test_a_rename_in_the_transcript_beats_the_slug_and_a_manual_name_beats_both(world):
    path = transcript(world, "n", names=[("ai-title", "aiTitle", "generated"), ("custom-title", "customTitle", "slug-one"),
                                         ("custom-title", "customTitle", "typed-later")])
    run_hook(world, hook_payload("SessionEnd", "s-7", "/w", path, "other"))
    r = rows(world)["s-7"]
    assert hist.display_name(r) == "typed-later"
    code, out, _ = cli(world, "history", "rename", "s-7", "My", "own name")
    assert code == 0 and hist.display_name(rows(world)["s-7"]) == "My own name"
    run_hook(world, hook_payload("Stop", "s-7", "/w", path))  # the next turn restates the transcript names
    assert hist.display_name(rows(world)["s-7"]) == "My own name"
    cli(world, "history", "rename", "s-7", "")
    assert hist.display_name(rows(world)["s-7"]) == "typed-later"


def test_a_name_found_in_the_tail_does_not_erase_an_older_kind(world):
    path = transcript(world, "t", names=[("custom-title", "customTitle", "kept")])
    run_hook(world, hook_payload("SessionEnd", "s-8", "/w", path))
    with open(path, "a") as f:
        f.write(json.dumps({"type": "ai-title", "aiTitle": "later ai"}) + "\n")
    run_hook(world, hook_payload("Stop", "s-8", "/w", path))
    assert hist.display_name(rows(world)["s-8"]) == "kept" and rows(world)["s-8"]["name_ai"] == "later ai"


# ---------------------------------------------------------------- the verbs

def seed(world, n=3):
    ids = []
    for i in range(n):
        path = transcript(world, "q%d" % i, prompts=("Plan the billing export %d" % i, "Now write the job"),
                          names=[("custom-title", "customTitle", "name-%d" % i)] if i != 1 else [])
        sid = "aaaa000%d-0000-4000-8000-00000000000%d" % (i, i)
        cwd = ("/work/shop" if i < 2 else "/work/blog/posts")
        run_hook(world, hook_payload("SessionStart", sid, cwd, path))
        run_hook(world, hook_payload("SessionEnd", sid, cwd, path, "other"))
        ids.append((sid, path))
    return ids


def test_ls_show_folder_and_json(world):
    seed(world)
    code, out, _ = cli(world, "history", "ls", "--json")
    data = json.loads(out)
    assert code == 0 and len(data) == 3
    assert {d["name"] for d in data} == {"name-0", "", "name-2"}
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


def test_delete_removes_the_row_and_never_the_transcript(world):
    (sid, path), *_ = seed(world)
    code, out, _ = cli(world, "history", "delete", sid[:8])
    assert code == 0 and sid not in rows(world) and len(rows(world)) == 2
    assert os.path.exists(path)


def test_ask_answers_from_the_transcript_with_one_headless_call(world, stub):
    (sid, path), *_ = seed(world)
    code, out, _ = cli(world, "history", "ask", sid[:8], "what", "was", "built?")
    assert code == 0 and out.strip() == "ANSWER from transcript: what was built?"
    (call,) = stub()
    assert "person: Plan the billing export 0" in call["prompt"] and "claude: Reply to: Now write the job" in call["prompt"]
    assert "noise" not in call["prompt"] and "meta noise" not in call["prompt"]
    assert call["argv"][:7] == ["-p", "--model", "sonnet", "--no-session-persistence", "--tools", "", "--strict-mcp-config"]  # no tools
    assert (call["no_record"], call["join"]) == ("1", None)


def test_ask_says_so_when_the_transcript_is_gone_or_claude_fails(world, stub):
    (sid, path), (sid2, _), _ = seed(world)
    os.unlink(path)
    code, _, err = cli(world, "history", "ask", sid[:8], "anything")
    assert code == 1 and "is gone" in err
    world.mp.setenv("STUB_FAIL", "1")
    code, _, err = cli(world, "history", "ask", sid2[:8], "anything")
    assert code == 1 and "stub failure" in err


def test_describe_fills_missing_descriptions_in_a_limited_paced_batch(world, stub):
    ids = seed(world, 3)
    naps = []
    world.mp.setattr(time, "sleep", lambda s: naps.append(s))
    world.mp.setenv("FLEET_DESCRIBE_PAUSE", "2")
    code, out, _ = cli(world, "history", "describe", "--limit", "2")
    assert code == 0 and "described 2, failed 0, 1 still waiting" in out
    assert len(stub()) == 2 and naps == [2.0]  # paced between calls, not before the first
    assert sum(1 for r in rows(world).values() if r["description"]) == 2
    d = [r["description"] for r in rows(world).values() if r["description"]][0]
    assert d.startswith("This session was about /work/")
    cli(world, "history", "describe")
    assert len(stub()) == 3  # only the missing one
    code, out, _ = cli(world, "history", "describe")
    assert "every session that can be described has a description" in out and len(stub()) == 3
    # the transcript grew: the description is stale and made again
    with open(ids[0][1], "a") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "one more thing"}}) + "\n")
    cli(world, "history", "describe")
    assert len(stub()) == 4


def test_describe_skips_a_live_quiet_gate_and_backs_off_after_a_failure(world, stub):
    path = transcript(world, "live")
    run_hook(world, hook_payload("SessionStart", "live-1", "/w", path))
    run_hook(world, hook_payload("Stop", "live-1", "/w", path))  # not ended, written just now
    assert hist.pending(world.here.db()) == []
    os.utime(path, (time.time() - 3600, time.time() - 3600))
    assert len(hist.pending(world.here.db())) == 1
    world.mp.setenv("STUB_FAIL", "1")
    code, out, err = cli(world, "history", "describe")
    assert "failed 1" in out and rows(world)["live-1"]["describe_error"]
    cli(world, "history", "describe")
    assert len(stub()) == 1  # not retried within the hour
    world.mp.delenv("STUB_FAIL")
    update = world.here.db()
    update.execute("UPDATE conversations SET describe_tried_at=?", (time.time() - 7200,))
    update.commit()
    cli(world, "history", "describe")
    assert rows(world)["live-1"]["description"]


def test_recording_never_calls_a_model(world, stub):
    seed(world)
    assert stub() == []


def test_search_reads_every_description_and_keeps_the_valid_matches(world, stub):
    seed(world)
    cli(world, "history", "describe")
    code, out, _ = cli(world, "history", "search", "the", "billing", "thing", "--json")
    res = json.loads(out)
    assert code == 0 and (res["described"], res["total"]) == (3, 3)
    assert len(res["hits"]) == 1 and res["hits"][0]["why"] == "it is about the billing export"  # 9 unknown, 2 once
    last = stub()[-1]
    assert last["prompt"].count("\n[") == 3 and "They are looking for: the billing thing" in last["prompt"]
    assert res["hits"][0]["id"] in rows(world)
    code, _, err = cli(world, "history", "search", "  ")
    assert code == 1


def test_search_with_no_descriptions_makes_no_call(world, stub):
    seed(world)
    code, out, _ = cli(world, "history", "search", "billing")
    assert "0 of 3 sessions have a description" in out and stub() == []


# ---------------------------------------------------------------- import

def old_store(world, with_digests=False):
    p = os.path.join(world.base, "old.db")
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE conversations (conversation_id TEXT PRIMARY KEY, cwd TEXT NOT NULL, transcript_path TEXT NOT NULL,
      title TEXT, started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, ended_at TEXT, end_reason TEXT, auto_title TEXT,
      auto_title_source TEXT, first_prompt TEXT, extra TEXT)""")
    con.executemany("INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("c-1", "/work/shop", "/t/c-1.jsonl", "Renamed by hand", "2026-01-02T03:04:05Z", "2026-01-02T04:00:00Z", "2026-01-02T04:00:01Z", "other", "gen", "ai", "Start here", "x"),
        ("c-2", "/work/blog", "/t/c-2.jsonl", None, "2026-02-02T03:04:05Z", "2026-02-02T04:00:00Z", None, None, "typed name", "custom", None, None),
        ("c-3", "/work/blog", "/t/c-3.jsonl", None, "2026-03-02T03:04:05Z", "2026-03-02T04:00:00Z", None, None, "the opening ask", "prompt", "the opening ask", None),
    ])
    if with_digests:
        con.execute("CREATE TABLE digests (id TEXT PRIMARY KEY, size INTEGER, mtime_ms REAL, digest TEXT, error TEXT, model TEXT, written_at INTEGER)")
        con.executemany("INSERT INTO digests VALUES (?,?,?,?,?,?,?)", [
            ("c-1", 100, 1.0, "Planned the shop checkout flow and decided on one page.", None, "m", 1767325200000),
            ("c-2", 100, 1.0, None, "failed", "m", 1767325200000)])
    con.commit()
    con.close()
    return p


def digest(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def test_import_maps_columns_is_idempotent_and_leaves_the_source_alone(world):
    p = old_store(world, with_digests=True)
    before = digest(p)
    code, out, _ = cli(world, "history", "import", p)
    assert code == 0 and "read 3, added 3, kept 0, descriptions filled 1" in out and "sessions 0 -> 3" in out
    r = rows(world)
    assert (r["c-1"]["manual_name"], r["c-1"]["name_ai"], r["c-1"]["name_custom"]) == ("Renamed by hand", "gen", None)
    assert hist.display_name(r["c-1"]) == "Renamed by hand" and hist.display_name(r["c-2"]) == "typed name"
    assert hist.display_name(r["c-3"]) == "" and r["c-3"]["first_prompt"] == "the opening ask"  # a prompt is not a name
    assert r["c-1"]["started_at"] == 1767323045.0 and r["c-1"]["ended_at"] == 1767326401.0 and r["c-2"]["ended_at"] is None
    assert (r["c-1"]["description"], r["c-1"]["described_size"], r["c-1"]["described_at"]) == \
        ("Planned the shop checkout flow and decided on one page.", 100, 1767325200.0)
    assert r["c-2"]["description"] is None and r["c-1"]["origin"] == "import"
    code, out, _ = cli(world, "history", "import", p)
    assert "read 3, added 0, kept 3, descriptions filled 0" in out and "sessions 3 -> 3" in out
    assert digest(p) == before and not os.path.exists(p + "-wal")


def test_import_keeps_what_this_store_already_has_and_takes_a_separate_digests_file(world):
    p = old_store(world)
    run_hook(world, hook_payload("SessionStart", "c-1", "/new/place", ""))
    d = os.path.join(world.base, "digests.db")
    con = sqlite3.connect(d)
    con.execute("CREATE TABLE digests (id TEXT PRIMARY KEY, size INTEGER, mtime_ms REAL, digest TEXT, error TEXT, model TEXT, written_at INTEGER)")
    con.execute("INSERT INTO digests VALUES ('c-2', 5, 1.0, 'Wrote the blog post about tides.', NULL, 'm', 1000)")
    con.commit(); con.close()
    code, out, _ = cli(world, "history", "import", p, "--descriptions", d)
    assert "added 2, kept 1, descriptions filled 1" in out
    assert rows(world)["c-1"]["cwd"] == "/new/place" and rows(world)["c-2"]["description"] == "Wrote the blog post about tides."


def test_import_refuses_what_is_not_a_conversations_store(world):
    code, _, err = cli(world, "history", "import", os.path.join(world.base, "missing.db"))
    assert code == 1 and "not a file" in err
    p = os.path.join(world.base, "other.db")
    sqlite3.connect(p).execute("CREATE TABLE t(a)").connection.close()
    code, _, err = cli(world, "history", "import", p)
    assert code == 1 and "no conversations table" in err


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


def test_page_lists_history_and_writes_through_the_same_functions(world, page):
    ids = seed(world)
    code, data = page("GET", "/api/history")
    assert code == 200 and data["counts"] == {"total": 3, "described": 0, "unreadable": 0} and len(data["rows"]) == 3
    sid = ids[0][0]
    code, d = page("POST", "/api/history/rename", {"id": sid, "name": "Shop work"})
    assert code == 200 and d["name"] == "Shop work" and d["renamed"]
    code, d = page("POST", "/api/history/ask", {"id": sid, "question": "what happened?"})
    assert code == 200 and d["answer"] == "ANSWER from transcript: what happened?"
    code, d = page("POST", "/api/history/delete", {"id": sid})
    assert code == 200 and sid not in rows(world) and os.path.exists(ids[0][1])
    code, d = page("POST", "/api/history/delete", {"id": "nope"})
    assert code == 404 and "no session" in d["error"]
    code, d = page("POST", "/api/history/search", {"query": "  "})
    assert code == 400


def test_a_write_must_come_from_the_page_itself(world, page, stub):
    sid = seed(world)[0][0]
    body = {"id": sid, "name": "hijacked"}
    refused = [
        page("POST", "/api/history/rename", body, {"Origin": None}),                          # no Origin: not a browser page
        page("POST", "/api/history/rename", body, {"Origin": "http://evil.example"}),         # another site
        page("POST", "/api/history/rename", body, {"Origin": "http://127.0.0.1:1"}),          # same host, another port
        page("POST", "/api/history/rename", body, {"Sec-Fetch-Site": "cross-site"}),
        page("POST", "/api/history/rename", body, {"Content-Type": "text/plain"}),            # what a plain cross-site form sends
        page("POST", "/api/history/rename", body, {"Content-Type": "application/x-www-form-urlencoded"}),
        page("POST", "/api/history/rename", body, {"Host": "evil.example:80", "Origin": "http://evil.example:80"}),  # DNS rebinding
    ]
    assert [c for c, _ in refused] == [403] * 7
    assert hist.display_name(rows(world)[sid]) == "name-0" and stub() == []
    code, _ = page("GET", "/api/history", headers={"Host": "evil.example"})
    assert code == 403  # rebinding cannot read it either
    code, _ = page("POST", "/api/history/rename", body, {"Sec-Fetch-Site": "same-origin"})
    assert code == 200


def test_a_proxy_name_works_only_when_ui_json_lists_it(world, page):
    seed(world)
    h = {"Host": "fleet.proxy.example"}
    assert page("GET", "/api/history", headers=h)[0] == 403
    with open(os.path.join(world.here.home, "ui.json"), "w") as f:
        json.dump({"hosts": ["fleet.proxy.example"]}, f)
    assert page("GET", "/api/history", headers=h)[0] == 200
    assert page("POST", "/api/history/search", {"query": "x"}, {"Host": "fleet.proxy.example", "Origin": "http://fleet.proxy.example"})[0] == 200


def test_history_is_not_served_when_the_page_listens_beyond_loopback(world):
    seed(world)
    srv = fleet.make_ui_server(port=0, host="0.0.0.0", ttl=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        host = "127.0.0.1:%d" % srv.server_address[1]
        req = urllib.request.Request("http://" + host + "/api/history", headers={"Host": host, "Authorization": "Bearer " + srv.fleet_token})
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
        req = urllib.request.Request("http://%s/api/history/search" % host, data=data, method="POST",
                                     headers={"Host": host, "Origin": "http://" + host, "Content-Type": "application/json",
                                              "Authorization": "Bearer " + page.srv.fleet_token})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req, timeout=10)
        assert e.value.code == 400
