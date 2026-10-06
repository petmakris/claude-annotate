"""A newly shown view comes to the front, and a saved file reloads its own frame and keeps
its slide without taking the front back, measured in a real browser.

Runs against this worker's private daemon (`wc_config`) and its shared browser."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

from skills.stage import model, scene, stage



def board(page, name):
    """Open a board from the list under "n of m", as a reader does: the tabs are that list's rows."""
    if page.locator(".boards").is_hidden():
        page.locator(".pos").click()
    page.locator(f'button[role=tab][data-view="{name}"]').click()

def test_a_new_view_comes_to_the_front_and_a_saved_file_reloads_only_its_frame(tmp_path, wc_config, browser):
    proj = tmp_path / "proj"
    proj.mkdir()
    deck = proj / "deck.html"
    deck.write_text("<section id='slide-2'><h1 id='v'>one</h1></section><section id='slide-3'></section>")
    # No background watcher: this test drives tick() itself, and a real watcher would race it.
    no_watch = patch.object(stage, "start_watch", lambda cwd, sid: None)
    no_watch.start()
    res = stage.show(str(proj), "deck", model.parse_source("deck.html#slide-2", proj), title="Deck")
    try:
        page = browser.new_page()
        page.goto(res["url"])
        frame_el = page.wait_for_selector('section.pane[data-view="deck"] iframe.frame')
        frame = frame_el.content_frame()
        frame.wait_for_function("document.getElementById('v')?.textContent === 'one'")
        # A second view shown (not --background) while the page is open comes to the front,
        # even though the daemon lists __layout__ before the view it names.
        stage.show(str(proj), "notes", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"})
        notes_tab = page.locator('button[role=tab][data-view="notes"]')
        notes_tab.wait_for(state="attached")
        page.wait_for_function(
            "document.querySelector('button[role=tab][data-view=\"notes\"]')"
            "?.getAttribute('aria-selected') === 'true'", timeout=5000)
        assert page.locator('button[role=tab][data-view="deck"]').get_attribute("aria-selected") == "false"
        # Back on the deck to move its slide, then onto the notes again.
        board(page, "deck")
        # Regression probes: move off the source fragment and onto the notes tab, and tag
        # the frame's wrapper, so a pane rebuild (which would lose all three) is
        # distinguishable from the double-buffered reload (which must keep all three).
        frame.evaluate("location.hash = 'slide-3'")
        page.eval_on_selector('section.pane[data-view="deck"] .framewrap', "e => e.dataset.probe = '1'")
        board(page, "notes")
        deck.write_text("<section id='slide-2'><h1 id='v'>two</h1></section><section id='slide-3'></section>")
        t = time.time() + 5
        os.utime(deck, (t, t))
        assert stage.tick(str(proj), res["sid"]) == ["deck"]
        # The new frame takes over only once loaded, and the old one is gone.
        page.wait_for_function(
            "(() => { const fs = document.querySelectorAll('section.pane[data-view=\"deck\"] iframe.frame');"
            " return fs.length === 1 && !fs[0].classList.contains('incoming')"
            " && fs[0].contentDocument?.getElementById('v')?.textContent === 'two'; })()", timeout=5000)
        reloaded = page.query_selector('section.pane[data-view="deck"] iframe.frame').content_frame()
        assert page.eval_on_selector('section.pane[data-view="deck"] .framewrap', "e => e.dataset.probe") == "1"
        assert reloaded.evaluate("location.hash") == "#slide-3"
        assert notes_tab.get_attribute("aria-selected") == "true"
        assert page.locator("button[role=tab]").count() == 2
    finally:
        no_watch.stop()
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_failed_first_load_says_so_instead_of_an_empty_stage(tmp_path, wc_config, browser):
    proj = tmp_path / "proj"
    proj.mkdir()
    res = stage.show(str(proj), "notes", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 1 |"})
    try:
        page = browser.new_page()
        page.route(lambda url: url.split("?")[0].endswith("/items"),
                   lambda route: route.fulfill(status=500, body="boom"))
        page.goto(res["url"])
        line = page.locator(".panes .empty")
        line.filter(has_text="Could not load the stage").wait_for(timeout=5000)
        assert line.locator(".msg").text_content() == "Could not load the stage: items: 500."
        # Later changes are dropped, not queued behind a snapshot that never comes.
        stage.show(str(proj), "more", {"type": "url", "url": "https://example.com"})
        page.wait_for_timeout(1000)
        assert page.locator("button[role=tab]").count() == 0
        assert line.is_visible()
        # 'Try again' fetches the snapshot again, with no page reload.
        page.unroute_all()
        page.evaluate("window.__same_page = 1")
        line.get_by_role("button", name="Try again").click()
        page.locator('button[role=tab][data-view="more"]').wait_for(state="attached", timeout=5000)
        assert page.locator("button[role=tab]").count() == 2
        assert page.evaluate("window.__same_page") == 1
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


TABLE = {"type": "inline", "format": "table", "body": "| area | what |\n|---|---|\n| kappa | lives here |"}
TALL = {"type": "inline", "format": "table",
        "body": "| area | what |\n|---|---|\n" + "\n".join(f"| row {i} | here |" for i in range(60))}
CODE = {"type": "inline", "format": "code", "path": "a.py", "start": 1, "lines": ["x = 1"], "highlight": None,
        "lang": "python"}
CDNS = ("cdn.jsdelivr.net", "cdnjs.cloudflare.com")


def _hang(page, hosts=CDNS):
    """Requests to these hosts never get an answer: a stalled CDN, not a failing one."""
    page.route(lambda url: any(h in url for h in hosts), lambda route: None)


def test_a_stalled_cdn_never_blocks_the_stage(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "areas", TABLE, title="Areas")
    stage.show(str(tmp_path), "code", CODE, title="Code")
    try:
        page = browser.new_page()
        _hang(page)
        page.goto(res["url"])
        page.locator('button[role=tab][data-view="areas"]').wait_for(state="attached", timeout=2000)
        page.locator('button[role=tab][data-view="code"]').wait_for(state="attached", timeout=2000)
        board(page, "areas")
        page.locator('section.pane[data-view="areas"] td', has_text="kappa").wait_for(timeout=2000)
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_diagram_waiting_on_mermaid_never_holds_up_the_next_view(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "first", CODE, title="First")
    try:
        page = browser.new_page()
        _hang(page, ("mermaid",))
        page.goto(res["url"])
        page.locator('button[role=tab][data-view="first"]').wait_for(state="attached", timeout=5000)
        stage.show(str(tmp_path), "flow", {"type": "inline", "format": "diagram", "body": "graph TD; A-->B"},
                   title="Flow")
        stage.show(str(tmp_path), "areas", TABLE, title="Areas")
        page.locator('section.pane[data-view="areas"] td', has_text="kappa").wait_for(timeout=2000)
        board(page, "flow")
        page.locator('section.pane[data-view="flow"]').get_by_text("Drawing the diagram…").wait_for(timeout=2000)
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_diagram_draws_from_the_vendored_mermaid_with_no_network(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "flow", {"type": "inline", "format": "diagram",
                                             "body": "graph TD; A[Ask] --> B[Answer]"}, title="Flow")
    try:
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        _hang(page)
        asked = []
        page.on("request", lambda r: asked.append(r.url))
        page.goto(res["url"])
        page.locator('section.pane[data-view="flow"] .diagram svg g.node').first.wait_for(timeout=20000)
        assert any(u.split("?")[0].endswith("/vendor/mermaid.min.js") for u in asked)
        assert not any(h in u for u in asked for h in CDNS)
        assert page.locator('section.pane[data-view="flow"] .diagram svg foreignObject').count() == 0
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_only_the_front_pane_renders_until_another_tab_is_opened(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "one", TABLE, title="One")
    stage.show(str(tmp_path), "two", {"type": "url", "url": "https://example.invalid/"}, title="Two")
    stage.show(str(tmp_path), "three", CODE, title="Three")
    try:
        page = browser.new_page()
        _hang(page)
        page.goto(res["url"])
        page.locator('section.pane[data-view="three"] .code').wait_for(timeout=5000)
        counts = page.evaluate("Object.fromEntries([...document.querySelectorAll('section.pane')]"
                               ".map(p => [p.dataset.view, p.childElementCount]))")
        assert counts["one"] == 0 and counts["two"] == 0 and counts["three"] > 0
        assert page.locator("iframe").count() == 0  # the url view's frame is not made until it is opened
        board(page, "one")
        page.locator('section.pane[data-view="one"] td', has_text="kappa").wait_for(timeout=2000)
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_the_stage_follows_dark_mode_with_the_shared_tokens(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "one", TABLE, title="One")
    try:
        page = browser.new_page()
        _hang(page)
        page.emulate_media(color_scheme="dark")
        page.goto(res["url"])
        page.locator('button[role=tab][data-view="one"]').wait_for(state="attached", timeout=5000)
        page.wait_for_function("getComputedStyle(document.body).backgroundColor === 'rgb(15, 19, 24)'", timeout=5000)
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


AREAS = """| Area | What lives there |
|---|---|
| `apps/` | Python and Swift apps, each a uv project with its own README |
| `bin/` | Dispatchers that must work with no profile loaded |
| `claude/` | The personal Claude Code plugin: skills, hooks, output styles |
| `libexec/` | One folder per domain, one executable per verb |
| `lib/` | Shared helpers: colours, pickers, launchd, services |
| `machines/` | The runbook and one page per machine |
| `profiles/` | Shell profiles loaded by env.sh |
| `personal/` | Αρχεία ζωής: λογαριασμοί, σαρωμένα έγγραφα και σημειώσεις |"""
STEPS = """| Step | Time | Note |
|---|---|---|
| Parse | 12 ms | reads the tags |
| Speak | 1.4 s | first sentence plays |
| Draw | 220 ms | mermaid in its own task |"""
DOCSTRING = {"type": "inline", "format": "code", "path": "lower.py", "start": 1, "highlight": [3, 3], "lang": "python",
             "lines": ['def lower(text):', '    """Return the text', '    in lower case,', '    keeping final sigma."""',
                       '    return text.lower()']}


def _page(browser, url, width=1400, height=900, scheme="light"):
    page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
    page.goto(url)
    return page


def test_a_table_board_has_a_real_header_and_sizes_its_own_columns(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "areas", {"type": "inline", "format": "table", "body": AREAS},
                     title="Repo at a glance")
    try:
        page = _page(browser, res["url"])
        pane = page.locator('section.pane[data-view="areas"]')
        pane.locator("td", has_text="personal/").wait_for(timeout=5000)
        assert pane.locator("h2.vtitle").inner_text() == "Repo at a glance"
        assert pane.locator("h2.vtitle").is_visible()
        assert "Table · 8 rows" in pane.locator(".vmeta").inner_text()
        assert pane.get_by_role("button", name="Copy").is_visible()
        # The raw format name never shows on its own (the stray 'table' label of old).
        raw = page.evaluate("""[...document.querySelectorAll('body *')].filter(e => e.offsetParent !== null
            && ['table', 'diagram'].includes(e.textContent.trim().toLowerCase())).length""")
        assert raw == 0
        key_w = pane.locator("tbody tr:first-child td:first-child").bounding_box()["width"]
        table_w = pane.locator("table").bounding_box()["width"]
        assert key_w < 0.3 * table_w
        # rows are divided by a line (the grid has no zebra stripes: the band is for the row being said)
        line = page.evaluate("""getComputedStyle(document.querySelector('section.pane[data-view="areas"] tbody td')).borderBottomStyle""")
        assert line == "solid"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_wide_table_turns_into_cards_on_a_phone(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "steps", {"type": "inline", "format": "table", "body": STEPS}, title="Steps")
    try:
        page = _page(browser, res["url"], 390, 844)
        td = page.locator('section.pane[data-view="steps"] td', has_text="Parse")
        td.wait_for(timeout=5000)
        before = td.evaluate("e => getComputedStyle(e, '::before').content")
        assert before not in ("", "none", "normal") and "Step" in before
        assert td.evaluate("e => getComputedStyle(e).display") == "grid"
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        # Numbers line up on the right where the table is a table.
        page.set_viewport_size({"width": 1400, "height": 900})
        assert page.locator('section.pane[data-view="steps"] td', has_text="12 ms").evaluate(
            "e => e.classList.contains('num') && getComputedStyle(e).textAlign") == "right"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_code_is_highlighted_across_lines_and_its_marked_lines_stand_out(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "lower", DOCSTRING, title="Lowercasing")
    try:
        page = _page(browser, res["url"])
        pane = page.locator('section.pane[data-view="lower"]')
        line3 = pane.locator('.ln[data-line="3"]')
        line3.wait_for(timeout=5000)
        page.wait_for_function("!!window.hljs", timeout=5000)
        page.wait_for_function(
            "!!document.querySelector('section.pane[data-view=\"lower\"] .ln[data-line=\"3\"] > span .hljs-string')",
            timeout=5000)
        assert "marked" in line3.get_attribute("class")
        opacity = float(pane.locator('.ln[data-line="1"]').evaluate("e => getComputedStyle(e).opacity"))
        assert abs(opacity - 0.6) < 0.05
        assert "Code · lower.py · lines 1–5 · line 3 marked" in pane.locator(".vmeta").inner_text()
        copy, wrap = pane.get_by_role("button", name="Copy"), pane.get_by_role("button", name="Wrap lines")
        assert copy.is_visible() and wrap.is_visible()
        assert wrap.get_attribute("aria-pressed") == "false"
        wrap.click()
        assert wrap.get_attribute("aria-pressed") == "true"
        assert "wrap" in pane.locator(".code").get_attribute("class")
        copy.click()
        pane.get_by_role("button", name="Copied").wait_for(timeout=2000)
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_cut_short_code_view_says_so(tmp_path, wc_config, browser):
    src = dict(DOCSTRING, highlight=None, truncated=True)
    res = stage.show(str(tmp_path), "long", src, title="Long")
    try:
        page = _page(browser, res["url"])
        meta = page.locator('section.pane[data-view="long"] .vmeta')
        meta.wait_for(timeout=5000)
        assert "showing the first 60 lines" in meta.inner_text()
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_angle_brackets_in_diagram_labels_are_escaped_and_arrows_are_not(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "one", TABLE, title="One")
    try:
        page = _page(browser, res["url"])
        _hang(page)
        page.locator('button[role=tab][data-view="one"]').wait_for(state="attached", timeout=5000)
        esc = lambda s: page.evaluate("s => window.__stageTest.escapeLabels(s)", s)  # noqa: E731
        assert esc("A[libexec/<domain>/<verb>] --> B") == "A[libexec/#lt;domain#gt;/#lt;verb#gt;] --> B"
        assert esc('A -->|a <b>| B("x > y") ==> C{<k>}') == 'A -->|a #lt;b#gt;| B("x #gt; y") ==> C{#lt;k#gt;}'
        assert esc("A((<x>)) -.-> B") == "A((#lt;x#gt;)) -.-> B"
        # A line break stays one; other diagram types keep their arrows, an open quote ends at its line.
        assert esc('graph TD\nA["a<br>b"] --> B[c<br/>d]') == 'graph TD\nA["a<br>b"] --> B[c<br/>d]'
        assert esc("graph TD\nA[x] --> B") == "graph TD\nA[x] --> B"
        assert esc("classDiagram\nDuck --|> Animal\nA ..|> B") == "classDiagram\nDuck --|> Animal\nA ..|> B"
        seq = 'sequenceDiagram\nA->>B: he said "hi\nB->>A: ok'
        assert esc(seq) == seq
        assert esc('graph TD\nA["open <x>\nB --> C') == 'graph TD\nA["open #lt;x#gt;\nB --> C'
        assert page.evaluate("window.__stageTest.diagramType('---\\ntitle: x\\n---\\n%% c\\nflowchart LR')") == "flowchart"
        # Line splitting keeps a span open across a newline.
        assert page.evaluate("window.__stageTest.splitLines('<span class=\"s\">a\\nb</span>c')") == [
            '<span class="s">a</span>', '<span class="s">b</span>c']
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_diagrams_draw_with_safe_labels_and_a_broken_one_says_so(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "flow", {"type": "inline", "format": "diagram",
                                             "body": "graph TD; A[libexec/<domain>/<verb>] --> B[stage]"}, title="Flow")
    stage.show(str(tmp_path), "bad", {"type": "inline", "format": "diagram", "body": "graph TD; A-->"},
               title="Bad", background=True)
    try:
        page = _page(browser, res["url"])
        svg = page.locator('section.pane[data-view="flow"] .diagram svg')
        svg.wait_for(timeout=20000)
        assert "<domain>" in svg.text_content()
        fit = page.locator('section.pane[data-view="flow"]').get_by_role("button", name="Fit")
        assert fit.get_attribute("aria-pressed") == "true"
        page.locator('section.pane[data-view="flow"]').get_by_role("button", name="Actual size").click()
        assert "actual" in page.locator('section.pane[data-view="flow"] .diagram').get_attribute("class")
        board(page, "bad")
        bad = page.locator('section.pane[data-view="bad"]')
        bad.get_by_text("This diagram could not be drawn.").wait_for(timeout=20000)
        assert bad.get_by_role("button", name="Try again").is_visible()
        assert "graph TD; A-->" in bad.locator(".srcframe").inner_text()
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_boards_stay_reachable_on_a_phone_and_mark_background_updates(tmp_path, wc_config, browser):
    cwd = str(tmp_path)
    res = stage.show(cwd, "v0", TABLE, title="The first view with a long title")
    for i in range(1, 5):
        stage.show(cwd, "v%d" % i, TABLE, title="View number %d with a long title" % i)
    try:
        page = _page(browser, res["url"], 390, 844)
        last = page.locator('button[role=tab][data-view="v4"]')
        last.wait_for(state="attached", timeout=5000)
        page.wait_for_function("document.querySelector('.tabpos')?.textContent === '5 of 5'", timeout=5000)
        # The history buttons say where the reader is and move between boards.
        nav = page.get_by_role("group", name="Boards")
        assert nav.is_visible() and nav.get_by_role("button", name="Next board").is_disabled()
        nav.get_by_role("button", name="Previous board").click()
        assert page.locator('button[role=tab][data-view="v3"]').get_attribute("aria-selected") == "true"
        assert nav.locator(".tabpos").inner_text() == "4 of 5"
        # The list of boards fits the phone, newest first.
        page.locator(".pos").click()
        box = page.locator(".boards").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390
        rows = page.locator("nav.tabs button[role=tab]")
        tops = {rows.nth(i).get_attribute("data-view"): rows.nth(i).bounding_box()["y"] for i in range(5)}
        assert sorted(tops, key=tops.get) == ["v4", "v3", "v2", "v1", "v0"]
        last.click()
        assert page.locator(".boards").is_hidden() and last.get_attribute("aria-selected") == "true"
        # A background change to a board that is not being read puts a dot on its row and on the counter.
        v1 = page.locator('button[role=tab][data-view="v1"]')
        stage.show(cwd, "v1", {"type": "inline", "format": "table", "body": "| a |\n|---|\n| 2 |"}, background=True)
        page.wait_for_function(
            "document.querySelector('button[role=tab][data-view=\"v1\"]').classList.contains('updated')", timeout=5000)
        assert v1.get_attribute("aria-label").endswith(", updated")
        assert page.locator(".posdot").is_visible() and page.locator(".pos").get_attribute("aria-label") == "All boards, one changed"
        assert last.get_attribute("aria-selected") == "true"
        board(page, "v1")
        assert "updated" not in v1.get_attribute("class") and page.locator(".posdot").is_hidden()
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_an_empty_stage_says_what_will_appear(tmp_path, wc_config, browser):
    url = stage.link(str(tmp_path))
    sid = stage.ensure_stage(str(tmp_path))["sid"]
    try:
        page = _page(browser, url)
        empty = page.locator(".panes .empty")
        empty.get_by_text("The stage is empty").wait_for(timeout=5000)
        assert empty.locator(".tile").count() == 4
        assert [t.strip() for t in empty.locator(".tile").all_inner_texts()] == ["Code", "Diagram", "Table", "Page"]
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % sid)


def test_an_in_place_update_lights_up_only_the_rows_that_changed(tmp_path, wc_config, browser):
    body = "| k | v |\n|---|---|\n| a | 1 |\n| b | 2 |\n| c | 3 |"
    res = stage.show(str(tmp_path), "t", {"type": "inline", "format": "table", "body": body}, title="T")
    try:
        page = _page(browser, res["url"])
        page.locator('section.pane[data-view="t"] td', has_text="c").wait_for(timeout=5000)
        stage.show(str(tmp_path), "t", {"type": "inline", "format": "table", "body": body.replace("| 2 |", "| 20 |")})
        page.locator('section.pane[data-view="t"] td', has_text="20").wait_for(timeout=5000)
        changed = page.evaluate("[...document.querySelectorAll('section.pane[data-view=t] tr.changed')]"
                                ".map(tr => tr.textContent.trim())")
        assert [t.split() for t in changed] == [["b", "20"]]
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


# -- following the voice, embedded in a talk call --------------------------------------------

CODE5 = {"type": "inline", "format": "code", "path": "five.py", "start": 1, "highlight": None, "lang": "python",
         "lines": [f"step_{i} = {i}" for i in range(1, 6)]}


def _embedded(browser, url, width=1300, height=850):
    """The stage in an iframe of a parent page that records what the stage posts to it. Returns
    (page, the stage's frame locator, send(msg) posting a message to the stage as talk does)."""
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_content("<body style='margin:0'><script>window.got = [];"
                     "addEventListener('message', e => got.push(e.data))</script>"
                     f"<iframe id='s' src='{url}' style='border:0;width:100vw;height:100vh'></iframe></body>")
    page.wait_for_function("got.some(m => m.type === 'stage:ready')", timeout=10000)

    def send(msg):
        page.evaluate("m => document.getElementById('s').contentWindow.postMessage(m, '*')", msg)
    return page, page.frame_locator("#s"), send


def _selected(frame, name):
    return frame.locator(f'button[role=tab][data-view="{name}"]').get_attribute("aria-selected") == "true"


def test_the_stage_follows_the_voice_until_a_tab_is_tapped(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "a", TABLE, title="Areas", extra={"answer": 3})
    stage.show(str(tmp_path), "b", CODE5, title="Five steps", background=True, extra={"answer": 3})
    try:
        alone = _page(browser, res["url"])
        alone.locator('button[role=tab][data-view="b"]').wait_for(state="attached", timeout=5000)
        assert alone.locator(".follow").count() == 0  # on its own the stage has no follow button
        alone.close()

        page, frame, send = _embedded(browser, res["url"])
        frame.locator('button[role=tab][data-view="b"]').wait_for(state="attached", timeout=5000)
        assert frame.locator(".follow").count() == 0  # the call page holds the switch
        # Where a board came from is said in plain words on the board, not as a badge on its tab.
        assert frame.locator('button[role=tab] .ans').count() == 0
        frame.locator('section.pane[data-view="a"] .vmeta').filter(has_text="from answer 3").wait_for(timeout=3000)
        views = page.evaluate("got.filter(m => m.type === 'stage:views').pop().list")
        assert {v["name"]: (v["title"], v["kind"], v["answer"]) for v in views} == {
            "a": ("Areas", "table", 3), "b": ("Five steps", "code", 3)}
        assert _selected(frame, "a")
        send({"type": "stage:front", "view": "b"})
        frame.locator('button[role=tab][data-view="b"][aria-selected="true"]').wait_for(state="attached", timeout=3000)
        # A tap on a tab turns following off, and tells the call page.
        board(frame, "a")
        page.wait_for_function("got.some(m => m.type === 'stage:follow' && m.on === false)", timeout=2000)
        send({"type": "stage:front", "view": "b"})
        page.wait_for_timeout(300)
        assert _selected(frame, "a")
        # A chip pressed in the conversation still works, and leaves following off.
        send({"type": "stage:front", "view": "b", "manual": True})
        frame.locator('button[role=tab][data-view="b"][aria-selected="true"]').wait_for(state="attached", timeout=3000)
        # A new answer turns it back on, and says so.
        send({"type": "stage:answer", "n": 4})
        page.wait_for_function("got.filter(m => m.type === 'stage:follow').pop().on === true", timeout=2000)
        # The call page's switch turns it off and on.
        send({"type": "stage:follow", "on": False})
        send({"type": "stage:front", "view": "a"})
        page.wait_for_timeout(300)
        assert _selected(frame, "b")
        send({"type": "stage:follow", "on": True})
        send({"type": "stage:front", "view": "a"})
        frame.locator('button[role=tab][data-view="a"][aria-selected="true"]').wait_for(state="attached", timeout=3000)
        # A new view is news for the call page.
        stage.show(str(tmp_path), "c", TABLE, title="Third", background=True)
        page.wait_for_function("got.some(m => m.type === 'stage:changed' && m.name === 'c' && m.isNew)", timeout=5000)
        assert page.evaluate("got.find(m => m.type === 'stage:changed').title") == "Third"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_point_lights_up_lines_a_row_and_a_node(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "c", CODE5, title="Five steps")
    stage.show(str(tmp_path), "t", {"type": "inline", "format": "table", "body": AREAS}, title="Areas", background=True)
    stage.show(str(tmp_path), "d", {"type": "inline", "format": "diagram", "body": "graph TD; P[Page]-->Q[Queue]"},
               title="Flow", background=True)
    try:
        page, frame, send = _embedded(browser, res["url"])
        frame.locator('section.pane[data-view="c"] .ln').first.wait_for(timeout=5000)
        send({"type": "stage:point", "view": "c", "target": {"type": "lines", "a": 2, "b": 3}})
        code = frame.locator('section.pane[data-view="c"] .code')
        frame.locator('section.pane[data-view="c"] .code.dimmed').wait_for(timeout=3000)
        assert frame.locator('section.pane[data-view="c"] .ln.spot').evaluate_all(
            "els => els.map(e => e.dataset.line)") == ["2", "3"]
        page.wait_for_timeout(400)  # the dimming fades in
        assert abs(float(frame.locator('.ln[data-line="1"]').evaluate("e => getComputedStyle(e).opacity")) - 0.45) < 0.05
        send({"type": "stage:point", "view": None, "target": None})
        frame.locator('section.pane[data-view="c"] .code:not(.dimmed)').wait_for(timeout=3000)
        assert frame.locator(".spot").count() == 0 and "dimmed" not in code.get_attribute("class")
        # A row, by its first cell (case and accents aside), in a pane not filled until now.
        send({"type": "stage:point", "view": "t", "target": {"type": "row", "text": "PERSONAL/"}})
        row = frame.locator('section.pane[data-view="t"] tbody tr.spot')
        row.wait_for(timeout=3000)
        assert row.count() == 1 and "Αρχεία ζωής" in row.inner_text()
        assert _selected(frame, "t")
        assert "dimmed" in frame.locator('section.pane[data-view="t"] table').get_attribute("class")
        send({"type": "stage:point", "view": "t", "target": {"type": "row", "n": 2}})
        frame.locator('section.pane[data-view="t"] tbody tr.spot', has_text="bin/").wait_for(timeout=3000)
        assert frame.locator('section.pane[data-view="t"] tbody tr.spot').count() == 1
        # A node of a diagram drawn after the point arrived.
        send({"type": "stage:point", "view": "d", "target": {"type": "node", "id": "Q"}})
        node = frame.locator('section.pane[data-view="d"] svg g.node.spot')
        node.wait_for(timeout=20000)
        assert "Queue" in node.text_content()
        assert "dimmed" in frame.locator('section.pane[data-view="d"] .diagram').get_attribute("class")
        assert frame.locator("svg g.node.spot").count() == 1
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


# -- what changed, and key points ----------------------------------------------------------

def _git_change(tmp_path):
    """A file committed, then edited by one word on one line: its change source."""
    import subprocess
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"}
    (tmp_path / "turns.py").write_text('def wait(queue):\n    """Park until a turn arrives."""\n'
                                       '    return queue.get(timeout=30)\n\n\ndone = True\n')
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "start"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True, env=env)
    (tmp_path / "turns.py").write_text('def wait(queue):\n    """Park until a turn arrives."""\n'
                                       '    return queue.get(timeout=90)\n\n\ndone = True\n')
    return model.change_source(tmp_path, "turns.py")


