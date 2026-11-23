from __future__ import annotations

import os
import time
from unittest.mock import patch

from skills.stage import stage
from skills.stage.tests.test_stage import FakeDaemon, ROW


def _bump(path):
    t = time.time() + 5
    os.utime(path, (t, t))


def _patched(f):
    return [patch.object(stage.wc, n, getattr(f, n)) for n in
            ("list_sessions", "create_or_attach", "register_assets", "register_mount",
             "get_items", "put_items", "delete_item")]


def _with(f, fn):
    ps = _patched(f) + [patch.object(stage, "start_watch", lambda cwd, sid: None)]
    for p in ps:
        p.start()
    try:
        return fn()
    finally:
        for p in ps:
            p.stop()


def test_tick_bumps_rev_when_the_folder_changes(tmp_path):
    f = FakeDaemon()
    deck = tmp_path / "index.html"
    deck.write_text("one")

    def go():
        stage.show(str(tmp_path), "deck", stage.model.parse_source("index.html", tmp_path))
        before = f.items["view:deck"]["rev"]
        assert stage.tick(str(tmp_path), "s1") == []
        deck.write_text("two")
        _bump(deck)
        assert stage.tick(str(tmp_path), "s1") == ["deck"]
        return before, f.items["view:deck"]["rev"]

    before, after = _with(f, go)
    assert after != before


def test_tick_marks_a_deleted_file_missing_and_back(tmp_path):
    f = FakeDaemon()
    deck = tmp_path / "index.html"
    deck.write_text("one")

    def go():
        stage.show(str(tmp_path), "deck", stage.model.parse_source("index.html", tmp_path))
        deck.unlink()
        stage.tick(str(tmp_path), "s1")
        gone = f.items["view:deck"]["source"]["missing"]
        deck.write_text("back")
        _bump(deck)
        stage.tick(str(tmp_path), "s1")
        return gone, f.items["view:deck"]["source"]["missing"]

    assert _with(f, go) == (True, False)


def test_tick_leaves_non_file_views_alone(tmp_path):
    f = FakeDaemon()
    _with(f, lambda: stage.show(str(tmp_path), "u", {"type": "url", "url": "https://a"}))
    assert _with(f, lambda: stage.tick(str(tmp_path), "s1")) == []


def test_watch_exits_when_the_stage_is_no_longer_live(tmp_path):
    f = FakeDaemon()
    clock = iter(range(0, 1000, 10))

    def go():
        f.rows = [dict(ROW, state="finished")]
        return stage.watch(str(tmp_path), "s1", interval=0, alive_every=5,
                           sleep=lambda s: None, clock=lambda: next(clock))

    assert _with(f, go) == 0
    assert not stage.watch_running("s1")


def test_start_watch_spawns_once(tmp_path):
    with patch.object(stage.subprocess, "Popen") as popen, \
         patch.object(stage, "watch_running", side_effect=[False, True]):
        stage.start_watch(str(tmp_path), "s1")
        stage.start_watch(str(tmp_path), "s1")
    assert popen.call_count == 1
    argv = popen.call_args.args[0]
    assert argv[1:] == [str(stage.Path(stage.__file__).resolve()), "watch", "--sid", "s1", "--cwd", str(tmp_path)]
