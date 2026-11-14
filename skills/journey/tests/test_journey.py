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


def test_a_long_answer_for_one_canvas_never_holds_another_canvass_wake(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    for key in ("shop-events", "ledger-bills", "tutor-trial"):
        record(key, key.split("-")[0], tmp_path / key, tmp_path / key / ".out")
    started, release = [], threading.Event()

    def tick(app):
        started.append(app)
        if app == "shop-events":
            release.wait(5)
        return "idle"

    monkeypatch.setattr(journey, "on_main", lambda: True)
    monkeypatch.setattr(journey, "doorman_tick", tick)
    t = threading.Thread(target=journey.doorman, kwargs={"once": True})
    t.start()
    for _ in range(100):
        if len(started) == 3:
            break
        threading.Event().wait(0.02)
    assert sorted(started) == ["ledger-bills", "shop-events", "tutor-trial"]  # all began while shop's still ran
    release.set()
    t.join(5)


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


def test_launch_resumes_the_session_in_its_sandbox_and_tells_claude_launch_to_stay_there(appenv, monkeypatch):
    """claude-launch moves a resumed session back to the folder it is filed under (env's session roots)
    unless CLAUDE_LAUNCH_HERE is set; Claude resumes a session from any folder."""
    make_sandbox(appenv)
    monkeypatch.setattr(journey, "on_main", lambda: True)
    monkeypatch.setattr(journey, "claude_launch", lambda: "/bin/claude-launch")
    monkeypatch.setattr(journey, "transcript_exists", lambda sid: True)
    journey.set_claude_session("shop-events", "8934f378-3e3f-4aa6-a378-33551af9caf5")
    monkeypatch.delenv("CLAUDE_LAUNCH_HERE", raising=False)
    seen = {}
    monkeypatch.setattr(journey.os, "chdir", lambda d: seen.setdefault("cwd", Path(d)))

    def execv(path, argv):
        seen.update(argv=argv, here=os.environ.get("CLAUDE_LAUNCH_HERE"))
    monkeypatch.setattr(journey.os, "execv", execv)
    journey.launch("shop-events")
    assert seen == {"cwd": appenv["sandbox"], "here": "1",
                    "argv": ["/bin/claude-launch", "--remote-control", "main-journey-shop-events",
                             "--resume", "8934f378-3e3f-4aa6-a378-33551af9caf5", "/journey shop-events"]}
    assert journey.owner("shop-events")["cwd"] == str(appenv["sandbox"])


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