def test_a_change_card_shows_added_and_removed_lines_and_the_edited_word(tmp_path, wc_config, browser):
    src = _git_change(tmp_path)
    res = stage.show(str(tmp_path), "edit", src, title="What I changed", extra={"kind": "change"})
    try:
        page = _page(browser, res["url"])
        pane = page.locator('section.pane[data-view="edit"]')
        pane.locator(".ln.add").first.wait_for(timeout=5000)
        assert "Change · turns.py · +1 −1" in pane.locator(".vmeta").inner_text()
        assert pane.locator(".hunk").first.inner_text() == "Line 1"
        add, dele = pane.locator(".ln.add"), pane.locator(".ln.del")
        assert add.count() == 1 and dele.count() == 1
        assert add.get_attribute("data-line") == "3" and dele.get_attribute("data-line") is None
        tints = page.evaluate("""['add', 'del'].map(k => getComputedStyle(document.querySelector(
            'section.pane[data-view="edit"] .ln.' + k)).backgroundColor)""")
        assert tints[0] != tints[1] and "rgba(0, 0, 0, 0)" not in tints
        assert add.locator("mark.chg").inner_text() == "90" and dele.locator("mark.chg").inner_text() == "30"
        assert "line-through" in dele.locator("mark.chg").evaluate("e => getComputedStyle(e).textDecorationLine")
        assert add.locator(".hljs-number").count() >= 1  # highlighted, and the mark sits inside it
        assert pane.get_by_role("button", name="Copy").is_visible()
        assert pane.get_by_role("button", name="Wrap lines").is_visible()
        assert page.locator('button[role=tab][data-view="edit"] svg.ico path').get_attribute("d").startswith("M4.5 2v6")
        assert pane.locator(".more").count() == 0
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_key_points_lead_the_tabs_and_light_up_as_they_are_said(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "a", TABLE, title="Areas", extra={"answer": 1})
    points = {"type": "inline", "format": "points", "items": [
        {"n": 1, "text": "Turns wait in a queue", "answer": 1},
        {"n": 2, "text": "The doorbell wakes the session", "answer": 1},
        {"n": 3, "text": "Ένα κλειδί στα ελληνικά", "answer": 2}]}
    stage.show(str(tmp_path), "key-points", points, title="Key points", background=True,
               extra={"kind": "points", "pinned": True})
    try:
        page, frame, send = _embedded(browser, res["url"])
        frame.locator('button[role=tab][data-view="key-points"]').wait_for(state="attached", timeout=5000)
        tabs = frame.locator("button[role=tab]").evaluate_all("els => els.map(e => e.dataset.view)")
        assert tabs == ["key-points", "a"]  # first, though shown last
        assert frame.locator('button[role=tab][data-view="key-points"] .count').inner_text() == "3"
        assert _selected(frame, "a")
        send({"type": "stage:key", "view": "key-points", "index": 2})
        # Never fronted for a key: the tab gets its dot instead.
        frame.locator('button[role=tab][data-view="key-points"].updated').wait_for(state="attached", timeout=3000)
        assert _selected(frame, "a")
        board(frame, "key-points")
        pane = frame.locator('section.pane[data-view="key-points"]')
        lit = pane.locator("li.lit")
        lit.wait_for(timeout=3000)
        assert lit.count() == 1 and "doorbell" in lit.inner_text()
        assert pane.locator(".kcap").all_text_contents() == ["Answer 1", "Answer 2"]  # in the order said
        assert pane.locator("li .kn").all_inner_texts() == ["1", "2", "3"]
        assert pane.locator(".kgroup").first.evaluate("e => getComputedStyle(e).borderTopStyle") == "solid"
        send({"type": "stage:key", "view": "key-points", "index": 3})
        pane.locator('li.lit[data-n="3"]').wait_for(timeout=3000)
        assert pane.locator("li.lit").count() == 1
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_table_board_never_runs_markup_from_its_cells(tmp_path, wc_config, browser):
    body = '| a | b |\n|---|---|\n| <img src=x onerror="window.pwned=1"> | <script>window.pwned=2</script> |'
    res = stage.show(str(tmp_path), "t", {"type": "inline", "format": "table", "body": body}, title="Unsafe")
    try:
        page = _page(browser, res["url"])
        page.locator('section.pane[data-view="t"] tbody tr').wait_for(timeout=5000)
        page.wait_for_timeout(300)
        assert page.evaluate("window.pwned") is None
        assert page.locator("img[onerror]").count() == 0 and page.locator(".panes script").count() == 0
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_phone_header_keeps_the_title_on_one_row_and_its_buttons_on_screen(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "lower", DOCSTRING, title="Lowercasing")
    try:
        page = _page(browser, res["url"], 390, 844)
        pane = page.locator('section.pane[data-view="lower"]')
        pane.locator(".ln").first.wait_for(timeout=5000)
        title, btns = pane.locator(".vtitle").bounding_box(), pane.locator(".pbtns").bounding_box()
        assert title["y"] + title["height"] <= 40 and btns["x"] + btns["width"] <= 390
        # What the board is waits in the title's tooltip.
        assert pane.locator(".vmeta").evaluate("e => getComputedStyle(e.closest('.vtip')).opacity") == "0"
        pane.locator(".vhead").hover()
        page.wait_for_function("getComputedStyle(document.querySelector('.vtip')).opacity === '1'", timeout=2000)
        assert pane.locator(".vmeta").inner_text().startswith("Code · ")
        # Wrapped on a phone, an indented line keeps its indent on the lines it wraps onto.
        ind = page.evaluate("""[...document.querySelectorAll('section.pane[data-view="lower"] .ln')]
            .map(l => +getComputedStyle(l).getPropertyValue('--ind') || 0)""")
        assert max(ind) >= 4
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_diagram_shown_while_the_stage_has_no_size_is_drawn_once_it_has_one(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "a", TABLE, title="Areas")
    try:
        page, frame, _ = _embedded(browser, res["url"])
        page.evaluate("document.getElementById('s').style.display = 'none'")
        stage.show(str(tmp_path), "flow", {"type": "inline", "format": "diagram",
                                           "body": "graph TD; A[Ask]-->B[Answer]-->C[Show]"}, title="Flow")
        page.wait_for_timeout(2500)  # mermaid would have drawn by now, at no size
        page.evaluate("document.getElementById('s').style.display = 'block'")
        svg = frame.locator('section.pane[data-view="flow"] .diagram svg')
        svg.wait_for(timeout=20000)
        size = "s => [s.getBoundingClientRect().width, s.viewBox.baseVal.width]"
        for _ in range(40):
            if svg.evaluate(size)[0] > 100:
                break
            page.wait_for_timeout(250)
        drawn, laid_out = svg.evaluate(size)
        assert drawn > 100 and laid_out > 16
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_short_board_sits_in_the_middle_and_a_tall_one_starts_at_the_top(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "short", TABLE, title="Short")
    stage.show(str(tmp_path), "tall", TALL, title="Tall", background=True)
    try:
        page = _page(browser, res["url"])
        short = page.locator('section.pane[data-view="short"] .tablewrap')
        short.wait_for(timeout=5000)
        body = page.locator('section.pane[data-view="short"] .pbody').bounding_box()
        box = short.bounding_box()
        assert abs((box["x"] + box["width"] / 2) - (body["x"] + body["width"] / 2)) < 2
        assert abs((box["y"] + box["height"] / 2) - (body["y"] + body["height"] / 2)) < 2
        board(page, "tall")
        tall = page.locator('section.pane[data-view="tall"] .tablewrap')
        tall.wait_for(timeout=5000)
        top = page.locator('section.pane[data-view="tall"] .pbody').bounding_box()["y"]
        assert tall.bounding_box()["y"] - top < 20  # the body's padding, nothing more
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_the_call_page_sets_the_stage_theme(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "one", TABLE, title="One")
    try:
        page, frame, send = _embedded(browser, res["url"])
        frame.locator('button[role=tab][data-view="one"]').wait_for(state="attached", timeout=5000)
        send({"type": "stage:theme", "theme": "dark"})
        frame.locator("html[data-theme='dark']").wait_for(state="attached", timeout=2000)
        assert frame.locator("body").evaluate("b => getComputedStyle(b).backgroundColor") == "rgb(15, 19, 24)"
        send({"type": "stage:theme", "theme": "light"})
        frame.locator("html[data-theme='light']").wait_for(state="attached", timeout=2000)
        assert frame.locator("body").evaluate("b => getComputedStyle(b).backgroundColor") == "rgb(245, 246, 248)"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_diagram_drawn_before_the_theme_changes_is_redrawn_in_the_new_one(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "flow", {"type": "inline", "format": "diagram", "body": "graph TD; A[Ask] --> B[Answer]"},
                     title="Flow")
    try:
        page, frame, send = _embedded(browser, res["url"])
        rect = frame.locator('section.pane[data-view="flow"] .diagram svg g.node rect').first
        rect.wait_for(timeout=20000)
        fill = "r => getComputedStyle(r).fill"
        assert rect.evaluate(fill) == "rgb(255, 255, 255)"
        send({"type": "stage:theme", "theme": "dark"})
        for _ in range(40):
            if rect.is_visible() and rect.evaluate(fill) == "rgb(22, 27, 34)":
                break
            page.wait_for_timeout(250)
        assert rect.evaluate(fill) == "rgb(22, 27, 34)"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


