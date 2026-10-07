"""Live mode, staged as scenes: a TV user with headphones, no keyboard, talking naturally.

Every test asserts what the user expects. A failing test is a broken scene, not a broken test.
The microphone is a WAV Chrome loops; each scene writes its own pattern of silence and loud noise.
"""
import random
import struct
import threading
import time
import wave
from unittest.mock import patch

import pytest

pytest.importorskip("playwright", reason="browser suite: add --with playwright")
# Each scene runs a live microphone: side by side they starve the machine, so they take turns on one worker.
pytestmark = pytest.mark.xdist_group("live-mic")

from helpers import talk  # noqa: E402
from test_browser_floor import two_calls  # noqa: E402
from test_browser_talk import FAKE_MIC, PAUSED, PLAYING, STAGE, on_loop, open_gear, served, stage_page  # noqa: E402

LONG = "A long answer that keeps going for a while. " * 12
NO_AUTOPLAY_POLICY = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                      "--autoplay-policy=user-gesture-required"]


def mic(path, *segments, rate=48000):
    """segments: ("s", seconds) of silence or ("v", seconds) of loud noise standing in for a voice."""
    rnd = random.Random(1)
    frames = []
    for kind, sec in segments:
        n = int(sec * rate)
        frames += [int(rnd.uniform(-0.35, 0.35) * 32767) for _ in range(n)] if kind == "v" else [0] * n
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
    return str(path)


def launch(pw, tmp_path, *segments, args=FAKE_MIC):
    return pw.chromium.launch(args=[*args, f"--use-file-for-fake-audio-capture={mic(tmp_path / 'mic.wav', *segments)}"])


def live_page(browser_or_ctx, url, **stored):
    page = browser_or_ctx.new_page()
    settings = {"talkMode": "live", **stored}
    page.add_init_script("".join(f"localStorage.setItem('talk.{k}', {repr(__import__('json').dumps(v))});" for k, v in settings.items()))
    if url:
        page.goto(url)
    return page


class Script:
    """speech-to-text that answers in turn from a list (the last repeats), each after a delay."""

    def __init__(self, *replies, delay=0.0):
        self.replies, self.delay, self.calls = list(replies), delay, []
        self.lock = threading.Lock()

    def __call__(self, audio, language=None):
        with self.lock:
            i = len(self.calls)
            self.calls.append(len(audio))
        delay = self.delay[i] if isinstance(self.delay, (list, tuple)) and i < len(self.delay) else (self.delay if not isinstance(self.delay, (list, tuple)) else 0)
        time.sleep(delay)
        return self.replies[min(i, len(self.replies) - 1)]


def listens(page):
    """Every /api/listen the page sends, as its query string."""
    seen = []
    page.on("request", lambda r: seen.append(r.url.split("?", 1)[-1]) if "/api/listen" in r.url else None)
    return seen


def drain(loop, call, timeout=1.0):
    """Every line Claude would collect now."""
    turn = on_loop(loop, call.turns.next(timeout=timeout))
    return [] if turn is None else turn["said"]


# ---- scene 1: first-time setup, Live chosen in the gear -------------------------------------

def test_s01_choosing_live_in_the_gear_listens_and_sends(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 4), ("v", 1), ("s", 20))
        try:
            page = browser.new_page(); page.goto(url)
            open_gear(page); page.click("#tmode button[data-choice='live']")
            page.wait_for_selector("#talk[aria-label='Stop listening']", timeout=5000)
            fake.heard = "hello"
            said = on_loop(loop, call.turns.next(timeout=10))["said"]
            assert [s["text"] for s in said] == ["hello"]
        finally:
            browser.close()


# ---- scenes 2 and 3: the page reloads with live remembered; Chrome wants a click first ------

# Headless Chromium starts an AudioContext running even without a gesture. This stands in for the
# desktop policy: a context made as the page loads, before any click, starts suspended, and resume()
# works only with a user activation (which a click inside the stage iframe also gives this page).
# (Under a loaded test run headless Chrome can report an activation before any click, so the hold does
# not ask navigator.userActivation at construction.)
GESTURE_POLICY = """
(() => {
  const Real = window.AudioContext;
  window.AudioContext = class extends Real {
    constructor(...a) { super(...a); this._held = true; super.suspend(); }  // made at load, before any click: held
    get state() { return this._held ? "suspended" : super.state; }
    resume() {
      if (!navigator.userActivation.hasBeenActive) return Promise.reject(new DOMException("no gesture", "NotAllowedError"));
      this._held = false; window.__resumed = (window.__resumed || 0) + 1; return super.resume();
    }
  };
})();
"""


