"""The journey tool (skills/journey): its store against the page's, batches, attaching, and a canvas on another
machine reached over ssh.

No test reaches webcompanion or starts Claude: the session and its directories are stand-ins, ssh and scp are
fake commands on PATH, and the state folder is a tmp_path."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from skills.journey import journey, store

STATIC = Path(__file__).resolve().parents[2] / "canvas" / "static"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

T = "2026-10-30T09:00:00.000Z"


def create(cid, board="today/01-today", at="2026-10-30T09:00:00Z", **extra):
    c = {"id": cid, "app": "shop", "board": board, "boardTitle": "Today", "chapter": "Today", "shot": "desktop",
         "fx": 0.5, "fy": 0.25, "text": "The total is cut off"}
    c.update(extra)
    return {"kind": "create", "at": at, "comment": c}


def msg(op, ts=0, role="user"):
    return {"text": "x", "role": role, "op": op, "ts": ts}


CASES = {
    "edits replies resolve and a refused op": {
        "today/01-today": {"messages": [
            msg(create("a")), msg({"kind": "reply", "id": "a", "at": "2026-10-30T09:02:00Z",
                                   "reply": {"id": "r1", "text": "Noted.", "by": "claude"}}, role="agent"),
            msg({"kind": "update", "id": "a", "status": "resolved", "at": "2026-10-30T09:05:00Z"}),
            msg({"kind": "update", "id": "ghost", "status": "resolved", "at": "2026-10-30T09:06:00Z"})]},
        "week/02-week": {"messages": [
            msg(create("b", board="week/02-week", at="2026-10-30T09:01:00Z", scope="both")),
            {"text": "a plain note", "role": "user", "ts": 3},
            msg({"kind": "update", "id": "b", "sentAt": "2026-10-30T09:03:00Z", "at": "2026-10-30T09:03:00Z"}),
            msg({"kind": "reply", "id": "b", "at": "2026-10-30T09:04:00Z", "reply": {"id": "r2", "text": "And the phone"}}),
            msg({"kind": "editReply", "id": "b", "replyId": "r2", "text": "And on the phone", "at": "2026-10-30T09:07:00Z"})]},
    },
    "a carried-over number, a delete and a move": {
        "a/01": {"messages": [msg(create("m", board="a/01", number=4)), msg(create("n", board="a/01", at="2026-10-30T09:01:00Z")),
                              msg({"kind": "delete", "id": "m", "at": "2026-10-30T09:02:00Z"}),
                              msg({"kind": "move", "id": "n", "board": "b/01", "boardTitle": "B", "at": "2026-10-30T09:03:00Z"})]},
    },
    "ops ordered by their own time across threads, the daemon's time without one": {
        "z/09": {"messages": [msg({"kind": "reply", "id": "q", "reply": {"id": "r", "text": "late"}}, ts=1793350000)]},
        "a/01": {"messages": [msg(create("q", board="z/09", at="2026-10-30T08:00:00Z"))]},
    },
}


def js_fold(threads):
    prog = (f"const S = require({json.dumps(str(STATIC / 'canvas-store.js'))});\n"
            f"const f = S.fold({json.dumps(threads)}, {json.dumps(T)});\n"
            "f.store.comments.forEach(function (c) { c.waiting = S.waiting(c); });\n"
            "process.stdout.write(JSON.stringify([f.store, f.refused.map(function (r) { return r.error; })]));")
    out = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
@pytest.mark.parametrize("name", list(CASES))
def test_the_python_store_folds_threads_exactly_as_the_page_does(name):
    st, refused = store.fold(CASES[name], T)
    for c in st["comments"]:
        c["waiting"] = store.waiting(c)
    assert [st, [r["error"] for r in refused]] == js_fold(CASES[name])


def test_waiting_is_open_and_written_on_after_claudes_last_answer():
    st, _ = store.fold(CASES["edits replies resolve and a refused op"], T)
    by = {c["id"]: c for c in st["comments"]}
    assert not store.waiting(by["a"])  # resolved
    assert store.waiting(by["b"])  # the user replied after it was sent
    assert by["b"]["sentAt"] == "2026-10-30T09:03:00.000Z" and by["b"]["askedAt"] == "2026-10-30T09:04:00.000Z"


# ── features, events, acks ─────────────────────────────────────────────────

FEATURE = """Feature: Shop journey
  @start-no-account
  Scenario: Sign in
    Given x
  # a comment between tags and their Scenario keeps them
  @start-plan @skip
  # note
  Scenario: Plan setup
  @start-today
  Scenario: Today's log, and more
