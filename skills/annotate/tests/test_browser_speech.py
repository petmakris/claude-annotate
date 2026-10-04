# skills/annotate/tests/test_browser_speech.py
"""Read-aloud and dictation, driven in a real browser against the local
daemon's page, with Azure and the daemon's speech routes replaced: the routes
by page.route, the SDK by a scripted double installed before the page loads.
Nothing here reaches Azure or runs claude."""
from __future__ import annotations

import json

import pytest

from skills.tests.harness import T, require_playwright, transitions_done  # noqa: E402

require_playwright()

from skills.annotate.tests.test_browser_review import (  # noqa: E402,F401
    BLOCKS, SEL, _PHONE_SELECT_JS, _call, _decorated, _phone, _put_block, document, page)

STATUS_OK = {"configured": True, "claude": True, "region": "westeurope"}


def _routes(page, status=STATUS_OK, script=None, script_status=200, token_calls=None):
    def status_route(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(status))

    def token_route(route):
        if token_calls is not None:
            token_calls.append(route.request.headers.get("x-webcompanion-contract"))
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"token": "tok", "region": "westeurope", "expires_in": 540}))

    def script_route(route):
        body = script or {"pieces": [{"say": "First, the point.", "src": "Paragraph one"}], "cached": False}
        route.fulfill(status=script_status, content_type="application/json" if script_status == 200 else "text/plain",
                      body=json.dumps(body) if script_status == 200 else body)

    page.route("**/api/speech/status", status_route)
    page.route("**/api/speech/token", token_route)
    page.route("**/api/speech/script", script_route)


def test_status_and_token_go_to_the_root_routes_with_the_contract_header(page):
    calls = []
    _routes(page, token_calls=calls)
    out = page.evaluate("""async () => {
      const s = await AnnotateSpeechClient.status();
      const t = await AnnotateSpeechClient.token();
      return {s, t}; }""")
    assert out["s"]["configured"] is True
    assert out["t"] == {"token": "tok", "region": "westeurope"}
    assert calls == ["1"]


def test_a_token_is_reused_until_it_expires_then_refreshed(page):
    calls = []
    _routes(page, token_calls=calls)
    page.evaluate("""async () => {
      const realNow = Date.now; let skew = 0; Date.now = () => realNow() + skew;
      await AnnotateSpeechClient.token(); await AnnotateSpeechClient.token();
      skew = 541 * 1000; await AnnotateSpeechClient.token(); }""")
    assert len(calls) == 2


def test_the_script_is_cached_by_its_request(page):
    _routes(page)
    n = page.evaluate("""async () => {
      let n = 0; const orig = window.fetch;
      window.fetch = (u, o) => { if (String(u).includes('/api/speech/script')) n++; return orig(u, o); };
      const req = {selection: 'Paragraph one', context: '', glossary: [], page_title: 'T'};
      await AnnotateSpeechClient.script(req); await AnnotateSpeechClient.script(req);
      return n; }""")
    assert n == 1


def test_a_script_failure_carries_the_daemons_words_and_status(page):
    _routes(page, script="busy: two explanations are already being written; try again in a moment",
            script_status=503)
    err = page.evaluate("""async () => {
      try { await AnnotateSpeechClient.script({selection: 'x', context: '', glossary: [], page_title: ''}); }
      catch (e) { return {m: e.message, s: e.status}; } }""")
    assert err == {"m": "busy: two explanations are already being written; try again in a moment", "s": 503}


def test_the_page_context_carries_the_glossary_and_block_text(page, document):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__doc__",
          {"response_id": "resp-browser-suite", "title": "annotate browser suite", "order": BLOCKS,
           "glossary": [{"term": "EDR", "definition": "External data reference"}]})
    page.reload()
    # The glossary arrives after the client has loaded.
    page.wait_for_function("() => !!window.AnnotateSpeechClient && window.AnnotateGlossary?.terms?.().length > 0")
    ctx = page.evaluate(f"""() => AnnotateSpeechClient.pageContext(document.querySelector('{SEL.format("section-1")}'))""")
    assert ctx["glossary"][0]["term"] == "EDR"
    assert "Paragraph one of block 1" in ctx["context"]
    assert ctx["page_title"]


def _count(page, path):
    calls = []
    page.on("request", lambda r: calls.append(r.url) if path in r.url else None)
    return calls


def test_a_not_configured_status_is_asked_again_and_a_configured_one_is_kept(page):
    calls = _count(page, "/api/speech/status")
    _routes(page, status={"configured": False, "claude": True, "reason": "not set"})
    page.evaluate("async () => { await AnnotateSpeechClient.status(); await AnnotateSpeechClient.status(); }")
    assert len(calls) == 2, "a configured:false answer was cached"
    page.unroute("**/api/speech/status")
    _routes(page)
    page.evaluate("async () => { await AnnotateSpeechClient.status(); await AnnotateSpeechClient.status(); }")
    assert len(calls) == 3, "a configured:true answer was not kept"


def test_two_first_calls_at_once_share_one_request(page):
    status_calls = _count(page, "/api/speech/status")
    token_calls = []
    _routes(page, token_calls=token_calls)
    page.evaluate("""async () => {
      await Promise.all([AnnotateSpeechClient.status(), AnnotateSpeechClient.status()]);
      await Promise.all([AnnotateSpeechClient.token(), AnnotateSpeechClient.token()]); }""")
    assert len(status_calls) == 1
    assert len(token_calls) == 1


def test_a_failed_status_or_token_is_not_remembered(page):
    n = {"status": 0, "token": 0}

    def flaky(kind, body):
        def route(r):
            n[kind] += 1
            if n[kind] == 1:
                r.fulfill(status=500, content_type="text/plain", body="down")
            else:
                r.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        return route
    page.route("**/api/speech/status", flaky("status", STATUS_OK))
    page.route("**/api/speech/token", flaky("token", {"token": "tok", "region": "westeurope", "expires_in": 540}))
    out = page.evaluate("""async () => {
      const r = [];
      for (const f of ['status', 'token']) {
        try { await AnnotateSpeechClient[f](); r.push('ok'); } catch (e) { r.push(e.status); }
        try { await AnnotateSpeechClient[f](); r.push('ok'); } catch (e) { r.push(e.status); }
      }
      return r; }""")
    assert out == [500, "ok", 500, "ok"]


def test_an_sdk_that_loads_without_starting_is_tried_again(page):
    bodies = ["/* loaded, but defines nothing */", "window.SpeechSDK = {started: true};"]
    page.route("**/vendor/speech-sdk.min.js", lambda r: r.fulfill(
        status=200, content_type="application/javascript", body=bodies.pop(0)))
    out = page.evaluate("""async () => {
      let first;
      try { await AnnotateSpeechClient.loadSdk(); first = 'resolved'; } catch (e) { first = e.message; }
      const sdk = await AnnotateSpeechClient.loadSdk();
      return {first, started: sdk.started,
              tags: document.querySelectorAll('script[src*="speech-sdk.min.js"]').length}; }""")
    assert out == {"first": "The speech engine loaded but did not start", "started": True, "tags": 1}


def test_the_owner_token_is_sent_when_the_page_holds_one(page):
    seen = []
    _routes(page)
    page.on("request", lambda r: seen.append(r.headers.get("x-webcompanion-token"))
            if "/api/speech/token" in r.url else None)
    page.evaluate("""async () => {
      sessionStorage.setItem('webcompanion.token.' + location.host, 'owner-secret');
      await AnnotateSpeechClient.token(); }""")
    assert seen == ["owner-secret"]