def _suspended_page(pw, tmp_path, url, stage=False):
    browser = launch(pw, tmp_path, ("s", 30), args=NO_AUTOPLAY_POLICY)
    page = live_page(browser, None)
    page.add_init_script(GESTURE_POLICY)
    if stage:
        stage_page(page)
    page.goto(url)
    try:
        page.wait_for_selector("#status:has-text('Click anywhere to start listening.')", timeout=5000)
    except Exception:
        raise AssertionError(page.evaluate("({act: navigator.userActivation.hasBeenActive, resumed: window.__resumed || 0, held: live && live.ctx._held, live: !!live, susp: live && live.suspended, parked: live && live.parked, state: live && live.ctx.state, status: $('status').textContent, hidden: $('status').hidden, subs: $('subs').hidden})"))
    return browser, page


def test_s02_after_a_reload_a_click_on_the_mic_button_starts_listening(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser, page = _suspended_page(pw, tmp_path, url)
        try:
            page.click("#talk")  # the obvious thing to click on a page that says "click anywhere"
            page.wait_for_timeout(800)
            state = page.evaluate("({live: !!live, suspended: live && live.suspended, resumed: window.__resumed || 0, label: $('talk').getAttribute('aria-label')})")
            assert state["live"] and not state["suspended"], state
        finally:
            browser.close()


def test_s03_after_a_reload_a_click_on_the_stage_starts_listening(tmp_path, pw):
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        browser, page = _suspended_page(pw, tmp_path, url, stage=True)
        try:
            page.wait_for_selector("#veil", state="hidden", timeout=5000)
            box = page.locator("#stage").bounding_box()
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 3)  # the stage fills the TV
            page.wait_for_timeout(800)
            state = page.evaluate("({live: !!live, suspended: live && live.suspended, resumed: window.__resumed || 0, activated: navigator.userActivation.hasBeenActive, status: $('status').textContent})")
            assert state["live"] and not state["suspended"], state
        finally:
            browser.close()


# ---- scene 5: a monologue longer than the cap ---------------------------------------------------

def test_s05_a_long_monologue_reaches_claude_as_one_turn(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 3), ("v", 5), ("s", 30))
        try:
            page = live_page(browser, url)
            page.wait_for_selector("#talk[aria-label='Stop listening']", timeout=5000)
            page.evaluate("LIVE.maxMs = 3000")  # the 60 s cap, scaled down: 5 s of speech crosses it
            script = Script("a long thought about the mapper", "the rest of it")  # ends whole: not held as a thought going on
            with patch.object(talk.speech, "transcribe", script):
                page.wait_for_timeout(9000)
            said = drain(loop, call)
            assert len(script.calls) == 1 and len(said) == 1, (script.calls, said)
        finally:
            browser.close()


# ---- scene 6: the answer's audio becomes ready while the user is making a noise / talking -----