FLOWCHARTS = {
    "example": """flowchart LR
  subgraph adv[":advisory"]
    pws[ProposalWorkflowServiceImpl]
    legacy[web.workflows.legacy]
  end
  wf[":workflows"]
  engine[(Flowable engine)]
  pws -->|imports 3 types| wf
  wf --> engine
  pws --> legacy""",
    "chains": "graph TD\n  A[Start] --> B & C\n  B --> D --> E\n  A --> B\n  A -- text --> B\n  A -.-> B\n"
              "  subgraph S1 [Group one]\n    D\n    E\n  end\n  X:::cls --> Y",
    "inline": "graph TD; P[Page]-->Q[Queue]",
    "shapes": 'graph TD\nA["f(x)"] --> B[(Store)]\nB --> C{Decide?}\nC -- Yes --> D>flag]\nD ==> E((End))\n'
              "subgraph outer [Outer]\n  subgraph inner_one [Inner]\n    F\n  end\n  G\nend\nE --> F\nF --> outer\n"
              "my_node --> my_other",
    "greek": "graph LR\n  αρχή[Αρχή] --> τέλος[Τέλος]\n  subgraph ομάδα [Ομάδα]\n    τέλος\n  end",
    "links": "flowchart TD\n  a-b[Dash id] --> c_d\n  c_d --> e.f\n  A1 --o B1\n  B1 --x C1\n  C1 <--> D1\n"
             "  D1 ~~~ E1\n  click A1 callback\n  style B1 fill:#f9f\n  classDef hot fill:#f00\n  class A1 hot",
}