"""


def record(key, app, checkout, canvas, **extra):
    """A canvas registered the way `journey.py register` writes it."""
    journey.write_json(journey.state_dir(key) / "canvas.json",
                       {"app": app, "name": key.split("-", 1)[1], "checkout": str(checkout), "canvas": str(canvas), **extra})


@pytest.fixture
def app_checkout(tmp_path, monkeypatch):
    co = tmp_path / "co"
    f = co / "apps" / "shop" / "frontend" / "e2e" / "journey" / "journey.feature"
    f.parent.mkdir(parents=True)
    f.write_text(FEATURE)
    monkeypatch.setattr(journey, "features_root", lambda app: co)
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    record("shop-events", "shop", co, tmp_path / "canvas")
    return co


def test_features_are_journey_features_scenarios_as_slugs_with_their_skip(app_checkout):
    assert journey.features("shop-events") == [
        {"id": "sign-in", "name": "Sign in", "skip": False},
        {"id": "plan-setup", "name": "Plan setup", "skip": True},
        {"id": "today-s-log-and-more", "name": "Today's log, and more", "skip": False}]


def test_a_rerun_refuses_any_id_the_journey_does_not_have_before_running_anything(app_checkout, monkeypatch):
    monkeypatch.setattr(journey, "on_main", lambda: True)
    ran = []
    monkeypatch.setattr(journey.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(journey.Refused, match="no feature plan-setup; rm -rf"):
        journey.rerun("shop-events", ["plan-setup; rm -rf"])
    with pytest.raises(journey.Refused, match="no feature plan-setup"):
        journey.rerun("shop-events", ["plan-setup"])  # @skip never runs
    assert ran == []


@pytest.fixture
def session(tmp_path, monkeypatch):
    dirs = {k: str(tmp_path / "wc" / k) for k in ("state_dir", "events_dir", "consumed_dir")}
    for d in dirs.values():
        Path(d).mkdir(parents=True)
    monkeypatch.setattr(journey, "sid_of", lambda app: "s-1")
    monkeypatch.setattr(journey, "session_dirs", lambda sid: dirs)
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    return dirs


def event(dirs, eid, body):
    (Path(dirs["events_dir"]) / f"{eid}.json").write_text(json.dumps({"anchor": "__general__", "text": json.dumps(body)}))


def test_pending_events_are_the_unacked_ones_oldest_first(session):
    event(session, "00000000000000000002-1-000000", {"type": "rerun", "features": ["today"]})
    event(session, "00000000000000000001-1-000000", {"type": "comments", "ids": ["a"]})
    event(session, "00000000000000000003-1-000000", {"type": "comments", "ids": ["b"]})
    (Path(session["consumed_dir"]) / "00000000000000000003-1-000000.ack").touch()
    got = [(eid, journey.event_body(rec)) for eid, rec in journey.pending_events(session)]
    assert got == [("00000000000000000001-1-000000", {"type": "comments", "ids": ["a"]}),
                   ("00000000000000000002-1-000000", {"type": "rerun", "features": ["today"]})]


def test_an_ack_with_no_watcher_archives_the_event_and_with_one_leaves_it_to_the_watcher(session):
    import time
    event(session, "e1", {"type": "comments", "ids": ["a"]})
    assert journey.ack("shop", "e1") == {"acked": "e1", "archived": True}
    assert not (Path(session["events_dir"]) / "e1.json").exists()
    assert (Path(session["consumed_dir"]) / "e1.json").exists()
    event(session, "e2", {"type": "comments", "ids": ["b"]})
    (Path(session["state_dir"]) / "watcher_heartbeat").write_text(f"{int(time.time())}\n")
    assert journey.ack("shop", "e2") == {"acked": "e2", "archived": False}
    assert (Path(session["consumed_dir"]) / "e2.ack").exists()
    with pytest.raises(journey.Refused):
        journey.ack("shop", "../e3")


# ── batches, attaching, Claude's state ─────────────────────────────────────

SENT = "2026-11-22T12:42:06.795Z"


def comment(number, **kw):
    c = {"id": f"c{number}", "number": number, "status": "open", "askedAt": "2026-11-22T12:30:00.000Z", "replies": []}
    c.update(kw)
    return c


def test_a_batch_is_the_comments_sent_together_and_still_waiting_oldest_send_first():
    later = "2026-11-22T13:00:00.000Z"
    comments = [
        comment(3, sentAt=SENT), comment(2, sentAt=SENT),
        comment(4, sentAt=later),
        comment(5),                                                       # written, never sent
        comment(6, sentAt=SENT, askedAt="2026-11-22T12:50:00.000Z"),      # written on after its send
        comment(7, sentAt=SENT, answeredAt="2026-11-22T12:45:00.000Z"),   # Claude answered it
        comment(8, sentAt=SENT, status="resolved"),
    ]
    got = [(b["sentAt"], [c["number"] for c in b["comments"]]) for b in journey.batches_of(comments)]
    assert got == [(SENT, [2, 3]), (later, [4])]


def test_pending_lists_the_batches_and_the_comments_not_sent_and_who_is_attached(session, monkeypatch):
    comments = {c["id"]: c for c in (comment(2, sentAt=SENT), comment(5))}
    for c in comments.values():
        c.update(board="b/01", boardTitle="B", chapter="b", shot="desktop", fx=0.1, fy=0.2, scope="app",
                 text="words", createdAt=c["askedAt"])
    monkeypatch.setattr(journey, "comments_of", lambda app, sid: comments)
    monkeypatch.setattr(journey, "board_files", lambda app, board: ["/x/b01.png"])
    monkeypatch.setattr(journey, "place", lambda app: {"folder": None})
    monkeypatch.setattr(journey.wc, "get_items", lambda sid, kind: {})
    monkeypatch.setattr(journey, "public_base", lambda: "https://wc.example.com")
    journey.attach("shop", "11111111-2222-3333-4444-555555555555", "mac", "/w")
    p = journey.pending("shop")
    assert [(b["sentAt"], b["count"], [c["number"] for c in b["comments"]]) for b in p["batches"]] == [(SENT, 1, [2])]
    assert p["batches"][0]["comments"][0]["images"] == ["/x/b01.png"]
    assert p["batches"][0]["comments"][0]["sentAt"] == SENT
    assert p["not_sent"] == [5]
    assert p["attached"] == "11111111-2222-3333-4444-555555555555"


def test_attach_records_the_session_and_its_machine_and_names_the_one_it_replaces(session):
    a, b = "11111111-2222-3333-4444-555555555555", "66666666-7777-8888-9999-000000000000"
    assert journey.attach("shop", a, "mac", "/work") == {"previous": None}
    o = journey.owner("shop")
    assert (o["session"], o["machine"], o["cwd"]) == (a, "mac", "/work")
    assert journey.attach("shop", a, "mac", "/work") == {"previous": None}
    assert journey.attach("shop", b, "main", "/w2") == {"previous": a}
    assert journey.claude_session("shop") == b
    assert [h["session"] for h in journey.owner("shop")["history"]] == [a]
    with pytest.raises(journey.Refused, match="inside a Claude Code session"):
        journey.attach("shop", "", "mac", "/work")


def test_claude_is_attached_only_while_the_attached_sessions_watcher_beats(session):
    import time
    st = journey.claude_state("shop", session)
    assert st["state"] == "detached" and st["attach"] == "/journey shop"
    journey.attach("shop", "11111111-2222-3333-4444-555555555555", "mac", "/w")
    assert journey.claude_state("shop", session)["state"] == "detached"   # attached, no watch yet
    beat = Path(session["state_dir"]) / "watcher_heartbeat"
    beat.write_text(f"{int(time.time()) - 20}\n")
    st = journey.claude_state("shop", session)
    assert (st["state"], st["session"], st["machine"]) == ("attached", "11111111", "mac")
    beat.write_text(f"{int(time.time()) - 200}\n")
    assert journey.claude_state("shop", session)["state"] == "detached"


def test_nothing_can_wake_a_session_or_install_a_doorman_any_more():
    for gone in ("doorman", "doorman_tick", "headless", "install_doorman", "launch", "claim"):
        assert not hasattr(journey, gone), gone
    with pytest.raises(SystemExit):
        journey.main(["doorman"])


# ── a canvas on another machine, over ssh ──────────────────────────────────

FAKE_SSH = r"""#!/usr/bin/env python3
# ssh as the tests need it: logs its argv, then runs the far command with that host's state folder.
import json, os, subprocess, sys
args = sys.argv[1:]
open(os.environ["FAKE_SSH_LOG"], "a").write(json.dumps(args) + "\n")
rest = []
i = 0
while i < len(args):
    if args[i] == "-o":
        i += 2
        continue
    rest.append(args[i])
    i += 1