# A scripted SpeechSDK, shaped like Azure's: speakTextAsync emits one
# WordBoundary per word of the text it is given, 400 ms apart, whose text
# carries no punctuation ("three", not "three."), and a separate
# PunctuationBoundary for each mark, then returns a silent WAV of the right
# length. Like Azure it answers only once all the audio exists, after a time
# that grows with the text: window.__msPerChar (default 2; Azure measured
# about 8) per character. Installed before any page script runs. The page asks for MP3 and
# labels the blob audio/mpeg; the browser sniffs the WAV regardless.
# window.__badBoundaryAt = n adds a boundary with textOffset -1 right after
# word n, at the same audio offset, as Azure can send for SSML it inserted.
SDK_DOUBLE = """
(() => {
  function wav(ms) {
    const rate = 8000, n = Math.max(1, Math.round(rate * ms / 1000));
    const b = new ArrayBuffer(44 + n * 2), v = new DataView(b);
    const s = (o, t) => [...t].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
    s(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); s(8, 'WAVE'); s(12, 'fmt ');
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true);
    v.setUint16(34, 16, true); s(36, 'data'); v.setUint32(40, n * 2, true); return b;
  }
  window.__spoken = [];
  window.__release = () => { window.__holdFrom = null; (window.__held || []).splice(0).forEach((f) => f()); };
  window.SpeechSDK = {
    SpeechConfig: { fromAuthorizationToken: (t, r) => ({ token: t, region: r }) },
    ResultReason: { SynthesizingAudioCompleted: 10, RecognizedSpeech: 3 },
    SpeechSynthesisOutputFormat: { Audio16Khz32KBitRateMonoMp3: 3, Audio24Khz48KBitRateMonoMp3: 8 },
    SpeechSynthesizer: class {
      constructor(cfg) { this.cfg = cfg; this.wordBoundary = null; }
      speakTextAsync(text, ok, err) {
        window.__spoken.push({ text, voice: this.cfg.speechSynthesisVoiceName,
                               format: this.cfg.speechSynthesisOutputFormat });
        const call = window.__spoken.length - 1;
        if (window.__synthFail) { setTimeout(() => err('synthesis failed'), 0); return; }
        if (window.__failNext === call) { window.__failNext = null; setTimeout(() => err('Connection was closed'), 0); return; }
        let at = 0, n = 0;
        const emit = (e) => this.wordBoundary && this.wordBoundary(this, e);
        for (const m of text.matchAll(/[A-Za-z0-9'\u2019-]+|[.,!?;:]/g)) {
          if (/^[.,!?;:]$/.test(m[0])) {
            emit({ boundaryType: 'PunctuationBoundary', audioOffset: at * 10000, duration: 0,
                   textOffset: m.index, wordLength: 1, text: m[0] });
            continue;
          }
          emit({ boundaryType: 'WordBoundary', audioOffset: at * 10000, duration: 300 * 10000,
                 textOffset: m.index, wordLength: m[0].length, text: m[0] });
          if (window.__badBoundaryAt === n)
            emit({ boundaryType: 'WordBoundary', audioOffset: at * 10000, duration: 0,
                   textOffset: -1, wordLength: 0, text: '' });
          n++;
          at += 400;
        }
        const wait = (window.__msPerChar ?? 2) * text.length;
        const done = () => ok({ reason: 10, audioData: wav(at + 200), audioDuration: (at + 200) * 10000 });
        // window.__holdFrom = n keeps call n and later unanswered until __release().
        if (window.__holdFrom != null && call >= window.__holdFrom) { (window.__held ||= []).push(done); return; }
        setTimeout(done, wait);
      }
      close() {}
    },
  };
})();
"""


@pytest.fixture
def spage(page):
    page.add_init_script(SDK_DOUBLE)
    page.reload()
    page.wait_for_function("() => !!window.AnnotateSpeech")
    # speech.js can load before script.js has drawn the cards.
    page.wait_for_selector("section.block .card-title", timeout=T(15000))
    return page


def _sel(page, anchor, needle):
    page.evaluate("""([sel, needle]) => { const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s); const i = AnnotateAnchors.textOf(root).indexOf(needle);
      const r = AnnotateAnchors.rangeFrom(root, i, i + needle.length);
      getSelection().removeAllRanges(); getSelection().addRange(r);
      const b = r.getBoundingClientRect();
      document.elementFromPoint(b.left + 2, b.top + b.height / 2)
        .dispatchEvent(new MouseEvent('mouseup', {bubbles: true, clientX: b.left + 2, clientY: b.top + b.height / 2})); }""",
                  [SEL.format(anchor), needle])
    page.wait_for_selector(".sel-menu", timeout=T(3000))


def test_explain_joins_the_menu_after_the_feedback_buttons(spage):
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.wait_for_selector('.sel-menu button[data-act="explain"]', timeout=T(3000))
    acts = spage.eval_on_selector_all(".sel-menu button", "bs => bs.map(b => b.dataset.act)")
    assert acts[:3] == ["comment", "delete", "compact"] and "explain" in acts and "voice-more" in acts


def test_explain_plays_the_script_and_lights_words_and_the_page_in_step(spage):
    _routes(spage, script={"pieces": [
        {"say": "First, the point.", "src": "Paragraph one"},
        {"say": "Then the rest.", "src": "long enough"}], "cached": False})
    _sel(spage, "section-1", "Paragraph one of block 1, long enough")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.inner_text(".sp-card .sp-script") == "First, the point. Then the rest."
    assert spage.evaluate("() => window.__spoken[0].voice") == "en-US-AvaMultilingualNeural"
    assert spage.evaluate("() => window.__spoken[0].format") == 8, "the page did not ask for MP3"
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'the'", timeout=T(5000))
    assert spage.evaluate("() => CSS.highlights.get('annotate-speaking')?.size") == 1
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Then'", timeout=T(5000))
    lit = spage.evaluate("""() => [...CSS.highlights.get('annotate-speaking')][0].toString()""")
    assert lit == "long enough"


def test_pause_back_and_speed_follow_the_audio_clock(spage):
    _routes(spage, script={"pieces": [{"say": "One two three. Four five six.", "src": "Paragraph one"}], "cached": False})
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Five'"
                            .replace("Five", "five"), timeout=T(8000))
    spage.click('.sp-card [data-sp="toggle"]')
    held = spage.inner_text(".sp-card .w.now")
    spage.wait_for_timeout(700)
    assert spage.inner_text(".sp-card .w.now") == held, "the highlight moved while paused"
    spage.click('.sp-card [data-sp="back"]')
    assert spage.inner_text(".sp-card .w.now") == "Four"
    spage.click('.sp-card [data-sp="speed"] button[data-rate="1.2"]')
    assert spage.evaluate("() => document.querySelector('.sp-card audio').playbackRate") == 1.2


def test_read_as_written_speaks_the_selection_itself_without_a_script(spage):
    calls = []
    _routes(spage)
    spage.on("request", lambda r: calls.append(r.url) if "/api/speech/script" in r.url else None)
    _sel(spage, "section-1", "Paragraph one of block 1")
    spage.click('.sel-menu button[data-act="voice-more"]')
    spage.click('.sel-menu button[data-act="read"]')
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.evaluate("() => window.__spoken[0].text") == "Paragraph one of block 1"
    assert calls == []


def test_a_failed_script_offers_read_as_written_instead(spage):
    _routes(spage, script="claude could not write the explanation: Not logged in", script_status=502)
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .sp-error", timeout=T(5000))
    assert "Couldn't write an explanation" in spage.inner_text(".sp-card .sp-error")
    assert "Not logged in" in spage.inner_text(".sp-card .sp-error")
    spage.click('.sp-card button[data-sp="fallback"]')
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))