def test_every_flowchart_key_resolves_in_the_vendored_mermaid(tmp_path, wc_config, browser):
    names = list(FLOWCHARTS)
    res = stage.show(str(tmp_path), names[0], {"type": "inline", "format": "diagram", "body": FLOWCHARTS[names[0]]})
    for name in names[1:]:
        stage.show(str(tmp_path), name, {"type": "inline", "format": "diagram", "body": FLOWCHARTS[name]},
                   background=True)
    try:
        page = _page(browser, res["url"])
        for name in names:
            board(page, name)
            svg = page.locator(f'section.pane[data-view="{name}"] .diagram svg')
            svg.wait_for(timeout=20000)
            got = svg.evaluate("s => [...window.__stageTest.flowchartKeys(s).keys()].sort()")
            assert got == sorted(scene.flowchart_model(FLOWCHARTS[name]).keys), name
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


# -- scenes: frames applied on keyed elements ------------------------------------------------------

def _scene(model, tags, title):
    built, _ = scene.compile_scene(model, [[scene.parse_verb(t) for t in group] for group in tags], title)
    return built


def _frames(frame):
    return frame.locator("body").evaluate("() => window.__stageTest.frames()")


def _until_frame(page, view, n):
    stage_frame = next(f for f in page.frames if f is not page.main_frame)
    stage_frame.wait_for_function(f"window.__stageTest.frames()[{view!r}] === {n}", timeout=5000)
    stage_frame.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")