tty = rest[0] == "-tt"
if tty:
    rest = rest[1:]
host, cmd = rest[0], rest[1]
if os.environ.get("FAKE_SSH_SAY"):
    sys.stdout.write(os.environ["FAKE_SSH_SAY"])
    sys.exit(0)
env = {**os.environ, "JOURNEY_STATE": os.path.join(os.environ["FAKE_HOSTS"], host)}
sys.exit(subprocess.run(["sh", "-c", cmd], env=env).returncode)
"""

FAKE_SCP = r"""#!/usr/bin/env python3
import os, shutil, sys
args = [a for a in sys.argv[1:] if a != "-q"]
args = [a for i, a in enumerate(args) if a != "-o" and (i == 0 or args[i - 1] != "-o")]
src, dest = args[-2], args[-1]
host, path = src.split(":", 1)
shutil.copy(path, dest)
"""


@pytest.fixture
def far(tmp_path, monkeypatch):
    """A canvas host `far` reached through a fake ssh: its own state folder, and journey.py run there for real."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("ssh", FAKE_SSH), ("scp", FAKE_SCP)):
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_SSH_LOG", str(tmp_path / "ssh.log"))
    monkeypatch.setenv("FAKE_HOSTS", str(tmp_path / "hosts"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "11111111-2222-3333-4444-555555555555")
    import sys
    monkeypatch.setattr(journey, "CONFIG", {"canvas_hosts": ["far"], "remote_python": sys.executable,
                                            "remote_journey": str(Path(journey.__file__))})
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "here-state")
    monkeypatch.setattr(journey, "CACHE", tmp_path / "cache")

    def log():
        return [json.loads(x) for x in (tmp_path / "ssh.log").read_text().splitlines()]
    return {"hosts": tmp_path / "hosts", "log": log, "tmp": tmp_path}