def test_s06_an_answer_ready_during_a_cough_still_plays_after_it(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 20.0
        browser = launch(pw, tmp_path, ("s", 3), ("v", 3), ("s", 30))
        try:
            page = live_page(browser, url)
            fake.heard = ""  # a cough: no words
            page.wait_for_selector("#app[data-state='listening']", timeout=8000)
            on_loop(loop, call.answer(LONG))  # Claude's answer is ready mid-cough
            page.wait_for_function("current !== null", timeout=5000)
            page.wait_for_selector("#app:not([data-state='listening'])", timeout=8000)
            page.wait_for_function("!busy", timeout=8000)
            page.wait_for_timeout(1500)
            assert page.evaluate(PLAYING), page.evaluate("({t: audio.currentTime, src: audio.dataset.src})")
        finally:
            browser.close()


# ---- scene 7: "uh" ... then the real question, while the first is still being transcribed -----

def test_s07_a_false_start_does_not_resume_the_answer_over_the_real_question(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 30.0
        browser = launch(pw, tmp_path, ("s", 3), ("v", 0.7), ("s", 1.4), ("v", 3), ("s", 30))
        try:
            page = live_page(browser, url, endPause=800)
            on_loop(loop, call.answer(LONG))
            page.wait_for_function(PLAYING, timeout=5000)
            script = Script("", "why is that", delay=[1.5, 0])  # "uh": no words, and a slow first transcription
            timeline = []
            with patch.object(talk.speech, "transcribe", script):
                page.wait_for_function(PAUSED, timeout=8000)   # cut in on
                t0 = time.time()
                while time.time() - t0 < 9:
                    # Playing over the user means playing at full volume: a ducked answer under them is the design.
                    timeline.append((round(time.time() - t0, 1), *page.evaluate("[!!(live && live.speech), !audio.paused && audio.volume > 0.5, busy]")))
                    page.wait_for_timeout(100)
            said = drain(loop, call, timeout=2)
            over_user = [t for t in timeline if t[1] and t[2]]
            print("S07 timeline (t, user speaking, answer playing, busy):", timeline[::5])
            print("S07 said:", said)
            assert not over_user and not page.evaluate("!audio.paused"), (over_user[:3], said)
        finally:
            browser.close()


# ---- scene 8: keyword mode, "Listen, why is that?" over a long answer ---------------------------

def test_s08_listen_with_a_question_stops_the_answer_and_the_reply_plays(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 40.0
        browser = launch(pw, tmp_path, ("s", 3), ("v", 1.2), ("s", 40))
        try:
            page = live_page(browser, url, barge="keyword")
            on_loop(loop, call.answer(LONG))
            page.wait_for_function(PLAYING, timeout=5000)
            fake.heard = "Wait, why is that?"
            said = on_loop(loop, call.turns.next(timeout=10))["said"]
            assert said[-1]["text"] == "why is that?" and said[-1]["interrupted"]["answer"] == 1
            page.wait_for_timeout(500)
            paused_after_question = page.evaluate(PAUSED)
            fake.heard = ""
            call.collected()
            on_loop(loop, call.answer("Because of the queue."))
            try:
                page.wait_for_function("current && current.n === 2 && !audio.paused", timeout=5000)
                reply_played = True
            except Exception:
                reply_played = False
            assert paused_after_question and reply_played, {"paused_after_question": paused_after_question,
                                                              "reply_played": reply_played,
                                                              "now": page.evaluate("({n: current && current.n, playing: !audio.paused})")}
        finally:
            browser.close()


def test_s09_keyword_mode_other_words_let_the_answer_go_on(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 30.0
        browser = launch(pw, tmp_path, ("s", 3), ("v", 1), ("s", 30))
        try:
            page = live_page(browser, url, barge="keyword")
            seen = listens(page)
            on_loop(loop, call.answer(LONG))
            page.wait_for_function(PLAYING, timeout=5000)
            fake.heard = "so anyway the dog"
            page.wait_for_timeout(6000)
            assert any("keyword=1" in q for q in seen), seen
            assert page.evaluate(PLAYING) and drain(loop, call, 0.5) == []
        finally:
            browser.close()


# ---- scene 11: the mic button pressed mid-utterance over an answer ------------------------------

def test_s11_stop_listening_mid_question_lets_the_answer_go_on_and_sends_nothing(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 30.0
        browser = launch(pw, tmp_path, ("s", 3), ("v", 4), ("s", 30))
        try:
            page = live_page(browser, url)
            seen = listens(page)
            on_loop(loop, call.answer(LONG))
            page.wait_for_function(PAUSED + " && live && live.speech", timeout=8000)
            page.click("#talk")
            page.wait_for_timeout(3000)
            out = page.evaluate("({live: !!live, playing: !audio.paused})")
            # The words so far are dropped, and the answer they had stopped picks up again.
            assert out == {"live": False, "playing": True} and not seen
        finally:
            browser.close()


# ---- scene 12: Live -> Press to talk while a send is in flight ---------------------------------

def test_s12_switching_to_press_to_talk_mid_send_still_delivers_the_turn(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 3), ("v", 1), ("s", 30))
        try:
            page = live_page(browser, url)
            with patch.object(talk.speech, "transcribe", Script("hello there", delay=2.0)):
                page.wait_for_function("busy === true", timeout=10000)
                open_gear(page); page.click("#tmode button[data-choice='manual']")
                said = on_loop(loop, call.turns.next(timeout=6))["said"]
            page.wait_for_function("busy === false", timeout=3000)
            assert [s["text"] for s in said] == ["hello there"]
            assert page.get_attribute("#talk", "aria-label") == "Talk" and not page.is_disabled("#talk")
        finally:
            browser.close()


# ---- scene 13: Space while live is sending ------------------------------------------------------

def test_s13_space_while_a_live_turn_is_sending_does_not_type_into_the_field(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 3), ("v", 1), ("s", 30))
        try:
            page = live_page(browser, url, autoplay=False)
            on_loop(loop, call.answer("A short answer."))
            page.wait_for_selector("#playpause:not([hidden])", timeout=5000)
            page.evaluate("document.activeElement.blur()")
            with patch.object(talk.speech, "transcribe", Script("hello", delay=2.5)):
                page.wait_for_function("busy === true", timeout=10000)
                page.keyboard.press(" ")
                value = page.input_value("#text")
                page.wait_for_function("busy === false", timeout=6000)
                page.keyboard.press(" ")
            assert value == "" and page.input_value("#text") == "", repr((value, page.input_value("#text")))
        finally:
            browser.close()


# ---- scene 14: typing while live listens ----------------------------------------------------------

def test_s14_typing_while_live_listens_sends_the_text_and_keeps_listening(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 30))
        try:
            page = live_page(browser, url)
            page.wait_for_selector("#talk[aria-label='Stop listening']", timeout=5000)
            page.fill("#text", "typed question"); page.press("#text", "Enter")
            said = on_loop(loop, call.turns.next(timeout=5))["said"]
            assert [s["text"] for s in said] == ["typed question"] and page.evaluate("!!live")
        finally:
            browser.close()


# ---- scene 17: the call ends while the user is talking -------------------------------------------

def test_s17_the_call_ending_mid_speech_stops_listening_and_sends_nothing(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 3), ("v", 5), ("s", 30))
        try:
            page = live_page(browser, url)
            seen = listens(page)
            page.wait_for_selector("#app[data-state='listening']", timeout=8000)
            loop.call_soon_threadsafe(call.end, "ended in the terminal")
            page.wait_for_selector("#app[data-ended]", timeout=5000)
            page.wait_for_timeout(4000)
            assert page.evaluate("live === null") and page.is_hidden("#talk") and not seen
        finally:
            browser.close()


# ---- scenes 18 and 19: another call takes the floor ----------------------------------------------

def test_s18_after_another_call_took_the_floor_this_call_listens_again_or_says_it_stopped(tmp_path, pw):
    with two_calls(tmp_path) as (base, a, b, loop, fake):
        browser = launch(pw, tmp_path, ("s", 60))
        try:
            ctx = browser.new_context()
            page_a = live_page(ctx, f"{base}/c/call-a")
            page_a.wait_for_selector("#talk[aria-label='Stop listening']", timeout=5000)
            page_b = ctx.new_page(); page_b.goto(f"{base}/c/call-b")
            page_b.fill("#text", "a question in Beta"); page_b.press("#text", "Enter")
            page_a.wait_for_timeout(1500)
            page_a.bring_to_front()
            page_a.wait_for_timeout(1500)
            out = page_a.evaluate("({live: !!live, toast: $('toast').hidden ? '' : $('toasttext').textContent, label: $('talk').getAttribute('aria-label')})")
            assert out["live"] or out["toast"], out
        finally:
            browser.close()


def test_s19_two_live_calls_hearing_one_voice_keep_one_listening(tmp_path, pw):
    with two_calls(tmp_path) as (base, a, b, loop, fake):
        browser = launch(pw, tmp_path, ("s", 3), ("v", 1), ("s", 60))
        try:
            ctx = browser.new_context()
            page_a = live_page(ctx, f"{base}/c/call-a")
            page_b = live_page(ctx, f"{base}/c/call-b")
            for p in (page_a, page_b):
                p.wait_for_selector("#talk[aria-label='Stop listening']", timeout=5000)
            page_a.wait_for_timeout(6000)
            out = [p.evaluate("!!live") for p in (page_a, page_b)]
            assert any(out), out
        finally:
            browser.close()


# ---- scene 20: the same call open twice (TV and laptop) -------------------------------------------

def test_s20_one_call_open_on_two_pages_sends_what_was_said_once(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        # Chrome's fake microphone replays its file from the start for each page's capture: the voice comes
        # late enough that both pages listen before either timeline reaches it, as one real microphone would.
        browser = launch(pw, tmp_path, ("s", 6), ("v", 1), ("s", 60))
        try:
            ctx = browser.new_context()
            p1, p2 = live_page(ctx, url), live_page(ctx, url)
            fake.heard = "what about the doorbell"
            for p in (p1, p2):
                p.wait_for_function("!!live", timeout=5000)  # both opened the microphone; one of them listens
            p1.wait_for_timeout(10000)
            said = drain(loop, call)
            assert [s["text"] for s in said] == ["what about the doorbell"], said
        finally:
            browser.close()


# ---- scene 24: Press to talk recording, then Live switched on mid-recording -----------------------

def test_s24_switching_to_live_during_a_recording_does_not_send_the_words_twice(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 0.3), ("v", 1), ("s", 30))
        try:
            page = browser.new_page(); page.goto(url)
            page.click("#talk")
            page.wait_for_selector("#app[data-state='listening']")
            page.wait_for_timeout(1800)  # the question is in the recording
            # Chrome's fake microphone replays its file from the start for every new capture, so live mode
            # "hears" the question again; a real microphone does not: that second hearing has no words.
            with patch.object(talk.speech, "transcribe", Script("one question", "")):
                open_gear(page); page.click("#tmode button[data-choice='live']")  # the recording goes, once
                page.keyboard.press("Escape")
                page.wait_for_function("recorder === null && !!live", timeout=5000)
                page.wait_for_timeout(4000)
            said = drain(loop, call)
            assert [s["text"] for s in said] == ["one question"], said
        finally:
            browser.close()


# ---- scene 25: a fan is switched on and stays on ------------------------------------------------

def test_s25_a_room_that_gets_louder_is_heard_once_not_forever(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 2), ("v", 40))  # the noise starts and never stops
        try:
            page = live_page(browser, url, endPause=800)
            seen = listens(page)
            fake.heard = ""
            page.wait_for_timeout(18000)
            # The noise read as speech until the floor rose to it (8 s), then it ended once; it never starts again.
            assert len(seen) == 1 and page.evaluate("!live.speech"), (len(seen), page.evaluate("live.speech"))
        finally:
            browser.close()


