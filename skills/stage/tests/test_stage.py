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

    def all_sessions(self, kind=None):
        return [r for r in self.rows if kind is None or r.get("kind", "stage") == kind]

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
    names = ["list_sessions", "all_sessions", "create_or_attach", "register_assets", "register_mount",
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


def test_during_a_call_a_page_opens_behind_and_never_takes_the_front(fake, tmp_path, capsys):
    fake.rows = [dict(ROW, slug="talk-abcd1234")]
    table = {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"}
    stage.show(str(tmp_path), "board", table, slug="talk-abcd1234")
    res = stage.show(str(tmp_path), "deck", {"type": "url", "url": "https://deck"}, slug="talk-abcd1234")
    assert res["behind"] and fake.items["__layout__"] == {"order": ["board", "deck"], "front": "board"}
    assert stage.main(["show", "site", "https://example.com", "--cwd", str(tmp_path), "--slug", "talk-abcd1234"]) == 0
    assert fake.items["__layout__"]["front"] == "board"
    assert "opened as a background tab" in capsys.readouterr().err


def test_a_page_on_an_empty_call_stage_still_waits_behind(fake, tmp_path):
    fake.rows = [dict(ROW, slug="talk-abcd1234")]
    stage.show(str(tmp_path), "deck", {"type": "url", "url": "https://deck"}, slug="talk-abcd1234")
    assert fake.items["__layout__"] == {"order": ["deck"], "front": None}
    res = stage.show(str(tmp_path), "board", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"},
                     slug="talk-abcd1234")
    assert not res["behind"] and fake.items["__layout__"]["front"] == "board"


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


def test_show_adds_only_the_known_extras_to_the_view(fake, tmp_path):
    stage.show(str(tmp_path), "t", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"},
               extra={"answer": 3, "kind": "table", "bogus": 1, "scene": {"steps": 1}})
    view = fake.items["view:t"]
    assert view["answer"] == 3 and view["kind"] == "table" and view["scene"] == {"steps": 1}
    assert "bogus" not in view


SID = "261005-120000-0123456789abcdef"


def test_a_slug_is_matched_as_the_daemon_stores_it(fake, tmp_path):
    fake.rows = [dict(ROW, sid=SID, slug="talk-lgqw7e9")]
    row = stage.ensure_stage(str(tmp_path), slug="Talk_LGQW7E9-")
    assert row["sid"] == SID and fake.created == []


def test_a_stage_named_by_sid_is_found_and_never_created(fake, tmp_path):
    fake.rows = [dict(ROW, sid=SID, slug="talk-abc")]
    assert stage.ensure_stage(str(tmp_path), slug=SID)["slug"] == "talk-abc" and fake.created == []


def test_without_a_slug_a_talk_calls_stage_is_never_picked(fake, tmp_path):
    fake.rows = [dict(ROW, sid="261005-100000-0000000000000001", slug="stage-proj"),
                 dict(ROW, sid="261005-110000-0000000000000002", slug="talk-ucccetsz")]
    assert stage.ensure_stage(str(tmp_path))["slug"] == "stage-proj"
    fake.rows = [dict(ROW, sid="261005-110000-0000000000000002", slug="talk-ucccetsz")]
    stage.ensure_stage(str(tmp_path), title="T")
    assert fake.created == [("stage", str(tmp_path), "T", None)]


def test_a_view_another_writer_put_there_is_never_replaced(fake, tmp_path):
    stage.show(str(tmp_path), "deck", {"type": "url", "url": "https://deck"})
    with pytest.raises(stage.ViewTaken, match="put there by hand"):
        stage.show(str(tmp_path), "deck", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"},
                   owner="talk call C1")
    assert fake.items["view:deck"]["source"]["url"] == "https://deck"
    stage.show(str(tmp_path), "plan", {"type": "url", "url": "https://a"}, owner="talk call C1")
    stage.show(str(tmp_path), "plan", {"type": "url", "url": "https://b"}, owner="talk call C1")
    assert fake.items["view:plan"]["owner"] == "talk call C1"
    with pytest.raises(stage.ViewTaken, match="talk call C1"):
        stage.show(str(tmp_path), "plan", {"type": "url", "url": "https://c"})
    assert stage.main(["show", "plan", "https://c", "--cwd", str(tmp_path)]) == 2


def test_a_session_source_in_another_folder_is_found_by_slug_or_sid(fake, tmp_path):
    fake.list_sessions = lambda cwd, kind: [r for r in fake.rows if r.get("kind") == kind and r.get("cwd") == cwd]
    fake.rows.append({"sid": "d1", "slug": "my-plan", "kind": "annotate", "cwd": "/elsewhere", "state": "live"})
    with patch.object(stage.wc, "list_sessions", fake.list_sessions):
        stage.show(str(tmp_path), "plan", {"type": "session", "kind": "annotate", "slug": "my-plan"})
        assert fake.items["view:plan"]["source"]["sid"] == "d1"
        fake.rows.append({"sid": "d2", "slug": "my-plan", "kind": "annotate", "cwd": "/third", "state": "live"})
        with pytest.raises(stage.model.SourceError, match="2 live annotate sessions are named my-plan"):
            stage.show(str(tmp_path), "plan2", {"type": "session", "kind": "annotate", "slug": "my-plan"})
        stage.show(str(tmp_path), "plan2", {"type": "session", "kind": "annotate", "slug": "d2"})
        assert fake.items["view:plan2"]["source"]["sid"] == "d2"
        with pytest.raises(stage.model.SourceError, match="live ones: my-plan in /elsewhere"):
            stage.show(str(tmp_path), "x", {"type": "session", "kind": "annotate", "slug": "nope"})


class FakeRegistry:
    """The daemon's /api/sessions as registry.py keeps it: slugs slugified, de-duplicated per kind across
    every folder and state."""

    def __init__(self):
        self.rows, self.finished, self.posts = [], [], []

    def __call__(self, method, path, body=None, **kw):
        if method == "GET" and path.startswith("/api/sessions?scope=all"):
            return list(self.rows)
        if method == "GET":
            from urllib.parse import parse_qs, urlsplit
            q = parse_qs(urlsplit(path).query)
            return [r for r in self.rows if r["cwd"] == q["cwd"][0] and r["kind"] == q["kind"][0]]
        if method == "POST" and path == "/api/sessions":
            self.posts.append(body)
            base = stage.wc.slugify(body.get("slug") or body.get("title") or "session")
            taken = {r["slug"] for r in self.rows if r["kind"] == body["kind"]}
            slug, n = base, 2
            while slug in taken:
                slug, n = f"{base}-{n}", n + 1
            row = {"sid": "261005-1200%02d-%016x" % (len(self.rows), len(self.rows)), "slug": slug,
                   "kind": body["kind"], "cwd": body["cwd"], "state": "live", "url": "u"}
            self.rows.append(row)
            return row
        if method == "POST" and path.endswith("/api/finish"):
            sid = path.split("/")[2]
            self.finished.append(sid)
            next(r for r in self.rows if r["sid"] == sid)["state"] = "finished"
            return {"ok": True}
        raise AssertionError((method, path))


@pytest.fixture
def registry():
    reg = FakeRegistry()
    with patch.object(stage.wc, "request", reg):
        yield reg


def test_asking_twice_for_a_slug_the_daemon_rewrites_attaches_once(registry):
    first = stage.wc.create_or_attach("stage", "/a", slug="talk-lgqw7e9-")
    again = stage.wc.create_or_attach("stage", "/a", slug="talk-lgqw7e9-")
    assert first["slug"] == "talk-lgqw7e9" and again["sid"] == first["sid"] and len(registry.posts) == 1


def test_a_slug_taken_in_another_folder_fails_instead_of_making_a_second_stage(registry):
    stage.wc.create_or_attach("stage", "/b", slug="probe-dup")
    with pytest.raises(stage.wc.SlugMismatch, match="probe-dup is in /b"):
        stage.wc.create_or_attach("stage", "/a", slug="probe-dup")
    assert len(registry.posts) == 1


def test_a_daemon_that_renames_the_slug_anyway_is_caught_and_its_session_ended(registry):
    registry.rows.append({"sid": "x", "slug": "probe-dup", "kind": "stage", "cwd": "/hidden", "state": "live"})
    def unlisted(kind=None):
        raise stage.wc.DaemonHTTPError("GET", "/api/sessions?scope=all", 403, "no owner token")

    with patch.object(stage.wc, "all_sessions", unlisted):
        with pytest.raises(stage.wc.SlugMismatch, match="got probe-dup-2"):
            stage.wc.create_or_attach("stage", "/a", slug="probe-dup")
    assert registry.finished == [registry.rows[-1]["sid"]]


def test_an_ended_stage_is_never_attached_to_or_replaced(registry):
    row = stage.wc.create_or_attach("stage", "/a", slug="talk-clean")
    registry("POST", "/s/%s/api/finish" % row["sid"])
    with pytest.raises(stage.wc.SlugMismatch, match="was ended"):
        stage.wc.create_or_attach("stage", "/a", slug="talk-clean")
    with pytest.raises(stage.wc.SlugMismatch, match="was ended"):
        stage.wc.create_or_attach("stage", "/a", slug=row["sid"])
    with patch.object(stage.wc, "register_assets", lambda *a, **k: None):
        with pytest.raises(stage.wc.SlugMismatch):
            stage.show("/a", "v", {"type": "url", "url": "https://a"}, slug="talk-clean")
    assert len(registry.posts) == 1


def test_an_unknown_sid_is_never_created(registry):
    with pytest.raises(stage.wc.SlugMismatch, match="no stage session with sid"):
        stage.wc.create_or_attach("stage", "/a", slug=SID)
    assert registry.posts == []
