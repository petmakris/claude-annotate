import asyncio
import re
from pathlib import Path
from unittest.mock import patch

from helpers import AUTH, CALL, make_args, run, running_app, talk

NAME_RE = talk.stage_mod.model.NAME_RE



def board(page, name):
    """Open a board from the list under "n of m", as a reader does: the tabs are that list's rows."""
    if page.locator(".boards").is_hidden():
        page.locator(".pos").click()
    page.locator(f'button[role=tab][data-view="{name}"]').click()

def serve(tmp_path, args):
    return talk.open_call(args, "T", tmp_path / "out", Path.cwd())


def test_stage_view_maps_code_diagram_and_table():
    code = {"id": 0, "kind": "code", "title": "Parser: entry", "path": "a.py", "start": 1,
            "lines": ["x"], "highlight": None, "lang": "py"}
    name, source, title = talk.stage_view(code)
    assert name == "parser-entry" and title == "Parser: entry"
    assert source == {"type": "inline", "format": "code", "path": "a.py", "start": 1,
                      "lines": ["x"], "highlight": None, "lang": "py"}
    name, source, _ = talk.stage_view({"id": 3, "kind": "diagram", "title": "", "body": "graph TD; A-->B"})
    assert re.fullmatch(r"diagram-[0-9a-f]{6}", name)
    assert source == {"type": "inline", "format": "diagram", "body": "graph TD; A-->B"}


def test_stage_view_takes_the_name_its_call_gave_it():
    name, _, _ = talk.stage_view({"id": 1, "kind": "diagram", "title": "Flow", "view": "flow-abc123",
                                  "body": "graph TD; A-->B"})
    assert name == "flow-abc123"


def test_stage_view_falls_back_when_the_title_has_no_letters_or_digits():
    name, _, _ = talk.stage_view({"id": 1, "kind": "diagram", "title": "!!!", "body": "graph TD; A-->B"})
    assert re.fullmatch(r"diagram-[0-9a-f]{6}", name) and NAME_RE.match(name)
    name, _, _ = talk.stage_view({"id": 2, "kind": "code", "title": "###", "path": "a.py", "start": 1,
                                  "lines": ["x"], "highlight": None, "lang": "py"})
    assert re.fullmatch(r"code-[0-9a-f]{6}", name)


def test_rebase_swaps_scheme_and_host_only():
    assert talk.rebase("http://127.0.0.1:3080/s/abc/", "https://wc.example") == "https://wc.example/s/abc/"
    assert talk.rebase("http://127.0.0.1:3080/s/abc/", None) == "http://127.0.0.1:3080/s/abc/"


