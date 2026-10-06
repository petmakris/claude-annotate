"""Two calls on one server, in real browser pages: the user talks in one call at a time."""
import asyncio
import threading
from contextlib import contextmanager
from unittest.mock import patch

import pytest

pytest.importorskip("playwright", reason="browser suite: add --with playwright")

from helpers import FakeSpeech, make_args, talk  # noqa: E402

FAKE_MIC = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            "--autoplay-policy=no-user-gesture-required"]
PAUSED = "document.getElementById('audio').paused"
PLAYING = "!document.getElementById('audio').paused"


@contextmanager
def two_calls(tmp_path):
    """Calls Alpha and Beta on one server, on a loop of its own. Yields (base url, a, b, loop, fake)."""
    from aiohttp import web

    fake = FakeSpeech()
    fake.seconds = 8.0  # long enough to still be playing when the other call takes the floor
    loop = asyncio.new_event_loop()
    box = {}
    ready = threading.Event()

    async def start():
        server = box["server"] = talk.Server("server-token")
        box["a"] = server.add(talk.Call(make_args(), "Alpha", tmp_path / "a"), call_id="call-a", token="token-a")
        box["b"] = server.add(talk.Call(make_args(), "Beta", tmp_path / "b"), call_id="call-b", token="token-b")
        box["runner"] = web.AppRunner(talk.build_app(server))
        await box["runner"].setup()
        site = web.TCPSite(box["runner"], "127.0.0.1", 0)
        await site.start()
        box["port"] = site._server.sockets[0].getsockname()[1]
        ready.set()

    async def stop():
        box["server"].speech.shutdown()
        await box["runner"].cleanup()

    thread = threading.Thread(target=loop.run_forever, daemon=True)
    with patch.object(talk.speech, "transcribe", fake.transcribe), patch.object(talk.speech, "speak", fake.speak):
        thread.start()
        asyncio.run_coroutine_threadsafe(start(), loop)
        assert ready.wait(10)
        try:
            yield f"http://127.0.0.1:{box['port']}", box["a"], box["b"], loop, fake
        finally:
            asyncio.run_coroutine_threadsafe(stop(), loop).result(10)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(10)


def answer(loop, call, text):
    asyncio.run_coroutine_threadsafe(call.answer(text), loop).result(10)


def test_one_call_talks_at_a_time_and_the_other_keeps_its_answer(tmp_path, pw):
    with two_calls(tmp_path) as (base, a, b, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            ctx = browser.new_context()
            page_a, page_b = ctx.new_page(), ctx.new_page()
            page_a.goto(f"{base}/c/call-a")
            page_b.goto(f"{base}/c/call-b")
            page_b.wait_for_selector("#calls .callrow:has-text('Alpha')", state="attached")
            assert page_b.is_visible("#callsbtn")

            # Typing in Alpha takes the floor there, so Alpha's answer plays.
            page_a.click("#type")
            page_a.fill("#text", "hello alpha")
            page_a.press("#text", "Enter")
            page_a.wait_for_selector("#asked:has-text('hello alpha')")
            answer(loop, a, "The answer for Alpha.")
            page_a.wait_for_function(PLAYING, timeout=5000)

            # Beta's answer arrives meanwhile: shown, not played, and new in Alpha's list of calls.
            answer(loop, b, "The answer for Beta.")
            page_b.wait_for_selector("#playpause")
            page_b.wait_for_timeout(1200)
            assert page_b.evaluate(PAUSED)
            page_a.wait_for_selector("#calls .callrow.new:has-text('Beta') >> text=new answer", state="attached")
            assert page_a.is_visible("#callsdot")

            # Playing Beta takes the floor: Alpha pauses at once and says why.
            page_b.click("#playpause")
            page_b.wait_for_function(PLAYING, timeout=5000)
            page_a.wait_for_function(PAUSED, timeout=3000)
            assert "talking in “Beta”" in page_a.inner_text("#toast")
            page_a.wait_for_selector("#calls .callrow:has-text('Beta') >> text=talking now", state="attached")

            # Pressing Talk in Alpha takes it back.
            page_a.click("#talk")
            page_a.wait_for_selector("#app[data-state='listening']")
            page_b.wait_for_function(PAUSED, timeout=3000)
        finally:
            browser.close()


def test_a_page_on_another_device_pauses_on_its_next_poll(tmp_path, pw):
    """Separate browser contexts share no BroadcastChannel, like a phone and a laptop."""
    with two_calls(tmp_path) as (base, a, b, loop, fake):
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            phone, laptop = browser.new_context().new_page(), browser.new_context().new_page()
            phone.goto(f"{base}/c/call-a")
            laptop.goto(f"{base}/c/call-b")
            phone.click("#type")
            phone.fill("#text", "hello")
            phone.press("#text", "Enter")
            phone.wait_for_selector("#asked:has-text('hello')")
            answer(loop, a, "Alpha speaks.")
            phone.wait_for_function(PLAYING, timeout=5000)
            laptop.click("#type")
            laptop.fill("#text", "my turn")
            laptop.press("#text", "Enter")
            phone.wait_for_function(PAUSED, timeout=4000)
        finally:
            browser.close()


def test_the_home_page_lists_the_open_calls_once_a_call_was_opened(tmp_path, pw):
    with two_calls(tmp_path) as (base, a, b, loop, fake):
        answer(loop, b, "Unplayed.")
        browser = pw.chromium.launch(args=FAKE_MIC)
        try:
            page = browser.new_context().new_page()
            page.goto(f"{base}/")
            assert "Open a call first" in page.inner_text("body")
            page.goto(f"{base}/c/call-a")
            page.goto(f"{base}/")
            page.wait_for_selector("a.call:has-text('Alpha')")
            assert page.inner_text("a.call.new").startswith("Beta")
            page.click("a.call:has-text('Beta')")
            page.wait_for_url(f"{base}/c/call-b")
            page.evaluate("localStorage.setItem('talk.theme', JSON.stringify('dark'))")
            page.goto(f"{base}/")
            assert page.get_attribute("html", "data-theme") == "dark"
        finally:
            browser.close()
