"""The journey tool (skills/journey): its store against the page's, and the doorman's decisions.

No test reaches webcompanion or starts Claude: the session, its directories and the wake-up are
stand-ins, and the state folder is a tmp_path."""
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


@pytest.fixture
def app_checkout(tmp_path, monkeypatch):
    co = tmp_path / "co"
    f = co / "apps" / "shop" / "frontend" / "e2e" / "journey" / "journey.feature"
    f.parent.mkdir(parents=True)
    f.write_text(FEATURE)
    monkeypatch.setattr(journey, "features_root", lambda app: co)
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    return co


def test_features_are_journey_features_scenarios_as_slugs_with_their_skip(app_checkout):
    assert journey.features("shop") == [
        {"id": "sign-in", "name": "Sign in", "skip": False},
        {"id": "plan-setup", "name": "Plan setup", "skip": True},
        {"id": "today-s-log-and-more", "name": "Today's log, and more", "skip": False}]


def test_a_rerun_refuses_any_id_the_journey_does_not_have_before_running_anything(app_checkout, monkeypatch):
    monkeypatch.setattr(journey, "on_main", lambda: True)
    ran = []
    monkeypatch.setattr(journey.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(journey.Refused, match="no feature plan-setup; rm -rf"):
        journey.rerun("shop", ["plan-setup; rm -rf"])
    with pytest.raises(journey.Refused, match="no feature plan-setup"):
        journey.rerun("shop", ["plan-setup"])  # @skip never runs
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


# ── Claude's state and the doorman ─────────────────────────────────────────

@pytest.fixture
def quiet(monkeypatch, session):
    """The doorman's world as stand-ins: one waiting event, nobody listening, the lock free."""
    world = {"events": [("e1", {"text": "{}"})], "held": [], "lock": True, "woke": [], "owner_alive": False}
    monkeypatch.setattr(journey, "find_session", lambda app: {"sid": "s-1"})
    monkeypatch.setattr(journey, "pending_events", lambda dirs: list(world["events"]))
    monkeypatch.setattr(journey, "processes_naming", lambda sid: world["held"])
    monkeypatch.setattr(journey, "lock_free", lambda app: world["lock"])
    monkeypatch.setattr(journey, "is_claude", lambda pid: world["owner_alive"])
    monkeypatch.setattr(journey, "put_item", lambda sid, anchor, body: None)
    journey.set_claude_session("shop", "11111111-2222-3333-4444-555555555555")

    def wake(app, sid):
        world["woke"].append(app)
        world["events"] = []
        return 0

    monkeypatch.setattr(journey, "headless", wake)
    return world


def test_the_doorman_wakes_an_app_with_a_waiting_event_and_nobody_listening(quiet):
    assert journey.doorman_tick("shop") == "woke (exit 0)"
    assert quiet["woke"] == ["shop"]


def test_the_doorman_leaves_an_app_alone_while_a_watcher_listens(quiet, session):
    import time
    (Path(session["state_dir"]) / "watcher_heartbeat").write_text(f"{int(time.time()) - 20}\n")
    assert journey.doorman_tick("shop") == "listening"
    assert quiet["woke"] == []


def test_the_doorman_wakes_once_the_heartbeat_is_older_than_90_seconds(quiet, session):
    import time
    (Path(session["state_dir"]) / "watcher_heartbeat").write_text(f"{int(time.time()) - 200}\n")
    assert journey.doorman_tick("shop").startswith("woke")


def test_the_doorman_leaves_a_session_the_user_has_open(quiet):
    journey.write_json(journey.state_dir("shop") / "owner.json", {"pid": 4242, "mode": "interactive"})
    quiet["owner_alive"] = True
    assert journey.doorman_tick("shop") == "open"
    quiet["owner_alive"] = False
    quiet["held"] = [999]  # a `claude --resume <id>` started some other way
    assert journey.doorman_tick("shop") == "held"
    assert quiet["woke"] == []


def test_the_doorman_never_starts_a_second_claude_while_the_lock_is_held(quiet):
    quiet["lock"] = False
    assert journey.doorman_tick("shop") == "locked"
    assert quiet["woke"] == []


def test_the_doorman_does_nothing_without_a_waiting_event(quiet):
    quiet["events"] = []
    assert journey.doorman_tick("shop") == "idle"
    assert quiet["woke"] == []


def test_a_wake_that_answers_nothing_backs_off_before_trying_again(quiet, monkeypatch):
    def fails(app, sid):
        quiet["woke"].append(app)
        return 1

    monkeypatch.setattr(journey, "headless", fails)
    assert journey.doorman_tick("shop") == "woke (exit 1)"
    assert journey.doorman_tick("shop") == "backing off"
    assert quiet["woke"] == ["shop"]
    d = journey.read_json(journey.state_dir("shop") / "doorman.json", {})
    assert d["failures"] == 1 and d["left"] == ["e1"]


# ── the migration ──────────────────────────────────────────────────────────

OLD = {"version": 1, "comments": [
    {"id": "cmold1", "number": 1, "app": "ledger", "board": "sign-in/01-sign-in", "boardTitle": "Sign in", "chapter": "Sign in",
     "shot": "desktop", "fx": 0.62, "fy": 0.23, "text": "Make them differ", "scope": "both", "status": "resolved",
     "createdAt": "2026-10-30T06:00:00.000Z", "updatedAt": "2026-10-30T07:00:00.000Z", "resolvedAt": "2026-10-30T07:00:00.000Z",
     "replies": [{"id": "rold1", "text": "And the icons", "createdAt": "2026-10-30T06:10:00.000Z"}]},
    {"id": "cmold2", "number": 3, "app": "shop", "board": "settings/01-settings", "boardTitle": "Settings", "chapter": "Settings",
     "shot": "phone", "fx": 0.43, "fy": 0.14, "text": "Icons, edited", "scope": "app", "status": "open",
     "createdAt": "2026-10-30T06:20:00.000Z", "updatedAt": "2026-10-30T06:30:00.000Z",
     "replies": [{"id": "rold2", "text": "Second", "createdAt": "2026-10-30T06:25:00.000Z", "updatedAt": "2026-10-30T06:26:00.000Z"}]},
]}


def test_the_migration_carries_every_comment_reply_edit_and_resolve_over_and_compares_equal(tmp_path, monkeypatch):
    threads: dict[str, dict] = {}

    def request(method, path, body=None, **kw):
        assert method == "POST" and "/threads/" in path
        sid, anchor = path.split("/")[2], journey.wc.urllib.parse.unquote(path.split("/threads/")[1])
        msgs = threads.setdefault(sid, {}).setdefault(anchor, {"messages": []})["messages"]
        if any(m.get("source_event_id") == body["source_event_id"] for m in msgs):
            return {"appended": False}
        msgs.append(body)
        return {"appended": True}

    monkeypatch.setattr(journey, "on_main", lambda: True)
    monkeypatch.setattr(journey, "ensure", lambda app: {"sid": f"s-{app}"})
    monkeypatch.setattr(journey, "sid_of", lambda app: f"s-{app}")
    monkeypatch.setattr(journey.wc, "request", request)
    monkeypatch.setattr(journey.wc, "get_threads", lambda sid, kind: threads.get(sid, {}))
    src = tmp_path / "comments.json"
    src.write_text(json.dumps(OLD))
    first = journey.migrate(src, apply=True)
    assert first["compare"] == {"same": 2, "different": [], "missing": []}
    assert first["ledger"]["messages"] == 3 and first["shop"]["messages"] == 4
    again = journey.migrate(src, apply=True)
    assert again["ledger"]["appended"] == 0 and again["shop"]["appended"] == 0


def test_a_long_answer_for_one_app_never_holds_another_apps_wake(monkeypatch):
    import threading
    started, release = [], threading.Event()

    def tick(app):
        started.append(app)
        if app == "shop":
            release.wait(5)
        return "idle"

    monkeypatch.setattr(journey, "on_main", lambda: True)
    monkeypatch.setattr(journey, "doorman_tick", tick)
    t = threading.Thread(target=journey.doorman, kwargs={"once": True})
    t.start()
    for _ in range(100):
        if len(started) == len(journey.APPS):
            break
        threading.Event().wait(0.02)
    assert sorted(started) == sorted(journey.APPS)  # all began while shop still ran
    release.set()
    t.join(5)


def test_the_build_item_carries_the_published_pages_own_time_so_a_reload_lands_on_it(tmp_path, monkeypatch):
    for app in ("shop", "ledger"):
        monkeypatch.setitem(journey.APPS, app, {**journey.APPS[app], "canvas": str(tmp_path / app)})
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "index.html").write_text(
        '<script type="application/json" id="canvas-data">{"title":"x","built":"2026-10-30T08:00:41.454Z","groups":[]}</script>')
    assert journey.page_built("shop") == "2026-10-30T08:00:41.454Z"
    assert journey.page_built("ledger") is None