def test_the_far_command_line_runs_the_hosts_journey_py_from_its_own_home():
    assert journey.remote_command(["has", "a b"]) == \
        'python3 "$HOME"/projects/claude-annotate/skills/journey/journey.py has \'a b\''


def test_a_canvas_this_machine_lacks_is_found_on_the_canvas_host_by_running_journey_py_there(far, monkeypatch):
    monkeypatch.setattr(journey, "CONFIG", {**journey.CONFIG, "canvas_hosts": ["near", "far"]})
    d = far["hosts"] / "far" / "shop-events"
    d.mkdir(parents=True)
    (d / "canvas.json").write_text(json.dumps({"app": "shop", "name": "events", "checkout": "/x", "canvas": "/x/.out"}))
    assert journey.remote_host("shop-events") == "far"
    assert journey.remote_host("shop-other") is None
    record("shop-mine", "shop", "/y", "/y/.out")
    assert journey.remote_host("shop-mine") is None  # registered here: never asked


def test_attach_from_another_machine_carries_this_sessions_id_machine_and_folder(far, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_SSH_SAY", '{"previous": null}\n')
    monkeypatch.setattr(journey, "MACHINE", "mac")
    assert journey.main(["attach", "shop-events", "--machine", "mac", "--cwd", "/work"]) == 0
    argv = far["log"]()[-1]
    assert argv[-2] == "far" and "-tt" not in argv
    far_cmd = argv[-1]
    assert far_cmd.endswith("attach shop-events --machine mac --cwd /work --session "
                            "11111111-2222-3333-4444-555555555555 --machine mac --cwd /work")
    assert "previous" in capsys.readouterr().out


def test_a_reply_from_another_machine_sends_its_text_on_stdin(far, monkeypatch, capsys):
    import io
    seen = {}

    def run(argv, **kw):
        seen.update(argv=argv, input=kw.get("input"))
        return subprocess.CompletedProcess(argv, 0, '{"appended": true}\n', "")
    monkeypatch.setattr(journey.subprocess, "run", run)
    monkeypatch.setattr(journey.sys, "stdin", io.StringIO("It goes into plan 41, group Preferences.\n"))
    assert journey.main(["reply", "shop-events", "c7", "-"]) == 0
    assert seen["input"] == "It goes into plan 41, group Preferences.\n"
    assert seen["argv"][-1].endswith("reply shop-events c7 -")


def test_a_batch_read_from_another_machine_has_its_board_images_copied_here(far, monkeypatch, capsys):
    img = far["tmp"] / "far-canvas" / "pref" / "01.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"png!")
    batch = [{"sentAt": SENT, "count": 1, "comments": [{"id": "c5", "number": 5, "images": [str(img)]}]}]
    monkeypatch.setenv("FAKE_SSH_SAY", json.dumps(batch) + "\n")
    assert journey.main(["--json", "batches", "shop-events"]) == 0
    got = json.loads(capsys.readouterr().out)
    local = Path(got[0]["comments"][0]["images"][0])
    assert local.parent.parent == far["tmp"] / "cache" and local.name.endswith("-01.png")
    assert local.read_bytes() == b"png!"
    assert "--json batches shop-events" in far["log"]()[-1][-1]


def test_the_far_watch_keeps_a_terminal_and_its_lines_arrive_without_carriage_returns(far, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_SSH_SAY", "WEBCOMPANION_EVENT skill=journey sid=s1 event_id=e1\r\n---end---\r\n")
    assert journey.main(["watch", "shop-events"]) == 0
    assert capsys.readouterr().out == "WEBCOMPANION_EVENT skill=journey sid=s1 event_id=e1\n---end---\n"
    argv = far["log"]()[-1]
    assert "-tt" in argv and argv[-1].endswith("watch shop-events --session 11111111-2222-3333-4444-555555555555")


def test_an_unreachable_canvas_host_is_said_in_one_line(far, monkeypatch, capsys):
    monkeypatch.setattr(journey.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 255, "", "ssh: connect to host far: refused\n"))
    assert journey.main(["pending", "shop-events"]) == 1
    assert "cannot reach far over ssh" in capsys.readouterr().err


def test_the_build_item_carries_the_published_pages_own_time_so_a_reload_lands_on_it(tmp_path, monkeypatch):
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    for app in ("shop", "ledger"):
        record(f"{app}-events", app, tmp_path, tmp_path / app)
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "index.html").write_text(
        '<script type="application/json" id="canvas-data">{"title":"x","built":"2026-10-30T08:00:41.454Z","groups":[]}</script>')
    assert journey.page_built("shop-events") == "2026-10-30T08:00:41.454Z"
    assert journey.page_built("ledger-events") is None


