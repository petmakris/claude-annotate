"""The call page in a real browser, against a served call with a fake VoiceStudio and a fake microphone."""
import asyncio
import threading
from contextlib import contextmanager
from unittest.mock import patch

import pytest

pytest.importorskip("playwright", reason="browser suite: add --with playwright")

from helpers import CALL, TOKEN, FakeSpeech, make_args, talk  # noqa: E402

FAKE_MIC = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            "--autoplay-policy=no-user-gesture-required"]
PLAYING = "!document.getElementById('audio').paused"
PAUSED = "document.getElementById('audio').paused"
STAGE = "http://stage.test/s/abc/"
STAGE_PROBE = ("<body style='margin:0;background:#cde'><script>window.got = [];"
               "addEventListener('message', e => got.push(e.data));"
               "parent.postMessage({type: 'stage:ready'}, '*')</script>the stage</body>")


@contextmanager
def served(tmp_path, stage_url=None):
    """A call served on a loop in its own thread. Yields (url, call, loop, fake)."""
    from aiohttp import web

    fake = FakeSpeech()
    loop = asyncio.new_event_loop()
    box = {}
    ready = threading.Event()

    async def start():
        box["server"] = talk.Server("server-token")
        box["call"] = box["server"].add(talk.Call(make_args(), "Browser topic", tmp_path / "out"),
                                        call_id=CALL, token=TOKEN, stage_url=stage_url)
        box["runner"] = web.AppRunner(talk.build_app(box["server"]))
        await box["runner"].setup()
        site = web.TCPSite(box["runner"], "127.0.0.1", 0)
        await site.start()
        box["port"] = site._server.sockets[0].getsockname()[1]
        ready.set()

    thread = threading.Thread(target=loop.run_forever, daemon=True)
    with patch.object(talk.speech, "transcribe", fake.transcribe), patch.object(talk.speech, "speak", fake.speak):
        thread.start()
        asyncio.run_coroutine_threadsafe(start(), loop)
        assert ready.wait(10)
        try:
            yield f"http://127.0.0.1:{box['port']}/c/{CALL}", box["call"], loop, fake
        finally:
            asyncio.run_coroutine_threadsafe(box["runner"].cleanup(), loop).result(10)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(10)


def on_loop(loop, coro):
    return asyncio.run_coroutine_threadsafe(coro, loop).result(10)


async def add_entry(call, who, text):
    call.add(who, text)


READY = "<script>parent.postMessage({type: 'stage:ready'}, '*')</script>"


def stage_page(page, body="<body style='margin:0;background:#cde'>the stage" + READY + "</body>"):
    """Serve the dummy stage URL as a page that says it is ready, as the real stage does."""
    page.route(STAGE, lambda route: route.fulfill(content_type="text/html", body=body))


def open_gear(page):
    if page.is_hidden("#pGear"):
        page.click("#gear")
    page.wait_for_selector("#pGear")


def no_autoplay(page):
    page.add_init_script("localStorage.setItem('talk.autoplay', 'false')")