def test_the_published_canvas_lives_outside_the_outbox_and_its_link_is_the_sessions_by_slug(monkeypatch):
    monkeypatch.setattr(journey, "public_base", lambda: "https://wc.example.com")
    assert journey.canvas_dir("ledger") == journey.HOME / ".local" / "share" / "journey-canvas" / "ledger"
    assert journey.stable_link("shop") == "https://wc.example.com/s/shop/"
    assert journey.board_link("tutor", "today/01-today") == \
        "https://wc.example.com/s/tutor/#board-today/01-today"


def test_every_app_names_its_canvas_features_run_and_results_and_no_sandbox_of_its_own():
    for app, spec in journey.APPS.items():
        assert {"name", "scopes", "canvas", "features", "run", "after", "results"} <= set(spec), app
        assert "sandbox" not in spec and "checkout" not in spec, app
        assert "gherkin" in spec["features"], app
        assert "{features}" in spec["run"], app


def test_the_example_apps_run_the_app_cli_sandbox_journey_with_no_kill_after_and_no_old_checkout():
    for app in ("shop", "ledger", "tutor"):
        spec = journey.APPS[app]
        assert spec["run"] == ["{cli}", "sandbox", "journey", app, "{features}", "--publish"]
        assert spec["after"] is None
        assert spec["env"] == {"APP_HOME": "{home}"}
        assert "fallback" not in spec
    assert list(journey.APPS) == ["shop", "ledger", "tutor"]