def test_a_canvas_is_its_registered_folder_and_its_link_is_its_sessions_by_key(tmp_path, monkeypatch):
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setattr(journey, "public_base", lambda: "https://wc.example.com")
    record("ledger-bills", "ledger", tmp_path / "co", tmp_path / "co" / ".out")
    assert journey.canvas_dir("ledger-bills") == tmp_path / "co" / ".out"
    assert journey.stable_link("shop-events") == "https://wc.example.com/s/shop-events/"
    assert journey.board_link("tutor-trial", "today/01-today") == \
        "https://wc.example.com/s/tutor-trial/#board-today/01-today"
    # An app alone is no canvas any more: the app-wide canvases are gone (14 November 2026).
    with pytest.raises(journey.Refused, match="no journey canvas 'ledger'"):
        journey.canvas_dir("ledger")
    with pytest.raises(journey.Refused, match="a canvas needs a name"):
        journey.canvas_key("ledger", "")
    assert journey.canvas_keys() == ["ledger-bills"]


def test_every_app_names_its_features_run_and_results_and_no_canvas_or_sandbox_of_its_own():
    for app, spec in journey.APPS.items():
        assert {"name", "features", "run", "after", "results"} <= set(spec), app
        assert not {"sandbox", "checkout", "canvas", "scopes"} & set(spec), app
        assert "gherkin" in spec["features"], app
        assert "{features}" in spec["run"], app


def test_the_example_apps_run_the_app_cli_sandbox_journey_with_no_kill_after_and_no_old_checkout():
    for app in ("shop", "ledger", "tutor"):
        spec = journey.APPS[app]
        assert spec["run"] == ["{cli}", "sandbox", "journey", app, "{--name}", "{features}", "--publish"]
        assert spec["after"] is None
        assert spec["env"] == {"APP_HOME": "{home}"}
        assert "fallback" not in spec
    assert list(journey.APPS) == ["shop", "ledger", "tutor"]