def test_a_code_scene_steps_its_focus_and_a_tapped_tab_opens_on_the_rest_frame(tmp_path, wc_config, browser):
    steps = _scene(scene.lines_model(range(1, 6)), [["focus 2-3"], ["focus 5"]], "Five steps")
    res = stage.show(str(tmp_path), "c", CODE5, title="Five steps", extra={"scene": steps})
    stage.show(str(tmp_path), "t", TABLE, title="Areas", background=True)
    try:
        page, frame, send = _embedded(browser, res["url"])
        code = frame.locator('section.pane[data-view="c"] .code')
        frame.locator('section.pane[data-view="c"] .ln').first.wait_for(timeout=5000)
        assert _frames(frame)["c"] == 3 and "k-dim" not in code.get_attribute("class")
        send({"type": "stage:frame", "view": "c", "n": 1, "animate": True})
        frame.locator('section.pane[data-view="c"] .code.k-dim').wait_for(timeout=3000)
        assert frame.locator(".ln.k-focus").evaluate_all("els => els.map(e => e.dataset.line)") == ["2", "3"]
        assert frame.locator('section.pane[data-view="c"] .vstep').inner_text() == "Step 1 of 2"
        send({"type": "stage:frame", "view": "c", "n": 2, "animate": True})
        _until_frame(page, "c", 2)
        assert frame.locator(".ln.k-focus").evaluate_all("els => els.map(e => e.dataset.line)") == ["5"]
        send({"type": "stage:state", "front": "c", "frames": {"c": 0}, "keys": 0})
        frame.locator('section.pane[data-view="c"] .code:not(.k-dim)').wait_for(timeout=3000)
        assert frame.locator(".ln.k-focus").count() == 0
        send({"type": "stage:frame", "view": "c", "n": 1})
        frame.locator('section.pane[data-view="c"] .code.k-dim').wait_for(timeout=3000)
        board(frame, "t")
        board(frame, "c")
        frame.locator('section.pane[data-view="c"] .code:not(.k-dim)').wait_for(timeout=3000)
        assert _frames(frame)["c"] == 3
        send({"type": "stage:frame", "view": "c", "n": 2})
        page.wait_for_timeout(300)
        assert _frames(frame)["c"] == 3
        send({"type": "stage:follow", "on": True})
        send({"type": "stage:frame", "view": "c", "n": 99})
        _until_frame(page, "c", 99)
        assert frame.locator(".ln.k-focus").count() == 0
        assert frame.locator('section.pane[data-view="c"] .vstep').inner_text() == "All shown"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_focus_below_the_fold_is_scrolled_into_view(tmp_path, wc_config, browser):
    code = {"type": "inline", "format": "code", "path": "long.py", "start": 1, "highlight": None, "lang": "python",
            "lines": [f"line_{i} = {i}" for i in range(1, 61)]}
    steps = _scene(scene.lines_model(range(1, 61)), [["focus 55-56"]], "Long")
    res = stage.show(str(tmp_path), "c", code, title="Long", extra={"scene": steps})
    try:
        page, frame, send = _embedded(browser, res["url"], height=700)
        frame.locator('section.pane[data-view="c"] .ln').first.wait_for(timeout=5000)
        send({"type": "stage:frame", "view": "c", "n": 1, "animate": True})
        _until_frame(page, "c", 1)
        stage_frame = next(f for f in page.frames if f is not page.main_frame)
        stage_frame.wait_for_function("""() => {
            const el = document.querySelector('section.pane[data-view="c"] .ln[data-line="55"]');
            const r = el.getBoundingClientRect();
            for (let box = el.parentElement; box; box = box.parentElement) {
                const b = box.getBoundingClientRect();
                if (box.scrollHeight > box.clientHeight + 1 && (r.top < b.top || r.bottom > b.bottom)) return false;
            }
            return r.top >= 0 && r.bottom <= innerHeight;
        }""", timeout=4000)
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_tapping_the_tab_already_in_front_keeps_the_frame_and_the_following(tmp_path, wc_config, browser):
    steps = _scene(scene.lines_model(range(1, 6)), [["focus 2-3"], ["focus 5"]], "Five steps")
    res = stage.show(str(tmp_path), "c", CODE5, title="Five steps", extra={"scene": steps})
    stage.show(str(tmp_path), "other", TABLE, title="Another board", background=True)  # so the list of boards shows
    try:
        page, frame, send = _embedded(browser, res["url"])
        frame.locator('section.pane[data-view="c"] .ln').first.wait_for(timeout=5000)
        send({"type": "stage:frame", "view": "c", "n": 1, "animate": True})
        _until_frame(page, "c", 1)
        board(frame, "c")
        page.wait_for_timeout(300)
        assert _frames(frame)["c"] == 1
        assert not page.evaluate("got.some(m => m.type === 'stage:follow')")
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_table_scene_grows_as_rows_are_said_and_says_its_repairs(tmp_path, wc_config, browser):
    body = "| Name | Region |\n|---|---|\n| Azure | eu |\n| AWS | us |\n| GCP | eu |\n| OVH | fr |"
    steps = _scene(scene.rows_model(["Azure", "AWS", "GCP", "OVH"]), [["+ row 1"], ["+ Azur, row 9"], ["all"]], "Clouds")
    res = stage.show(str(tmp_path), "t", {"type": "inline", "format": "table", "body": body}, title="Clouds",
                     extra={"scene": steps})
    try:
        page, frame, send = _embedded(browser, res["url"])
        table = frame.locator('section.pane[data-view="t"] table')
        table.wait_for(timeout=5000)
        full = table.bounding_box()["height"]
        meta = frame.locator('section.pane[data-view="t"] .vmeta').inner_text()
        assert meta.endswith("· 2 repairs")
        send({"type": "stage:state", "frames": {"t": 1}, "keys": 0})
        _until_frame(page, "t", 1)
        hidden = frame.locator('section.pane[data-view="t"] tbody tr.k-hidden')
        assert hidden.count() == 3 and table.bounding_box()["height"] < full / 2  # rows not said yet take no room
        assert frame.locator('section.pane[data-view="t"] tbody tr').nth(0).evaluate(
            "r => getComputedStyle(r).opacity") == "1"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_scene_shown_during_a_call_opens_on_frame_0_and_a_frame_sent_early_waits_for_it(tmp_path, wc_config,
                                                                                          browser):
    steps = _scene(scene.lines_model(range(1, 6)), [["focus 2"], ["focus 3"]], "Five steps")
    res = stage.show(str(tmp_path), "first", TABLE, title="First")
    try:
        page, frame, send = _embedded(browser, res["url"])
        frame.locator('button[role=tab][data-view="first"]').wait_for(state="attached", timeout=5000)
        send({"type": "stage:frame", "view": "early", "n": 2})
        stage.show(str(tmp_path), "fresh", CODE5, title="Fresh", extra={"scene": steps})
        frame.locator('section.pane[data-view="fresh"] .ln').first.wait_for(timeout=5000)
        assert _frames(frame)["fresh"] == 0
        assert frame.locator('section.pane[data-view="fresh"] .vstep').inner_text() == "2 steps"
        stage.show(str(tmp_path), "early", CODE5, title="Early", extra={"scene": steps})
        frame.locator('section.pane[data-view="early"] .ln').first.wait_for(timeout=5000)
        assert _frames(frame)["early"] == 2
        assert frame.locator('section.pane[data-view="early"] .ln.k-focus').evaluate_all(
            "els => els.map(e => e.dataset.line)") == ["3"]
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