def test_a_board_tag_is_published_to_the_stage(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("x = 1\n")

    async def go():
        async with running_app(tmp_path, code=code) as (client, ctl, log):
            ctl.stage_cwd, ctl.stage_slug = str(code), "talk-abcd1234"
            with patch.object(talk.stage_mod, "show") as show:
                ctl.offer("show me", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                await client.post("/api/reply", json={"id": "t1", "text": "[[show code: a.py:1-1 | A]] Here."},
                                  headers=AUTH)
            return show.call_args, ctl.entries

    call, entries = run(go())
    assert call.args[0] == str(code) and call.args[1] == "a"
    assert call.args[2]["format"] == "code"
    assert call.kwargs == {"title": "A", "slug": "talk-abcd1234", "extra": {"answer": 1, "kind": "code"},
                           "owner": f"talk call {CALL}"}
    board = next(e for e in entries if e["who"] == "board")
    assert (board["view"], board["kind"], board["answer"]) == ("a", "code", 1)


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
            serve(tmp_path, make_args())
        except talk.CallError:
            pass
    assert seen == [str(repo.resolve())]


def test_a_daemon_refusal_stops_talk_with_a_clear_message(tmp_path):
    with patch.object(talk.stage_mod, "ensure_stage", side_effect=talk.stage_mod.wc.DaemonHTTPError("POST", "/api/sessions", 500, "boom")):
        try:
            serve(tmp_path, make_args(code=tmp_path))
        except talk.CallError as e:
            message = str(e)
        else:
            message = None
    assert message == "talk needs the webcompanion daemon for its stage: POST /api/sessions -> 500 boom"


def test_a_stage_show_runs_off_the_event_loop_one_at_a_time(tmp_path):
    """stage.show makes blocking HTTP calls; on the loop they would stall every other request."""
    import threading
    import time

    calls = []

    def slow_show(cwd, name, source, title=None, **kw):
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


def test_every_call_gets_a_stage_of_its_own(tmp_path, capsys):
    seen = []

    def refuse(cwd, **kw):
        seen.append(kw)
        raise talk.stage_mod.wc.DaemonUnreachable("down")

    with patch.object(talk.stage_mod, "ensure_stage", side_effect=refuse):
        for _ in range(2):
            try:
                serve(tmp_path, make_args(code=tmp_path))
            except talk.CallError:
                pass
    slugs = [kw["slug"] for kw in seen]
    assert len(set(slugs)) == 2
    assert all(re.fullmatch(r"talk-[a-z0-9](?:[a-z0-9-]{0,6}[a-z0-9])?", s) for s in slugs)
    assert all(s == talk.stage_mod.wc.slugify(s) for s in slugs)
    assert seen[0]["title"] == "Talk · T"


def test_only_the_first_board_of_a_reply_comes_to_the_front_at_once(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.stage_cwd, ctl.stage_slug = str(tmp_path), "talk-abcd1234"
            with patch.object(talk.stage_mod, "show") as show:
                ctl.offer("two", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                await client.post("/api/reply", json={"id": "t1", "text":
                                  "[[show table | A]]| a |\n|---|\n| 1 |[[/show]] About A. "
                                  "[[show table | B]]| b |\n|---|\n| 2 |[[/show]] About B."}, headers=AUTH)
            return show.call_args_list

    calls = run(go())
    assert [c.args[1] for c in calls] == ["a", "b"]
    assert not calls[0].kwargs.get("background") and calls[1].kwargs["background"] is True


def test_a_scene_reaches_the_stage_with_its_frames_and_a_later_verb_shows_it_again(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.stage_cwd, ctl.stage_slug = str(tmp_path), "talk-abcd1234"
            with patch.object(talk.stage_mod, "show") as show:
                ctl.offer("why", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                await client.post("/api/reply", json={"id": "t1", "text":
                                  "[[show diagram | Flow]]graph TD; P[Page]-->Q[Queue][[/show]] First. [[+ P]] "
                                  "The page. [[+ P->Q]] Then the queue."}, headers=AUTH)
                ctl.offer("and", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                await client.post("/api/reply", json={"id": "t2", "text": "Back to it. [[focus Flow: Q]] The queue."},
                                  headers=AUTH)
            return show.call_args_list

    calls = run(go())
    assert [c.args[1] for c in calls] == ["flow", "flow"]
    first, again = calls[0].kwargs["extra"]["scene"], calls[1].kwargs["extra"]["scene"]
    assert (first["steps"], first["start"], first["frames"][1]["show"]) == (2, "empty", ["node:P"])
    assert (again["steps"], again["start"], again["frames"][1]["focus"]) == (1, "full", ["node:Q"])


# -- the board follows the voice, in a real browser against the private daemon's stage --------

def _call_with_stage(tmp_path):
    """A served call whose stage is a real one on this worker's private daemon."""
    import pytest
    pytest.importorskip("playwright", reason="browser suite: add --with playwright")
    from test_browser_talk import served
    cwd = tmp_path / "proj"
    cwd.mkdir(exist_ok=True)
    slug = "talk-follow01"
    url = talk.stage_mod.ensure_stage(str(cwd), slug=slug, title="Talk · T")["url"]
    return served(tmp_path, stage_url=url), str(cwd), slug


def _table(title, cell):
    return f"[[show table | {title}]]| name | value |\n|---|---|\n| {cell} | 1 |[[/show]]"


FILLER = " ".join(f"Alpha sentence {i} goes on." for i in range(12))  # most of the answer's words


def test_the_second_board_comes_forward_only_when_the_voice_reaches_it(tmp_path, wc_config, pw):
    ctx, cwd, slug = _call_with_stage(tmp_path)
    with ctx as (url, call, loop, fake):
        call.stage_cwd, call.stage_slug = cwd, slug
        fake.seconds = 3.0  # long enough that the voice reaches Beta well after it starts
        browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url)
            page.wait_for_selector("#veil", state="hidden", timeout=10000)
            stage = page.frame_locator("#stage")
            asyncio.run_coroutine_threadsafe(call.answer(
                f"{_table('Alpha', 'a1')} {FILLER} {_table('Beta', 'b1')} About Beta at last."), loop).result(10)
            beta = stage.locator('button[role=tab][data-view="beta"]')
            beta.wait_for(state="attached", timeout=10000)
            page.wait_for_function("!document.getElementById('audio').paused", timeout=10000)
            assert stage.locator('button[role=tab][data-view="alpha"]').get_attribute("aria-selected") == "true"
            assert beta.get_attribute("aria-selected") == "false"
            cue_time = page.evaluate("""(() => { const e = current, c = e.cues.find(c => c.view === 'beta');
                return e.words.find(w => w[0] >= c.at)[2]; })()""")
            assert cue_time >= 1.0
            assert page.evaluate("audio.currentTime") < cue_time
            stage.locator('button[role=tab][data-view="beta"][aria-selected="true"]').wait_for(state="attached", timeout=15000)
            heard = page.evaluate("audio.currentTime")
            assert heard >= cue_time - 0.25
        finally:
            browser.close()
            wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % slug)


def _stage_frame(page):
    return next(f for f in page.frames if f is not page.main_frame)


def _applied(stage_frame, view):
    return stage_frame.evaluate(f"window.__stageTest.frames()[{view!r}] ?? null")


def _cue_times(page, view):
    return page.evaluate(f"""(() => {{ const e = current;
        return e.cues.filter(c => c.kind === 'frame' && c.view === {view!r})
                     .map(c => [c.n, e.words.find(w => w[0] >= c.at)[2]]); }})()""")


def test_the_worked_example_steps_with_the_voice_and_lands_right_after_every_jump(tmp_path, wc_config, pw):
    from test_call import WORKED
    view = "advisory-drops-workflows"
    ctx, cwd, slug = _call_with_stage(tmp_path)
    with ctx as (url, call, loop, fake):
        call.stage_cwd, call.stage_slug = cwd, slug
        fake.seconds = 12.0
        browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.add_init_script("localStorage.setItem('talk.autoplay', 'false')")
            page.goto(url)
            page.wait_for_selector("#veil", state="hidden", timeout=10000)
            stage = page.frame_locator("#stage")
            asyncio.run_coroutine_threadsafe(call.answer(WORKED), loop).result(10)
            card = stage.locator(f'section.pane[data-view="{view}"] .map .k-card')  # a Mermaid graph is drawn as a map
            card.wait_for(timeout=20000)
            assert card.inner_text() == "advisory drops :workflows"
            inner = _stage_frame(page)
            assert _applied(inner, view) == 0
            page.wait_for_selector("#playpause:not([hidden])", timeout=10000)
            page.click("#playpause")
            seen = {}
            while not page.evaluate("audio.ended"):
                t, n = page.evaluate("audio.currentTime"), _applied(inner, view)
                seen.setdefault(n, t)
                page.wait_for_timeout(20)
            cues = dict(_cue_times(page, view))
            assert sorted(n for n in seen if n) == [1, 2, 3, 4, 5, 6]
            for n, said in cues.items():
                assert said - 0.25 <= seen[n] <= said + 0.4, (n, said, seen[n])
            assert _applied(inner, view) == 6
            assert stage.locator(f'section.pane[data-view="{view}"] .m-node.k-focus').count() == 1
            page.evaluate(f"audio.currentTime = {cues[3] + 0.05}")
            inner.wait_for_function(f"window.__stageTest.frames()[{view!r}] === 3", timeout=5000)
            page.click("#gear")
            page.click("#theme button[data-choice='dark']")
            stage.locator("html[data-theme='dark']").wait_for(state="attached", timeout=3000)
            page.wait_for_timeout(500)
            stage.locator(f'section.pane[data-view="{view}"] .map .m-node').first.wait_for(timeout=10000)
            assert _applied(inner, view) == 3
            page.click("#gear")
            page.click("#back")
            inner.wait_for_function(f"window.__stageTest.frames()[{view!r}] === 0", timeout=5000)
            card.wait_for(timeout=3000)
            page.evaluate(f"audio.currentTime = {cues[6] + 0.05}")
            inner.wait_for_function(f"window.__stageTest.frames()[{view!r}] === 6", timeout=5000)
            page.evaluate("audio.currentTime = audio.duration")
            page.wait_for_function("audio.ended", timeout=5000)
            page.click("#playpause")
            inner.wait_for_function(f"window.__stageTest.frames()[{view!r}] === 0", timeout=5000)
            inner.wait_for_function(f"window.__stageTest.frames()[{view!r}] === 1", timeout=10000)
        finally:
            browser.close()
            wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % slug)


def test_a_code_scene_steps_its_focus_with_the_voice(tmp_path, wc_config, pw):
    ctx, cwd, slug = _call_with_stage(tmp_path)
    (Path(cwd) / "a.py").write_text("".join(f"step_{i} = {i}\n" for i in range(1, 11)))
    with ctx as (url, call, loop, fake):
        call.stage_cwd, call.stage_slug, call.args.code = cwd, slug, Path(cwd)
        call.board.code_dir = Path(cwd).resolve()
        fake.seconds = 5.0
        browser = pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(url)
            page.wait_for_selector("#veil", state="hidden", timeout=10000)
            stage = page.frame_locator("#stage")
            asyncio.run_coroutine_threadsafe(call.answer(
                "[[show code: a.py:1-10 | Steps]] Here are ten small steps in one file. [[focus 2-3]] These two set "
                "up the start. [[point: line 7]] And this one carries the middle of it."), loop).result(10)
            page.wait_for_function("audio.ended", timeout=15000)
            lines = stage.locator('section.pane[data-view="steps"] .ln.k-focus')
            assert lines.evaluate_all("els => els.map(e => e.dataset.line)") == ["7"]
            assert stage.locator('section.pane[data-view="steps"] .vstep').inner_text() == "Step 2 of 2"
            page.evaluate(f"audio.currentTime = {dict(_cue_times(page, 'steps'))[1] + 0.05}")
            stage.locator('section.pane[data-view="steps"] .ln.k-focus[data-line="2"]').wait_for(timeout=5000)
            assert lines.count() == 2
        finally:
            browser.close()
            wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % slug)


def test_a_board_chip_brings_its_board_to_the_front(tmp_path, wc_config, browser):
    ctx, cwd, slug = _call_with_stage(tmp_path)
    with ctx as (url, call, loop, fake):
        call.stage_cwd, call.stage_slug = cwd, slug
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.add_init_script("localStorage.setItem('talk.autoplay', 'false')")
        page.goto(url)
        page.wait_for_selector("#veil", state="hidden", timeout=10000)
        stage = page.frame_locator("#stage")
        asyncio.run_coroutine_threadsafe(call.answer(
            f"{_table('Alpha', 'a1')} About alpha. {_table('Beta', 'b1')} About beta."), loop).result(10)
        stage.locator('button[role=tab][data-view="beta"]').wait_for(state="attached", timeout=10000)
        stage.locator('button[role=tab][data-view="alpha"][aria-selected="true"]').wait_for(state="attached", timeout=5000)
        page.click("#hist")
        chips = page.locator("#convo .chips")
        chips.locator("button.chip.board").nth(1).wait_for(timeout=5000)
        assert chips.count() == 1 and chips.locator(".clbl").inner_text().lower() == "on the stage"
        assert chips.locator("button.chip.board").count() == 2  # one labelled row, not a chip per line
        page.get_by_role("button", name="On the stage: Beta").click()
        assert page.is_hidden("#pHist")  # the sheet steps aside to show the board
        stage.locator('button[role=tab][data-view="beta"][aria-selected="true"]').wait_for(state="attached", timeout=5000)
        page.click("#hist")
        page.get_by_role("button", name="On the stage: Alpha").click()
        stage.locator('button[role=tab][data-view="alpha"][aria-selected="true"]').wait_for(state="attached", timeout=5000)
    wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % slug)


def test_a_board_chip_without_a_stage_is_disabled_and_says_why(tmp_path, browser):
    from test_browser_talk import served
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        page.goto(url)
        call.board_item({"kind": "table", "title": "Alpha", "view": "alpha"})
        chip = page.locator("button.chip.board")
        chip.wait_for(state="attached", timeout=5000)
        assert chip.is_disabled() and chip.get_attribute("title") == "The stage is not available"


def test_key_points_go_to_one_pinned_view_in_the_background(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.stage_cwd, ctl.stage_slug = str(tmp_path), "talk-abcd1234"
            with patch.object(talk.stage_mod, "show") as show:
                for i, text in enumerate(["A. [[key: one]] B. [[key: two]]", "C. [[key: three]]"], 1):
                    ctl.offer("go", typed=True)
                    await client.get("/api/turn?wait=1", headers=AUTH)
                    await client.post("/api/reply", json={"id": f"t{i}", "text": text}, headers=AUTH)
            return show.call_args_list

    calls = run(go())
    assert [c.args[1] for c in calls] == ["key-points", "key-points"]
    last = calls[-1]
    assert last.kwargs == {"title": "Key points", "slug": "talk-abcd1234", "background": True,
                           "extra": {"kind": "points", "pinned": True}, "owner": f"talk call {CALL}"}
    assert last.args[2] == {"type": "inline", "format": "points", "items": [
        {"n": 1, "text": "one", "answer": 1}, {"n": 2, "text": "two", "answer": 1}, {"n": 3, "text": "three", "answer": 2}]}


def test_a_key_points_chip_opens_the_pinned_board(tmp_path, wc_config, browser):
    ctx, cwd, slug = _call_with_stage(tmp_path)
    with ctx as (url, call, loop, fake):
        call.stage_cwd, call.stage_slug = cwd, slug
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.add_init_script("localStorage.setItem('talk.autoplay', 'false')")
        page.goto(url)
        page.wait_for_selector("#veil", state="hidden", timeout=10000)
        stage = page.frame_locator("#stage")
        asyncio.run_coroutine_threadsafe(call.answer(
            f"{_table('Alpha', 'a1')} About alpha. [[key: alpha comes first]] And more. [[key: then more]]"),
            loop).result(10)
        stage.locator('button[role=tab][data-view="key-points"]').wait_for(state="attached", timeout=10000)
        stage.locator('button[role=tab][data-view="alpha"][aria-selected="true"]').wait_for(state="attached", timeout=5000)
        assert stage.locator("button[role=tab]").evaluate_all("els => els.map(e => e.dataset.view)") == ["key-points", "alpha"]
        page.click("#hist")
        page.locator("button.chip.board", has_text="Key points: +2").click()
        stage.locator('button[role=tab][data-view="key-points"][aria-selected="true"]').wait_for(state="attached", timeout=5000)
        stage.locator('section.pane[data-view="key-points"] li .kt').nth(1).wait_for(timeout=5000)
        assert stage.locator('section.pane[data-view="key-points"] li .kt').all_text_contents() == [
            "alpha comes first", "then more"]
    wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % slug)


# -- the call's stage is the one the daemon made: its sid, its slug, never a second one ------------

SID = "261005-204314-0123456789abcdef"


def test_a_call_keeps_the_sid_and_slug_the_daemon_gave_its_stage(tmp_path):
    def made(cwd, slug, title):
        return {"sid": SID, "slug": slug, "url": f"http://127.0.0.1:3080/s/{SID}/"}

    with patch.object(talk.stage_mod, "ensure_stage", side_effect=made), \
         patch.object(talk.speech, "resolve_voice", lambda v: ("v", None)):
        call, _ = serve(tmp_path, make_args(code=tmp_path))
    assert call.stage_sid == SID and call.stage_slug.startswith("talk-")


def test_a_stage_the_daemon_renamed_fails_the_call_loudly(tmp_path):
    def renamed(cwd, slug, title):
        return {"sid": SID, "slug": slug + "-2", "url": "u"}

    with patch.object(talk.stage_mod, "ensure_stage", side_effect=renamed):
        try:
            serve(tmp_path, make_args(code=tmp_path))
        except talk.CallError as e:
            message = str(e)
        else:
            message = None
    assert message and "came back as" in message and "-2" in message


def test_boards_go_to_the_stage_by_its_sid(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.stage_cwd, ctl.stage_slug, ctl.stage_sid = str(tmp_path), "talk-abcd1234", SID
            with patch.object(talk.stage_mod, "show") as show:
                ctl.offer("draw", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                await client.post("/api/reply", json={"id": "t1", "text": "[[show table | T]]| a |\n|---|\n| 1 |[[/show]] "
                                                                          "Done. [[key: one]]"}, headers=AUTH)
            return [c.kwargs["slug"] for c in show.call_args_list]

    assert run(go()) == [SID, SID]


def test_a_show_still_running_is_reported_and_its_failure_reaches_the_next_reply(tmp_path):
    import threading
    gate = threading.Event()

    def slow_then_fail(cwd, name, source, **kw):
        if name == "slow":
            gate.wait(5)
            raise talk.stage_mod.wc.SlugMismatch("stage session talk-x in /a was ended (finished)")

    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.stage_cwd = str(tmp_path)
            with patch.object(talk.stage_mod, "show", side_effect=slow_then_fail), \
                 patch.object(talk, "STAGE_SETTLE_S", 0.2):
                ctl.offer("one", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                first = await (await client.post("/api/reply", json={
                    "id": "t1", "text": "[[show table | Slow]]| a |\n|---|\n| 1 |[[/show]] One."}, headers=AUTH)).json()
                gate.set()
                ctl.offer("two", typed=True)
                await client.get("/api/turn?wait=1", headers=AUTH)
                second = await (await client.post("/api/reply", json={"id": "t2", "text": "Two."}, headers=AUTH)).json()
            return first["board_problems"], second["board_problems"]

    first, second = run(go())
    assert first == ["1 board(s) still going onto the stage after 0.2 s; a failure shows with the next reply"]
    assert second == ["not shown on the stage: stage session talk-x in /a was ended (finished)"]


def test_a_closed_call_ends_its_stage(tmp_path):
    from helpers import running_server

    async def go(fail):
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path)
            call.stage_sid, call.stage_slug = SID, "talk-abcd1234"
            call.end("over")
            call.turns.end_collected.set()
            ended = []

            def finish(sid):
                if fail:
                    raise talk.stage_mod.wc.DaemonUnreachable("down")
                ended.append(sid)

            with patch.object(talk.stage_mod.wc, "finish_session", finish):
                await server.close(call)
            return ended

    from helpers import add_call
    assert run(go(False)) == [SID]
    assert run(go(True)) == []
