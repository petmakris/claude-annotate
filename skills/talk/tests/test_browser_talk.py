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


@contextmanager
def served(tmp_path):
    """A call served on a loop in its own thread. Yields (url, call, loop, fake)."""
    from aiohttp import web

    fake = FakeSpeech()
    loop = asyncio.new_event_loop()
    box = {}
    ready = threading.Event()

    async def start():
        box["call"] = talk.Call(make_args(), "Browser topic", tmp_path / "out")
        box["runner"] = web.AppRunner(talk.build_app(box["call"], TOKEN, CALL))
        await box["runner"].setup()
        site = web.TCPSite(box["runner"], "127.0.0.1", 0)
        await site.start()
        box["port"] = site._server.sockets[0].getsockname()[1]
        ready.set()

    thread = threading.Thread(target=loop.run_forever, daemon=True)
    with patch.object(talk.speech, "transcribe", fake.transcribe), patch.object(talk.speech, "synthesize", fake.synthesize):
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


def test_speak_send_hear_the_answer_and_steer_the_player(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            fake.heard = "explain the doorbell"
            page.click("#talk")
            page.wait_for_selector("#recording:not([hidden])")
            page.wait_for_timeout(600)
            page.click("#send")
            page.wait_for_selector(".turn.you")
            assert page.inner_text(".turn.you .text") == "explain the doorbell"

            turn = on_loop(loop, call.turns.next(timeout=2))
            assert turn["said"] == [{"who": "you", "text": "explain the doorbell"}]
            on_loop(loop, call.answer("The doorbell waits for your turn."))
            call.turns.accept_reply(turn["id"])

            page.wait_for_selector(".turn.claude button.play")
            page.wait_for_function("!document.getElementById('audio').paused", timeout=5000)
            assert page.inner_text("#ptitle").startswith("Answer 1")
            page.click("#speeds button[data-speed='1.25']")
            assert page.evaluate("document.getElementById('audio').playbackRate") == 1.25
            page.click("#playpause")
            assert page.evaluate("document.getElementById('audio').paused")
            page.evaluate("document.getElementById('audio').currentTime = 0.8")
            page.click("#back5")
            assert page.evaluate("document.getElementById('audio').currentTime") == 0
            page.click("#autoplay")
            assert page.inner_text("#autoplay").endswith("off")

            page.fill("#text", "and then?")
            page.press("#text", "Enter")
            page.wait_for_function("document.querySelectorAll('.turn.you').length === 2")
            assert page.locator(".turn.you .who").last.inner_text().lower().endswith("typed")
        finally:
            browser.close()


def test_the_speed_and_language_are_kept_per_viewer(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            page.click("#lang button[data-lang='el']")
            page.click("#talk")
            page.wait_for_selector("#recording:not([hidden])")
            page.click("#send")
            page.wait_for_selector("#idle:not([hidden])")
            assert fake.languages == ["el"]
            page.reload()
            assert page.get_attribute("#lang button[data-lang='el']", "aria-pressed") == "true"
        finally:
            browser.close()


def test_nothing_heard_says_so_and_cancel_sends_nothing(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            page.click("#talk")
            page.wait_for_selector("#recording:not([hidden])")
            page.click("#cancel")
            assert fake.languages == []
            fake.heard = ""
            page.click("#talk")
            page.wait_for_selector("#recording:not([hidden])")
            page.click("#send")
            page.wait_for_selector("#err:has-text('Nothing was heard')")
            assert call.entries == []
        finally:
            browser.close()


def test_an_ended_call_disables_talking_and_keeps_replay(tmp_path, pw):
    with served(tmp_path) as (url, call, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_page()
            page.goto(url)
            page.click("#autoplay")  # so the answer waits for its own Play button
            on_loop(loop, call.answer("One last thing."))
            page.wait_for_selector(".turn.claude button.play")
            page.click("#end")
            page.wait_for_selector("#ended:not([hidden])")
            assert page.is_hidden("#idle") and page.is_hidden("#typed")
            page.click(".turn.claude button.play")
            page.wait_for_function("!document.getElementById('audio').paused", timeout=5000)
        finally:
            browser.close()