WORKED_TAGS = [["+ pws"], ["+ pws->wf"], ["+ wf->engine"], ["focus pws->wf"], ["focus none"],
               ["+ legacy, pws->legacy", "focus legacy"]]


def _hidden(frame, selector):
    found = frame.locator(f'section.pane[data-view="flow"] .diagram > svg {selector}').first
    return "k-hidden" in (found.get_attribute("class") or "")


def test_a_flowchart_scene_draws_its_frames_on_the_one_layout_and_a_theme_switch_keeps_the_frame(
        tmp_path, wc_config, browser):
    body = FLOWCHARTS["example"]
    steps = _scene(scene.flowchart_model(body), WORKED_TAGS, "advisory drops :workflows")
    res = stage.show(str(tmp_path), "flow", {"type": "inline", "format": "diagram", "body": body},
                     title="advisory drops :workflows", extra={"scene": steps})
    try:
        page, frame, send = _embedded(browser, res["url"])
        frame.locator('section.pane[data-view="flow"] .diagram svg g.node').first.wait_for(timeout=20000)
        assert _frames(frame)["flow"] == 7 and not _hidden(frame, '[id*="-flowchart-legacy-"]')
        send({"type": "stage:state", "front": "flow", "frames": {"flow": 0}, "keys": 0})
        card = frame.locator('section.pane[data-view="flow"] .diagram .k-card')
        card.wait_for(timeout=3000)
        assert card.inner_text() == "advisory drops :workflows"
        assert frame.locator('section.pane[data-view="flow"] .diagram > svg .k-key:not(.k-hidden)').count() == 0
        box = frame.locator('section.pane[data-view="flow"] .diagram > svg [id*="-flowchart-wf-"]').bounding_box()
        send({"type": "stage:frame", "view": "flow", "n": 1, "animate": True})
        _until_frame(page, "flow", 1)
        assert card.count() == 0
        assert not _hidden(frame, 'g.cluster[id$="-adv"]') and not _hidden(frame, '[id*="-flowchart-pws-"]')
        assert _hidden(frame, '[id*="-flowchart-legacy-"]') and _hidden(frame, '[id*="-flowchart-wf-"]')
        send({"type": "stage:frame", "view": "flow", "n": 2, "animate": True})
        _until_frame(page, "flow", 2)
        edge = frame.locator('section.pane[data-view="flow"] .diagram > svg path[data-id="L_pws_wf_0"]')
        assert "k-hidden" not in edge.get_attribute("class") and not _hidden(frame, '[id*="-flowchart-wf-"]')
        page.wait_for_timeout(900)
        assert edge.get_attribute("marker-end") and not edge.evaluate("p => p.style.strokeDasharray")
        assert frame.locator('section.pane[data-view="flow"] .diagram > svg [id*="-flowchart-wf-"]').bounding_box() == box
        send({"type": "stage:frame", "view": "flow", "n": 3, "animate": True})
        _until_frame(page, "flow", 3)
        send({"type": "stage:frame", "view": "flow", "n": 4, "animate": True})
        _until_frame(page, "flow", 4)
        assert "k-dim" in frame.locator('section.pane[data-view="flow"] .diagram').get_attribute("class")
        assert "k-focus" in edge.get_attribute("class")
        send({"type": "stage:state", "frames": {"flow": 3}, "keys": 0})
        _until_frame(page, "flow", 3)
        send({"type": "stage:theme", "theme": "dark"})
        frame.locator("html[data-theme='dark']").wait_for(state="attached", timeout=2000)
        page.wait_for_timeout(300)
        _until_frame(page, "flow", 3)
        assert not _hidden(frame, '[id*="-flowchart-engine-"]') and _hidden(frame, '[id*="-flowchart-legacy-"]')
        assert "k-dim" not in (frame.locator('section.pane[data-view="flow"] .diagram').get_attribute("class") or "")
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_scene_on_a_diagram_that_cannot_be_drawn_leaves_the_error_card_alone(tmp_path, wc_config, browser):
    body = "graph TD; A-->B-->C-->D; B-->"
    steps = _scene(scene.flowchart_model(body), [["+ A"], ["all"]], "Bad")
    res = stage.show(str(tmp_path), "bad", {"type": "inline", "format": "diagram", "body": body}, title="Bad",
                     extra={"scene": steps})
    try:
        page, frame, send = _embedded(browser, res["url"])
        pane = frame.locator('section.pane[data-view="bad"]')
        pane.get_by_text("This diagram could not be drawn.").wait_for(timeout=20000)
        send({"type": "stage:state", "front": "bad", "frames": {"bad": 1}, "keys": 0})
        send({"type": "stage:frame", "view": "bad", "n": 2, "animate": True})
        page.wait_for_timeout(300)
        assert pane.get_by_role("button", name="Try again").is_visible()
        assert pane.locator(".k-card").count() == 0 and _frames(frame)["bad"] is None
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_markdown_and_other_text_files_show_on_the_stage_instead_of_downloading(tmp_path, wc_config, browser):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "notes.md").write_text("# Plan\n\n- one <b>bold</b>\n\n<img src=x onerror=\"window.hit=1\">\n")
    (proj / "conf.yaml").write_text("key: <value>\n")
    no_watch = patch.object(stage, "start_watch", lambda cwd, sid: None)
    no_watch.start()
    res = stage.show(str(proj), "notes", model.parse_source("notes.md", proj), title="Notes")
    stage.show(str(proj), "conf", model.parse_source("conf.yaml", proj), title="Conf", background=True)
    try:
        page = _page(browser, res["url"])
        downloads = []
        page.on("download", lambda d: downloads.append(d.suggested_filename))
        page.wait_for_selector('section.pane[data-view="notes"] .doc h1')
        assert page.inner_text('section.pane[data-view="notes"] .doc h1') == "Plan"
        assert page.evaluate("window.hit") is None
        assert page.locator('section.pane[data-view="notes"] iframe').count() == 0
        board(page, "conf")
        page.wait_for_selector('section.pane[data-view="conf"] pre.filetext')
        assert page.inner_text('section.pane[data-view="conf"] pre.filetext').strip() == "key: <value>"
        (proj / "notes.md").write_text("# Plan two\n")
        t = time.time() + 5
        os.utime(proj / "notes.md", (t, t))
        assert "notes" in stage.tick(str(proj), res["sid"])
        board(page, "notes")
        page.wait_for_function(
            "document.querySelector('section.pane[data-view=\"notes\"] .doc h1')?.textContent === 'Plan two'",
            timeout=5000)
        assert downloads == []
    finally:
        no_watch.stop()
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


