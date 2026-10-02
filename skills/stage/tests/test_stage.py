from __future__ import annotations

from unittest.mock import patch

import pytest

from skills.stage import stage

ROW = {"sid": "s1", "slug": "s1", "kind": "stage", "url": "http://127.0.0.1:3080/s/s1/", "state": "live"}


class FakeDaemon:
    """Items for one stage session, kept in memory; every wc call the module makes."""

    def __init__(self, rows=None):
        self.rows = list(rows if rows is not None else [ROW])
        self.items: dict = {}
        self.mounts: dict = {}
        self.assets = []
        self.created = []

    def list_sessions(self, cwd, kind):
        return list(self.rows)

    def create_or_attach(self, kind, cwd, title=None, slug=None, supersede=False):
        row = dict(ROW, slug=slug or "s1")
        self.created.append((kind, cwd, title, slug))
        self.rows.append(row)
        return row

    def register_assets(self, sid, root, entry, kind):
        self.assets.append((sid, root, entry, kind))

    def register_mount(self, sid, name, root, kind):
        self.mounts[name] = root
        return {"name": name, "url": f"mounts/{name}/"}

    def get_items(self, sid, kind):
        return {a: {"body": b, "version": 1} for a, b in self.items.items()}

    def put_items(self, sid, items, kind, replace=False):
        self.items.update(items)

    def delete_item(self, sid, anchor, kind):
        self.items.pop(anchor, None)


@pytest.fixture
def fake():
    f = FakeDaemon()
    names = ["list_sessions", "create_or_attach", "register_assets", "register_mount",
             "get_items", "put_items", "delete_item"]
    patches = [patch.object(stage.wc, n, getattr(f, n)) for n in names]
    patches.append(patch.object(stage, "start_watch", lambda cwd, sid: None))
    for p in patches:
        p.start()
    yield f
    for p in patches:
        p.stop()


def test_ensure_stage_attaches_to_the_live_one_and_registers_the_renderer(fake, tmp_path):
    row = stage.ensure_stage(str(tmp_path))
    assert row["sid"] == "s1" and fake.created == []
    assert fake.assets == [("s1", str(stage.STATIC_DIR), "entry.js", "stage")]


def test_ensure_stage_creates_one_when_none_is_live(tmp_path):
    f = FakeDaemon(rows=[dict(ROW, state="finished")])
    with patch.object(stage.wc, "list_sessions", f.list_sessions), \
         patch.object(stage.wc, "create_or_attach", f.create_or_attach), \
         patch.object(stage.wc, "register_assets", f.register_assets):
        stage.ensure_stage(str(tmp_path), title="T")
    assert f.created == [("stage", str(tmp_path), "T", None)]


def test_show_a_file_mounts_its_folder_and_fronts_it(fake, tmp_path):
    (tmp_path / "deck").mkdir()
    (tmp_path / "deck" / "index.html").write_text("x")
    src = stage.model.parse_source("deck/index.html#slide-2", tmp_path)
    res = stage.show(str(tmp_path), "deck", src, title="Q3 deck")
    view = fake.items["view:deck"]
    assert res["url"] == ROW["url"] and res["view"] == view
    assert view["title"] == "Q3 deck"
    assert view["source"]["file"] == "index.html" and view["source"]["fragment"] == "slide-2"
    assert view["source"]["missing"] is False
    assert fake.mounts[view["source"]["mount"]] == str((tmp_path / "deck").resolve())
    assert view["rev"] > 0
    assert fake.items["__layout__"] == {"order": ["deck"], "front": "deck"}


def test_show_a_missing_file_says_so(fake, tmp_path):
    src = stage.model.parse_source("later.html", tmp_path)
    stage.show(str(tmp_path), "later", src)
    assert fake.items["view:later"]["source"]["missing"] is True


def test_show_twice_updates_in_place(fake, tmp_path):
    stage.show(str(tmp_path), "a", {"type": "url", "url": "https://a"})
    stage.show(str(tmp_path), "b", {"type": "url", "url": "https://b"})
    stage.show(str(tmp_path), "a", {"type": "url", "url": "https://a2"}, title="A2")
    assert fake.items["__layout__"] == {"order": ["a", "b"], "front": "a"}
    assert fake.items["view:a"]["source"]["url"] == "https://a2"
    assert fake.items["view:a"]["title"] == "A2"


def test_show_in_the_background_keeps_the_front(fake, tmp_path):
    stage.show(str(tmp_path), "a", {"type": "url", "url": "https://a"})
    stage.show(str(tmp_path), "b", {"type": "url", "url": "https://b"}, background=True)
    assert fake.items["__layout__"]["front"] == "a"


def test_show_a_session_resolves_its_sid(fake, tmp_path):
    fake.rows.append({"sid": "d9", "slug": "my-deck", "kind": "deck", "state": "live"})
    stage.show(str(tmp_path), "deckview", {"type": "session", "kind": "deck", "slug": "my-deck"})
    assert fake.items["view:deckview"]["source"]["sid"] == "d9"


def test_show_an_unknown_session_is_refused(fake, tmp_path):
    with pytest.raises(stage.model.SourceError):
        stage.show(str(tmp_path), "x", {"type": "session", "kind": "deck", "slug": "nope"})


def test_a_bad_view_name_is_refused(fake, tmp_path):
    with pytest.raises(ValueError):
        stage.show(str(tmp_path), "Bad Name", {"type": "url", "url": "https://a"})


def test_hide_removes_the_view_and_moves_the_front(fake, tmp_path):
    stage.show(str(tmp_path), "a", {"type": "url", "url": "https://a"})
    stage.show(str(tmp_path), "b", {"type": "url", "url": "https://b"})
    stage.hide(str(tmp_path), "b")
    assert "view:b" not in fake.items
    assert fake.items["__layout__"] == {"order": ["a"], "front": "a"}


def test_cli_show_prints_the_stage_url(fake, tmp_path, capsys):
    code = stage.main(["show", "u", "https://example.com", "--cwd", str(tmp_path)])
    assert code == 0
    assert capsys.readouterr().out.strip() == ROW["url"]


def test_cli_refuses_a_bad_source_with_exit_2(fake, tmp_path, capsys):
    code = stage.main(["show", "x", "../outside.html", "--cwd", str(tmp_path)])
    assert code == 2
    assert "outside" in capsys.readouterr().err


def test_cli_reports_an_unreachable_daemon_with_exit_3(tmp_path, capsys):
    def down(*a, **k):
        raise stage.wc.DaemonUnreachable("cannot reach the webcompanion daemon")
    with patch.object(stage.wc, "list_sessions", down):
        assert stage.main(["link", "--cwd", str(tmp_path)]) == 3
    assert "webcompanion" in capsys.readouterr().err


def test_cli_reports_a_daemon_refusal_with_exit_3(fake, tmp_path, capsys):
    def refuse(*a, **k):
        raise RuntimeError("PUT /s/s1/api/items -> 400 bad item")
    with patch.object(stage.wc, "put_items", refuse):
        assert stage.main(["show", "u", "https://example.com", "--cwd", str(tmp_path)]) == 3
    assert capsys.readouterr().err.strip() == "stage: PUT /s/s1/api/items -> 400 bad item"


def test_cli_reports_a_corrupt_config_with_exit_3(tmp_path, capsys):
    import json

    def corrupt(*a, **k):
        return json.loads("{not json")
    with patch.object(stage.wc, "list_sessions", corrupt):
        assert stage.main(["link", "--cwd", str(tmp_path)]) == 3
    assert capsys.readouterr().err.startswith("stage: ")