def test_a_comments_images_are_its_boards_shots_by_id_or_by_number(tmp_path, monkeypatch):
    for app in ("ledger", "shop"):
        monkeypatch.setitem(journey.APPS, app, {**journey.APPS[app], "canvas": str(tmp_path / app)})
    (tmp_path / "ledger" / "fix").mkdir(parents=True)
    (tmp_path / "ledger" / "fix" / "014.png").write_bytes(b"png")
    (tmp_path / "ledger" / "canvas.json").write_text(json.dumps({"groups": [{"boards": [
        {"number": 14, "shots": [{"file": "fix/014.png"}]}]}]}))
    assert journey.board_files("ledger", 14) == [str(tmp_path / "ledger" / "fix" / "014.png")]
    assert journey.board_files("ledger", 15) == []
    (tmp_path / "shop" / "today").mkdir(parents=True)
    for f in ("01-today.png", "01-today.phone.png"):
        (tmp_path / "shop" / "today" / f).write_bytes(b"png")
    (tmp_path / "shop" / "canvas.json").write_text(json.dumps({"groups": [{"boards": [
        {"number": 1, "id": "today/01-today", "shots": [{"file": "today/01-today.png"}, {"file": "today/01-today.phone.png"}]}]}]}))
    assert journey.board_files("shop", "today/01-today") == [str(tmp_path / "shop" / "today" / f)
                                                             for f in ("01-today.png", "01-today.phone.png")]