# -- the shared tools on the stage ------------------------------------------------------------------

SEQ_SPEC = {"actors": [{"id": "c", "label": "Contract"}, {"id": "l", "label": "Ledger"}, {"id": "k", "label": "Core"}],
            "steps": [{"id": "s1", "from": "c", "to": "c", "arrow": "self", "label": "dev build", "sub": "2026-R1-dev-139"},
                      {"id": "s2", "from": "c", "to": "l", "arrow": "request", "label": "pins 139", "note": "13 Jan"},
                      {"id": "s3", "from": "c", "to": "k", "arrow": "request", "label": "jumps to 16", "tone": "good"}]}
FLOW_SPEC = {"nodes": [{"id": "a", "role": "entry", "label": "Turn"}, {"id": "b", "role": "decision", "label": "Free?"},
                       {"id": "c", "role": "success", "label": "Played"}],
             "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "yes"}]}


def _visual(tool, spec):
    return model.parse_source(f"{tool}:-", Path("."), json.dumps(spec))


def _all_hidden(frame, view, key):
    return frame.locator(f'section.pane[data-view="{view}"] [data-key="{key}"]').evaluate_all(
        "els => els.length > 0 && els.every(e => e.classList.contains('k-hidden'))")


def test_a_sequence_unfolds_as_lanes_with_the_step_being_said_large_and_its_own_words_on_it(tmp_path, wc_config, browser):
    steps = _scene(scene.sequence_model(SEQ_SPEC), [["next"], ["next"], ["focus s2"]], "Pins")
    res = stage.show(str(tmp_path), "seq", _visual("sequence", SEQ_SPEC), title="Pins", extra={"scene": steps})
    try:
        page, frame, send = _embedded(browser, res["url"], width=1400)
        pane = frame.locator('section.pane[data-view="seq"]')
        pane.locator(".lanes .ln-row").first.wait_for(state="attached", timeout=5000)
        row = lambda s: pane.locator(f'.ln-row[data-step="{s}"]')  # noqa: E731
        cur = lambda: pane.locator(".ln-row.ln-cur").evaluate_all("els => els.map(e => e.dataset.step)")  # noqa: E731
        send({"type": "stage:frame", "view": "seq", "n": 0})
        _until_frame(page, "seq", 0)
        assert _all_hidden(frame, "seq", "step:s1") and _all_hidden(frame, "seq", "actor:c")
        assert pane.locator(".k-card").inner_text() == "Pins"
        send({"type": "stage:frame", "view": "seq", "n": 1, "animate": True})
        _until_frame(page, "seq", 1)
        page.wait_for_timeout(200)
        assert not _all_hidden(frame, "seq", "step:s1") and not _all_hidden(frame, "seq", "actor:c")
        assert _all_hidden(frame, "seq", "step:s2") and row("s2").evaluate("e => getComputedStyle(e).display") == "none"
        assert cur() == ["s1"] and row("s1").locator(".ln-lbl b").inner_text() == "dev build"
        send({"type": "stage:frame", "view": "seq", "n": 2, "animate": True})
        _until_frame(page, "seq", 2)
        assert cur() == ["s2"]  # the newest step is the one being said
        assert row("s2").evaluate("e => parseFloat(getComputedStyle(e.querySelector('.ln-lbl b')).fontSize)") == 19
        assert row("s1").evaluate("e => parseFloat(getComputedStyle(e.querySelector('.ln-lbl b')).fontSize)") == 13.5
        send({"type": "stage:frame", "view": "seq", "n": 3})
        _until_frame(page, "seq", 3)
        lit = pane.locator(".k-focus").evaluate_all("els => els.map(e => e.tagName.toLowerCase() + ':' + e.dataset.key)")
        assert lit == ["div:step:s2"] and cur() == ["s2"]  # a pointed step is the large one
        on = pane.locator(".ln-chip.ln-on").evaluate_all("els => els.map(e => e.dataset.actor)")
        assert sorted(on) == ["c", "l"]
        assert pane.locator(".vkey, .seq-key-row").count() == 0  # the words are on the arrows: no key
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_flowchart_spec_brings_each_arrow_with_its_second_end_and_back_and_next_step_by_hand(tmp_path, wc_config, browser):
    steps = _scene(scene.flowchart_spec_model(FLOW_SPEC), [["+ a"], ["+ b"], ["+ c"]], "Floor")
    res = stage.show(str(tmp_path), "flow", _visual("flowchart", FLOW_SPEC), title="Floor", extra={"scene": steps})
    try:
        page, frame, send = _embedded(browser, res["url"])
        frame.locator('section.pane[data-view="flow"] .map .m-node').first.wait_for(state="attached", timeout=5000)
        send({"type": "stage:frame", "view": "flow", "n": 1})
        _until_frame(page, "flow", 1)
        assert _all_hidden(frame, "flow", "edge:a->b#0") and not _all_hidden(frame, "flow", "node:a")
        # not said yet is a ghost on the map: there, faint and dashed, not gone
        ghost = frame.locator('section.pane[data-view="flow"] .m-node[data-key="node:b"]')
        assert float(ghost.evaluate("e => getComputedStyle(e).opacity")) > 0.1
        assert ghost.evaluate("e => getComputedStyle(e).borderTopStyle") == "dashed"
        assert frame.locator('section.pane[data-view="flow"] .m-node.m-cur').get_attribute("data-key") == "node:a"
        send({"type": "stage:frame", "view": "flow", "n": 2})
        _until_frame(page, "flow", 2)
        assert not _all_hidden(frame, "flow", "edge:a->b#0") and _all_hidden(frame, "flow", "edge:b->c#0")
        assert frame.locator('section.pane[data-view="flow"] .vstep').inner_text() == "Step 2 of 3"
        frame.locator('section.pane[data-view="flow"] .stepnext').click()
        _until_frame(page, "flow", 3)
        assert not _all_hidden(frame, "flow", "edge:b->c#0")
        page.wait_for_function("got.some(m => m.type === 'stage:follow' && m.on === false)", timeout=3000)
        frame.locator('section.pane[data-view="flow"] .stepback').click()
        _until_frame(page, "flow", 2)
        send({"type": "stage:frame", "view": "flow", "n": 1})
        page.wait_for_timeout(300)
        assert _frames(frame)["flow"] == 2, "stepping by hand stops the voice moving the frame"
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_map_fits_its_board_and_draws_in_the_stages_own_fonts_with_no_network(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "flow", _visual("flowchart", FLOW_SPEC), title="Floor")
    try:
        page = _page(browser, res["url"])
        hosts = []
        page.on("request", lambda r: hosts.append(r.url.split("/")[2]))
        page.reload()
        node = page.locator('section.pane[data-view="flow"] .m-node').first
        node.wait_for(timeout=5000)
        page.wait_for_function("document.fonts.check('12px \"Geist Mono\"') && document.fonts.check('12px Geist')",
                               timeout=5000)
        assert set(hosts) == {res["url"].split("/")[2]}, hosts
        board_box = page.locator('section.pane[data-view="flow"] .map').bounding_box()
        for b in page.locator('section.pane[data-view="flow"] .m-node').evaluate_all("els => els.map(e => e.getBoundingClientRect().toJSON())"):
            assert board_box["x"] - 1 <= b["x"] and b["x"] + b["width"] <= board_box["x"] + board_box["width"] + 1
        assert page.locator("button", has_text="Actual size").count() == 0  # a map always fits: no size buttons
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_every_arrow_on_every_map_draws_its_own_head(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "one", _visual("flowchart", FLOW_SPEC), title="One")
    stage.show(str(tmp_path), "two", _visual("flowchart", FLOW_SPEC), title="Two")
    try:
        page = _page(browser, res["url"])
        for name in ("one", "two"):
            board(page, name)
            page.locator(f'section.pane[data-view="{name}"] .m-edge').first.wait_for(timeout=5000)
            heads = page.locator(f'section.pane[data-view="{name}"] .m-edge').evaluate_all(
                "els => els.map(g => [g.querySelector('.m-tip').getAttribute('d') || '', getComputedStyle(g.querySelector('.m-tip')).fill])")
            assert len(heads) == 2 and all(d.startswith("M ") and fill not in ("none", "rgba(0, 0, 0, 0)") for d, fill in heads), heads
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_a_markdown_documents_links_open_apart_and_its_images_resolve_beside_it(tmp_path, wc_config, browser):
    proj = tmp_path / "proj"
    (proj / "docs").mkdir(parents=True)
    (proj / "docs" / "guide.md").write_text("# Guide\n\n[out](https://example.com) [down](#install) ![pic](pic.svg)\n\n"
                                            + "filler\n\n" * 80 + "## Install\n\nhere\n")
    (proj / "docs" / "pic.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
    no_watch = patch.object(stage, "start_watch", lambda cwd, sid: None)
    no_watch.start()
    res = stage.show(str(proj), "g", model.parse_source("docs/guide.md#install", proj), title="Guide")
    try:
        page = _page(browser, res["url"])
        page.wait_for_selector('section.pane[data-view="g"] .doc h2')
        out = page.locator('section.pane[data-view="g"] a', has_text="out")
        assert (out.get_attribute("target"), out.get_attribute("rel")) == ("_blank", "noopener")
        page.wait_for_function("document.querySelector('section.pane[data-view=\"g\"] img').naturalWidth > 0", timeout=5000)
        page.wait_for_function("document.querySelector('section.pane[data-view=\"g\"] .doc').scrollTop > 0", timeout=5000)
    finally:
        no_watch.stop()
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


def test_in_a_call_space_and_the_arrows_go_to_the_call_page_unless_a_control_has_them(tmp_path, wc_config, browser):
    res = stage.show(str(tmp_path), "c", CODE5, title="Five lines")
    try:
        page, frame, _ = _embedded(browser, res["url"])
        frame.locator('section.pane[data-view="c"] .ln').first.wait_for(timeout=5000)
        frame.locator(".pbody").first.click()
        for key in ("Space", "ArrowLeft", "ArrowRight"):
            page.keyboard.press(key)
        keys = lambda: page.evaluate("got.filter(m => m.type === 'stage:key').map(m => m.key)")  # noqa: E731
        page.wait_for_function("got.filter(m => m.type === 'stage:key').length === 3", timeout=2000)
        assert keys() == [" ", "ArrowLeft", "ArrowRight"]
        # A focused button takes its own Space.
        frame.get_by_role("button", name="Copy").focus()
        page.keyboard.press("Space")
        page.wait_for_timeout(200)
        assert len(keys()) == 3
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])