def test_a_comments_images_are_its_boards_shots_by_id_or_by_number(tmp_path, monkeypatch):
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    for app in ("ledger", "shop"):
        record(f"{app}-events", app, tmp_path, tmp_path / app)
    (tmp_path / "ledger" / "fix").mkdir(parents=True)
    (tmp_path / "ledger" / "fix" / "014.png").write_bytes(b"png")
    (tmp_path / "ledger" / "canvas.json").write_text(json.dumps({"groups": [{"boards": [
        {"number": 14, "shots": [{"file": "fix/014.png"}]}]}]}))
    assert journey.board_files("ledger-events", 14) == [str(tmp_path / "ledger" / "fix" / "014.png")]
    assert journey.board_files("ledger-events", 15) == []
    (tmp_path / "shop" / "today").mkdir(parents=True)
    for f in ("01-today.png", "01-today.phone.png"):
        (tmp_path / "shop" / "today" / f).write_bytes(b"png")
    (tmp_path / "shop" / "canvas.json").write_text(json.dumps({"groups": [{"boards": [
        {"number": 1, "id": "today/01-today", "shots": [{"file": "today/01-today.png"}, {"file": "today/01-today.phone.png"}]}]}]}))
    assert journey.board_files("shop-events", "today/01-today") == [str(tmp_path / "shop" / "today" / f)
                                                             for f in ("01-today.png", "01-today.phone.png")]


# ── a canvas's sandbox: its record names it ──

FAKE_CLI = """#!/usr/bin/env python3
import datetime, json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"argv": args, "cli": sys.argv[0], "cwd": os.getcwd(), "home": os.environ.get("APP_HOME")}) + "\\n")
if args[:2] == ["sandbox", "journey"] or args[1:2] == ["journey"]:
    assert args[-1] == "--publish"
    if "--name" in args:
        i = args.index("--name")
        args = args[:i] + args[i + 2:]
    sb = os.environ["FAKE_SANDBOX"]
    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for f in args[(3 if args[0] == "sandbox" else 2):-1] or ["sign-in", "today-s-log-and-more"]:
        d = os.path.join(sb, "apps", "shop", "frontend", "e2e", "journey", ".out", f)
        os.makedirs(d, exist_ok=True)
        json.dump({"status": "passed", "finishedAt": at, "boards": [1, 2, 3]}, open(os.path.join(d, "manifest.json"), "w"))
    sys.exit(0)
sys.exit(3)
"""


def fake_cli(root: Path, named: bool) -> Path:
    """An app CLI stand-in under root; `named`: its source knows `sandbox journey --name`."""
    cli = root / "tools" / "app" / "bin" / "app"
    cli.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text(FAKE_CLI)
    cli.chmod(0o755)
    src = root / "tools" / "app" / "src" / "commands" / "sandbox" / "journey.ts"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("const taken = takeNameFlag(argv)\n" if named else "journeySandboxOf(...)\n")
    return cli


@pytest.fixture
def appenv(tmp_path, monkeypatch):
    """A session home whose CLI is a stand-in, a shop sandbox folder, and its canvas, shop-events."""
    home = tmp_path / "app-home"
    cli = fake_cli(home, named=True)
    f = home / "apps" / "shop" / "frontend" / "e2e" / "journey" / "journey.feature"
    f.parent.mkdir(parents=True)
    f.write_text("Feature: x\n  Scenario: From main\n")
    sandbox = tmp_path / "checkouts" / "07-shop-sandbox-events"
    canvas = sandbox / ".out"
    logf = tmp_path / "cli.log"
    monkeypatch.setenv("FAKE_LOG", str(logf))
    monkeypatch.setenv("FAKE_SANDBOX", str(sandbox))
    monkeypatch.setattr(journey, "APP_HOME", home)
    monkeypatch.setattr(journey, "CONFIG", {"cli": "tools/app/bin/app",
                                            "cli_probe": {"file": "src/commands/sandbox/journey.ts", "needle": "takeNameFlag"}})
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    record("shop-events", "shop", sandbox, canvas)

    def calls():
        return [json.loads(x) for x in logf.read_text().splitlines()] if logf.exists() else []
    return {"home": home, "cli": cli, "sandbox": sandbox, "canvas": canvas, "calls": calls}


def make_sandbox(appenv, feature=FEATURE):
    """The canvas's sandbox folder, with its journey.feature."""
    f = appenv["sandbox"] / "apps" / "shop" / "frontend" / "e2e" / "journey" / "journey.feature"
    f.parent.mkdir(parents=True)
    f.write_text(feature)


def test_a_canvass_folder_is_the_sandbox_its_record_names(appenv):
    make_sandbox(appenv)
    p = journey.place("shop-events")
    assert (p["from"], p["folder"], p["name"]) == ("sandbox", appenv["sandbox"], "events")
    assert p["run"] == ["{cli}", "sandbox", "journey", "shop", "{--name}", "{features}", "--publish"]
    assert appenv["calls"]() == []  # read from the record: nothing runs


