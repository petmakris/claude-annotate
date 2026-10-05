import asyncio
from unittest.mock import patch

from helpers import AUTH, CALL, make_args, run, running_app, talk


async def serve(tmp_path, args):
    await talk.serve(talk.Call(args, "T", tmp_path / "out"))


def test_stage_view_maps_code_diagram_and_table():
    code = {"id": 0, "kind": "code", "title": "Parser: entry", "path": "a.py", "start": 1,
            "lines": ["x"], "highlight": None, "lang": "py"}
    name, source, title = talk.stage_view(code)
    assert name == "parser-entry" and title == "Parser: entry"
    assert source == {"type": "inline", "format": "code", "path": "a.py", "start": 1,
                      "lines": ["x"], "highlight": None, "lang": "py"}
    name, source, _ = talk.stage_view({"id": 3, "kind": "diagram", "title": "", "body": "graph TD; A-->B"})
    assert name == "diagram-3" and source == {"type": "inline", "format": "diagram", "body": "graph TD; A-->B"}


def test_stage_view_falls_back_when_the_title_has_no_letters_or_digits():
    name, _, _ = talk.stage_view({"id": 1, "kind": "diagram", "title": "!!!", "body": "graph TD; A-->B"})
    assert name == "diagram-1"
    name, _, _ = talk.stage_view({"id": 2, "kind": "code", "title": "###", "path": "a.py", "start": 1,
                                  "lines": ["x"], "highlight": None, "lang": "py"})
    assert name == "code-2"


def test_rebase_swaps_scheme_and_host_only():
    assert talk.rebase("http://127.0.0.1:3080/s/abc/", "https://wc.example") == "https://wc.example/s/abc/"
    assert talk.rebase("http://127.0.0.1:3080/s/abc/", None) == "http://127.0.0.1:3080/s/abc/"


def test_a_board_tag_is_published_to_the_stage(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("x = 1\n")

    async def go():
        async with running_app(tmp_path, code=code) as (client, ctl, log):
            ctl.stage_cwd = str(code)
            with patch.object(talk.stage_mod, "show") as show:
                ctl.offer("show me", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                await client.post("/api/reply", json={"id": "t1", "text": "[[show code: a.py:1-1 | A]] Here."},
                                  headers=AUTH)
            return show.call_args

    call = run(go())
    assert call.args[0] == str(code) and call.args[1] == "a"
    assert call.args[2]["format"] == "code" and call.kwargs == {"title": "A"}


def test_a_stage_failure_is_reported_as_a_board_problem(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.stage_cwd = str(tmp_path)
            with patch.object(talk.stage_mod, "show", side_effect=RuntimeError("daemon said no")):
                ctl.offer("draw", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                resp = await client.post("/api/reply", json={
                    "id": "t1", "text": "[[show diagram | D]]graph TD; A-->B[[/show]] Done."}, headers=AUTH)
                return (await resp.json())["board_problems"]

    assert any("daemon said no" in p for p in run(go()))


def test_the_page_embeds_the_stage_and_no_longer_renders_a_board(tmp_path):
    async def go():
        async with running_app(tmp_path, stage_url="http://127.0.0.1:3080/s/abc/") as (client, ctl, log):
            return await (await client.get(f"/c/{CALL}")).text()

    html = run(go())
    assert "http://127.0.0.1:3080/s/abc/" in html
    assert 'id="stage"' in html
    assert "renderItem" not in html and "mermaid.esm" not in html


def _git_repo_with_subfolder(tmp_path):
    import subprocess
    repo = tmp_path / "repo"
    (repo / "sub" / "deeper").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_without_code_the_stage_folder_is_the_git_root_of_the_current_folder(tmp_path, monkeypatch):
    """stage.py falls back to the git root too, so both land on the same stage."""
    repo = _git_repo_with_subfolder(tmp_path)
    monkeypatch.chdir(repo / "sub" / "deeper")
    seen = []

    def refuse(cwd, **kw):
        seen.append(cwd)
        raise talk.stage_mod.wc.DaemonUnreachable("down")

    with patch.object(talk.stage_mod, "ensure_stage", side_effect=refuse):
        try:
            run(serve(tmp_path, make_args()))
        except SystemExit:
            pass
    assert seen == [str(repo.resolve())]


def test_a_daemon_refusal_stops_talk_with_a_clear_message(tmp_path):
    with patch.object(talk.stage_mod, "ensure_stage", side_effect=talk.stage_mod.wc.DaemonHTTPError("POST", "/api/sessions", 500, "boom")):
        try:
            run(serve(tmp_path, make_args(code=tmp_path)))
        except SystemExit as e:
            message = str(e)
        else:
            message = None
    assert message == "talk needs the webcompanion daemon for its stage: POST /api/sessions -> 500 boom"


def test_a_stage_show_runs_off_the_event_loop_one_at_a_time(tmp_path):
    """stage.show makes blocking HTTP calls; on the loop they would stall every other request."""
    import threading
    import time

    calls = []

    def slow_show(cwd, name, source, title=None):
        calls.append((name, threading.get_ident(), time.monotonic()))
        time.sleep(0.2)
        calls.append((name, threading.get_ident(), time.monotonic()))

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.stage_cwd = str(tmp_path)
            ticks = []

            async def ticker():
                while True:
                    ticks.append(time.monotonic())
                    await asyncio.sleep(0.02)

            t = asyncio.create_task(ticker())
            with patch.object(talk.stage_mod, "show", side_effect=slow_show):
                ctl.offer("draw", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                await client.post("/api/reply", json={
                    "id": "t1", "text": "[[show table | T1]]| a |\n|---|\n| 1 |[[/show]]"
                                    "[[show table | T2]]| b |\n|---|\n| 2 |[[/show]] Done."}, headers=AUTH)
            t.cancel()
            return ticks

    ticks = run(go())
    loop_thread = threading.get_ident()
    assert [c[0] for c in calls] == ["t1", "t1", "t2", "t2"]  # in order, never overlapping
    assert all(c[1] != loop_thread for c in calls)
    # The loop kept turning while the shows slept.
    during = [x for x in ticks if calls[0][2] < x < calls[-1][2]]
    assert len(during) >= 5