def test_voice_buttons_are_disabled_when_speech_is_not_set_up(spage):
    _routes(spage, status={"configured": False, "claude": True,
                           "reason": "AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are not both set"})
    _sel(spage, "section-1", "Paragraph one")
    b = spage.locator('.sel-menu button[data-act="explain"]')
    b.wait_for(timeout=T(3000))
    assert b.is_disabled()
    assert "webcompanion doctor" in b.get_attribute("title")
    assert b.get_attribute("aria-label") == b.get_attribute("title"), "the reason is not read out"



def test_a_rewrite_while_playing_stops_cleanly(spage, document):
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .w.now", timeout=T(5000))
    _put_block(document, "section-1", "Brand new words.", title="Block 1")
    spage.wait_for_function("() => !document.querySelector('.sp-card')", timeout=T(10000))
    assert spage.evaluate("() => CSS.highlights.get('annotate-speaking')?.size || 0") == 0
    assert spage.__dict__["js_errors"] == []


def test_the_voice_setting_reaches_the_synthesizer(spage):
    spage.evaluate("() => localStorage.setItem('annotate.view:speechvoice', 'sonia')")
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="voice-more"]')
    spage.click('.sel-menu button[data-act="read"]')
    spage.wait_for_function("() => window.__spoken.length === 1", timeout=T(5000))
    assert spage.evaluate("() => window.__spoken[0].voice") == "en-GB-SoniaNeural"


def test_r_explains_and_shift_r_reads_as_written_from_the_menu(spage):
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.wait_for_function("""() => { const b = document.querySelector('.sel-menu button[data-act="explain"]');
      return b && !b.disabled; }""", timeout=T(3000))
    spage.keyboard.press("r")
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.inner_text(".sp-card .sp-head b") == "Explained aloud"
    _sel(spage, "section-1", "Paragraph one of block 1")
    spage.wait_for_function("""() => { const b = document.querySelector('.sel-menu button[data-act="voice-more"]');
      return b && !b.disabled; }""", timeout=T(3000))
    spage.keyboard.press("Shift+R")
    spage.wait_for_function("() => window.__spoken.length === 2", timeout=T(5000))
    assert spage.evaluate("() => window.__spoken[1].text") == "Paragraph one of block 1"
    assert spage.inner_text(".sp-card .sp-head b") == "Read as written"
    assert spage.locator(".sp-card").count() == 1


def test_the_card_is_not_page_text_and_its_buttons_do_not_reopen_the_menu(spage):
    _routes(spage, script={"pieces": [{"say": "Unmistakable card words.", "src": "Paragraph one"}], "cached": False})
    _sel(spage, "section-1", "Paragraph one of block 1")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .w.now", timeout=T(5000))
    text = spage.evaluate(f"""() => AnnotateAnchors.textOf(AnnotateAnchors.contentOf(
        document.querySelector('{SEL.format("section-1")}')))""")
    assert "Unmistakable" not in text, "the card's script became part of the page's text"
    spage.click('.sp-card [data-sp="toggle"]')
    spage.wait_for_timeout(300)
    assert spage.locator(".sel-menu").count() == 0, "pausing reopened the selection menu"


# ── review fixes ────────────────────────────────────────────────────────────

def _explain(page, needle="Paragraph one", script=None):
    _routes(page, script=script)
    _sel(page, "section-1", needle)
    page.click('.sel-menu button[data-act="explain"]')
    page.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))


def test_the_progress_bar_shows_elapsed_and_total_from_the_audio(spage):
    _explain(spage, script={"pieces": [{"say": "One two three four five six seven.", "src": "Paragraph one"}],
                            "cached": False})
    # seven words at 400 ms plus 200 ms: 3.0 s of audio
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'four'", timeout=T(8000))
    out = spage.evaluate("""() => { const a = document.querySelector('.sp-card audio');
      const bar = document.querySelector('.sp-card [data-sp="progress"]');
      return {time: document.querySelector('.sp-card .sp-time').textContent,
              now: Number(bar.getAttribute('aria-valuenow')), max: Number(bar.getAttribute('aria-valuemax')),
              fill: parseFloat(bar.querySelector('i').style.width), t: a.currentTime, d: a.duration}; }""")
    assert out["time"] == "0:01 / 0:03", out
    assert out["max"] == 3 and 1 <= out["now"] <= 2, out
    assert abs(out["fill"] - 100 * out["t"] / out["d"]) < 15, out


def test_the_mode_switch_replays_the_same_selection_the_other_way(spage):
    _explain(spage, needle="Paragraph one of block 1")
    modes = spage.eval_on_selector_all('.sp-card [data-sp="mode"] button',
                                       "bs => bs.map(b => [b.dataset.mode, b.getAttribute('aria-pressed')])")
    assert modes == [["explain", "true"], ["read", "false"]]
    spage.click('.sp-card [data-sp="mode"] button[data-mode="read"]')
    spage.wait_for_function("() => window.__spoken.length === 2", timeout=T(5000))
    assert spage.evaluate("() => window.__spoken[1].text") == "Paragraph one of block 1"
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.locator(".sp-card").count() == 1
    assert spage.inner_text(".sp-card .sp-head b") == "Read as written"
    spage.click('.sp-card [data-sp="mode"] button[data-mode="explain"]')
    spage.wait_for_function("() => window.__spoken.length === 3", timeout=T(5000))
    assert spage.evaluate("() => window.__spoken[2].text") == "First, the point."


def test_azure_not_answering_offers_a_retry(spage):
    n = {"token": 0}

    def token_once_down(route):
        n["token"] += 1
        if n["token"] == 1:
            route.fulfill(status=502, content_type="text/plain", body="Azure did not answer")
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"token": "tok", "region": "westeurope", "expires_in": 540}))
    _routes(spage)
    spage.route("**/api/speech/token", token_once_down)
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .sp-error", timeout=T(5000))
    assert "Azure didn't answer" in spage.inner_text(".sp-card .sp-error")
    spage.click('.sp-card button[data-sp="retry"]')
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert n["token"] == 2


def test_the_audio_element_is_unlocked_inside_the_click(spage):
    # Safari lets an element play later only if it played inside the gesture.
    spage.evaluate("""() => { window.__plays = [];
      const orig = HTMLMediaElement.prototype.play;
      HTMLMediaElement.prototype.play = function () {
        if (!this.__id) this.__id = Math.random();
        window.__plays.push({id: this.__id, during: window.event ? window.event.type : null,
                             blob: (this.src || '').startsWith('blob:')});
        return orig.apply(this, arguments); }; }""")
    _explain(spage)
    spage.wait_for_selector(".sp-card .w.now", timeout=T(5000))
    plays = spage.evaluate("() => window.__plays")
    assert plays[0]["during"] == "click" and not plays[0]["blob"], plays
    assert any(p["blob"] and p["id"] == plays[0]["id"] for p in plays[1:]), plays


# Counted only from speech.js: a11y.js asks for a frame on DOM mutations.
def test_when_the_audio_ends_nothing_stays_lit_and_nothing_keeps_ticking(spage):
    _explain(spage, script={"pieces": [{"say": "One two.", "src": "Paragraph one"}], "cached": False})
    spage.wait_for_function("() => document.querySelector('.sp-card audio').ended", timeout=T(8000))
    spage.wait_for_timeout(100)
    out = spage.evaluate("""async () => {
      let n = 0; const orig = window.requestAnimationFrame;
      window.requestAnimationFrame = (f) => { if (/speech\\.js/.test(new Error().stack)) n++; return orig(f); };
      await new Promise((r) => setTimeout(r, 300));
      window.requestAnimationFrame = orig;
      return {now: document.querySelectorAll('.sp-card .w.now').length,
              done: [...document.querySelectorAll('.sp-card .w')].every((w) => w.classList.contains('done')),
              lit: CSS.highlights.get('annotate-speaking')?.size || 0, ticks: n}; }""")
    assert out == {"now": 0, "done": True, "lit": 0, "ticks": 0}