def test_a_gone_sandbox_or_an_archived_canvas_gives_no_folder(appenv, tmp_path):
    assert journey.place("shop-events")["folder"] is None  # its folder does not exist yet
    make_sandbox(appenv)
    assert journey.place("shop-events")["folder"] == appenv["sandbox"]
    record("shop-events", "shop", appenv["sandbox"], tmp_path / "archive", archived="2026-11-14T16:00:00Z")
    assert journey.place("shop-events")["folder"] is None


def test_feature_ids_come_from_the_canvas_sandbox_when_it_exists_else_from_the_main_checkout(appenv):
    assert [f["id"] for f in journey.features("shop-events")] == ["from-main"]
    make_sandbox(appenv)
    assert [f["id"] for f in journey.features("shop-events")] == ["sign-in", "plan-setup", "today-s-log-and-more"]


@pytest.fixture
def canvas_stubs(monkeypatch):
    monkeypatch.setattr(journey, "on_main", lambda: True)
    monkeypatch.setattr(journey, "sid_of", lambda app: "s-1")
    items = {}
    monkeypatch.setattr(journey, "put_item", lambda sid, anchor, body: items.setdefault(anchor, []).append(body))
    monkeypatch.setattr(journey, "ensure", lambda app: {"sid": "s-1"})
    monkeypatch.setattr(journey, "public_base", lambda: "https://wc.example.com")
    return items


def test_a_rerun_runs_the_cli_sandbox_journey_from_the_session_home_and_reads_results_from_the_canvass_sandbox(appenv, canvas_stubs):
    make_sandbox(appenv)
    res = journey.rerun("shop-events", ["sign-in"], "e-1")
    assert appenv["calls"]() == [{"argv": ["sandbox", "journey", "shop", "--name", "events", "sign-in", "--publish"], "cli": str(appenv["cli"]),
                                 "cwd": str(appenv["home"]), "home": str(appenv["home"])}]
    assert res["features"] == {"sign-in": {"state": "passed", "boards": 3}}
    assert [b["state"] for b in canvas_stubs["run/sign-in"]] == ["running", "passed"]


def test_until_main_knows_named_journeys_a_rerun_uses_the_canvas_sandboxs_cli_or_refuses(appenv, canvas_stubs, tmp_path):
    """An older CLI would make a permanent journey sandbox again: never run it."""
    fake_cli(appenv["home"], named=False)
    with pytest.raises(journey.Refused, match="cannot run a journey in a named sandbox yet"):
        journey.rerun("shop-events", ["all"])
    assert appenv["calls"]() == []
    assert "run/from-main" not in canvas_stubs  # refused before anything showed running
    make_sandbox(appenv)
    own = fake_cli(appenv["sandbox"], named=True)
    journey.rerun("shop-events", ["sign-in"])
    # Run from the sandbox's own checkout: an app CLI shim runs the CLI of the checkout its working directory is in.
    assert [(c["cli"], c["cwd"], c["argv"]) for c in appenv["calls"]()] == [
        (str(own), str(appenv["sandbox"]), ["sandbox", "journey", "shop", "--name", "events", "sign-in", "--publish"])]


def test_a_rerun_of_a_checkouts_own_cli_runs_from_that_checkout(appenv, canvas_stubs, monkeypatch):
    """With no sandboxes (the Mac), the apps file runs the canvas checkout's CLI: run it from that checkout, or the
    CLI shim runs the session home's checkout instead."""
    make_sandbox(appenv)
    own = fake_cli(appenv["sandbox"], named=True)
    monkeypatch.setitem(journey.APPS, "shop", {**journey.APPS["shop"], "run": ["tools/app/bin/app", "shop", "journey", "{features}", "--publish"]})
    journey.rerun("shop-events", ["sign-in"])
    assert [(c["cli"], c["cwd"], c["argv"]) for c in appenv["calls"]()] == [
        (str(own), str(appenv["sandbox"]), ["shop", "journey", "sign-in", "--publish"])]


