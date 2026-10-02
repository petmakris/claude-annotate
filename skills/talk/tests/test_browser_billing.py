"""The page's own guards against a paid GPT-Live session left open: it closes the session itself when
the talk server stops answering, and when the tab goes away. A second page plays GPT-Live (see
go_live); no OpenAI session is created.

Skips without playwright: run with `--with playwright` (and `playwright install chromium` once)."""
import asyncio
import time

import pytest

pytest.importorskip("playwright", reason="browser suite: add --with playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import RecordingSocket, talk  # noqa: E402
from test_browser_dormant import FAKE_MIC, FAKE_VOICE, go_live, on_loop, served, wait_for  # noqa: E402

LOST = "Lost contact with the talk server; the voice was closed to stop billing."
RECORD = "() => { window.got = []; window.dc.onmessage = (e) => window.got.push(JSON.parse(e.data)); }"
CLOSE_SENT = "window.got.some(m => m.type === 'session.close')"


def test_a_page_that_loses_the_server_closes_its_voice_session(tmp_path):
    with served(tmp_path, dormant_after=45) as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        voice = go_live(box, browser, page)
        voice.evaluate(RECORD)
        page.route("**/api/state", lambda route: route.abort())  # talk.py is gone
        lost_at = time.monotonic()
        voice.wait_for_function(CLOSE_SENT, timeout=40000)
        waited = time.monotonic() - lost_at
        page.wait_for_function("document.getElementById('status').textContent.startsWith('Lost contact')")
        status = page.text_content("#status")
        page.wait_for_function("document.body.dataset.state === 'ended'")
        voice.wait_for_function("window.pc.connectionState !== 'connected'", timeout=15000)
        browser.close()
    assert 19.5 <= waited < 27  # a 25 s outage closes the voice; see the 6 s one below
    assert status == LOST


def test_a_six_second_outage_keeps_the_call(tmp_path):
    with served(tmp_path, dormant_after=45) as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        voice = go_live(box, browser, page)
        voice.evaluate(RECORD)
        page.route("**/api/state", lambda route: route.abort())
        page.wait_for_timeout(6000)  # sync Playwright runs route handlers only while it waits itself
        page.unroute("**/api/state")
        page.wait_for_timeout(3000)
        got = voice.evaluate("window.got")
        status, state = page.text_content("#status"), page.evaluate("document.body.dataset.state")
        browser.close()
    assert got == [] and not status.startswith("Lost contact") and state != "ended"


def test_a_poll_still_in_flight_is_not_stacked_on(tmp_path):
    with served(tmp_path, dormant_after=45) as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        seen = []
        page.route("**/api/state", lambda route: seen.append(route))  # never answered: a hung server
        page.wait_for_timeout(3000)
        count = len(seen)
        browser.close()
    assert count == 1  # one request waits out its 4 s timeout; the 700 ms ticks skip meanwhile


def test_leaving_the_page_closes_its_voice_session(tmp_path):
    with served(tmp_path, dormant_after=45) as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.on("dialog", lambda d: d.accept())  # the "leave this call?" prompt
        page.goto(box["url"])
        voice = go_live(box, browser, page)
        voice.evaluate(RECORD)
        page.goto("about:blank")
        voice.wait_for_function(CLOSE_SENT, timeout=5000)
        browser.close()


# Every RTCPeerConnection the page makes, so a test can see that none is left open.
TRACK_PEERS = """(() => { const Real = window.RTCPeerConnection; window.pcs = [];
  window.RTCPeerConnection = function (...a) { const pc = new Real(...a); window.pcs.push(pc); return pc; };
  window.RTCPeerConnection.prototype = Real.prototype; })();"""
ALL_CLOSED = "window.pcs.length > 0 && window.pcs.every(pc => pc.signalingState === 'closed')"


def test_a_wake_the_page_cannot_use_after_create_closes_the_session_and_the_peer(tmp_path):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box, sync_playwright() as p:
        ctl = box["ctl"]

        async def create(sdp):  # OpenAI created the session, but its answer is unusable
            ctl.session_id, ctl.sessions, ctl.state = "s1", ctl.sessions + 1, "live"
            ctl.wake_segment = None  # consumed, as the real create() does
            ctl.ws = RecordingSocket()
            ctl.attached.set()
            return 201, {"session": {"id": "s1"}, "transport": {"sdp": "not an sdp"}}

        ctl.create = create
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.add_init_script(TRACK_PEERS)
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None)
        on_loop(box, ctl.hear, {"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
        assert wait_for(lambda: isinstance(ctl.ws, RecordingSocket) and ctl.ws.events)
        sent = [e["type"] for e in ctl.ws.events]
        page.wait_for_function(ALL_CLOSED)
        on_loop(box, ctl.sideband_ended, "s1")  # GPT-Live confirms; the sideband ends
        assert wait_for(lambda: ctl.state == "dormant" and ctl.session_id is None)
        browser.close()
    assert sent == ["session.close"]


SILENT_VOICE = FAKE_VOICE.replace('e.channel.send(JSON.stringify({ type: "session.started" }))', "null")


def test_a_session_the_server_closed_for_never_starting_drops_the_pages_peer(tmp_path):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box, sync_playwright() as p:
        ctl, seen = box["ctl"], {}

        async def create(sdp):
            seen["answer"] = asyncio.get_running_loop().create_future()
            seen["offer"] = sdp
            answer = await seen["answer"]
            ctl.session_id, ctl.sessions, ctl.state = "s1", ctl.sessions + 1, "live"
            ctl.ws = RecordingSocket()
            ctl.attached.set()
            return 201, {"session": {"id": "s1"}, "transport": {"sdp": answer}}

        ctl.create = create
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.add_init_script(TRACK_PEERS)
        page.goto(box["url"])
        voice = browser.new_page()
        voice.evaluate("() => {" + SILENT_VOICE + "}")
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None)
        on_loop(box, ctl.hear, {"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
        assert wait_for(lambda: "offer" in seen)
        sdp = voice.evaluate("offer => window.answer(offer)", seen["offer"])
        box["loop"].call_soon_threadsafe(seen["answer"].set_result, sdp)
        voice.wait_for_function("window.dc && window.dc.readyState === 'open'")
        begun = ctl.ear.begun

        def closed_unstarted():  # what abandon_start() and the sideband's end leave behind
            ctl.failed_starts += 1
            ctl.state, ctl.session_id = "dormant", None

        on_loop(box, closed_unstarted)
        page.wait_for_function(ALL_CLOSED)
        assert wait_for(lambda: ctl.ear.begun > begun)  # listening locally again
        page.wait_for_function("document.getElementById('status').textContent.includes('did not start')")
        status = page.text_content("#status")
        browser.close()
    assert status.startswith("The voice did not start, so it was closed to stop billing.")


def test_a_capped_dormant_page_says_why_it_will_not_wake_and_shows_todays_total(tmp_path):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box, sync_playwright() as p:
        ctl = box["ctl"]
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None)
        page.wait_for_function("document.getElementById('cost').textContent.includes('today $')")
        cost = page.text_content("#cost")
        on_loop(box, setattr, ctl, "capped", talk.call_cap_message(30))
        page.wait_for_function("document.getElementById('status').textContent.startsWith('Live-minute cap')")
        status = page.text_content("#status")
        time.sleep(1.0)  # later poll ticks keep it
        after = page.text_content("#status")
        browser.close()
    assert "· today $0.00" in cost
    assert status == after == ("Live-minute cap for this call reached (30 min, $1.50). End the call, or start a "
                               "new one with a higher --max-live-minutes.")


NO_CREDIT = "OpenAI account has no credit — add credit at https://platform.openai.com/settings/organization/billing"


def test_a_failed_start_shows_why_and_leaves_start_usable(tmp_path):
    with served(tmp_path, dormant_after=0) as box, sync_playwright() as p:
        ctl, calls = box["ctl"], []

        async def create(sdp):
            calls.append(sdp)
            return 429, {"error": NO_CREDIT}

        ctl.create = create
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.add_init_script(TRACK_PEERS)
        page.goto(box["url"])
        page.click("#start")
        page.wait_for_function("document.getElementById('status').textContent.includes('no credit')")
        time.sleep(1.0)  # poll ticks must not replace it
        status = page.text_content("#status")
        usable = page.evaluate("!document.getElementById('start').disabled")
        state = page.evaluate("document.body.dataset.state")
        page.wait_for_function(ALL_CLOSED)
        page.click("#start")
        assert wait_for(lambda: len(calls) == 2)  # pressing Start again tries again
        browser.close()
    assert status == NO_CREDIT
    assert usable and state == "idle"


def test_the_cost_line_links_the_real_bill(tmp_path):
    with served(tmp_path, dormant_after=0) as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.wait_for_function("document.getElementById('cost').textContent.includes('GPT-Live')")
        link = page.eval_on_selector("#cost a", "a => [a.textContent, a.getAttribute('href')]")
        browser.close()
    assert link == ["real bill ↗", "https://platform.openai.com/usage"]


def test_a_page_leaving_a_live_session_for_dormancy_tells_gpt_live_to_close_it(tmp_path):
    with served(tmp_path, dormant_after=45) as box, sync_playwright() as p:
        ctl = box["ctl"]
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        voice = go_live(box, browser, page)
        voice.evaluate(RECORD)
        on_loop(box, setattr, ctl, "state", "dormant")  # the server slept; GPT-Live never said closed
        voice.wait_for_function(CLOSE_SENT, timeout=10000)
        browser.close()


def test_a_page_ending_the_call_tells_gpt_live_to_close_the_session(tmp_path):
    with served(tmp_path, dormant_after=0) as box, sync_playwright() as p:
        ctl = box["ctl"]
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        voice = go_live(box, browser, page)
        voice.evaluate(RECORD)
        on_loop(box, ctl.done.set)  # the call ended on the server
        voice.wait_for_function(CLOSE_SENT, timeout=10000)
        browser.close()


def test_the_cost_line_spans_the_card_like_the_status_line(tmp_path):
    with served(tmp_path, dormant_after=0) as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.wait_for_function("document.getElementById('cost').textContent.includes('GPT-Live')")
        cost, status = (page.eval_on_selector(s, "e => { const r = e.getBoundingClientRect(); return [r.left, r.width]; }")
                        for s in ("#cost", "#status"))
        browser.close()
    assert cost == status