def test_nothing_ticks_while_paused(spage):
    _explain(spage, script={"pieces": [{"say": "One two three four five six.", "src": "Paragraph one"}],
                            "cached": False})
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'two'", timeout=T(8000))
    spage.click('.sp-card [data-sp="toggle"]')
    ticks = spage.evaluate("""async () => {
      let n = 0; const orig = window.requestAnimationFrame;
      window.requestAnimationFrame = (f) => { if (/speech\\.js/.test(new Error().stack)) n++; return orig(f); };
      await new Promise((r) => setTimeout(r, 300));
      window.requestAnimationFrame = orig; return n; }""")
    assert ticks == 0
    spage.click('.sp-card [data-sp="toggle"]')
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'four'", timeout=T(8000))


def test_caps_lock_r_explains_and_only_shift_reads(spage):
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.wait_for_function("""() => { const b = document.querySelector('.sel-menu button[data-act="explain"]');
      return b && !b.disabled; }""", timeout=T(3000))
    spage.evaluate("""() => document.dispatchEvent(new KeyboardEvent('keydown',
      {key: 'R', shiftKey: false, bubbles: true, cancelable: true}))""")
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.inner_text(".sp-card .sp-head b") == "Explained aloud"


def test_dimmed_words_meet_contrast_in_both_themes(spage):
    _explain(spage, script={"pieces": [{"say": "One two three four five six seven eight.", "src": "Paragraph one"}],
                            "cached": False})
    spage.click('.sp-card [data-sp="toggle"]')
    got = {}
    for theme in ("light", "dark"):
        spage.evaluate("t => { document.body.dataset.pageTheme = t; }", theme)
        transitions_done(spage)
        got[theme] = spage.evaluate("""() => {
          const rgba = (s) => { const m = s.match(/[\\d.]+/g).map(Number); return [m[0], m[1], m[2], m[3] ?? 1]; };
          const over = (top, bot) => [0, 1, 2].map((i) => top[i] * top[3] + bot[i] * (1 - top[3])).concat(1);
          let bg = [255, 255, 255, 1];
          const chain = []; for (let e = document.querySelector('.sp-card'); e; e = e.parentElement) chain.unshift(e);
          for (const e of chain) bg = over(rgba(getComputedStyle(e).backgroundColor), bg);
          const w = [...document.querySelectorAll('.sp-card .w')].find((x) => !x.classList.contains('now')
                                                                      && !x.classList.contains('done'));
          const cs = getComputedStyle(w); const fg = rgba(cs.color); fg[3] = Number(cs.opacity);
          const eff = over(fg, bg);
          const lum = (c) => { const [r, g, b] = c.slice(0, 3).map((v) => { v /= 255;
            return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
          const a = lum(eff), b = lum(bg);
          return {ratio: Math.round(100 * (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)) / 100,
                  opacity: Number(cs.opacity)}; }""")
    print("dimmed-word contrast", got)
    assert got["light"]["opacity"] == 0.74 and got["dark"]["opacity"] == 0.6, got
    assert got["light"]["ratio"] >= 4.5 and got["dark"]["ratio"] >= 4.5, got


def test_a_boundary_with_no_place_in_the_text_is_ignored(spage):
    spage.evaluate("() => { window.__badBoundaryAt = 1; }")
    _explain(spage, script={"pieces": [{"say": "One two three four five six.", "src": "Paragraph one"}],
                            "cached": False})
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'two'", timeout=T(8000))


def test_a_repeated_sentence_lights_the_occurrence_that_was_selected(spage, document):
    _put_block(document, "section-1", "Same words here. Other words. Same words here.", title="Block 1")
    spage.wait_for_function(f"""() => (document.querySelector('{SEL.format("section-1")}')?.textContent || '')
      .includes('Other words')""", timeout=T(10000))
    _routes(spage)
    _sel(spage, "section-1", "Other words. Same words here.")
    spage.click('.sel-menu button[data-act="voice-more"]')
    spage.click('.sel-menu button[data-act="read"]')
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Same'", timeout=T(8000))
    start = spage.evaluate(f"""() => {{ const root = AnnotateAnchors.contentOf(document.querySelector('{SEL.format("section-1")}'));
      const r = [...CSS.highlights.get('annotate-speaking')][0];
      const text = AnnotateAnchors.textOf(root);
      return [r.toString(), text.indexOf('Same words here.', 1) ,
              AnnotateAnchors.offsetsOf ? null : null,
              (() => {{ const pre = document.createRange(); pre.setStart(root, 0); pre.setEnd(r.startContainer, r.startOffset);
                       return pre.toString().replace(/\\s+/g, ' ').trimStart().length; }})()]; }}""")
    assert start[0] == "Same words here."
    assert start[3] > 10, f"the first occurrence was lit, not the selected one: {start}"


REC_DOUBLE = """
(() => {
  const base = window.SpeechSDK;
  window.__rec = null;
  window.SpeechSDK = Object.assign({}, base, {
    AudioConfig: { fromDefaultMicrophoneInput: () => ({ mic: true }) },
    PhraseListGrammar: { fromRecognizer: (r) => ({ addPhrase: (p) => r.phrases.push(p) }) },
    SpeechRecognizer: class {
      constructor(cfg) { this.cfg = cfg; this.phrases = []; this.stopped = false; window.__rec = this; }
      startContinuousRecognitionAsync(ok) { setTimeout(() => ok && ok(), 0); }
      stopContinuousRecognitionAsync(ok) { this.stopped = true; setTimeout(() => ok && ok(), 0); }
      close() {}
    },
  });
  window.__say = (partial, final) => {
    const r = window.__rec;
    if (partial) r.recognizing && r.recognizing(r, { result: { text: partial } });
    if (final) r.recognized && r.recognized(r, { result: { reason: 3, text: final } });
  };
})();
"""


@pytest.fixture
def dpage(page):
    page.add_init_script(SDK_DOUBLE)
    page.add_init_script(REC_DOUBLE)
    page.reload()
    page.wait_for_function("() => !!window.AnnotateSpeech")
    page.wait_for_selector("section.block .card-title", timeout=T(15000))
    return page


def _open_span_comment(page):
    _sel(page, "section-1", "Paragraph one")
    page.click('.sel-menu button[data-act="comment"]')
    page.wait_for_selector(".sel-composer textarea")


def test_dictation_writes_grey_then_solid_text_into_the_box(dpage):
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec && !!window.__rec.recognizing", timeout=T(5000))
    dpage.evaluate("() => __say('the taxon', null)")
    assert dpage.inner_text(".sel-composer .voice-interim") == "the taxon"
    assert dpage.input_value(".sel-composer textarea") == ""
    dpage.evaluate("() => __say(null, 'The taxon waits for EDR.')")
    assert dpage.input_value(".sel-composer textarea") == "The taxon waits for EDR."
    assert dpage.inner_text(".sel-composer .voice-interim") == ""


def test_dictation_is_primed_with_the_glossary(dpage, document):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__doc__",
          {"response_id": "resp-browser-suite", "title": "annotate browser suite", "order": BLOCKS,
           "glossary": [{"term": "EDR"}, {"term": "taxon"}]})
    dpage.reload()
    dpage.wait_for_function("() => !!window.AnnotateSpeech && window.AnnotateGlossary?.terms?.().length === 2")
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => window.__rec && window.__rec.phrases.length === 2", timeout=T(5000))
    assert dpage.evaluate("() => window.__rec.phrases") == ["EDR", "taxon"]


def test_the_language_setting_reaches_the_recognizer(dpage):
    dpage.evaluate("() => localStorage.setItem('annotate.view:dictationlang', 'el-GR')")
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec", timeout=T(5000))
    assert dpage.evaluate("() => window.__rec.cfg.speechRecognitionLanguage") == "el-GR"