def test_speak_send_hear_the_answer_and_steer_the_player(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            fake.heard = "explain the doorbell"
            page.click("#talk")
            page.wait_for_selector("#app[data-state='listening']")
            assert page.is_visible("#send") and page.is_visible("#cancel") and page.is_hidden("#hist")
            page.wait_for_timeout(600)
            page.click("#send")
            page.wait_for_selector("#asked:has-text('explain the doorbell')")

            turn = on_loop(loop, call.turns.next(timeout=2))
            call.collected()  # as /api/turn does when the doorbell takes the turn
            assert turn["said"] == [{"who": "you", "text": "explain the doorbell"}]
            page.wait_for_selector("#status:has-text('Claude is working…')")
            assert page.get_attribute("#app", "data-state") == "working"
            on_loop(loop, call.answer("The doorbell waits for your turn."))
            call.turns.accept_reply(turn["id"])

            page.wait_for_function(PLAYING, timeout=5000)
            page.wait_for_selector("#app[data-state='speaking']")
            assert page.inner_text("#cap") == "The doorbell waits for your turn."
            open_gear(page)
            page.click("#speeds button[data-speed='1.25']")
            assert page.evaluate("document.getElementById('audio').playbackRate") == 1.25
            page.keyboard.press("Escape")
            assert page.is_hidden("#pGear")
            page.click("#playpause")
            assert page.evaluate(PAUSED)
            page.evaluate("document.getElementById('audio').currentTime = 0.8")
            page.click("#back")
            assert page.evaluate("document.getElementById('audio').currentTime") == 0
            open_gear(page)
            page.click("#autoplay")
            assert page.get_attribute("#autoplay", "aria-pressed") == "false"

            page.fill("#text", "and then?")
            page.press("#text", "Enter")
            page.wait_for_selector("#asked:has-text('and then?')")
            assert page.input_value("#text") == "" and page.is_disabled("#sendtext")
            page.click("#hist")
            assert page.locator("#convo .turn.you .who").last.inner_text().lower().endswith("typed")
        finally:
            browser.close()


def test_the_speed_and_language_are_kept_per_viewer(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            open_gear(page)
            page.click("#lang button[data-lang='el']")
            page.click("#talk")
            page.wait_for_selector("#app[data-state='listening']")
            page.click("#send")
            page.wait_for_function("busy === false && recorder === null")
            assert fake.languages == ["el"]
            open_gear(page)
            page.click("#speeds button[data-speed='1.25']")
            page.reload()
            assert page.get_attribute("#lang button[data-lang='el']", "aria-pressed") == "true"
            assert page.get_attribute("#speeds button[data-speed='1.25']", "aria-pressed") == "true"
        finally:
            browser.close()


def test_nothing_heard_says_so_and_cancel_sends_nothing(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            page.click("#talk")
            page.wait_for_selector("#app[data-state='listening']")
            page.click("#cancel")
            page.wait_for_selector("#app[data-state='idle']")
            assert fake.languages == []
            fake.heard = ""
            page.click("#talk")
            page.wait_for_selector("#app[data-state='listening']")
            page.click("#send")
            page.wait_for_selector("#toast:has-text('Nothing was heard')")
            assert call.entries == []
        finally:
            browser.close()


def test_an_ended_call_disables_talking_and_keeps_replay(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            no_autoplay(page)
            page.goto(url)
            on_loop(loop, call.answer("One last thing."))
            page.wait_for_selector("#playpause")
            open_gear(page)
            assert page.inner_text("#endlbl") == "End call"
            page.click("#end")
            page.wait_for_selector("#status:has-text('The call has ended')")
            assert page.is_hidden("#talk") and page.is_hidden("#text")
            assert page.get_attribute("#app", "data-ended") is not None
            assert page.inner_text("#endlbl") == "Close"
            page.click("#playpause")
            page.wait_for_function(PLAYING, timeout=5000)
        finally:
            browser.close()


def test_an_answer_shows_a_progress_bar_until_its_whole_audio_is_ready(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.hold = threading.Semaphore(0)
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            on_loop(loop, call.answer("First sentence alone. " + " ".join(f"Then part {i} follows." for i in range(30))))
            page.wait_for_selector("#prep", state="visible", timeout=5000)
            page.wait_for_function("document.getElementById('preplbl').textContent.startsWith('Preparing the voice')",
                                   timeout=5000)
            page.wait_for_function("parseFloat(document.getElementById('prepfill').style.width) > 0", timeout=5000)
            assert page.is_hidden("#playpause")
            # A second answer waits behind the first: its bar says so until the voice gets to it.
            on_loop(loop, call.answer("And a second answer."))
            page.wait_for_function("document.getElementById('preplbl').textContent === 'Waiting for the voice…'",
                                   timeout=5000)
            fake.hold.release()
            fake.hold.release()
            page.wait_for_function(PLAYING, timeout=5000)
            page.wait_for_selector("#prep", state="hidden", timeout=5000)
            assert page.evaluate("document.getElementById('audio').src").endswith(".wav")
        finally:
            fake.hold = None
            browser.close()


def test_the_word_being_said_is_highlighted_and_a_tap_plays_from_a_word(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            on_loop(loop, call.answer(" ".join(f"word{i}" for i in range(60)) + "."))
            page.wait_for_selector("#cap .w.now-word", timeout=5000)
            first = int(page.get_attribute("#cap .w.now-word", "data-i"))
            page.wait_for_function(f"Number(document.querySelector('#cap .w.now-word')?.dataset.i) > {first + 20}",
                                   timeout=8000)
            assert page.locator("#cap .w.said").count() >= 20
            # The word being said stays inside the caption's visible box, though the answer is longer.
            inside = """() => { const c = document.getElementById('cap').getBoundingClientRect(),
                                     w = document.querySelector('#cap .now-word').getBoundingClientRect();
                                return w.top >= c.top - 1 && w.bottom <= c.bottom + 1; }"""
            # A word that starts a new line is scrolled to smoothly, so it is in view once that scroll settles.
            page.wait_for_function(inside, timeout=1000)
            page.click("#playpause")  # pause
            word = page.locator("#cap .w.now-word")
            target = int(word.get_attribute("data-i")) - 2
            page.click(f"#cap .w[data-i='{target}']")
            page.wait_for_function(f"Number(document.querySelector('#cap .w.now-word')?.dataset.i) >= {target}",
                                   timeout=5000)
        finally:
            browser.close()


def test_the_theme_starts_light_is_kept_and_auto_follows_the_system(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        page.emulate_media(color_scheme="dark")
        page.goto(url)
        bg = "getComputedStyle(document.body).backgroundColor"
        assert page.get_attribute("html", "data-theme") == "light"
        assert page.evaluate(bg) == "rgb(233, 237, 242)"
        open_gear(page)
        page.click("#theme button[data-choice='dark']")
        assert page.get_attribute("html", "data-theme") == "dark"
        assert page.evaluate(bg) == "rgb(6, 8, 12)"
        page.reload()
        assert page.get_attribute("html", "data-theme") == "dark"
        open_gear(page)
        assert page.get_attribute("#theme button[data-choice='dark']", "aria-pressed") == "true"
        page.click("#theme button[data-choice='system']")
        assert page.get_attribute("html", "data-theme") == "dark"
        page.emulate_media(color_scheme="light")
        page.wait_for_function("document.documentElement.dataset.theme === 'light'", timeout=2000)


def test_the_theme_and_the_follow_switch_reach_the_stage(tmp_path, browser):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        page = browser.new_page()
        stage_page(page, STAGE_PROBE)
        page.goto(url)
        page.wait_for_function("stageUp === true", timeout=5000)
        stage = page.frame(url=STAGE)
        stage.wait_for_function("got.some(m => m.type === 'stage:theme' && m.theme === 'light')", timeout=2000)
        open_gear(page)
        page.click("#theme button[data-choice='dark']")
        stage.wait_for_function("got.some(m => m.type === 'stage:theme' && m.theme === 'dark')", timeout=2000)
        assert page.get_attribute("#follow", "aria-pressed") == "true"
        page.click("#follow")
        stage.wait_for_function("got.some(m => m.type === 'stage:follow' && m.on === false)", timeout=2000)
        assert page.get_attribute("#follow", "aria-pressed") == "false"
        # The stage turns following back on by itself (a new answer); the switch shows it.
        stage.evaluate("parent.postMessage({type: 'stage:follow', on: true}, '*')")
        page.wait_for_selector("#follow[aria-pressed='true']")


def test_the_page_state_follows_talking_working_and_speaking(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            assert page.get_attribute("#app", "data-state") == "idle"
            height = lambda: round(page.locator(".frame").bounding_box()["height"])
            idle = height()
            page.click("#talk")
            page.wait_for_selector("#app[data-state='listening']")
            assert page.is_visible("#wave") and page.locator("#bars i").count() == 28
            assert height() == idle  # the stage never moves as the line under it changes
            assert page.is_hidden("#cap")
            page.click("#talk")  # pressing the mic again sends
            turn = on_loop(loop, call.turns.next(timeout=2))
            call.collected()  # as /api/turn does when the doorbell takes the turn
            page.wait_for_selector("#status:has-text('Claude is working…')")
            assert page.get_attribute("#app", "data-state") == "working" and page.is_hidden("#cap")
            on_loop(loop, call.answer("Now I speak, and at some length: " + " ".join(f"word{i}" for i in range(60)) + "."))
            call.turns.accept_reply(turn["id"])
            page.wait_for_selector("#app[data-state='speaking']", timeout=5000)
            assert height() == idle
            page.click("#playpause")
            page.wait_for_selector("#app[data-state='idle']")
        finally:
            browser.close()


def test_one_layer_opens_at_a_time_and_escape_or_a_click_outside_closes_it(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url)
        page.click("#gear")
        assert page.is_visible("#pGear") and page.get_attribute("#gear", "aria-expanded") == "true"
        page.click("#hist")
        assert page.is_hidden("#pGear") and page.is_visible("#pHist")
        page.keyboard.press("Escape")
        assert page.is_hidden("#pHist")
        page.click("#gear")
        page.click("#text")
        assert page.is_hidden("#pGear") and page.evaluate("document.activeElement.id") == "text"


def test_the_conversation_sheet_lists_every_entry_and_replays_an_old_answer(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        no_autoplay(page)
        page.goto(url)
        on_loop(loop, add_entry(call, "you", "first question"))
        on_loop(loop, call.answer("First answer."))
        on_loop(loop, call.answer("Second answer."))
        page.wait_for_selector("#cap:has-text('Second answer.')")
        page.click("#hist")
        assert page.locator("#convo .turn .text").all_inner_texts() == ["first question", "First answer.", "Second answer."]
        assert page.locator("#convo .turn.claude .who small").all_inner_texts() == ["answer 1", "answer 2"]
        page.locator("#convo .turn.claude button.play").first.click()
        page.wait_for_function(PLAYING, timeout=5000)
        assert page.inner_text("#cap") == "First answer."


def test_before_any_answer_the_text_field_invites_you_to_type_or_talk(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url)
        assert page.get_attribute("#text", "placeholder") == "Type to Claude, or press the mic to talk"
        assert page.is_hidden("#subs") and page.is_visible("#talk") and page.is_disabled("#sendtext")
        for sel in ("#playpause", "#back", "#seek", "#callsbtn", "#asked"):
            assert page.is_hidden(sel), sel
        assert page.inner_text("#topic") == "Browser topic"


def test_a_phone_shows_stage_subtitles_and_controls_without_sideways_scroll(tmp_path, browser):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        page = browser.new_page(viewport={"width": 390, "height": 844})
        stage_page(page)
        page.goto(url)
        on_loop(loop, call.answer("A first answer that is long enough to wrap onto a few lines on a phone, and then some."))
        page.wait_for_selector("#playpause")
        page.click("#gear")
        assert page.evaluate("document.documentElement.scrollWidth") <= 390
        for sel in ("#stage", "#cap", "#talk", "#gear", "#pGear"):
            box = page.locator(sel).bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["y"] + box["height"] <= 844, sel
        assert page.is_hidden(".left")


def test_a_new_entry_leaves_the_earlier_ones_untouched(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        no_autoplay(page)
        page.goto(url)
        for text in ("One answer here.", "Two answers here.", "Three answers here."):
            on_loop(loop, call.answer(text))
        page.click("#hist")
        page.wait_for_function("document.querySelectorAll('#convo .turn.claude button.play').length === 3", timeout=10000)
        page.evaluate("document.querySelector('#convo .turn.claude').dataset.probe = 'kept'")
        page.evaluate("""() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('#convo .turn.claude .text'));
                                getSelection().removeAllRanges(); getSelection().addRange(r); }""")
        on_loop(loop, call.answer("Four answers here."))
        page.wait_for_function("document.querySelectorAll('#convo .turn.claude').length === 4")
        assert page.evaluate("document.querySelector('#convo .turn.claude').dataset.probe") == "kept"
        assert page.evaluate("getSelection().toString()").startswith("One")


def test_a_lost_connection_says_so_and_retry_recovers(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector("#talk")
        page.route("**/api/state*", lambda route: route.abort())
        page.wait_for_selector("#toast:has-text('Reconnecting to the call')", timeout=4000)
        assert page.is_visible("#retry")
        page.unroute("**/api/state*")
        page.click("#retry")
        page.wait_for_selector("#toast:has-text('Reconnected.')", timeout=2000)
        assert not page.is_visible("#retry")
        page.wait_for_selector("#toast", state="hidden", timeout=6000)


def test_a_server_restarting_shows_reconnecting_not_ended(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        page.goto(url)
        page.wait_for_selector("#talk")
        page.route("**/api/state*", lambda route: route.fulfill(
            status=503, content_type="application/json", body='{"error": "the talk server is restarting"}'))
        page.wait_for_selector("#toast:has-text('Reconnecting to the call')", timeout=4000)
        assert page.get_attribute("#app", "data-ended") is None
        page.unroute("**/api/state*")
        page.wait_for_selector("#toast:has-text('Reconnected.')", timeout=8000)
        assert page.get_attribute("#app", "data-ended") is None


def test_a_stage_that_does_not_load_offers_reload_and_a_new_tab(tmp_path, browser):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.add_init_script("window.__stageTimeoutMs = 500")
        requests = []  # the first request never answers; a reload's is served

        def stage(route):
            requests.append(route)
            if len(requests) > 1:
                route.fulfill(content_type="text/html", body="<body>the stage" + READY + "</body>")
        page.route(STAGE, stage)
        page.goto(url, wait_until="domcontentloaded")  # the page's own load waits on the stalled stage
        assert page.is_visible("text=Loading the stage")
        page.wait_for_selector("text=The stage did not load.")
        assert page.is_visible("#reloadstage") and page.get_attribute("#openstage", "href") == STAGE
        page.click("#reloadstage")
        page.wait_for_selector("#veil", state="hidden")


def test_a_stage_that_loads_again_gets_the_theme_and_the_follow_state_again(tmp_path, browser):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('talk.theme', JSON.stringify('dark'))")
        stage_page(page, STAGE_PROBE)
        page.goto(url)
        page.wait_for_function("stageUp === true", timeout=5000)
        open_gear(page)
        page.click("#follow")
        page.frame(url=STAGE).wait_for_function("got.some(m => m.type === 'stage:follow' && m.on === false)", timeout=2000)
        # The stage page loads again (a daemon restart): it starts from nothing.
        page.evaluate("document.getElementById('stage').src = document.getElementById('stage').src")
        page.wait_for_timeout(500)
        stage = page.frame(url=STAGE)
        stage.wait_for_function("got.some(m => m.type === 'stage:theme' && m.theme === 'dark')", timeout=3000)
        stage.wait_for_function("got.some(m => m.type === 'stage:follow' && m.on === false)", timeout=3000)


def test_a_click_on_the_stage_or_another_button_closes_an_open_layer(tmp_path, browser):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        no_autoplay(page)
        stage_page(page)
        page.goto(url)
        page.wait_for_selector("#veil", state="hidden")
        page.click("#gear")
        assert page.is_visible("#pGear")
        box = page.locator("#stage").bounding_box()
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)  # into the stage's own page
        page.wait_for_selector("#pGear", state="hidden", timeout=2000)
        on_loop(loop, call.answer("Something to play."))
        page.wait_for_selector("#playpause")
        page.click("#hist")
        assert page.is_visible("#pHist")
        page.click("#playpause")
        assert page.is_hidden("#pHist")


def test_the_page_names_the_speech_engine(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        page.goto(url)
        assert page.inner_text("#engine") == "VoiceStudio"
        assert "VoiceStudio on this Mac" in page.get_attribute("#engine", "title")


def six(name):
    return " ".join(f"{name}{i}" for i in range(6))


def test_frames_follow_the_voice_and_every_jump_sends_the_whole_state(tmp_path, pw):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        fake.seconds = 6.0
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            stage_page(page, STAGE_PROBE)
            page.goto(url)
            page.wait_for_function("stageUp === true", timeout=5000)
            stage = page.frame(url=STAGE)
            on_loop(loop, call.answer(f"[[show diagram | Flow]]graph TD; P[Page]-->Q[Queue]-->R[Reply][[/show]] "
                                      f"{six('lead')} [[+ P]] {six('page')} [[+ P->Q]] {six('queue')} "
                                      f"[[+ Q->R]] {six('reply')}."))
            stage.wait_for_function("got.some(m => m.type === 'stage:frame' && m.n === 3)", timeout=15000)
            sent = stage.evaluate("got.filter(m => m.type === 'stage:state' || m.type === 'stage:frame')")
            assert sent[0] == {"type": "stage:state", "front": "flow", "frames": {"flow": 0}, "keys": 0}
            assert [(m["n"], m["animate"]) for m in sent[1:]] == [(1, True), (2, True), (3, True)]
            page.wait_for_function("document.getElementById('audio').ended", timeout=10000)
            stage.evaluate("got.length = 0")
            page.click("#playpause")
            stage.wait_for_function("got.some(m => m.type === 'stage:state')", timeout=5000)
            assert stage.evaluate("got.find(m => m.type === 'stage:state').frames") == {"flow": 0}
            page.click("#playpause")
            stage.evaluate("got.length = 0")
            page.click("#cap .w[data-i='14']")
            stage.wait_for_function("got.some(m => m.type === 'stage:state')", timeout=5000)
            assert stage.evaluate("got.find(m => m.type === 'stage:state').frames") == {"flow": 2}
            open_gear(page)
            page.click("#follow")
            stage.evaluate("got.length = 0")
            page.click("#follow")
            stage.wait_for_function("got.some(m => m.type === 'stage:state')", timeout=5000)
            page.click("#gear")
            page.click("#playpause")
            stage.evaluate("got.length = 0")
            page.click("#back")
            stage.wait_for_function("got.some(m => m.type === 'stage:state')", timeout=5000)
            assert stage.evaluate("got.find(m => m.type === 'stage:state').frames") == {"flow": 0}
        finally:
            browser.close()


def test_an_answer_that_could_not_be_read_aloud_puts_its_scenes_on_their_last_frame(tmp_path, browser):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        fake.fail = "the voice is down"
        page = browser.new_page()
        stage_page(page, STAGE_PROBE)
        page.goto(url)
        page.wait_for_function("stageUp === true", timeout=5000)
        stage = page.frame(url=STAGE)
        on_loop(loop, call.answer("[[show diagram | Flow]]graph TD; P[Page]-->Q[Queue][[/show]] First. [[+ P]] "
                                  "The page. [[+ P->Q]] The queue."))
        stage.wait_for_function("got.some(m => m.type === 'stage:state')", timeout=10000)
        assert stage.evaluate("got.find(m => m.type === 'stage:state').frames") == {"flow": 2}


def test_a_key_point_lights_once_even_when_the_view_changes_during_the_answer(tmp_path, pw):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        fake.seconds = 8.0
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            stage_page(page, STAGE_PROBE)
            page.goto(url)
            page.wait_for_function("stageUp === true", timeout=5000)
            stage = page.frame(url=STAGE)
            on_loop(loop, call.answer(f"{six('lead')} [[key: the first point]] {six('middle')} {six('tail')}."))
            stage.wait_for_function("got.some(m => m.type === 'stage:key')", timeout=15000)
            on_loop(loop, add_entry(call, "system", "Something else happened."))
            page.wait_for_function("view.entries.some(e => e.text === 'Something else happened.')", timeout=5000)
            page.wait_for_timeout(600)
            assert stage.evaluate("got.filter(m => m.type === 'stage:key').length") == 1
        finally:
            browser.close()


def test_a_stage_that_reloads_before_an_unheard_answer_plays_gets_its_first_frame(tmp_path, pw):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        fake.seconds = 6.0
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            no_autoplay(page)
            stage_page(page, STAGE_PROBE)
            page.goto(url)
            page.wait_for_function("stageUp === true", timeout=5000)
            stage = page.frame(url=STAGE)
            on_loop(loop, call.answer(f"[[show diagram | Flow]]graph TD; P[Page]-->Q[Queue]-->R[Reply][[/show]] "
                                      f"{six('lead')} [[+ P]] {six('page')} [[+ P->Q]] {six('queue')}."))
            page.wait_for_function("current && current.speech === 'ready'", timeout=15000)
            assert page.evaluate("document.getElementById('audio').currentTime") == 0
            stage.evaluate("got.length = 0; parent.postMessage({type: 'stage:ready'}, '*')")
            stage.wait_for_function("got.some(m => m.type === 'stage:state')", timeout=5000)
            assert stage.evaluate("got.find(m => m.type === 'stage:state').frames") == {"flow": 0}
        finally:
            browser.close()


def test_the_subtitles_hide_and_come_back_and_stay_hidden_across_a_reload(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        no_autoplay(page)
        page.goto(url)
        on_loop(loop, call.answer("An answer to hide."))
        page.wait_for_selector("#cap:has-text('An answer to hide.')")
        assert page.is_hidden("#subsbtn")
        page.click("#subsx")
        assert page.is_hidden("#subs") and page.is_visible("#subsbtn")
        page.reload()
        page.wait_for_selector("#playpause")
        assert page.is_hidden("#subs") and page.is_visible("#subsbtn")
        page.click("#subsbtn")
        assert page.inner_text("#cap") == "An answer to hide." and page.is_hidden("#subsbtn")


def test_a_hidden_answer_still_shows_what_claude_is_doing(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        no_autoplay(page)
        page.goto(url)
        on_loop(loop, call.answer("First."))
        page.wait_for_selector("#cap:has-text('First.')")
        page.click("#subsx")
        page.fill("#text", "go on")
        page.press("#text", "Enter")
        on_loop(loop, call.turns.next(timeout=2))
        call.collected()
        page.wait_for_selector("#status:has-text('Claude is working…')")
        assert page.is_visible("#subs") and page.is_hidden("#cap") and page.is_hidden("#subsx")


def test_a_key_typed_with_nothing_focused_goes_to_the_text_field(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        page.goto(url)
        page.evaluate("document.activeElement.blur()")
        page.keyboard.type("hi there")
        assert page.evaluate("document.activeElement.id") == "text" and page.input_value("#text") == "hi there"
        assert page.is_enabled("#sendtext")


def test_space_pauses_and_plays_and_the_arrows_move_a_sentence(tmp_path, pw):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        fake.seconds = 9.0  # three sentences of three words: they start at 0, 3 and 6 s
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            stage_page(page, STAGE_PROBE)
            page.goto(url)
            on_loop(loop, call.answer("One two three. Four five six. Seven eight nine."))
            page.wait_for_function(PLAYING, timeout=5000)
            assert page.evaluate("document.activeElement.id") == "text"  # empty: the keys still steer the answer
            page.keyboard.press("Space")
            page.wait_for_function(PAUSED)
            assert page.input_value("#text") == ""
            at = lambda: round(page.evaluate("document.getElementById('audio').currentTime"), 2)  # noqa: E731
            page.evaluate("document.getElementById('audio').currentTime = 4.5")
            page.keyboard.press("ArrowLeft")
            assert at() == 3.0  # the start of the sentence being said
            page.keyboard.press("ArrowLeft")
            assert at() == 0.0  # pressed again at its start: the sentence before
            page.keyboard.press("ArrowRight")
            assert at() == 3.0
            page.keyboard.press("ArrowRight")
            assert at() == 6.0 and page.evaluate(PAUSED)
            page.keyboard.press("Space")
            page.wait_for_function(PLAYING)
            # The stage passes the keys on when they are pressed there.
            page.frame(url=STAGE).evaluate("parent.postMessage({type: 'stage:key', key: ' '}, '*')")
            page.wait_for_function(PAUSED)
            # Typing is typing: with words in the field, Space is a space.
            page.fill("#text", "so")
            page.press("#text", "Space")
            assert page.input_value("#text") == "so " and page.evaluate(PAUSED)
        finally:
            browser.close()


def test_space_with_no_answer_yet_goes_to_the_text_field(tmp_path, browser):
    with served(tmp_path) as (url, call, loop, fake):
        page = browser.new_page()
        page.goto(url)
        page.evaluate("document.activeElement.blur()")
        page.keyboard.type(" hi")
        assert page.input_value("#text") == " hi"


def _mic_file(path, before=3.0, speech=1.0, after=3.0, rate=48000):
    """A WAV Chrome plays as the microphone, over and over: silence, a second of loud noise standing in
    for speech, silence."""
    import random
    import struct
    import wave
    rnd = random.Random(1)
    frames = [0] * int(before * rate) + [int(rnd.uniform(-0.35, 0.35) * 32767) for _ in range(int(speech * rate))] + [0] * int(after * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
    return str(path)


def _live_browser(pw, tmp_path):
    return pw.chromium.launch(args=[*FAKE_MIC, f"--use-file-for-fake-audio-capture={_mic_file(tmp_path / 'mic.wav')}"])


@pytest.mark.xdist_group("live-mic")
def test_live_mode_sends_what_is_said_after_a_pause_with_no_button(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = _live_browser(pw, tmp_path)
        try:
            page = browser.new_page()
            page.add_init_script("localStorage.setItem('talk.talkMode', '\"live\"')")
            page.goto(url)
            page.wait_for_selector("#talk[aria-label='Stop listening']", timeout=5000)  # the microphone opened
            assert page.is_hidden("#subs") and page.inner_text("#modechip") == "Live · listening"  # no card for "listening"
            fake.heard = "how does the doorbell work"
            page.wait_for_selector("#app[data-state='listening']", timeout=8000)  # the noise: "Hearing you…"
            turn = on_loop(loop, call.turns.next(timeout=8))
            assert [s["text"] for s in turn["said"]] == ["how does the doorbell work"]
            # The mic button is the switch: off, nothing more is heard.
            page.click("#talk")
            assert page.get_attribute("#talk", "aria-label") == "Listen" and page.evaluate("document.querySelector('#talk').classList.contains('muted')")
        finally:
            browser.close()


@pytest.mark.xdist_group("live-mic")
def test_live_speech_over_an_answer_pauses_it_and_noise_lets_it_go_on(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 30.0
        browser = _live_browser(pw, tmp_path)
        try:
            page = browser.new_page()
            page.add_init_script("localStorage.setItem('talk.talkMode', '\"live\"')")
            page.goto(url)
            fake.heard = ""  # the noise is no words: the answer carries on
            on_loop(loop, call.answer("A long answer that keeps going. " * 6))
            page.wait_for_function(PLAYING, timeout=5000)
            page.wait_for_function(PAUSED, timeout=8000)          # cut in on
            try:
                page.wait_for_function(PLAYING, timeout=8000)     # nothing said: it resumes
            except Exception:
                raise AssertionError(page.evaluate("({held, deferred: !!deferred, speech: live && live.speech, q: liveQueue.length, sending: liveSending, busy, vol: audio.volume, t: audio.currentTime, paused: audio.paused, cur: current && current.id})"))
            fake.heard = "hold on, why?"
            page.wait_for_function(PAUSED, timeout=10000)
            turn = on_loop(loop, call.turns.next(timeout=10))
            said = turn["said"][-1]
            assert said["text"] == "hold on, why?" and said["interrupted"]["answer"] == 1
            page.wait_for_timeout(1500)
            assert page.evaluate(PAUSED)                          # words said: the answer stays stopped
        finally:
            browser.close()


def test_a_stage_that_loads_an_error_page_says_it_did_not_load(tmp_path, browser):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.add_init_script("window.__stageReadyMs = 500")
        # Loaded, but not the stage: what Chrome shows when the daemon does not answer fires "load" too.
        page.route(STAGE, lambda route: route.fulfill(status=502, content_type="text/html", body="<body>Bad gateway</body>"))
        page.goto(url)
        page.wait_for_selector("text=The stage did not load.", timeout=5000)
        assert page.is_visible("#reloadstage")


def test_typing_while_an_answer_plays_stops_it_and_the_reply_plays(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 20.0
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            on_loop(loop, call.answer("A long first answer."))
            page.wait_for_function(PLAYING, timeout=5000)
            page.fill("#text", "and then?"); page.press("#text", "Enter")
            page.wait_for_function(PAUSED, timeout=3000)  # what you send moves the call on
            on_loop(loop, call.answer("The reply."))
            page.wait_for_function("current && current.n === 2 && !audio.paused", timeout=8000)
        finally:
            browser.close()


def test_the_gears_stage_demo_opens_the_demo_in_a_new_tab(tmp_path, browser, monkeypatch):
    monkeypatch.setattr(talk, "open_call", lambda args, topic, out, cwd, base=None: (talk.Call(args, topic, out), []))
    monkeypatch.setattr(talk.speech, "ensure_running", lambda **kw: {})
    with served(tmp_path) as (url, call, loop, fake):
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(url)
        open_gear(page)
        assert page.is_visible("#demo")
        with ctx.expect_page() as opened:
            page.click("#demo")
        demo = opened.value  # opened blank at once (no pop-up block), then sent to the demo call
        demo.wait_for_url("**/c/**", timeout=5000)
        assert demo.url != url
        demo.wait_for_function("CFG.demo === true && CFG.topic === 'Stage demo'", timeout=5000)
        open_gear(demo)
        assert demo.is_hidden("#demo")  # the demo needs no button to itself


def test_an_answer_whose_voice_comes_after_you_moved_on_does_not_play(tmp_path, pw):
    import threading
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            fake.hold = threading.Semaphore(0)  # the first answer's voice is still being made
            on_loop(loop, call.answer("The old board."))
            page.wait_for_function("view.entries.some(e => e.who === 'claude')", timeout=5000)
            page.fill("#text", "next"); page.press("#text", "Enter")  # you move on before it is ready
            page.wait_for_function("view.entries.some(e => e.who === 'you')", timeout=5000)
            fake.hold.release()  # now its voice is ready
            page.wait_for_function("view.entries.find(e => e.who === 'claude').speech === 'ready'", timeout=5000)
            page.wait_for_timeout(800)
            assert page.evaluate("current === null || audio.paused")  # it does not start on its own
            fake.hold.release()
            on_loop(loop, call.answer("The new board."))
            page.wait_for_function("current && current.text === 'The new board.' && !audio.paused", timeout=8000)
        finally:
            fake.hold = None
            browser.close()