# ── an app's journey: any sandbox, read from the canvas's source.json ──

FAKE_CLI = """#!/usr/bin/env python3
import datetime, json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({"argv": args, "cli": sys.argv[0], "cwd": os.getcwd(), "home": os.environ.get("APP_HOME")}) + "\\n")
if args[:2] == ["sandbox", "journey"]:
    assert args[-1] == "--publish"
    sb = os.environ["FAKE_SANDBOX"]
    at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    for f in args[3:-1] or ["sign-in", "today-s-log-and-more"]:
        d = os.path.join(sb, "apps", "shop", "frontend", "e2e", "journey", ".out", f)
        os.makedirs(d, exist_ok=True)
        json.dump({"status": "passed", "finishedAt": at, "boards": [1, 2, 3]}, open(os.path.join(d, "manifest.json"), "w"))
    canvas = os.environ["FAKE_CANVAS"]
    os.makedirs(canvas, exist_ok=True)
    json.dump({"app": "shop", "sandbox": "events", "branch": "shop/sandbox-events", "path": sb, "head": "abc", "ranAt": at},
              open(os.path.join(canvas, "source.json"), "w"))
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
    """A session home whose CLI is a stand-in, a shop sandbox folder, and the shop canvas folder."""
    home = tmp_path / "app-home"
    cli = fake_cli(home, named=True)
    f = home / "apps" / "shop" / "frontend" / "e2e" / "journey" / "journey.feature"
    f.parent.mkdir(parents=True)
    f.write_text("Feature: x\n  Scenario: From main\n")
    sandbox = tmp_path / "checkouts" / "07-shop-sandbox-events"
    canvas = tmp_path / "canvas" / "shop"
    logf = tmp_path / "cli.log"
    monkeypatch.setenv("FAKE_LOG", str(logf))
    monkeypatch.setenv("FAKE_SANDBOX", str(sandbox))
    monkeypatch.setenv("FAKE_CANVAS", str(canvas))
    monkeypatch.setattr(journey, "APP_HOME", home)
    monkeypatch.setattr(journey, "CONFIG", {"cli": "tools/app/bin/app",
                                            "cli_probe": {"file": "src/commands/sandbox/journey.ts", "needle": "takeNameFlag"}})
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    monkeypatch.setitem(journey.APPS, "shop", {**journey.APPS["shop"], "canvas": str(canvas)})

    def calls():
        return [json.loads(x) for x in logf.read_text().splitlines()] if logf.exists() else []
    return {"home": home, "cli": cli, "sandbox": sandbox, "canvas": canvas, "calls": calls}


def make_sandbox(appenv, feature=FEATURE, **source):
    """The sandbox folder with its journey.feature, and the canvas's source.json naming it."""
    f = appenv["sandbox"] / "apps" / "shop" / "frontend" / "e2e" / "journey" / "journey.feature"
    f.parent.mkdir(parents=True)
    f.write_text(feature)
    appenv["canvas"].mkdir(parents=True, exist_ok=True)
    (appenv["canvas"] / "source.json").write_text(json.dumps({"app": "shop", "sandbox": "events", "branch": "shop/sandbox-events",
                                                            "path": str(appenv["sandbox"]), "head": "abc", "ranAt": "x", **source}))


def test_an_apps_folder_is_the_sandbox_its_canvas_was_captured_on(appenv):
    make_sandbox(appenv)
    p = journey.place("shop")
    assert (p["from"], p["folder"]) == ("sandbox", appenv["sandbox"])
    assert p["run"] == ["{cli}", "sandbox", "journey", "shop", "{features}", "--publish"]
    assert appenv["calls"]() == []  # read from source.json: nothing runs