def test_the_mic_is_disabled_with_a_reason_when_speech_is_not_set_up(dpage):
    _routes(dpage, status={"configured": False, "claude": False, "reason": "x"})
    _open_span_comment(dpage)
    mic = dpage.locator(".sel-composer .voice-mic-btn")
    mic.wait_for(timeout=T(3000))
    dpage.wait_for_function("() => document.querySelector('.sel-composer .voice-mic-btn').disabled", timeout=T(3000))
    assert "webcompanion doctor" in mic.get_attribute("title")


def test_the_section_comment_card_has_the_mic_too(dpage):
    _routes(dpage)
    dpage.dblclick(SEL.format("section-1") + " .card-title")
    dpage.click('.sel-menu button[data-act="comment"]')
    dpage.wait_for_selector(".comment-card .card-submit-row .voice-mic-btn", timeout=T(3000))


def test_dictated_text_locks_submit_like_typed_text(dpage):
    _routes(dpage)
    _sel(dpage, "section-2", "Paragraph one")           # a mark, so the dock has a Submit
    dpage.click('.sel-menu button[data-act="delete"]')
    dpage.wait_for_selector("#round-submit:not([disabled])", timeout=T(5000))
    _open_span_comment(dpage)
    assert dpage.evaluate("() => document.body.classList.contains('has-sel-draft')") is False
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec && !!window.__rec.recognized", timeout=T(5000))
    dpage.evaluate("() => __say(null, 'Spoken, not typed.')")
    assert dpage.evaluate("() => document.body.classList.contains('has-sel-draft')") is True
    dpage.wait_for_function("() => document.querySelector('#round-submit').disabled", timeout=T(3000))
    assert "Finish or discard" in dpage.inner_text("#round-submit")


def test_pressing_the_mic_again_stops_listening(dpage):
    _routes(dpage)
    _open_span_comment(dpage)
    mic = dpage.locator(".sel-composer .voice-mic-btn")
    mic.click()
    dpage.wait_for_selector(".sel-composer .voice-mic-btn.listening", timeout=T(5000))
    mic.click()
    dpage.wait_for_selector(".sel-composer .voice-mic-btn:not(.listening)", timeout=T(3000))
    assert dpage.evaluate("() => window.__rec.stopped") is True


def test_a_long_dictation_gets_a_fresh_token_before_the_old_one_expires(dpage):
    n = {"i": 0}

    def token_route(route):
        n["i"] += 1
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"token": f"tok-{n['i']}", "region": "westeurope", "expires_in": 540}))
    _routes(dpage)
    dpage.unroute("**/api/speech/token")
    dpage.route("**/api/speech/token", token_route)
    # A clock that can be pushed forward, and the 30 s refresh check made quick.
    dpage.evaluate("""() => {
      const realNow = Date.now; window.__skew = 0; Date.now = () => realNow() + window.__skew;
      const si = window.setInterval; window.setInterval = (f, ms) => si(f, ms > 1000 ? 100 : ms); }""")
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec", timeout=T(5000))
    assert dpage.evaluate("() => window.__rec.cfg.token") == "tok-1"
    assert dpage.evaluate("() => window.__rec.authorizationToken") is None
    dpage.evaluate("() => { window.__skew = 480 * 1000; }")      # 60 s of the 540 left
    dpage.wait_for_function("() => window.__rec.authorizationToken === 'tok-2'", timeout=T(5000))
    assert n["i"] == 2


def _listen(page):
    _open_span_comment(page)
    page.click(".sel-composer .voice-mic-btn")
    page.wait_for_selector(".sel-composer .voice-mic-btn.listening", timeout=T(5000))


def _closed(page):
    page.wait_for_function("() => window.__rec.stopped === true", timeout=T(4000))
    assert page.evaluate("() => !document.querySelector('.voice-mic-btn.listening')")


def test_cancel_on_the_span_box_closes_the_microphone(dpage):
    _routes(dpage)
    _listen(dpage)
    dpage.click(".sel-composer .sel-cancel")
    _closed(dpage)


def test_add_to_round_closes_the_microphone(dpage):
    _routes(dpage)
    _listen(dpage)
    dpage.fill(".sel-composer textarea", "typed words")
    dpage.click(".sel-composer .card-submit-btn")
    _closed(dpage)


def test_a_rewrite_removing_the_box_closes_the_microphone(dpage, document):
    _routes(dpage)
    _listen(dpage)
    _put_block(document, "section-1", "Rewritten while the mic was open.")
    _closed(dpage)


def test_leaving_the_page_closes_the_microphone(dpage):
    _routes(dpage)
    _listen(dpage)
    dpage.evaluate("() => window.dispatchEvent(new Event('pagehide'))")
    _closed(dpage)


def test_every_exit_clears_the_refresh_timer(dpage):
    _routes(dpage)
    dpage.evaluate("""() => { window.__live = new Set(); const si = window.setInterval, ci = window.clearInterval;
      window.setInterval = (f, ms) => { const id = si(f, ms); window.__live.add(id); return id; };
      window.clearInterval = (id) => { window.__live.delete(id); return ci(id); }; }""")
    _listen(dpage)
    assert dpage.evaluate("() => window.__live.size") >= 2
    dpage.click(".sel-composer .sel-cancel")
    _closed(dpage)
    assert dpage.evaluate("() => window.__live.size") == 0


def test_a_recognizer_that_cannot_be_built_says_why(page):
    page.add_init_script(SDK_DOUBLE)
    page.add_init_script(REC_DOUBLE)
    page.add_init_script("""window.SpeechSDK.AudioConfig = {
      fromDefaultMicrophoneInput: () => { throw new Error('mediaDevices is not available'); } };""")
    page.reload()
    page.wait_for_function("() => !!window.AnnotateSpeech")
    # speech.js can load before script.js has drawn the cards.
    page.wait_for_selector("section.block .card-title", timeout=T(15000))
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    _routes(page)
    _open_span_comment(page)
    page.click(".sel-composer .voice-mic-btn")
    page.wait_for_function(
        "() => document.querySelector('.sel-composer .voice-interim').textContent.includes('mediaDevices')",
        timeout=T(4000))
    assert page.inner_text(".sel-composer .voice-interim") == "Dictation could not start — mediaDevices is not available"
    assert "Microphone blocked" not in page.inner_text(".sel-composer .voice-interim")
    assert not page.evaluate("() => !!document.querySelector('.voice-mic-btn.listening')")
    assert errors == []


def test_a_refused_microphone_is_written_beside_the_field_and_cleared_on_the_next_try(dpage):
    _routes(dpage)
    _listen(dpage)
    dpage.evaluate("() => { const r = window.__rec; r.canceled(r, { errorDetails: 'Permission denied' }); }")
    dpage.wait_for_function("() => document.querySelector('.sel-composer .voice-interim').textContent.includes('Permission denied')")
    assert dpage.inner_text(".sel-composer .voice-interim") == "Microphone blocked — Permission denied"
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_selector(".sel-composer .voice-mic-btn.listening", timeout=T(4000))
    assert dpage.inner_text(".sel-composer .voice-interim") == ""


def test_a_second_press_while_loading_cancels_instead_of_restarting(dpage):
    held = []
    _routes(dpage)
    dpage.unroute("**/api/speech/token")
    dpage.route("**/api/speech/token", lambda r: held.append(r))
    _open_span_comment(dpage)
    mic = dpage.locator(".sel-composer .voice-mic-btn")
    mic.click()
    dpage.wait_for_function("() => true")
    while not held:
        dpage.wait_for_timeout(50)
    mic.click()                                     # cancel while the token is still out
    held[0].fulfill(status=200, content_type="application/json",
                    body=json.dumps({"token": "tok", "region": "westeurope", "expires_in": 540}))
    dpage.wait_for_timeout(500)
    assert dpage.evaluate("() => window.__rec") is None
    assert dpage.evaluate("() => !!document.querySelector('.voice-mic-btn.listening')") is False