# ---- scene 26: a click, shorter than any word -----------------------------------------------------

def test_s26_a_click_shorter_than_a_word_sends_nothing(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 2), ("v", 0.2), ("s", 30))
        try:
            page = live_page(browser, url)
            seen = listens(page)
            page.wait_for_timeout(5000)
            assert seen == []
        finally:
            browser.close()


# ---- scene 27: "pause" and "go on" said over an answer ---------------------------------------------

def test_s27_saying_pause_then_go_on_steers_the_answer_with_no_turn(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        fake.seconds = 40.0
        browser = launch(pw, tmp_path, ("s", 3), ("v", 1), ("s", 3))  # one word every 7 s
        try:
            page = live_page(browser, url, endPause=800)
            on_loop(loop, call.answer(LONG))
            page.wait_for_function(PLAYING, timeout=5000)
            with patch.object(talk.speech, "transcribe", Script("Pause.", "go on")):
                page.wait_for_function(PAUSED, timeout=8000)
                page.wait_for_timeout(2500)
                assert page.evaluate(PAUSED)                       # it stays paused: "pause" was acted on
                page.wait_for_function(PLAYING, timeout=9000)      # "go on"
            assert drain(loop, call, 0.5) == []                     # neither became a turn
        finally:
            browser.close()


# ---- scene 28: the Undo button takes back a turn Claude has not collected ---------------------------

def test_s28_undo_takes_back_what_was_just_said(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 3), ("v", 1), ("s", 30))
        try:
            page = live_page(browser, url, endPause=800)
            fake.heard = "a question I regret"
            page.wait_for_selector("#undo:not([hidden])", timeout=8000)
            page.click("#undo")
            page.wait_for_selector("#status:has-text('Taken back.')", timeout=3000)
            assert drain(loop, call, 0.5) == []
            assert any(e.get("withdrawn") for e in call.entries if e["who"] == "you")
        finally:
            browser.close()


# ---- scene 29: the TV screen ------------------------------------------------------------------------

def test_s29_the_tv_screen_grows_the_subtitles_and_zooms_the_stage(tmp_path, pw):
    from test_browser_talk import STAGE_PROBE
    with served(tmp_path, stage_url=STAGE) as (url, call, loop, fake):
        browser = launch(pw, tmp_path, ("s", 30))
        try:
            page = live_page(browser, None)
            stage_page(page, STAGE_PROBE)
            page.goto(url)
            on_loop(loop, call.answer("A short answer."))
            page.wait_for_selector("#cap:has-text('A short answer.')", timeout=5000)
            desk = page.evaluate("parseFloat(getComputedStyle($('cap')).fontSize)")
            open_gear(page); page.click("#screen button[data-choice='tv']"); page.keyboard.press("Escape")
            tv = page.evaluate("parseFloat(getComputedStyle($('cap')).fontSize)")
            page.frame(url=STAGE).wait_for_function("got.some(m => m.type === 'stage:zoom' && m.zoom === 1.35)", timeout=2000)
            assert (desk, tv) == (18.0, 30.0)
            assert page.inner_text("#modechip") in ("Live · listening", "Live · off")
        finally:
            browser.close()