def test_no_source_an_ended_sandbox_or_a_gone_folder_gives_no_folder(appenv):
    assert journey.place("shop")["folder"] is None
    make_sandbox(appenv, ended="shipped #840")
    assert journey.place("shop")["folder"] is None
    (appenv["canvas"] / "source.json").write_text(json.dumps({"path": str(appenv["sandbox"] / "gone")}))
    assert journey.place("shop")["folder"] is None


def test_feature_ids_come_from_the_canvas_sandbox_when_it_exists_else_from_the_main_checkout(appenv):
    assert [f["id"] for f in journey.features("shop")] == ["from-main"]
    make_sandbox(appenv)
    assert [f["id"] for f in journey.features("shop")] == ["sign-in", "plan-setup", "today-s-log-and-more"]


@pytest.fixture
def canvas_stubs(monkeypatch):
    monkeypatch.setattr(journey, "on_main", lambda: True)
    monkeypatch.setattr(journey, "sid_of", lambda app: "s-1")
    items = {}
    monkeypatch.setattr(journey, "put_item", lambda sid, anchor, body: items.setdefault(anchor, []).append(body))
    monkeypatch.setattr(journey, "ensure", lambda app: {"sid": "s-1"})
    monkeypatch.setattr(journey, "public_base", lambda: "https://wc.example.com")
    return items


def test_a_rerun_runs_the_cli_sandbox_journey_from_the_session_home_and_reads_results_from_the_sandbox_it_published_from(appenv, canvas_stubs):
    make_sandbox(appenv)
    res = journey.rerun("shop", ["sign-in"], "e-1")
    assert appenv["calls"]() == [{"argv": ["sandbox", "journey", "shop", "sign-in", "--publish"], "cli": str(appenv["cli"]),
                                 "cwd": str(appenv["home"]), "home": str(appenv["home"])}]
    assert res["features"] == {"sign-in": {"state": "passed", "boards": 3}}
    assert [b["state"] for b in canvas_stubs["run/sign-in"]] == ["running", "passed"]


def test_a_first_rerun_with_no_source_reads_the_results_where_the_publish_says_it_ran(appenv, canvas_stubs):
    res = journey.rerun("shop", ["all"])
    assert [c["argv"] for c in appenv["calls"]()] == [["sandbox", "journey", "shop", "--publish"]]  # every feature main lists: no ids
    # main lists from-main, which the stand-in did not run: failed; the folder came from the new source.json.
    assert res["features"]["from-main"]["state"] == "failed"
    assert journey.place("shop")["folder"] == appenv["sandbox"]


def test_until_main_knows_named_journeys_a_rerun_uses_the_canvas_sandboxs_cli_or_refuses(appenv, canvas_stubs, tmp_path):
    """An older CLI would make a permanent journey sandbox again: never run it."""
    fake_cli(appenv["home"], named=False)
    with pytest.raises(journey.Refused, match="cannot run a journey in a named sandbox yet"):
        journey.rerun("shop", ["all"])
    assert appenv["calls"]() == []
    assert "run/from-main" not in canvas_stubs  # refused before anything showed running
    make_sandbox(appenv)
    own = fake_cli(appenv["sandbox"], named=True)
    journey.rerun("shop", ["sign-in"])
    # Run from the sandbox's own checkout: an app CLI shim runs the CLI of the checkout its working directory is in.
    assert [(c["cli"], c["cwd"], c["argv"]) for c in appenv["calls"]()] == [
        (str(own), str(appenv["sandbox"]), ["sandbox", "journey", "shop", "sign-in", "--publish"])]