def test_dictation_pads_both_sides_and_lands_at_the_caret(dpage):
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.fill(".sel-composer textarea", "foobar")
    dpage.evaluate("() => { const t = document.querySelector('.sel-composer textarea'); t.setSelectionRange(3, 3); }")
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec && !!window.__rec.recognized", timeout=T(5000))
    dpage.evaluate("() => __say(null, 'dictated')")
    assert dpage.input_value(".sel-composer textarea") == "foo dictated bar"
    dpage.evaluate("() => __say(null, 'again')")
    assert dpage.input_value(".sel-composer textarea") == "foo dictated again bar"


# ── final review fixes ──────────────────────────────────────────────────────

def _put_and_wait(page, document, markdown, needle):
    _put_block(document, "section-1", markdown, title="Block 1")
    page.wait_for_function(f"""() => AnnotateAnchors.textOf(AnnotateAnchors.contentOf(
      document.querySelector('{SEL.format("section-1")}'))).includes({json.dumps(needle)})""", timeout=T(10000))


def _read(page, needle):
    _sel(page, "section-1", needle)
    page.click('.sel-menu button[data-act="voice-more"]')
    page.click('.sel-menu button[data-act="read"]')


def _media_log(page):
    """Every play, playing and ended of any media element, with its time."""
    page.evaluate("""() => { window.__media = [];
      for (const type of ['play', 'playing', 'ended'])
        document.addEventListener(type, (e) => window.__media.push(
          {type, t: performance.now(), src: e.target.currentSrc || e.target.src || ''}), true); }""")


LONG = " ".join(f"Sentence number {i} says a few plain words." for i in range(1, 71))


def test_the_first_sound_comes_after_the_first_chunk_not_the_whole_script(spage, document):
    # 3,000 characters at 2 ms each is 6 s of synthesis before anything could
    # play if the script went to Azure whole; Azure itself takes about 24 s.
    assert 2900 <= len(LONG) <= 3200, len(LONG)
    _put_and_wait(spage, document, LONG, LONG)
    _routes(spage)
    _media_log(spage)
    _sel(spage, "section-1", LONG)
    spage.click('.sel-menu button[data-act="voice-more"]')
    t0 = spage.evaluate("() => performance.now()")
    spage.click('.sel-menu button[data-act="read"]')
    spage.wait_for_function("() => __media.some((m) => m.type === 'playing' && m.src.startsWith('blob:'))",
                            timeout=T(8000))
    first = spage.evaluate("() => __media.find((m) => m.type === 'playing' && m.src.startsWith('blob:')).t")
    assert first - t0 < 2500, f"the first sound waited {first - t0:.0f} ms, as long as the whole script"
    spoken = spage.evaluate("() => window.__spoken.map((s) => s.text)")
    assert len(spoken[0]) <= 200, spoken[0]
    assert spage.inner_text(".sp-card .sp-time").endswith("/ …"), "the total was shown before it was known"
    spage.evaluate("() => { window.__msPerChar = 0; }")
    spage.wait_for_function(f"() => window.__spoken.map((s) => s.text).join(' ').length >= {len(LONG)}",
                            timeout=T(10000))
    spoken = spage.evaluate("() => window.__spoken.map((s) => s.text)")
    assert " ".join(spoken) == LONG, "the chunks do not add up to the script"
    assert all(s.endswith(".") for s in spoken), "a chunk split a sentence"
    assert all(len(s) <= 800 for s in spoken[1:]), [len(s) for s in spoken]
    spage.wait_for_function("() => !document.querySelector('.sp-card .sp-time').textContent.endsWith('…')",
                            timeout=T(5000))


def test_back_one_sentence_crosses_a_chunk_boundary(spage, document):
    _put_and_wait(spage, document, "One two three. Four five six. Seven eight nine.", "Seven eight nine.")
    _routes(spage)
    _read(spage, "One two three. Four five six. Seven eight nine.")
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Seven'", timeout=T(8000))
    spage.click('.sp-card [data-sp="toggle"]')
    assert spage.evaluate("() => window.__spoken.map((s) => s.text)") == \
        ["One two three. Four five six.", "Seven eight nine."]
    spage.click('.sp-card [data-sp="back"]')
    assert spage.inner_text(".sp-card .w.now") == "Four"
    at = spage.evaluate("() => document.querySelector('.sp-card audio').currentTime")
    assert abs(at - 1.2) < 0.05, f"back did not land on 'Four' in the first chunk's audio: {at}"
    spage.click('.sp-card [data-sp="toggle"]')
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'five'", timeout=T(5000))
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Seven'", timeout=T(8000))


def test_the_next_chunk_starts_without_a_gap(spage, document):
    _put_and_wait(spage, document, "One two three. Four five six. Seven eight nine.", "Seven eight nine.")
    _routes(spage)
    _media_log(spage)
    _read(spage, "One two three. Four five six. Seven eight nine.")
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'eight'", timeout=T(10000))
    log = spage.evaluate("() => __media")
    ended = [m for m in log if m["type"] == "ended"]
    assert ended, f"no chunk ended before the next was heard: {log}"
    after = [m for m in log if m["type"] == "playing" and m["t"] > ended[0]["t"]]
    assert after and after[0]["src"] != ended[0]["src"], log
    gap = after[0]["t"] - ended[0]["t"]
    assert gap < 150, f"{gap:.0f} ms of silence between chunks"
    assert spage.locator(".sp-card audio").count() == 1, "more than one player"


def test_closing_the_card_cancels_the_chunks_still_to_come(spage, document):
    _put_and_wait(spage, document, LONG, LONG)
    _routes(spage)
    _media_log(spage)
    _read(spage, LONG)
    spage.wait_for_selector(".sp-card .w.now", timeout=T(8000))
    spage.click(".sp-card .sp-x")
    n = spage.evaluate("() => window.__spoken.length")
    closed_at = spage.evaluate("() => performance.now()")
    spage.wait_for_timeout(2500)          # long enough for the chunk in flight to come back
    assert spage.evaluate("() => window.__spoken.length") == n, "synthesis went on after the card closed"
    assert spage.evaluate(f"() => __media.filter((m) => m.type === 'play' && m.t > {closed_at}).length") == 0
    assert spage.locator(".sp-card").count() == 0


def test_dictation_names_azure_when_the_token_fails(dpage):
    _routes(dpage)
    dpage.unroute("**/api/speech/token")
    dpage.route("**/api/speech/token", lambda r: r.fulfill(status=502, content_type="text/plain",
                                                             body="Azure did not answer"))
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => document.querySelector('.sel-composer .voice-interim').textContent", timeout=T(4000))
    got = dpage.inner_text(".sel-composer .voice-interim")
    assert got == "Azure didn't answer — Azure did not answer · press 🎤 to retry", got
    assert "Microphone" not in got and "(HTTP" not in got


