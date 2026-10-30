"""The journey tool (skills/journey): its store against the page's, and the doorman's decisions.

No test reaches webcompanion or starts Claude: the session, its directories and the wake-up are
stand-ins, and the state folder is a tmp_path."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skills.journey import journey, store

STATIC = Path(__file__).resolve().parents[2] / "canvas" / "static"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

T = "2026-10-30T09:00:00.000Z"


def create(cid, board="today/01-today", at="2026-10-30T09:00:00Z", **extra):
    c = {"id": cid, "app": "mealy", "board": board, "boardTitle": "Today", "chapter": "Today", "shot": "desktop",
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
    assert store.waiting(by["b"])  # Petros replied after it was sent
    assert by["b"]["sentAt"] == "2026-10-30T09:03:00.000Z" and by["b"]["askedAt"] == "2026-10-30T09:04:00.000Z"


# ── features, events, acks ─────────────────────────────────────────────────

FEATURE = """Feature: Mealy journey
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
    f = co / "apps" / "mealy" / "frontend" / "e2e" / "journey" / "journey.feature"
    f.parent.mkdir(parents=True)
    f.write_text(FEATURE)
    monkeypatch.setattr(journey, "checkout", lambda app: co)
    monkeypatch.setattr(journey, "STATE_ROOT", tmp_path / "state")
    return co


def test_features_are_journey_features_scenarios_as_slugs_with_their_skip(app_checkout):
    assert journey.features("mealy") == [
        {"id": "sign-in", "name": "Sign in", "skip": False},
        {"id": "plan-setup", "name": "Plan setup", "skip": True},
        {"id": "today-s-log-and-more", "name": "Today's log, and more", "skip": False}]


def test_a_rerun_refuses_any_id_the_journey_does_not_have_before_running_anything(app_checkout, monkeypatch):
    monkeypatch.setattr(journey, "on_main", lambda: True)
    ran = []
    monkeypatch.setattr(journey.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(journey.Refused, match="no feature plan-setup; rm -rf"):
        journey.rerun("mealy", ["plan-setup; rm -rf"])
    with pytest.raises(journey.Refused, match="no feature plan-setup"):
        journey.rerun("mealy", ["plan-setup"])  # @skip never runs
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
    assert journey.ack("mealy", "e1") == {"acked": "e1", "archived": True}
    assert not (Path(session["events_dir"]) / "e1.json").exists()
    assert (Path(session["consumed_dir"]) / "e1.json").exists()
    event(session, "e2", {"type": "comments", "ids": ["b"]})
    (Path(session["state_dir"]) / "watcher_heartbeat").write_text(f"{int(time.time())}\n")
    assert journey.ack("mealy", "e2") == {"acked": "e2", "archived": False}
    assert (Path(session["consumed_dir"]) / "e2.ack").exists()
    with pytest.raises(journey.Refused):
        journey.ack("mealy", "../e3")


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
    journey.set_claude_session("mealy", "11111111-2222-3333-4444-555555555555")

    def wake(app, sid):
        world["woke"].append(app)
        world["events"] = []
        return 0

    monkeypatch.setattr(journey, "headless", wake)
    return world


def test_the_doorman_wakes_an_app_with_a_waiting_event_and_nobody_listening(quiet):
    assert journey.doorman_tick("mealy") == "woke (exit 0)"
    assert quiet["woke"] == ["mealy"]


def test_the_doorman_leaves_an_app_alone_while_a_watcher_listens(quiet, session):
    import time
    (Path(session["state_dir"]) / "watcher_heartbeat").write_text(f"{int(time.time()) - 20}\n")
    assert journey.doorman_tick("mealy") == "listening"
    assert quiet["woke"] == []


def test_the_doorman_wakes_once_the_heartbeat_is_older_than_90_seconds(quiet, session):
    import time
    (Path(session["state_dir"]) / "watcher_heartbeat").write_text(f"{int(time.time()) - 200}\n")
    assert journey.doorman_tick("mealy").startswith("woke")


def test_the_doorman_leaves_a_session_petros_has_open(quiet):
    journey.write_json(journey.state_dir("mealy") / "owner.json", {"pid": 4242, "mode": "interactive"})
    quiet["owner_alive"] = True
    assert journey.doorman_tick("mealy") == "open"
    quiet["owner_alive"] = False
    quiet["held"] = [999]  # a `claude --resume <id>` started some other way
    assert journey.doorman_tick("mealy") == "held"
    assert quiet["woke"] == []


def test_the_doorman_never_starts_a_second_claude_while_the_lock_is_held(quiet):
    quiet["lock"] = False
    assert journey.doorman_tick("mealy") == "locked"
    assert quiet["woke"] == []


def test_the_doorman_does_nothing_without_a_waiting_event(quiet):
    quiet["events"] = []
    assert journey.doorman_tick("mealy") == "idle"
    assert quiet["woke"] == []


def test_a_wake_that_answers_nothing_backs_off_before_trying_again(quiet, monkeypatch):
    def fails(app, sid):
        quiet["woke"].append(app)
        return 1

    monkeypatch.setattr(journey, "headless", fails)
    assert journey.doorman_tick("mealy") == "woke (exit 1)"
    assert journey.doorman_tick("mealy") == "backing off"
    assert quiet["woke"] == ["mealy"]
    d = journey.read_json(journey.state_dir("mealy") / "doorman.json", {})
    assert d["failures"] == 1 and d["left"] == ["e1"]


# ── the migration ──────────────────────────────────────────────────────────

OLD = {"version": 1, "comments": [
    {"id": "cmold1", "number": 1, "app": "billpod", "board": "sign-in/01-sign-in", "boardTitle": "Sign in", "chapter": "Sign in",
     "shot": "desktop", "fx": 0.62, "fy": 0.23, "text": "Make them differ", "scope": "both", "status": "resolved",
     "createdAt": "2026-10-30T06:00:00.000Z", "updatedAt": "2026-10-30T07:00:00.000Z", "resolvedAt": "2026-10-30T07:00:00.000Z",
     "replies": [{"id": "rold1", "text": "And the icons", "createdAt": "2026-10-30T06:10:00.000Z"}]},
    {"id": "cmold2", "number": 3, "app": "mealy", "board": "settings/01-settings", "boardTitle": "Settings", "chapter": "Settings",
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
    assert first["billpod"]["messages"] == 3 and first["mealy"]["messages"] == 4
    again = journey.migrate(src, apply=True)
    assert again["billpod"]["appended"] == 0 and again["mealy"]["appended"] == 0


def test_a_long_answer_for_one_app_never_holds_another_apps_wake(monkeypatch):
    import threading
    started, release = [], threading.Event()

    def tick(app):
        started.append(app)
        if app == "mealy":
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
    assert sorted(started) == ["billpod", "mealy", "tunatutor"]  # all began while mealy still ran
    release.set()
    t.join(5)