def test_a_rerun_of_a_checkouts_own_cli_runs_from_that_checkout(appenv, canvas_stubs, monkeypatch):
    """With no sandboxes (the Mac), the apps file runs the canvas checkout's CLI: run it from that checkout, or the
    CLI shim runs the session home's checkout instead."""
    make_sandbox(appenv)
    own = fake_cli(appenv["sandbox"], named=True)
    monkeypatch.setitem(journey.APPS, "shop", {**journey.APPS["shop"], "run": ["tools/app/bin/app", "shop", "journey", "{features}", "--publish"]})
    journey.rerun("shop", ["sign-in"])
    assert [(c["cli"], c["cwd"], c["argv"]) for c in appenv["calls"]()] == [
        (str(own), str(appenv["sandbox"]), ["shop", "journey", "sign-in", "--publish"])]


def test_the_session_folder_is_the_main_checkout_and_no_sandbox_is_made(appenv):
    make_sandbox(appenv)
    assert journey.session_folder("shop") == appenv["home"]
    assert appenv["calls"]() == []


def test_apps_lists_each_folder_and_warns_when_env_starts_a_session_elsewhere(appenv, tmp_path, monkeypatch, capsys):
    make_sandbox(appenv)
    env = tmp_path / "env"
    (env / "machines").mkdir(parents=True)
    (env / "machines" / "claude-sessions").write_text(
        f"main journey-shop     {appenv['home']}  python3 journey.py launch shop\n"
        "main journey-ledger   ~/projects/checkouts/06-journey-ledger  python3 journey.py launch ledger\n")
    monkeypatch.setattr(journey, "CONFIG", {**journey.CONFIG, "sessions_file": str(env / "machines" / "claude-sessions")})
    monkeypatch.setattr(journey, "on_main", lambda: False)
    assert journey.main(["--json", "apps"]) == 0
    rows = {r["app"]: r for r in json.loads(capsys.readouterr().out)}
    assert (rows["shop"]["folder"], rows["shop"]["from"]) == (str(appenv["sandbox"]), "sandbox")
    assert "warning" not in rows["shop"]
    assert rows["ledger"]["warning"] == (f"sessions file starts journey-ledger in "
                                          f"{journey.HOME}/projects/checkouts/06-journey-ledger, not {appenv['home']}")
    assert rows["tutor"]["warning"] == f"sessions file starts journey-tutor in no line, not {appenv['home']}"


def test_launch_resumes_the_session_in_the_main_checkout_and_tells_claude_launch_to_stay_there(appenv, monkeypatch):
    """claude-launch moves a resumed session back to the folder it is filed under (env's session roots)
    unless CLAUDE_LAUNCH_HERE is set; Claude resumes a session from any folder."""
    make_sandbox(appenv)
    monkeypatch.setattr(journey, "on_main", lambda: True)
    monkeypatch.setattr(journey, "claude_launch", lambda: "/bin/claude-launch")
    monkeypatch.setattr(journey, "transcript_exists", lambda sid: True)
    journey.set_claude_session("shop", "8934f378-3e3f-4aa6-a378-33551af9caf5")
    monkeypatch.delenv("CLAUDE_LAUNCH_HERE", raising=False)
    seen = {}
    monkeypatch.setattr(journey.os, "chdir", lambda d: seen.setdefault("cwd", Path(d)))

    def execv(path, argv):
        seen.update(argv=argv, here=os.environ.get("CLAUDE_LAUNCH_HERE"))
    monkeypatch.setattr(journey.os, "execv", execv)
    journey.launch("shop")
    assert seen == {"cwd": appenv["home"], "here": "1",
                    "argv": ["/bin/claude-launch", "--remote-control", "main-journey-shop",
                             "--resume", "8934f378-3e3f-4aa6-a378-33551af9caf5", "/journey shop"]}
    assert journey.owner("shop")["cwd"] == str(appenv["home"])


def test_a_command_that_runs_too_long_is_stopped_and_reported_as_timed_out(tmp_path, monkeypatch):
    """A hung journey run must not hold the doorman for ever: run_bounded gives the timeout(1) exit
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