def test_on_a_phone_the_sheet_leads_with_two_labelled_voice_buttons_and_the_card_is_touch_sized(
        document, browser):
    with _phone(browser, document) as pg:
        pg.add_init_script(SDK_DOUBLE)
        pg.reload()
        _decorated(pg)
        pg.wait_for_function("() => !!window.AnnotateSpeech")
        _routes(pg)
        pg.evaluate(_PHONE_SELECT_JS, [SEL.format("section-1"), "Paragraph one of block 1"])
        pg.wait_for_selector('.sel-sheet button[data-act="explain"]', timeout=T(8000))
        bs = pg.eval_on_selector_all(".sel-sheet button[data-act]", """bs => bs.map(b => ({
          act: b.dataset.act, text: b.innerText.trim(), w: b.getBoundingClientRect().width}))""")
        assert [b["act"] for b in bs[:2]] == ["explain", "read"], bs
        assert [b["text"] for b in bs[:2]] == ["Explain aloud", "Read as written"], bs
        assert "voice-more" not in [b["act"] for b in bs], "the sheet still has the chevron"
        comment = next(b for b in bs if b["act"] == "comment")
        assert min(bs[0]["w"], bs[1]["w"]) > comment["w"] * 1.3, f"the voice buttons are not wide: {bs}"
        pg.click('.sel-sheet button[data-act="read"]')
        pg.wait_for_selector(".sp-card .sp-script .w", timeout=T(8000))
        hs = pg.eval_on_selector_all(".sp-card .sp-btn, .sp-card .sp-seg button, .sp-card .sp-x",
                                     "bs => bs.map(b => [b.className || b.textContent, b.getBoundingClientRect().height])")
        assert len(hs) >= 8, hs
        assert all(h >= 44 for _, h in hs), f"card controls under 44 px: {hs}"


def test_esc_stops_a_card_opened_with_r_while_it_is_still_waiting(spage):
    spage.evaluate("() => { window.__msPerChar = 400; }")     # a long wait for Azure
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.wait_for_function("""() => { const b = document.querySelector('.sel-menu button[data-act="explain"]');
      return b && !b.disabled; }""", timeout=T(3000))
    spage.keyboard.press("r")
    spage.wait_for_selector(".sp-card .sp-wait", timeout=T(3000))
    assert spage.evaluate("() => document.activeElement === document.querySelector('.sp-card')")
    spage.keyboard.press("Escape")
    spage.wait_for_function("() => !document.querySelector('.sp-card')", timeout=T(2000))


def test_focus_moves_to_play_pause_and_stays_in_the_card_across_the_mode_switch(spage):
    _explain(spage, needle="Paragraph one of block 1")
    assert spage.evaluate("() => document.activeElement?.dataset.sp") == "toggle"
    spage.click('.sp-card [data-sp="mode"] button[data-mode="read"]')
    spage.wait_for_function("() => window.__spoken.length === 2", timeout=T(5000))
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.evaluate("() => document.querySelector('.sp-card').contains(document.activeElement)")


def test_the_mode_switch_keeps_the_speed(spage):
    _explain(spage, needle="Paragraph one of block 1")
    spage.click('.sp-card [data-sp="speed"] button[data-rate="1.2"]')
    spage.click('.sp-card [data-sp="mode"] button[data-mode="read"]')
    spage.wait_for_function("() => window.__spoken.length === 2", timeout=T(5000))
    spage.wait_for_selector(".sp-card .w.now", timeout=T(5000))
    assert spage.evaluate("() => document.querySelector('.sp-card audio').playbackRate") == 1.2
    assert spage.get_attribute('.sp-card [data-sp="speed"] button[aria-pressed="true"]', "data-rate") == "1.2"


def test_one_esc_in_a_maximised_card_stops_the_reading_and_keeps_the_card(spage):
    spage.wait_for_function("() => !!window.AnnotateMaximize", timeout=T(15000))
    spage.evaluate("(sel) => AnnotateMaximize.open(document.querySelector(sel))", SEL.format("section-1"))
    spage.wait_for_selector(SEL.format("section-1") + ".is-maximized")
    _explain(spage)
    spage.wait_for_selector(".sp-card .w.now", timeout=T(5000))
    spage.keyboard.press("Escape")
    spage.wait_for_function("() => !document.querySelector('.sp-card')", timeout=T(2000))
    assert spage.locator(SEL.format("section-1") + ".is-maximized").count() == 1, "Esc closed the card too"
    spage.keyboard.press("Escape")
    spage.wait_for_function(f"() => !document.querySelector('{SEL.format('section-1')}.is-maximized')", timeout=T(2000))


def test_r_on_a_focused_block_explains_the_section_and_shift_r_reads_it(spage):
    asked = []
    _routes(spage)
    spage.on("request", lambda r: asked.append(json.loads(r.post_data)) if "/api/speech/script" in r.url else None)
    spage.click("body", position={"x": 5, "y": 5})
    spage.keyboard.press("j")
    spage.wait_for_selector("section.block[data-kb-focus]", timeout=T(3000))
    spage.keyboard.press("r")
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.inner_text(".sp-card .sp-head b") == "Explained aloud"
    focused = spage.get_attribute("section.block[data-kb-focus]", "data-block-id")
    assert asked and asked[0]["selection"].startswith(f"Paragraph one of block {focused[-1]}")
    assert "Paragraph two" in asked[0]["selection"]
    spage.click("body", position={"x": 5, "y": 5})
    spage.keyboard.press("Shift+R")
    spage.wait_for_function("() => window.__spoken.length === 2", timeout=T(5000))
    assert spage.inner_text(".sp-card .sp-head b") == "Read as written"
    assert "Paragraph two" in spage.evaluate("() => window.__spoken[1].text")


@pytest.mark.parametrize("bare, full", [("el", "el-GR"), ("fr", "fr-FR"), ("en", "en-US"), ("qq", "en-US")])
def test_a_bare_browser_language_becomes_a_full_locale(dpage, bare, full):
    dpage.evaluate("""(l) => Object.defineProperty(Navigator.prototype, 'language',
      {get: () => l, configurable: true})""", bare)
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec", timeout=T(5000))
    assert dpage.evaluate("() => window.__rec.cfg.speechRecognitionLanguage") == full


def test_a_status_call_that_is_refused_says_read_aloud_is_not_available_here(spage):
    _routes(spage)
    spage.unroute("**/api/speech/status")
    spage.route("**/api/speech/status", lambda r: r.fulfill(status=403, content_type="text/plain", body="forbidden"))
    _sel(spage, "section-1", "Paragraph one")
    spage.wait_for_function("""() => document.querySelector('.sel-menu button[data-act="explain"]')?.disabled""",
                            timeout=T(3000))
    b = spage.locator('.sel-menu button[data-act="explain"]')
    assert b.get_attribute("title") == "Read-aloud isn't available here (403)"
    assert b.get_attribute("aria-label") == b.get_attribute("title")


def test_read_as_written_takes_each_list_item_as_its_own_sentence(spage, document):
    _put_and_wait(spage, document, "- First item here\n- Second item here\n- Third item here", "Third item here")
    _routes(spage)
    spage.dblclick(SEL.format("section-1") + " .card-title")
    spage.click('.sel-menu button[data-act="voice-more"]')
    spage.click('.sel-menu button[data-act="read"]')
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Second'", timeout=T(8000))
    lit = spage.evaluate("() => [...CSS.highlights.get('annotate-speaking')][0].toString()")
    assert lit == "Second item here", f"the list was lit as one sentence: {lit!r}"


def test_starting_dictation_stops_the_reading(dpage):
    _explain(dpage)
    dpage.wait_for_selector(".sp-card .w.now", timeout=T(5000))
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_selector(".sel-composer .voice-mic-btn.listening", timeout=T(5000))
    assert dpage.locator(".sp-card").count() == 0, "the card kept talking over the dictation"


