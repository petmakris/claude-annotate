"""The dormant page in a real browser: it streams 16 kHz PCM to the ear, and a wake closes that
stream before it asks for a live session. Chrome's fake microphone (a beep) stands in for the
user; no OpenAI session is created.

Skips without playwright: run with `--with playwright` (and `playwright install chromium` once)."""
import asyncio
import threading
import time
from contextlib import contextmanager

import pytest

pytest.importorskip("playwright", reason="browser suite: add --with playwright")

from aiohttp import web  # noqa: E402

from helpers import CALL, TOKEN, FakeEar, RecordingSocket, make_args, talk  # noqa: E402

FAKE_MIC = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]


class TimedEar(FakeEar):
    def __init__(self):
        super().__init__()
        self.arrivals: list[tuple[float, int]] = []

    def feed(self, pcm):
        super().feed(pcm)
        self.arrivals.append((time.monotonic(), len(pcm)))


@contextmanager
def served(tmp_path, **overrides):
    """The talk app on a real port, on its own loop in a thread (Playwright's sync API owns this one)."""
    loop = asyncio.new_event_loop()
    ready, box = threading.Event(), {}

    async def start():
        args = make_args(**overrides)
        log = talk.SessionLog(tmp_path / "out", "Test topic", "test")
        ctl = talk.LiveController(args, "Test topic", "", log, None, None)
        ctl.ear = TimedEar()
        runner = web.AppRunner(talk.build_app(args, "Test topic", log, ctl, TOKEN, CALL))
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        box.update(ctl=ctl, runner=runner, loop=loop,
                   url=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/c/{CALL}")
        ready.set()

    def main():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start())
        loop.run_forever()

    threading.Thread(target=main, daemon=True).start()
    assert ready.wait(10)
    try:
        yield box
    finally:
        async def stop():
            for task in (box["ctl"].dormant_task, box["ctl"].away_task):
                if task:
                    task.cancel()
            await box["runner"].cleanup()

        asyncio.run_coroutine_threadsafe(stop(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def on_loop(box, fn, *args):
    """Run fn on the server's loop and wait for it: the controller is not thread-safe."""
    async def call():
        return fn(*args)
    return asyncio.run_coroutine_threadsafe(call(), box["loop"]).result(5)


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_a_dormant_page_streams_16_khz_pcm_to_the_ear(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        ear = box["ctl"].ear
        assert wait_for(lambda: len(ear.arrivals) > 20)
        time.sleep(3)
        arrivals = list(ear.arrivals)[10:]
        title = page.text_content("#cardtitle")
        browser.close()
    seconds = arrivals[-1][0] - arrivals[0][0]
    rate = sum(n for _, n in arrivals[1:]) / seconds
    assert 16000 * 2 * 0.85 < rate < 16000 * 2 * 1.15, rate  # 16-bit mono at 16 kHz
    assert all(n % 2 == 0 for _, n in arrivals)
    assert title == "Dormant · listening on this Mac · free"


def test_the_cost_line_is_present_and_updates_after_a_usage_report(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box:
        ctl = box["ctl"]
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None)
        assert wait_for(lambda: page.text_content("#cost").startswith("GPT-Live"))
        before = page.text_content("#cost")
        asyncio.run_coroutine_threadsafe(
            ctl.on_event({"type": "session.usage.updated", "usage": {"seconds": 90}}), box["loop"]
        ).result(5)
        page.wait_for_function("document.getElementById('cost').textContent !== " + repr(before))
        after = page.text_content("#cost")
        browser.close()
    assert before.startswith("GPT-Live 0m 0s")
    assert "GPT-Live 1m 30s · $0.08" in after
    assert "Claude: your plan" in after


def test_the_cost_line_labels_the_brain_by_llm_mode(tmp_path, pw):
    # --llm session and --llm claude-code both bill the user's subscription; --llm api does not.
    with served(tmp_path, dormant_after=0, llm="claude-code") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.wait_for_function("document.getElementById('cost').textContent.includes('Claude')")
        claude_code_label = page.text_content("#cost")
        browser.close()
    with served(tmp_path, dormant_after=0, llm="api") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.wait_for_function("document.getElementById('cost').textContent.includes('Claude')")
        api_label = page.text_content("#cost")
        browser.close()
    assert "Claude: your plan" in claude_code_label
    assert "Claude: API, billed separately" in api_label


def test_a_wake_stops_the_ear_before_the_session_is_requested_and_a_failure_listens_again(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box:
        ctl, seen = box["ctl"], {}

        async def failing_create(sdp):
            seen["ear_open"] = ctl.ear_ws is not None
            ctl.state = "dormant"  # what create() does when OpenAI refuses a wake
            return 429, {"error": "session create HTTP 429: insufficient_quota"}

        ctl.create = failing_create
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None and ctl.ear.frames)
        on_loop(box, ctl.hear, {"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
        assert wait_for(lambda: "ear_open" in seen)
        assert wait_for(lambda: ctl.ear.begun == 2)  # listening again
        page.wait_for_function("document.getElementById('status').textContent.includes('insufficient_quota')")
        status = page.text_content("#status")
        # I1: a poll tick (700 ms) must not clobber the error with the ordinary dormant hint.
        time.sleep(1.5)
        status_after = page.text_content("#status")
        browser.close()
    assert seen["ear_open"] is False
    assert "Still listening on this Mac" in status
    assert ctl.wake_segment["text"] == "Nova, is it three?"
    assert "insufficient_quota" in status_after


def test_wake_now_is_a_visible_button_that_starts_a_wake(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box:
        ctl, seen = box["ctl"], {}

        async def failing_create(sdp):
            seen["called"] = True
            ctl.state = "dormant"
            return 429, {"error": "session create HTTP 429: insufficient_quota"}

        ctl.create = failing_create
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None)
        assert page.is_visible("#wake")
        assert page.text_content("#wake").strip() == "Wake now"
        page.click("#wake")
        assert wait_for(lambda: "called" in seen)
        browser.close()
    assert seen["called"] is True


def test_mute_while_dormant_stops_frames_reaching_the_ear(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        ear = box["ctl"].ear
        assert wait_for(lambda: len(ear.frames) > 5)
        page.click("#mute")
        page.wait_for_function("document.getElementById('mute').getAttribute('aria-pressed') === 'true'")
        count_at_mute = len(ear.frames)
        time.sleep(1.5)
        after = len(ear.frames)
        browser.close()
    assert after == count_at_mute


def test_a_409_during_the_sleep_handoff_shows_one_clean_sentence(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box:
        ctl = box["ctl"]
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None)
        # The real 409: create_session's own guard, before ctl.create() is even called, while the
        # old session id has not yet been cleared by rest().
        on_loop(box, setattr, ctl, "session_id", "still-closing")
        page.click("#wake")
        page.wait_for_function("document.getElementById('status').textContent.includes('still closing')")
        status = page.text_content("#status")
        on_loop(box, setattr, ctl, "session_id", None)
        browser.close()
    assert "The voice is still closing; try again in a few seconds." in status
    assert "Still listening on this Mac" in status


def test_ending_while_dormant_does_not_reopen_the_ear(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box:
        ctl = box["ctl"]
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None and ctl.ear.frames)
        begun_before = ctl.ear.begun
        page.click("#stop")
        page.click("#stop")
        assert wait_for(lambda: ctl.done.is_set())
        time.sleep(2)
        browser.close()
    assert ctl.ear.begun == begun_before


def test_the_projector_view_gives_the_stage_the_screen_and_says_how_to_ask(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        before = page.text_content("#pbartext")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Listening')")
        bar, aside = page.text_content("#pbartext"), page.is_visible("aside")
        # While dormant the bar still offers a way back in: Wake now (reusing #start/#wake) and End
        # (reusing #stop) are both visible, so the call can be operated without the hidden sidebar.
        wake_label = page.text_content("#pstart").strip()
        end_visible = page.is_visible("#pend")
        browser.close()
    assert before == "Press Start to begin listening"
    assert bar == "Listening · say 'Nova' to ask"
    assert not aside
    assert wake_label == "Wake now" and end_visible


def test_the_projector_bar_arms_and_ends_the_call_on_two_presses(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        ctl = box["ctl"]
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Listening')")
        page.click("#pend")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Press again')")
        armed = page.text_content("#pbartext")
        page.click("#pend")
        assert wait_for(lambda: ctl.done.is_set())
        browser.close()
    assert armed == "Press again to end · Esc Esc also works"


def test_the_projector_bar_shows_muted(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Listening')")
        # Space works even though the mute button itself lives in the hidden sidebar.
        page.keyboard.press("Space")
        page.wait_for_function("document.getElementById('pbartext').textContent === \"Muted · Space to unmute\"")
        muted = page.text_content("#pbartext")
        browser.close()
    assert muted == "Muted · Space to unmute"


def test_the_projector_bar_gives_speaking_priority_over_muted(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Listening')")
        # A real GPT-Live session can't be created in this sandbox (no OPENAI_API_KEY/network), so
        # "tutor" is set directly; the mute toggle itself is the real Space-key path, and it's that
        # real toggle's call to paintBar() that must give speaking priority over the mute marker.
        page.evaluate("document.body.dataset.state = 'tutor'")
        page.keyboard.press("Space")
        page.wait_for_function("document.getElementById('pbartext').textContent.includes('is speaking')")
        bar = page.text_content("#pbartext")
        browser.close()
    assert bar == "Nova is speaking · Muted"


def test_the_projector_bar_mirrors_a_failed_wake(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        ctl = box["ctl"]
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        assert wait_for(lambda: ctl.ear_ws is not None)
        # The real 409: create_session's own guard, before ctl.create() is even called, while the
        # old session id has not yet been cleared by rest() (see test_a_409_... in this file).
        on_loop(box, setattr, ctl, "session_id", "still-closing")
        page.click("#pstart")  # Wake now, reusing the same #start path as the sidebar's #wake
        page.wait_for_function("document.getElementById('pbartext').textContent.includes('still closing')")
        bar = page.text_content("#pbartext")
        on_loop(box, setattr, ctl, "session_id", None)
        browser.close()
    assert "The voice is still closing; try again in a few seconds." in bar
    assert "Still listening on this Mac." in bar


# A second page plays GPT-Live's side of the WebRTC call: it answers the page's offer, and once the
# page's "oai-events" channel opens it sends session.started, as GPT-Live does.
FAKE_VOICE = """
window.answer = async (offer) => {
  const pc = new RTCPeerConnection(); window.pc = pc;
  pc.ondatachannel = (e) => { window.dc = e.channel;
    e.channel.onopen = () => e.channel.send(JSON.stringify({ type: "session.started" })); };
  await pc.setRemoteDescription({ type: "offer", sdp: offer });
  await pc.setLocalDescription(await pc.createAnswer());
  if (pc.iceGatheringState !== "complete") await new Promise((res) => {
    const t = setTimeout(res, 3000);
    pc.addEventListener("icegatheringstatechange", () => { if (pc.iceGatheringState === "complete") { clearTimeout(t); res(); } });
  });
  return pc.localDescription.sdp;
};
"""


def go_live(box, browser, page):
    """Start the page's live call against a fake voice in a second page; returns the voice page."""
    ctl, seen = box["ctl"], {}

    async def fake_create(sdp):
        seen["answer"] = asyncio.get_running_loop().create_future()
        seen["offer"] = sdp
        answer = await seen["answer"]
        ctl.session_id, ctl.sessions, ctl.state = "s1", ctl.sessions + 1, "live"
        ctl.ws = RecordingSocket()
        ctl.attached.set()
        return 201, {"session": {"id": "s1"}, "transport": {"sdp": answer}}

    ctl.create = fake_create
    voice = browser.new_page()
    voice.evaluate("() => {" + FAKE_VOICE + "}")  # a bare assignment would be called as a function
    page.click("#start")
    assert wait_for(lambda: "offer" in seen)
    sdp = voice.evaluate("offer => window.answer(offer)", seen["offer"])
    box["loop"].call_soon_threadsafe(seen["answer"].set_result, sdp)
    page.wait_for_function("!document.getElementById('stop').disabled")  # session.started arrived
    voice.wait_for_function("window.dc && window.dc.readyState === 'open'")
    return voice


def test_a_sleep_whose_close_gpt_live_never_confirms_still_closes_the_pages_peer(tmp_path, pw):
    with served(tmp_path, dormant_after=45) as box:
        ctl = box["ctl"]
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        voice = go_live(box, browser, page)

        async def sleep_unconfirmed():
            await ctl.sleep(wait=0.1)  # GPT-Live never answers session.close: the timeout path
            ctl.sideband_ended()  # what the sideband's end does once sleep() closed it

        asyncio.run_coroutine_threadsafe(sleep_unconfirmed(), box["loop"]).result(5)
        assert ctl.state == "dormant"
        voice.wait_for_function("window.dc.readyState === 'closed'", timeout=5000)
        assert wait_for(lambda: ctl.ear_ws is not None)  # and the page listens locally instead
        title = page.text_content("#cardtitle")
        browser.close()
    assert title == "Dormant · listening on this Mac · free"


def test_while_the_model_downloads_a_name_wake_meeting_says_to_press_wake_now(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        box["ctl"].ear.status = "loading"
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Preparing')")
        bar, status = page.text_content("#pbartext"), page.text_content("#status")
        browser.close()
    assert bar == "Preparing local listening (one-time download)… press Wake now to ask"
    assert status == bar
    assert "any speech" not in bar


def test_a_speech_wake_call_still_says_speech_wakes_it_while_the_model_downloads(tmp_path, pw):
    with served(tmp_path, dormant_after=45, wake="speech") as box:
        ctl = box["ctl"]
        ctl.ear.status = "loading"
        on_loop(box, setattr, ctl, "state", "dormant")
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Preparing')")
        bar = page.text_content("#pbartext")
        browser.close()
    assert bar == "Preparing local listening (one-time download)… wakes on any speech until then"


def test_local_listening_that_fails_to_load_shows_on_the_page_and_the_projector_bar(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        ctl = box["ctl"]
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Listening')")
        on_loop(box, setattr, ctl.ear, "error", "no metal device")
        on_loop(box, setattr, ctl.ear, "status", "failed")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Local listening failed')")
        bar, kind = page.text_content("#pbartext"), page.evaluate("document.body.dataset.pbar")
        status, bad = page.text_content("#status"), page.evaluate("document.getElementById('status').className")
        time.sleep(1.0)  # a later poll tick must not paint the ordinary hint back over it
        bar_after = page.text_content("#pbartext")
        browser.close()
    assert bar == "Local listening failed — press Wake now to ask (no metal device)"
    assert kind == "error"
    assert status == bar and "bad" in bad
    assert bar_after == bar


def test_a_page_opened_from_another_machine_says_the_audio_goes_to_the_talk_machine(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        ctl = box["ctl"]
        port = box["url"].split(":")[2].split("/")[0]
        # talk.test resolves to this machine, but to the page it is another host, as a tailnet name would be.
        # The microphone needs a secure context; only the new headless mode honours the flag that grants it.
        browser = pw.chromium.launch(channel="chromium", args=FAKE_MIC + [
            "--host-resolver-rules=MAP talk.test 127.0.0.1",
            f"--unsafely-treat-insecure-origin-as-secure=http://talk.test:{port}"])
        page = browser.new_page()
        page.goto(box["url"].replace("http://127.0.0.1", "http://talk.test"))
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None)
        page.wait_for_function("document.getElementById('cardtitle').textContent.startsWith('Dormant')")
        title, status = page.text_content("#cardtitle"), page.text_content("#status")
        browser.close()
    assert title == "Dormant · listening on the talk machine · free"
    assert status == 'Say "Nova" to ask. Until then, audio goes only to the talk machine.'
    assert "this Mac" not in title + status


def test_a_wake_that_fails_before_its_post_goes_back_to_dormant_instead_of_retrying(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        ctl, seen = box["ctl"], []

        async def create(sdp):
            seen.append(sdp)  # a retry reaching the server; the wake must not get this far
            ctl.state = "dormant"
            return 429, {"error": "unexpected"}

        ctl.create = create
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None and ctl.ear.frames)
        # The live call's microphone fails once (unplugged between the dormant stream and the wake).
        page.evaluate("""() => {
          const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices); let calls = 0;
          navigator.mediaDevices.getUserMedia = (c) => calls++ ? real(c) : Promise.reject(new Error("Requested device not found"));
        }""")
        begun = ctl.ear.begun
        on_loop(box, ctl.hear, {"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
        assert wait_for(lambda: ctl.ear.begun > begun)  # listening again
        page.wait_for_function("document.getElementById('status').textContent.includes('Requested device not found')")
        time.sleep(2.0)  # several poll ticks: none may retry the wake
        status, state = page.text_content("#status"), ctl.state
        browser.close()
    assert state == "dormant"
    assert seen == []
    assert "Still listening on this Mac." in status
    assert ctl.wake_segment["text"] == "Nova, is it three?"  # kept for the next attempt


def hang_create(box):
    """A session create that stays in flight until released; returns (calls, release)."""
    ctl, calls, gate = box["ctl"], [], {}

    async def create(sdp):
        gate["event"] = asyncio.Event()
        calls.append(sdp)
        await gate["event"].wait()
        return 410, {"error": "the call ended while the voice was connecting"}

    ctl.create = create
    return calls, lambda: gate and box["loop"].call_soon_threadsafe(gate["event"].set)


def test_end_works_while_the_page_is_connecting(tmp_path, pw):
    with served(tmp_path, dormant_after=0) as box:
        ctl = box["ctl"]
        calls, release = hang_create(box)
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: calls)  # connecting: the POST is in flight
        page.click("#stop", timeout=3000)
        page.click("#stop", timeout=3000)
        assert wait_for(lambda: ctl.done.is_set(), timeout=5)
        release()
        page.wait_for_function("document.body.dataset.state === 'ended'")
        time.sleep(1.0)
        state = page.evaluate("document.body.dataset.state")
        browser.close()
    assert state == "ended"


def test_end_works_while_a_meeting_is_waking_and_never_reopens_the_ear(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        ctl = box["ctl"]
        calls, release = hang_create(box)
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None and ctl.ear.frames)
        on_loop(box, ctl.hear, {"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
        assert wait_for(lambda: calls)  # waking: the ear is closed and the POST is in flight
        begun = ctl.ear.begun
        page.click("#stop", timeout=3000)
        page.click("#stop", timeout=3000)
        assert wait_for(lambda: ctl.done.is_set(), timeout=5)
        release()
        time.sleep(2.0)
        browser.close()
    assert ctl.ear.begun == begun


def test_the_projector_bar_gives_working_priority_over_muted(tmp_path, pw):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box:
        browser = pw.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Listening')")
        # As in the speaking test above: no real session here, so the state is set directly and the
        # real Space-key mute toggle repaints the bar.
        page.evaluate("document.body.dataset.state = 'thinking'")
        page.keyboard.press("Space")
        page.wait_for_function("document.getElementById('mute').getAttribute('aria-pressed') === 'true'")
        bar, kind = page.text_content("#pbartext"), page.evaluate("document.body.dataset.pbar")
        browser.close()
    assert bar == "Nova is looking it up… · Muted"
    assert kind == "thinking"