def test_apps_lists_every_registered_canvas_with_its_folder(appenv, monkeypatch, capsys):
    make_sandbox(appenv)
    monkeypatch.setattr(journey, "on_main", lambda: False)
    monkeypatch.setattr(journey, "public_base", lambda: "https://wc.example.com")
    assert journey.main(["--json", "apps"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [(r["app"], r["folder"], r["canvas"], r["link"]) for r in rows] == [
        ("shop-events", str(appenv["sandbox"]), str(appenv["canvas"]), "https://wc.example.com/s/shop-events/")]


def test_a_command_that_runs_too_long_is_stopped_and_reported_as_timed_out(tmp_path, monkeypatch):
    """A hung journey run must not hold the session for ever: run_bounded gives the timeout(1) exit
    code 124 and says why in the run's log, where a failed run's error already points."""
    seen = {}

    def hung(argv, timeout, **kw):
        seen.update(argv=argv, timeout=timeout)
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr(journey.subprocess, "run", hung)
    log = tmp_path / "run.log"
    with open(log, "w") as lf:
        code = journey.run_bounded(["npm", "test"], 90, lf, cwd=tmp_path)
    assert code == 124
    assert seen == {"argv": ["npm", "test"], "timeout": 90}
    assert log.read_text() == "\nstopped: ran longer than 90s\n"


def test_progress_writes_run_items_only_and_nothing_without_a_session(monkeypatch):
    sent = []
    monkeypatch.setattr(journey, "sid_of", lambda app: "s-1")
    monkeypatch.setattr(journey.wc, "put_items", lambda sid, items, kind: sent.append((sid, items, kind)))
    items = {"run/__journey__": {"state": "running", "done": 1, "total": 3}, "run/today": {"state": "running"}}
    assert journey.progress("shop", items) == {"written": 2}
    assert sent == [("s-1", items, "journey")]
    with pytest.raises(journey.Refused, match="run/<id> items only"):
        journey.progress("shop", {"claude/status": {"state": "listening"}})

    def no_session(app):
        raise journey.Refused("no session")
    monkeypatch.setattr(journey, "sid_of", no_session)
    assert journey.progress("shop", items)["written"] == 0
    assert len(sent) == 1


# ── a journey belongs to a sandbox: one canvas each, keyed <app>-<name> ──

def test_a_sandboxs_canvas_has_its_own_key_folder_session_and_link_and_reruns_with_its_name(appenv, canvas_stubs, monkeypatch):
    make_sandbox(appenv)
    own = appenv["sandbox"] / "apps" / "shop" / "frontend" / "e2e" / "journey" / ".out"
    own.mkdir(parents=True)
    monkeypatch.setattr(journey, "ensure", lambda key: {"sid": "s-" + key, "url": journey.stable_link(key)})
    res = journey.register("shop", "Sandbox Events", str(appenv["sandbox"]), str(own))
    assert (res["key"], res["url"]) == ("shop-sandbox-events", "https://wc.example.com/s/shop-sandbox-events/")
    assert journey.app_of("shop-sandbox-events") == "shop"
    assert journey.canvas_dir("shop-sandbox-events") == own
    # One Claude session per canvas, in its sandbox.
    assert journey.session_folder("shop-sandbox-events") == appenv["sandbox"]
    assert "shop-sandbox-events" in journey.canvas_keys()
    journey.rerun("shop-sandbox-events", ["sign-in"])
    assert [c["argv"] for c in appenv["calls"]()] == [["sandbox", "journey", "shop", "--name", "Sandbox Events", "sign-in", "--publish"]]
    with pytest.raises(journey.Refused, match="no journey canvas 'shop-nothing'"):
        journey.app_of("shop-nothing")


def test_a_removed_sandboxs_canvas_is_archived_its_page_moves_and_it_runs_nothing(appenv, canvas_stubs, monkeypatch, tmp_path):
    make_sandbox(appenv)
    own = appenv["sandbox"] / ".out"
    own.mkdir(parents=True, exist_ok=True)
    (own / "index.html").write_text("canvas")
    monkeypatch.setattr(journey, "ensure", lambda key: {"sid": "s-1", "url": journey.stable_link(key)})
    journey.register("shop", "events", str(appenv["sandbox"]), str(own))
    res = journey.archive("shop-events", str(tmp_path / "archive" / "shop-events"))
    assert (tmp_path / "archive" / "shop-events" / "index.html").read_text() == "canvas"
    assert journey.canvas_dir("shop-events") == tmp_path / "archive" / "shop-events"
    assert res["url"] == "https://wc.example.com/s/shop-events/"
    assert journey.place("shop-events")["folder"] is None
    with pytest.raises(journey.Refused, match="archived"):
        journey.rerun("shop-events", ["sign-in"])
    assert appenv["calls"]() == []