def test_a_late_cancel_from_an_old_recognizer_leaves_the_new_one_listening(dpage):
    _routes(dpage)
    _listen(dpage)
    dpage.evaluate("() => { window.__old = window.__rec; }")
    mic = dpage.locator(".sel-composer .voice-mic-btn")
    mic.click()
    dpage.wait_for_selector(".sel-composer .voice-mic-btn:not(.listening)", timeout=T(3000))
    mic.click()
    dpage.wait_for_selector(".sel-composer .voice-mic-btn.listening", timeout=T(5000))
    assert dpage.evaluate("() => window.__rec !== window.__old")
    dpage.evaluate("() => { const r = window.__old; r.canceled && r.canceled(r, { errorDetails: 'late' }); }")
    dpage.wait_for_timeout(100)
    assert dpage.locator(".sel-composer .voice-mic-btn.listening").count() == 1
    assert dpage.inner_text(".sel-composer .voice-interim") == ""


# ── follow-up: real-speed chunks, Azure codes, keys in the card ─────────────

SHORT_OPENING = "Short one. Then this. " + " ".join(
    f"Here sentence {i} carries a fair number of ordinary words so the chunk runs long." for i in range(1, 16))


def test_at_azure_speed_no_chunk_waits_for_the_next(spage, document):
    import time
    spage.evaluate("() => { window.__msPerChar = 8; }")       # measured against real Azure
    _put_and_wait(spage, document, SHORT_OPENING, "Short one.")
    _routes(spage)
    _media_log(spage)
    _read(spage, SHORT_OPENING)
    # The first two hand-overs (chunk 1 to 2, 2 to 3): each must be heard
    # within 300 ms. Polled, so a long silence fails as soon as it is one.
    deadline = time.time() + 30
    gaps = []
    while time.time() < deadline:
        log, now = spage.evaluate("() => [__media, performance.now()]")
        ended = [m for m in log if m["type"] == "ended"]
        gaps, heard = [], 0
        for e in ended:
            nxt = next((m for m in log if m["type"] == "playing" and m["t"] > e["t"]), None)
            gaps.append(round((nxt["t"] if nxt else now) - e["t"]))
            heard += nxt is not None
        if any(g >= 300 for g in gaps) or heard >= 2:
            break
        spage.wait_for_timeout(100)
    sizes = spage.evaluate("() => window.__spoken.map((s) => s.text.length)")
    print("chunk sizes", sizes, "gaps", gaps)
    assert len(gaps) >= 2, f"two hand-overs never happened: {gaps}"
    assert all(g < 300 for g in gaps), f"silence between chunks: {gaps} ms (chunks {sizes})"


def test_a_wait_for_the_next_chunk_says_preparing(spage, document):
    _put_and_wait(spage, document, "One two three. Four five six. Seven eight nine.", "Seven eight nine.")
    spage.evaluate("() => { window.__holdFrom = 1; }")        # chunk 2 does not come back
    _routes(spage)
    _read(spage, "One two three. Four five six. Seven eight nine.")
    spage.wait_for_function("() => document.querySelector('.sp-card audio')?.ended", timeout=T(8000))
    assert spage.inner_text('.sp-card [data-sp="toggle"]') == "Preparing…"
    assert spage.inner_text(".sp-card .sp-time") == "…"
    spage.evaluate("() => __release()")
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Seven'", timeout=T(5000))
    assert spage.inner_text('.sp-card [data-sp="toggle"]') == "Pause"


def _cancel(page, code, details):
    page.evaluate("([c, d]) => { const r = window.__rec; r.canceled(r, { reason: 0, errorCode: c, errorDetails: d }); }",
                  [code, details])
    page.wait_for_function("() => document.querySelector('.sel-composer .voice-interim').textContent", timeout=T(3000))
    return page.inner_text(".sel-composer .voice-interim")


def test_an_azure_cancel_says_azure_not_the_microphone(dpage):
    _routes(dpage)
    _listen(dpage)
    got = _cancel(dpage, 4, "websocket error code: 1006")        # ConnectionFailure
    assert got == "Azure didn't answer — websocket error code: 1006 · press 🎤 to retry", got


def test_a_refused_microphone_cancel_says_microphone_blocked(dpage):
    _routes(dpage)
    _listen(dpage)
    got = _cancel(dpage, 7, "Error occurred during microphone initialization: NotAllowedError: Permission denied")
    assert got.startswith("Microphone blocked — ") and "NotAllowedError" in got, got


def test_block_keys_still_work_with_focus_in_the_card(spage):
    _routes(spage)
    spage.click("body", position={"x": 5, "y": 5})
    spage.keyboard.press("j")
    spage.wait_for_selector("section.block[data-kb-focus]", timeout=T(3000))
    first = spage.get_attribute("section.block[data-kb-focus]", "data-block-id")
    spage.keyboard.press("r")
    spage.wait_for_selector(f'{SEL.format(first)} .sp-card .sp-script .w', timeout=T(5000))
    assert spage.evaluate("() => document.querySelector('.sp-card').contains(document.activeElement)")
    spage.keyboard.press("j")
    spage.wait_for_function(f"() => document.querySelector('section.block[data-kb-focus]')?.dataset.blockId !== '{first}'",
                            timeout=T(3000))
    second = spage.get_attribute("section.block[data-kb-focus]", "data-block-id")
    spage.keyboard.press("Shift+R")
    spage.wait_for_selector(f'{SEL.format(second)} .sp-card .sp-script .w', timeout=T(5000))
    assert spage.locator(".sp-card").count() == 1
    assert spage.inner_text(".sp-card .sp-head b") == "Read as written"


def test_a_failed_later_chunk_freezes_the_total_and_retry_resumes_there(spage, document):
    _put_and_wait(spage, document, "One two three. Four five six. Seven eight nine.", "Seven eight nine.")
    spage.evaluate("() => { window.__failNext = 1; }")
    _routes(spage)
    _read(spage, "One two three. Four five six. Seven eight nine.")
    spage.wait_for_selector('.sp-card [data-sp="retry"]', timeout=T(8000))
    spage.wait_for_function("() => document.querySelector('.sp-card audio').ended", timeout=T(8000))
    t = spage.inner_text(".sp-card .sp-time")
    assert not t.endswith("…") and t.split(" / ")[1] == "0:03", t
    spage.click('.sp-card [data-sp="retry"]')
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Seven'", timeout=T(8000))
    assert spage.evaluate("() => window.__spoken.map((s) => s.text)") == \
        ["One two three. Four five six.", "Seven eight nine.", "Seven eight nine."], "retry did not resume at the failed chunk"
    assert spage.locator('.sp-card [data-sp="retry"]').count() == 0
    assert spage.evaluate("() => document.querySelectorAll('.sp-card .w.done').length") >= 6, "what was heard was lost"


def test_an_empty_explanation_offers_read_as_written(spage):
    _routes(spage, script={"pieces": [], "cached": False})
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .sp-error", timeout=T(5000))
    assert "Claude returned no explanation" in spage.inner_text(".sp-card .sp-error")
    spage.click('.sp-card button[data-sp="fallback"]')
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=T(5000))
    assert spage.__dict__["js_errors"] == []


def _r_on_first_block(page):
    page.click("body", position={"x": 5, "y": 5})
    page.keyboard.press("j")
    page.wait_for_selector("section.block[data-kb-focus]", timeout=T(3000))
    page.keyboard.press("r")
    page.wait_for_selector(".sp-card .sp-error", timeout=T(5000))
    return page.inner_text(".sp-card .sp-error")


def test_r_on_a_block_says_when_speech_is_not_set_up(spage):
    _routes(spage, status={"configured": False, "claude": True, "reason": "not set"})
    assert "webcompanion doctor" in _r_on_first_block(spage)
    assert spage.evaluate("() => window.__spoken.length") == 0


def test_r_on_a_block_too_long_says_so(spage, document):
    text = " ".join(f"Sentence number {i} says a few plain words." for i in range(1, 101))
    assert len(text) > 4000
    _put_and_wait(spage, document, text, "Sentence number 100")
    _routes(spage)
    assert "Select less than about a page" in _r_on_first_block(spage)