ENGINES = {"type": "inline", "format": "table", "body": "| | Azure | VoiceStudio |\n|---|---|---|\n"
           "| Speed | a second or two per answer | about as long to make as to play |\n| Cost | billed per character | free |\n"
           "| Needs | `TALK_AZURE_KEY_COMMAND` | the VoiceStudio app open |"}


def test_a_table_board_grows_the_row_being_said_and_spots_a_cell(tmp_path, wc_config, browser):
    model = scene.rows_model(["Speed", "Cost", "Needs"], ["", "Azure", "VoiceStudio"])
    steps = _scene(model, [["next"], ["focus cell Speed / Azure"], ["next"]], "Engines")
    res = stage.show(str(tmp_path), "t", ENGINES, title="Engines", extra={"scene": steps})
    try:
        page, frame, send = _embedded(browser, res["url"], width=1300)
        pane = frame.locator('section.pane[data-view="t"]')
        pane.locator("tbody tr").first.wait_for(state="attached", timeout=5000)
        size = lambda sel: pane.locator(sel).evaluate("e => parseFloat(getComputedStyle(e).fontSize)")  # noqa: E731
        send({"type": "stage:frame", "view": "t", "n": 1, "animate": True})
        _until_frame(page, "t", 1)
        page.wait_for_timeout(450)  # rows grow over .35 s
        assert pane.locator("tbody tr:visible").count() == 1 and size('tr[data-key="row#1"] td:nth-child(2)') == 21
        send({"type": "stage:frame", "view": "t", "n": 2})
        _until_frame(page, "t", 2)
        page.wait_for_timeout(450)  # rows grow over .35 s
        assert pane.locator("td.k-focus").evaluate_all("els => els.map(e => e.dataset.key)") == ["cell#1.2"]
        spot = pane.locator("td.k-focus").evaluate("e => getComputedStyle(e).backgroundColor")
        band = pane.locator('tr[data-key="row#1"] td:nth-child(3)').evaluate("e => getComputedStyle(e).backgroundColor")
        assert spot != band  # the cell stands out from its row
        assert size('tr[data-key="row#1"] td:nth-child(2)') == 21  # the pointed cell's row is the one being said
        send({"type": "stage:frame", "view": "t", "n": 3, "animate": True})
        _until_frame(page, "t", 3)
        page.wait_for_timeout(450)
        assert size('tr[data-key="row#2"] td:nth-child(2)') == 21 and size('tr[data-key="row#1"] td:nth-child(2)') == 15  # the new row is said
        wrap, board = pane.locator(".tablewrap").bounding_box(), pane.locator(".pbody").bounding_box()
        assert wrap["width"] > board["width"] - 60  # the grid spans the stage
    finally:
        wc_config.call("DELETE", "/s/%s/?kind=stage&force=1" % res["sid"])
