# Read-aloud and dictation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:**
- **Read-aloud:** the selection menu gets **Explain**, with a ▾ that holds **Read as written**. The selection is spoken by Azure in an explainer card under the passage. The card highlights the script word by word, karaoke style, while the page sentence being explained lights up yellow.
- **Dictation:** comment boxes dictate through Azure speech-to-text.

**Architecture:**
- `speech-client.js` talks to the daemon's `/api/speech/*` routes (built in Plan 1). It lazy-loads Azure's browser SDK from `static/vendor/`.
- `speech.js` registers Explain with the selection menu (Plan 2's `registerAction`). It builds the card, synthesises the script with word boundaries, plays it in an `<audio>` element, and drives the highlight from `audio.currentTime`.
- `voice.js` is rewritten to recognise speech with Azure.

**Tech Stack:**
- Vanilla JS, Azure Speech SDK 1.51.0 browser bundle (MIT), and the CSS Custom Highlight API.
- pytest with Playwright. The tests replace `window.SpeechSDK` with a scripted double, so nothing reaches Azure in the suite.

**Spec:** `docs/superpowers/specs/2026-10-01-selection-menu-and-speech-design.md`, §2 (rows 2, 3, 4, 6), §3.4, §3.5, §4.1, §4.5 and §5.

**Depends on:** Plan 1 (deployed: `GET /api/speech/status`, `POST /api/speech/token`, `POST /api/speech/script`) and Plan 2 (`AnnotateSelection.registerAction`, `AnnotateAnchors`).

## Global Constraints

- **Daemon routes** live at the site root, not under the session: `/api/speech/status`, `/api/speech/token`, `/api/speech/script`. Requests carry the same headers the daemon's `core.js` sends: `X-WebCompanion-Contract: 1`, plus `X-WebCompanion-Token` from `sessionStorage["webcompanion.token." + location.host]` when present.
- **Token reuse:** refresh at `expires_in` (540 s) after it was issued.
- **The SDK:** `static/vendor/speech-sdk.min.js` is the unmodified `microsoft.cognitiveservices.speech.sdk.bundle-min.js` from `microsoft-cognitiveservices-speech-sdk@1.51.0`, with its `LICENSE` beside it as `static/vendor/speech-sdk.LICENSE`. It is loaded lazily on first use, never from `entry.js`, and it defines `window.SpeechSDK`.
- **Voices:** from a new Settings row "Read-aloud voice" (global):

  | Option | Azure voice |
  |--------|-------------|
  | `ava` (default) | `en-US-AvaMultilingualNeural` |
  | `andrew` | `en-US-AndrewMultilingualNeural` |
  | `emma` | `en-US-EmmaMultilingualNeural` |
  | `brian` | `en-US-BrianMultilingualNeural` |
  | `sonia` | `en-GB-SoniaNeural` |
  | `ryan` | `en-GB-RyanNeural` |

  All six were confirmed present in `germanywestcentral` on 2026-10-01.
- **Recognition language:** a new Settings row "Dictation language" (global). The default is `auto`, which uses `navigator.language` (else `en-US`). The options are `auto`, `en-US`, `en-GB`, `el-GR`, `fr-FR`.
- **Synthesis:** plain text through `speakTextAsync` (never SSML), so each `wordBoundary.textOffset` indexes the script string. Only boundaries with `boundaryType === "WordBoundary"` count. `audioOffset` and `duration` are in 100-ns ticks, so divide by 10,000 for milliseconds.
- **Highlight timing** comes from `audio.currentTime`, never from a wall clock. Speed is `audio.playbackRate` (0.85, 1, 1.2), with pitch preserved.
- **Karaoke:** words ahead at 38% opacity, the current word tinted. The page sentence for the current piece is painted with the Highlight registry `annotate-speaking`.
- **Limits:** a selection over 4,000 characters disables the voice buttons ("Select less than about a page"). One card plays at a time.
- **Errors** are worded exactly as in spec §5.
- **Commits:** one line, with no body and no trailers.
- **Tests:** `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills -q`, with focused runs adding `-n 0`.

## Review Focus

1. **The script never arrives.** A 45 s timeout, a 502, or "busy" should leave the card with a readable message and **Read as written instead**, never a spinner forever. Pinned in Task 2.
2. **Pause, back one sentence, and speed change mid-word.** The highlighted word must stay the one being heard, because the loop reads `audio.currentTime`. Pinned in Task 2 with a scripted clock.
3. **A rewrite or re-render of the section while it is playing.** The card and the page lighting must stop cleanly, with no exceptions and no highlight on stale nodes. Pinned in Task 2.
4. **The token expires during a long session.** The second Explain after 9 minutes must fetch a new token, not fail. Pinned in Task 1 with a fake clock.
5. **Speech is not configured, or `claude` is missing.** The voice buttons and 🎤 must be disabled with the spec's tooltip, and the rest of the page must be unaffected. Pinned in Tasks 2 and 3.

---

### Task 1: the SDK and `speech-client.js`

**Files:**
- Create: `skills/annotate/static/vendor/speech-sdk.min.js`, `skills/annotate/static/vendor/speech-sdk.LICENSE` (copied unmodified)
- Create: `skills/annotate/static/speech-client.js`
- Modify: `skills/annotate/static/entry.js` (load `speech-client.js` after `selection.js`)
- Modify: `skills/annotate/static/popover.js` (`AnnotateGlossary.terms()` returns the current glossary array)
- Test: `skills/annotate/tests/test_browser_speech.py` (new; daemon-backed, reusing `test_browser_review.py`'s fixtures)

**Interfaces:**
- Produces `window.AnnotateSpeechClient`:
  - `status() -> Promise<{configured, claude, region?, reason?}>`, cached for 60 s
  - `token() -> Promise<{token, region}>`, refreshed after `expires_in` seconds
  - `script({selection, context, glossary, page_title}) -> Promise<{pieces: [{say, src}]}>`. It is cached in memory by its JSON body. It rejects with `Error(message)`, where `message` is the daemon's response body text and `err.status` is the HTTP status.
  - `loadSdk() -> Promise<SpeechSDK>`
  - `pageContext(section) -> {context, glossary, page_title}`
- Produces `AnnotateGlossary.terms() -> [{term, definition?, role?}]`.

- [ ] **Step 1: Copy the SDK**

```bash
P=/Users/petros.makris/projects/lomem/node_modules/.pnpm/microsoft-cognitiveservices-speech-sdk@1.51.0/node_modules/microsoft-cognitiveservices-speech-sdk
mkdir -p skills/annotate/static/vendor
cp "$P/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js" skills/annotate/static/vendor/speech-sdk.min.js
cp "$P/LICENSE" skills/annotate/static/vendor/speech-sdk.LICENSE
shasum -a 256 skills/annotate/static/vendor/speech-sdk.min.js
```

Record the hash in the report. If that path is gone, download the same file from `https://cdn.jsdelivr.net/npm/microsoft-cognitiveservices-speech-sdk@1.51.0/distrib/browser/microsoft.cognitiveservices.speech.sdk.bundle-min.js` and record where it came from.

- [ ] **Step 2: Write the failing tests**

```python
# skills/annotate/tests/test_browser_speech.py
"""Read-aloud and dictation, driven in a real browser against the local
daemon's page, with Azure and the daemon's speech routes replaced: the routes
by page.route, the SDK by a scripted double installed before the page loads.
Nothing here reaches Azure or runs claude."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")

from test_browser_review import (  # noqa: E402,F401
    BLOCKS, SEL, _call, _put_block, document, page)

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
    page.wait_for_function("() => !!window.AnnotateSpeechClient")
    ctx = page.evaluate(f"""() => AnnotateSpeechClient.pageContext(document.querySelector('{SEL.format("section-1")}'))""")
    assert ctx["glossary"][0]["term"] == "EDR"
    assert "Paragraph one of block 1" in ctx["context"]
    assert ctx["page_title"]
```

- [ ] **Step 3: Watch them fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_speech.py -q -n 0`
Expected: every test fails with `ReferenceError: AnnotateSpeechClient is not defined`.

- [ ] **Step 4: Implement**

In `popover.js`, add `terms: () => glossary.slice()` to the exported `AnnotateGlossary` object, and update the header comment's export list to match.

Create `speech-client.js`:

```javascript
// skills/annotate/static/speech-client.js
/* The page's side of the daemon's speech routes (Plan 1).
 *
 * The routes live at the site root, not under the session, so they are called
 * with fetch directly rather than through WebCompanion.api (whose paths are
 * session-relative). The headers are the ones core.js sends: the contract
 * number, and the owner token from sessionStorage when the page was opened
 * through an owner URL. Keep the two in step if core.js's ever change.
 *
 * Azure's browser SDK is 378 KB, so it is loaded the first time something
 * speaks or listens, never at page load.
 */
(function () {
  "use strict";

  const BASE = new URL("./", document.currentScript ? document.currentScript.src : location.href);
  const SDK_SRC = new URL("vendor/speech-sdk.min.js", BASE).href;
  const CONTRACT = "1";
  const TOKEN_KEY = "webcompanion.token." + location.host;

  function headers(extra) {
    const h = Object.assign({ "X-WebCompanion-Contract": CONTRACT }, extra || {});
    try { const t = sessionStorage.getItem(TOKEN_KEY); if (t) h["X-WebCompanion-Token"] = t; } catch (_) {}
    return h;
  }

  async function call(method, path, body) {
    const opts = { method, headers: headers(body ? { "Content-Type": "application/json" } : null) };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(path, opts);
    if (!r.ok) {
      const e = new Error((await r.text()).trim() || `HTTP ${r.status}`);
      e.status = r.status;
      throw e;
    }
    return r.json();
  }

  let statusCache = null, statusAt = 0;
  async function status() {
    if (statusCache && Date.now() - statusAt < 60000) return statusCache;
    statusCache = await call("GET", "/api/speech/status");
    statusAt = Date.now();
    return statusCache;
  }

  let tok = null, tokUntil = 0;
  async function token() {
    if (tok && Date.now() < tokUntil) return tok;
    const t = await call("POST", "/api/speech/token");
    tok = { token: t.token, region: t.region };
    tokUntil = Date.now() + (t.expires_in || 540) * 1000;
    return tok;
  }

  const scripts = new Map();
  function script(req) {
    const key = JSON.stringify(req);
    if (!scripts.has(key)) {
      const p = call("POST", "/api/speech/script", req);
      scripts.set(key, p);
      p.catch(() => scripts.delete(key));      // a failure is not remembered
    }
    return scripts.get(key);
  }

  let sdk = null;
  function loadSdk() {
    if (window.SpeechSDK) return Promise.resolve(window.SpeechSDK);
    if (!sdk) {
      sdk = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = SDK_SRC;
        s.onload = () => window.SpeechSDK ? resolve(window.SpeechSDK)
          : reject(new Error("The speech engine loaded but did not start"));
        s.onerror = () => { sdk = null; reject(new Error("The speech engine could not load")); };
        document.head.appendChild(s);
      });
    }
    return sdk;
  }

  function pageContext(section) {
    const root = window.AnnotateAnchors?.contentOf(section);
    const context = root ? window.AnnotateAnchors.textOf(root).slice(0, 4000) : "";
    const glossary = window.AnnotateGlossary?.terms ? window.AnnotateGlossary.terms() : [];
    const title = document.querySelector(".header-text")?.textContent?.trim() || document.title || "";
    return { context, glossary, page_title: title };
  }

  window.AnnotateSpeechClient = { status, token, script, loadSdk, pageContext };
})();
```

In `entry.js`, add `"speech-client.js"` immediately after `"selection.js"`.

- [ ] **Step 5: Run the tests, then everything**

Run: the command from Step 3. Expected: `5 passed`.
Then the full suite. Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add skills/annotate/static/vendor skills/annotate/static/speech-client.js skills/annotate/static/entry.js skills/annotate/static/popover.js skills/annotate/tests/test_browser_speech.py
git commit -m "feat(annotate): the page reaches the daemon's speech routes and loads Azure's SDK only when it first speaks"
```

---

### Task 2: Explain, Read as written, and the karaoke card

**Files:**
- Create: `skills/annotate/static/speech.js`
- Modify: `skills/annotate/static/anchors.js` (`setScope(range, name = "annotate-scope")`, so `annotate-speaking` reuses it)
- Modify: `skills/annotate/static/entry.js` (load `speech.js` after `speech-client.js`)
- Modify: `skills/annotate/static/script.js` (Settings row "Read-aloud voice")
- Modify: `skills/annotate/static/style.css` (card, karaoke, `::highlight(annotate-speaking)`)
- Modify: `skills/annotate/static/export.js` (STRIP gains `.sp-card`)
- Test: `skills/annotate/tests/test_browser_speech.py` (append)

**Interfaces:**
- Consumes:
  - `AnnotateSelection.registerAction` (Plan 2)
  - `AnnotateSpeechClient.*` (Task 1)
  - `AnnotateAnchors.locate`, `rangeFrom`, `contentOf`, `textOf` and `setScope(range, name)`
- Produces:
  - Menu buttons `button[data-act="explain"]` and `button[data-act="voice-more"]`. The second opens `button[data-act="read"]`.
  - `window.AnnotateSpeech = { play(target, mode), stop(), isPlaying() }`
  - A card `.sp-card` with `.sp-script .w` word spans, and controls: `[data-sp="toggle"]`, `[data-sp="back"]`, `[data-sp="speed"] button[data-rate]`, `[data-sp="mode"] button[data-mode]` and `.sp-x`.

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/annotate/tests/test_browser_speech.py

# A scripted SpeechSDK. speakTextAsync emits one WordBoundary per word of the
# text it is given, 400 ms apart, then returns a silent WAV of the right
# length. Installed before any page script runs.
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
  window.SpeechSDK = {
    SpeechConfig: { fromAuthorizationToken: (t, r) => ({ token: t, region: r }) },
    ResultReason: { SynthesizingAudioCompleted: 10, RecognizedSpeech: 3 },
    SpeechSynthesisOutputFormat: { Audio16Khz32KBitRateMonoMp3: 3 },
    SpeechSynthesizer: class {
      constructor(cfg) { this.cfg = cfg; this.wordBoundary = null; }
      speakTextAsync(text, ok, err) {
        window.__spoken.push({ text, voice: this.cfg.speechSynthesisVoiceName });
        if (window.__synthFail) { setTimeout(() => err('synthesis failed'), 0); return; }
        let at = 0;
        for (const m of text.matchAll(/\\S+/g)) {
          this.wordBoundary && this.wordBoundary(this, { boundaryType: 'WordBoundary',
            audioOffset: at * 10000, duration: 300 * 10000, textOffset: m.index, wordLength: m[0].length, text: m[0] });
          at += 400;
        }
        setTimeout(() => ok({ reason: 10, audioData: wav(at + 200) }), 0);
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
    page.wait_for_selector(".sel-menu", timeout=3000)


def test_explain_joins_the_menu_after_the_feedback_buttons(spage):
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.wait_for_selector('.sel-menu button[data-act="explain"]', timeout=3000)
    acts = spage.eval_on_selector_all(".sel-menu button", "bs => bs.map(b => b.dataset.act)")
    assert acts[:3] == ["comment", "delete", "compact"] and "explain" in acts and "voice-more" in acts


def test_explain_plays_the_script_and_lights_words_and_the_page_in_step(spage):
    _routes(spage, script={"pieces": [
        {"say": "First, the point.", "src": "Paragraph one"},
        {"say": "Then the rest.", "src": "long enough"}], "cached": False})
    _sel(spage, "section-1", "Paragraph one of block 1, long enough")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=5000)
    assert spage.inner_text(".sp-card .sp-script") == "First, the point. Then the rest."
    assert spage.evaluate("() => window.__spoken[0].voice") == "en-US-AvaMultilingualNeural"
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'the'", timeout=5000)
    assert spage.evaluate("() => CSS.highlights.get('annotate-speaking')?.size") == 1
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Then'", timeout=5000)
    lit = spage.evaluate("""() => [...CSS.highlights.get('annotate-speaking')][0].toString()""")
    assert lit == "long enough"


def test_pause_back_and_speed_follow_the_audio_clock(spage):
    _routes(spage, script={"pieces": [{"say": "One two three. Four five six.", "src": "Paragraph one"}], "cached": False})
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_function("() => document.querySelector('.sp-card .w.now')?.textContent === 'Five'"
                            .replace("Five", "five"), timeout=8000)
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
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=5000)
    assert spage.evaluate("() => window.__spoken[0].text") == "Paragraph one of block 1"
    assert calls == []


def test_a_failed_script_offers_read_as_written_instead(spage):
    _routes(spage, script="claude could not write the explanation: Not logged in", script_status=502)
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .sp-error", timeout=5000)
    assert "Couldn't write an explanation" in spage.inner_text(".sp-card .sp-error")
    assert "Not logged in" in spage.inner_text(".sp-card .sp-error")
    spage.click('.sp-card button[data-sp="fallback"]')
    spage.wait_for_selector(".sp-card .sp-script .w", timeout=5000)


def test_voice_buttons_are_disabled_when_speech_is_not_set_up(spage):
    _routes(spage, status={"configured": False, "claude": True,
                           "reason": "AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are not both set"})
    _sel(spage, "section-1", "Paragraph one")
    b = spage.locator('.sel-menu button[data-act="explain"]')
    b.wait_for(timeout=3000)
    assert b.is_disabled()
    assert "webcompanion doctor" in b.get_attribute("title")


def test_a_rewrite_while_playing_stops_cleanly(spage, document):
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="explain"]')
    spage.wait_for_selector(".sp-card .w.now", timeout=5000)
    _put_block(document, "section-1", "Brand new words.", title="Block 1")
    spage.wait_for_function("() => !document.querySelector('.sp-card')", timeout=10000)
    assert spage.evaluate("() => CSS.highlights.get('annotate-speaking')?.size || 0") == 0
    assert spage.__dict__["js_errors"] == []


def test_the_voice_setting_reaches_the_synthesizer(spage):
    spage.evaluate("() => localStorage.setItem('annotate.view:speechvoice', 'sonia')")
    _routes(spage)
    _sel(spage, "section-1", "Paragraph one")
    spage.click('.sel-menu button[data-act="voice-more"]')
    spage.click('.sel-menu button[data-act="read"]')
    spage.wait_for_function("() => window.__spoken.length === 1", timeout=5000)
    assert spage.evaluate("() => window.__spoken[0].voice") == "en-GB-SoniaNeural"
```

- [ ] **Step 2: Watch them fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_speech.py -q -n 0 -k "explain or pause or read_as or failed_script or disabled or rewrite_while or voice_setting"`
Expected: every new test errors in the `spage` fixture, timing out on `window.AnnotateSpeech`.

- [ ] **Step 3: Generalise `setScope` in `anchors.js`**

Change `setScope(range)` to `setScope(range, name = "annotate-scope")`, using `registry(name)`. Nothing else changes, so existing callers keep the default.

- [ ] **Step 4: Write `speech.js`**

```javascript
// skills/annotate/static/speech.js
/* Read-aloud: Explain (a spoken explanation Claude writes) and Read as
 * written (the selection itself), played in a card under the passage.
 *
 * The voice's words are not the page's words, so two things light up: each
 * word of the script as it is heard, and the page sentence the current piece
 * explains. Both are driven by audio.currentTime against Azure's word
 * boundaries, so pause, back-one-sentence and speed stay in sync with what
 * is heard. A wall clock would drift the moment anything paused.
 */
(function () {
  "use strict";

  const VOICES = {
    ava: "en-US-AvaMultilingualNeural", andrew: "en-US-AndrewMultilingualNeural",
    emma: "en-US-EmmaMultilingualNeural", brian: "en-US-BrianMultilingualNeural",
    sonia: "en-GB-SoniaNeural", ryan: "en-GB-RyanNeural",
  };
  const LIMIT = 4000;
  const SETUP_HINT = "Read-aloud needs Azure set up — run `webcompanion doctor`";
  const ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><polygon points="6 4 20 12 6 20 6 4"/></svg>';
  const ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>';
  const ICON_MORE = '<svg viewBox="0 0 24 24" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>';

  const C = () => window.AnnotateSpeechClient;
  const A = () => window.AnnotateAnchors;
  let current = null;   // {card, audio, raf, section, words, bounds, pieces, sentenceStarts}

  function voiceName() {
    let v = null;
    try { v = localStorage.getItem("annotate.view:speechvoice"); } catch (_) {}
    return VOICES[v] || VOICES.ava;
  }

  function selectionText(t) {
    if (t.whole) return A().textOf(A().contentOf(t.section)).trim();
    return t.anchor.selected_text;
  }

  // ── the menu buttons ────────────────────────────────────────────────────
  function addButtons(t, menu) {
    const text = selectionText(t);
    const explain = document.createElement("button");
    explain.type = "button";
    explain.dataset.act = "explain";
    explain.innerHTML = ICON_PLAY + "<span>Explain</span>";
    explain.title = "Explain aloud (r)";
    explain.setAttribute("aria-label", explain.title);
    const more = document.createElement("button");
    more.type = "button";
    more.dataset.act = "voice-more";
    more.innerHTML = ICON_MORE;
    more.title = "More ways to listen";
    more.setAttribute("aria-label", more.title);
    menu.append(explain, more);

    const disable = (why) => { for (const b of [explain, more]) { b.disabled = true; b.title = why; } };
    if (text.length > LIMIT) disable("Select less than about a page");
    else C().status().then((s) => {
      if (!s.configured) disable(SETUP_HINT);
      else if (!s.claude) { explain.disabled = true; explain.title = s.reason || "claude was not found"; }
    }).catch(() => disable(SETUP_HINT));

    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    explain.addEventListener("mousedown", stop);
    more.addEventListener("mousedown", stop);
    explain.addEventListener("click", (e) => { stop(e); window.AnnotateSelection.close(); play(t, "explain"); });
    more.addEventListener("click", (e) => {
      stop(e);
      if (menu.querySelector('[data-act="read"]')) return;
      const read = document.createElement("button");
      read.type = "button";
      read.dataset.act = "read";
      read.textContent = "Read as written";
      read.title = "Read as written (⇧r)";
      read.addEventListener("mousedown", stop);
      read.addEventListener("click", (ev) => { stop(ev); window.AnnotateSelection.close(); play(t, "read"); });
      more.after(read);
    });
  }

  // ── the card ────────────────────────────────────────────────────────────
  function hostFor(t) {
    const content = A().contentOf(t.section);
    if (t.whole || !t.range) return content;
    const end = t.range.endContainer.nodeType === 1 ? t.range.endContainer : t.range.endContainer.parentElement;
    const block = end && end.closest("li, p, pre, blockquote, table");
    return block && content.contains(block) ? block : content;
  }

  function stop() {
    if (!current) return;
    cancelAnimationFrame(current.raf);
    try { current.audio.pause(); } catch (_) {}
    if (current.audio.src) URL.revokeObjectURL(current.audio.src);
    current.card.remove();
    A().setScope(null, "annotate-speaking");
    current = null;
  }

  function buildCard(t, mode) {
    const card = document.createElement("div");
    card.className = "sp-card";
    card.innerHTML =
      `<div class="sp-head"><b>${mode === "explain" ? "Explained aloud" : "Read as written"}</b>`
      + `<span class="sp-voice"></span><button type="button" class="sp-x" aria-label="Stop and close">×</button></div>`
      + `<div class="sp-body"><span class="sp-wait"><i></i><i></i><i></i> `
      + `${mode === "explain" ? "Writing the explanation…" : "Preparing the reading…"}</span></div>`;
    card.querySelector(".sp-voice").textContent = "· " + voiceName();
    card.querySelector(".sp-x").addEventListener("click", stop);
    const host = hostFor(t);
    if (host === A().contentOf(t.section) || host.tagName === "LI") host.appendChild(card);
    else host.insertAdjacentElement("afterend", card);
    return card;
  }

  function sentenceSplit(text) {
    const out = [];
    const re = /[^.!?]+[.!?]+["')\]]*\s*|[^.!?]+$/g;
    let m;
    while ((m = re.exec(text))) if (m[0].trim()) out.push(m[0].trim());
    return out;
  }

  async function play(t, mode) {
    stop();
    const card = buildCard(t, mode);
    current = { card, audio: new Audio(), raf: 0, section: t.section };
    const mine = current;
    const text = selectionText(t);
    let pieces;
    try {
      if (mode === "explain") {
        const ctx = C().pageContext(t.section);
        pieces = (await C().script({ selection: text, ...ctx })).pieces;
      } else {
        pieces = sentenceSplit(text).map((s) => ({ say: s, src: s }));
      }
    } catch (e) {
      if (current !== mine) return;
      return showError(card, "Couldn't write an explanation", e.message, () => play(t, "read"));
    }
    if (current !== mine) return;
    await speak(t, mode, pieces, mine);
  }

  function showError(card, title, detail, fallback) {
    const body = card.querySelector(".sp-body");
    body.innerHTML = `<div class="sp-error"><b></b> <span></span></div>`;
    body.querySelector("b").textContent = title + ".";
    body.querySelector("span").textContent = detail || "";
    if (fallback) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "sp-btn";
      b.dataset.sp = "fallback";
      b.textContent = "Read as written instead";
      b.addEventListener("click", fallback);
      body.appendChild(b);
    }
  }

  async function speak(t, mode, pieces, mine) {
    const card = mine.card;
    let SDK, tok;
    try { SDK = await C().loadSdk(); tok = await C().token(); }
    catch (e) { return showError(card, "Azure didn't answer", e.message + (e.status ? ` (HTTP ${e.status})` : "")); }

    let script = "";
    const spans = [];                                   // piece char ranges in the script
    pieces.forEach((p, i) => {
      if (i) script += " ";
      spans.push({ start: script.length, end: script.length + p.say.length, src: p.src });
      script += p.say;
    });

    const cfg = SDK.SpeechConfig.fromAuthorizationToken(tok.token, tok.region);
    cfg.speechSynthesisVoiceName = voiceName();
    const synth = new SDK.SpeechSynthesizer(cfg, null);
    const bounds = [];
    synth.wordBoundary = (_s, e) => {
      if (e.boundaryType !== "WordBoundary") return;
      bounds.push({ ms: e.audioOffset / 10000, off: e.textOffset, len: e.wordLength });
    };
    let audioData;
    try {
      audioData = await new Promise((ok, err) => synth.speakTextAsync(script, (r) => {
        if (r.reason === SDK.ResultReason.SynthesizingAudioCompleted) ok(r.audioData);
        else err(new Error(r.errorDetails || "synthesis did not complete"));
      }, (e) => err(new Error(String(e)))));
    } catch (e) {
      synth.close();
      if (current === mine) showError(card, "Azure didn't answer", e.message);
      return;
    } finally {
      try { synth.close(); } catch (_) {}
    }
    if (current !== mine) return;

    // The script, one span per word, each knowing its offset in the script.
    const body = card.querySelector(".sp-body");
    body.innerHTML = `<div class="sp-script"></div><div class="sp-ctl"></div>`;
    const box = body.querySelector(".sp-script");
    const words = [];
    for (const m of script.matchAll(/\S+/g)) {
      const w = document.createElement("span");
      w.className = "w";
      w.textContent = m[0];
      box.append(w, " ");
      words.push({ el: w, off: m.index });
    }
    box.classList.add("playing");

    const audio = mine.audio;
    audio.src = URL.createObjectURL(new Blob([audioData], { type: mode ? "audio/mpeg" : "" }));
    card.appendChild(audio);
    Object.assign(mine, { words, bounds, spans, script });
    buildControls(body.querySelector(".sp-ctl"), mine);
    audio.addEventListener("ended", () => { paint(mine, -1); setToggle(mine); });
    await audio.play().catch(() => {});
    setToggle(mine);
    loop(mine, t);
  }

  function boundaryAt(m, ms) {
    let lo = 0, hi = m.bounds.length - 1, idx = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (m.bounds[mid].ms <= ms) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
    return idx;
  }

  function paint(m, bi) {
    const off = bi >= 0 ? m.bounds[bi].off : -1;
    let wi = -1;
    for (let i = 0; i < m.words.length; i++) if (m.words[i].off <= off) wi = i;
    m.words.forEach((w, i) => { w.el.classList.toggle("now", i === wi); w.el.classList.toggle("done", i < wi); });
    const piece = off >= 0 ? m.spans.find((s) => off >= s.start && off < s.end) : null;
    if (piece === m.lit) return;
    m.lit = piece;
    if (!piece || !piece.src) return A().setScope(null, "annotate-speaking");
    const root = A().contentOf(m.section);
    const text = A().textOf(root);
    const i = text.indexOf(piece.src);
    A().setScope(i >= 0 ? A().rangeFrom(root, i, i + piece.src.length) : null, "annotate-speaking");
  }

  function loop(m) {
    const tick = () => {
      if (current !== m) return;
      if (!document.contains(m.section)) return stop();
      paint(m, boundaryAt(m, m.audio.currentTime * 1000));
      m.raf = requestAnimationFrame(tick);
    };
    m.raf = requestAnimationFrame(tick);
  }

  function setToggle(m) {
    const b = m.card.querySelector('[data-sp="toggle"]');
    if (!b) return;
    const playing = !m.audio.paused && !m.audio.ended;
    b.innerHTML = (playing ? ICON_PAUSE : ICON_PLAY) + `<span>${playing ? "Pause" : "Play"}</span>`;
  }

  function backOneSentence(m) {
    const bi = boundaryAt(m, m.audio.currentTime * 1000);
    if (bi < 0) { m.audio.currentTime = 0; return; }
    const ends = /[.!?]["')\]]*$/;
    const startOf = (i) => { while (i > 0 && !ends.test(m.script.slice(m.bounds[i - 1].off, m.bounds[i - 1].off + m.bounds[i - 1].len))) i--; return i; };
    let s = startOf(bi);
    if (m.audio.currentTime * 1000 - m.bounds[s].ms < 600 && s > 0) s = startOf(s - 1);
    m.audio.currentTime = m.bounds[s].ms / 1000;
    paint(m, s);
  }

  function buildControls(ctl, m) {
    ctl.innerHTML =
      `<button type="button" class="sp-btn primary" data-sp="toggle"></button>`
      + `<button type="button" class="sp-btn" data-sp="back" aria-label="Back one sentence" title="Back one sentence">⟲</button>`
      + `<div class="sp-seg" data-sp="speed" role="group" aria-label="Speed">`
      + `<button type="button" data-rate="0.85">0.85×</button><button type="button" data-rate="1" aria-pressed="true">1×</button>`
      + `<button type="button" data-rate="1.2">1.2×</button></div>`;
    ctl.querySelector('[data-sp="toggle"]').addEventListener("click", () => {
      if (m.audio.paused || m.audio.ended) m.audio.play().catch(() => {}); else m.audio.pause();
      setToggle(m);
    });
    ctl.querySelector('[data-sp="back"]').addEventListener("click", () => backOneSentence(m));
    ctl.querySelectorAll('[data-sp="speed"] button').forEach((b) => b.addEventListener("click", () => {
      m.audio.playbackRate = Number(b.dataset.rate);
      ctl.querySelectorAll('[data-sp="speed"] button').forEach((o) => o.setAttribute("aria-pressed", String(o === b)));
    }));
  }

  // ── keys ────────────────────────────────────────────────────────────────
  document.addEventListener("keydown", (ev) => {
    if (!current || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (!current.card.contains(document.activeElement)) return;
    if (ev.key === " ") { ev.preventDefault(); current.card.querySelector('[data-sp="toggle"]')?.click(); }
    if (ev.key === "Escape") { ev.preventDefault(); stop(); }
  });
  document.addEventListener("annotate:rendered", () => { if (current && !document.contains(current.section)) stop(); });

  if (window.AnnotateSelection) window.AnnotateSelection.registerAction(addButtons);
  window.AnnotateSpeech = { play, stop, isPlaying: () => !!current };
})();
```

Then make three changes:
- In `entry.js`, add `"speech.js"` immediately after `"speech-client.js"`.
- In `selection.js`'s keydown handler, while a menu is open, map `r` to clicking `.sel-menu button[data-act="explain"]`. Map `R` (Shift+r) to clicking `voice-more`, then `read`, only if those buttons exist and are enabled.
- In `script.js`, add to `SETTINGS`, after the reading-size row:

```javascript
    { key: "speechvoice", attr: "speechVoice", label: "Read-aloud voice", scope: "global",
      def: "ava",
      options: [["ava", "Ava (US)"], ["andrew", "Andrew (US)"], ["emma", "Emma (US)"],
                ["brian", "Brian (US)"], ["sonia", "Sonia (UK)"], ["ryan", "Ryan (UK)"]] },
```

- [ ] **Step 5: Style it**

Append to `style.css`:

```css
/* ── Read-aloud ─────────────────────────────────────────────────────────
   The explainer card sits under the passage, in the comment box's wash.
   Words ahead are dimmed, the word being heard is tinted, and the page
   sentence being explained is lit like a reading highlight. */
.sp-card {
  display: block; margin: 8px 0 4px; padding: 10px 12px; border-radius: 10px;
  background: var(--type-comment-wash);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 16%, transparent);
  font-weight: 400; font-style: normal;
}
.sp-head { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-dim); margin-bottom: 6px; }
.sp-head b { color: var(--text-strong); }
.sp-x { margin-left: auto; width: 24px; height: 24px; border-radius: 50%; border: 1px solid var(--border);
  background: var(--surface); color: var(--text-dim); cursor: pointer; }
.sp-script { font-size: 15px; line-height: 1.65; color: var(--text); }
.sp-script .w { border-radius: 4px; transition: opacity 90ms linear, background 90ms linear; }
.sp-script.playing .w { opacity: .38; }
.sp-script.playing .w.done { opacity: 1; }
.sp-script .w.now { opacity: 1; color: var(--text-strong); background: color-mix(in srgb, var(--accent) 16%, transparent); }
.sp-ctl { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.sp-btn { height: 28px; padding: 0 10px; border-radius: 6px; border: 1px solid var(--control-border);
  background: transparent; color: var(--text); font: inherit; font-size: 12.5px; font-weight: 500;
  display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.sp-btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); font-weight: 600; }
.sp-btn svg, .sel-menu [data-act="explain"] svg { width: 13px; height: 13px; fill: currentColor; }
.sp-seg { display: inline-flex; border: 1px solid var(--control-border); border-radius: 6px; overflow: hidden; }
.sp-seg button { border: 0; background: transparent; color: var(--text); font: inherit; font-size: 12px; padding: 4px 9px; cursor: pointer; }
.sp-seg button[aria-pressed="true"] { background: var(--accent); color: var(--accent-fg); }
.sp-wait { display: inline-flex; gap: 6px; align-items: center; font-size: 12.5px; color: var(--text-dim); }
.sp-wait i { width: 5px; height: 5px; border-radius: 50%; background: var(--accent); animation: sp-blink 1s infinite; }
.sp-wait i:nth-child(2) { animation-delay: .2s; } .sp-wait i:nth-child(3) { animation-delay: .4s; }
@keyframes sp-blink { 50% { opacity: .2; } }
.sp-error { font-size: 13px; color: var(--text); margin-bottom: 8px; }
::highlight(annotate-speaking) { background-color: var(--highlight); }
.sel-menu button[disabled] { opacity: .45; cursor: not-allowed; }
@media (prefers-reduced-motion: reduce) { .sp-script .w { transition: none; } .sp-wait i { animation: none; } }
body.read-only .sp-card { display: none; }
```

Add `.sp-card` to `export.js`'s STRIP list.

- [ ] **Step 6: Run the tests, look at it, run everything**

Run: the command from Step 2. Expected: all 8 pass.
Take two screenshots of `SEL.format("section-1")` while the karaoke is on its second piece, one in light and one in dark (`document.body.dataset.pageTheme = 'dark'`). Read them and confirm three things: the current word is readable, the dimmed words are still legible, and the yellow page lighting doesn't hide the struck or underlined marks. Put the paths in the report.
Then run the full suite. Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add skills/annotate/static/speech.js skills/annotate/static/anchors.js skills/annotate/static/entry.js skills/annotate/static/selection.js skills/annotate/static/script.js skills/annotate/static/style.css skills/annotate/static/export.js skills/annotate/tests/test_browser_speech.py
git commit -m "feat(annotate): Explain and Read as written speak the selection, lighting each word and the page sentence in step"
```

---

### Task 3: dictation through Azure

**Files:**
- Modify: `skills/annotate/static/voice.js` (rewrite)
- Modify: `skills/annotate/static/script.js` (Settings row "Dictation language")
- Modify: `skills/annotate/static/style.css` (the listening state and grey interim text)
- Test: `skills/annotate/tests/test_browser_speech.py` (append)

**Interfaces:**
- Consumes: `AnnotateSpeechClient.status`, `token`, `loadSdk`, `pageContext` (Task 1).
- Produces: 🎤 in every `.card-submit-row` (the section comment card) and every `.sel-row` (the span comment box). Text is inserted at the caret. Interim text shows in `.voice-interim` beside the field and is committed on `recognized`. Each change dispatches a synthetic `input` event, as today.

- [ ] **Step 1: Write the failing tests**

```python
# append to skills/annotate/tests/test_browser_speech.py

REC_DOUBLE = """
(() => {
  const base = window.SpeechSDK;
  window.__rec = null;
  window.SpeechSDK = Object.assign({}, base, {
    AudioConfig: { fromDefaultMicrophoneInput: () => ({ mic: true }) },
    PhraseListGrammar: { fromRecognizer: (r) => ({ addPhrase: (p) => r.phrases.push(p) }) },
    SpeechRecognizer: class {
      constructor(cfg) { this.cfg = cfg; this.phrases = []; window.__rec = this; }
      startContinuousRecognitionAsync(ok) { setTimeout(() => ok && ok(), 0); }
      stopContinuousRecognitionAsync(ok) { setTimeout(() => ok && ok(), 0); }
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
    return page


def _open_span_comment(page):
    _sel(page, "section-1", "Paragraph one")
    page.click('.sel-menu button[data-act="comment"]')
    page.wait_for_selector(".sel-composer textarea")


def test_dictation_writes_grey_then_solid_text_into_the_box(dpage):
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec && !!window.__rec.recognizing", timeout=5000)
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
    dpage.wait_for_function("() => !!window.AnnotateSpeech")
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => window.__rec && window.__rec.phrases.length === 2", timeout=5000)
    assert dpage.evaluate("() => window.__rec.phrases") == ["EDR", "taxon"]


def test_the_language_setting_reaches_the_recognizer(dpage):
    dpage.evaluate("() => localStorage.setItem('annotate.view:dictationlang', 'el-GR')")
    _routes(dpage)
    _open_span_comment(dpage)
    dpage.click(".sel-composer .voice-mic-btn")
    dpage.wait_for_function("() => !!window.__rec", timeout=5000)
    assert dpage.evaluate("() => window.__rec.cfg.speechRecognitionLanguage") == "el-GR"


def test_the_mic_is_disabled_with_a_reason_when_speech_is_not_set_up(dpage):
    _routes(dpage, status={"configured": False, "claude": False, "reason": "x"})
    _open_span_comment(dpage)
    mic = dpage.locator(".sel-composer .voice-mic-btn")
    mic.wait_for(timeout=3000)
    dpage.wait_for_function("() => document.querySelector('.sel-composer .voice-mic-btn').disabled", timeout=3000)
    assert "webcompanion doctor" in mic.get_attribute("title")


def test_the_section_comment_card_has_the_mic_too(dpage):
    _routes(dpage)
    dpage.dblclick(SEL.format("section-1") + " .card-title")
    dpage.click('.sel-menu button[data-act="comment"]')
    dpage.wait_for_selector(".comment-card .card-submit-row .voice-mic-btn", timeout=3000)
```

- [ ] **Step 2: Watch them fail**

Run: `uv run -q --with pytest --with pytest-xdist --with playwright python -m pytest skills/annotate/tests/test_browser_speech.py -q -n 0 -k "dictation or mic or language"`
Expected: they fail. The span box has no `.voice-mic-btn`, because the old `voice.js` only scans `.card-submit-row`. Recognition never reaches the double, because the old code uses the browser's own `SpeechRecognition`.

- [ ] **Step 3: Rewrite `voice.js`**

```javascript
// skills/annotate/static/voice.js
/* Dictation into annotate's comment boxes, through Azure speech-to-text.
 *
 * The 🎤 sits in every comment box (the section card's submit row and the
 * span comment box). Words still being recognised show in grey beside the
 * field; when Azure finalises a phrase it is inserted at the caret and an
 * `input` event is dispatched, so draft saving and auto-grow behave exactly
 * as if it had been typed. The page's glossary terms are given to Azure as a
 * phrase list, so the document's own vocabulary is recognised.
 *
 * Azure replaces the browser's SpeechRecognition, which only Chrome had and
 * which refused the .mac domains.
 */
(function () {
  "use strict";

  const SETUP_HINT = "Dictation needs Azure set up — run `webcompanion doctor`";
  let active = null;   // {rec, btn, ta, interim}

  function language() {
    let v = null;
    try { v = localStorage.getItem("annotate.view:dictationlang"); } catch (_) {}
    if (v && v !== "auto") return v;
    return navigator.language || "en-US";
  }

  function insertAtCaret(ta, text) {
    const s = ta.selectionStart ?? ta.value.length, e = ta.selectionEnd ?? ta.value.length;
    const before = ta.value.slice(0, s), after = ta.value.slice(e);
    const pad = before && !/\s$/.test(before) ? " " : "";
    ta.value = before + pad + text + after;
    const at = (before + pad + text).length;
    ta.setSelectionRange(at, at);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function stopActive() {
    if (!active) return;
    const a = active;
    active = null;
    try { a.rec.stopContinuousRecognitionAsync(() => a.rec.close(), () => a.rec.close()); } catch (_) {}
    a.btn.classList.remove("listening");
    a.btn.setAttribute("aria-pressed", "false");
    a.interim.textContent = "";
  }

  async function start(ta, btn, interim) {
    stopActive();
    const C = window.AnnotateSpeechClient;
    let SDK, tok;
    try { SDK = await C.loadSdk(); tok = await C.token(); }
    catch (e) { btn.title = "Azure didn't answer — " + e.message; return; }
    const cfg = SDK.SpeechConfig.fromAuthorizationToken(tok.token, tok.region);
    cfg.speechRecognitionLanguage = language();
    const rec = new SDK.SpeechRecognizer(cfg, SDK.AudioConfig.fromDefaultMicrophoneInput());
    const phrases = SDK.PhraseListGrammar.fromRecognizer(rec);
    const section = ta.closest("section.block");
    for (const g of (C.pageContext(section).glossary || [])) if (g && g.term) phrases.addPhrase(g.term);
    rec.recognizing = (_r, e) => { if (ta.isConnected) interim.textContent = e.result.text; };
    rec.recognized = (_r, e) => {
      if (!ta.isConnected) return stopActive();
      interim.textContent = "";
      if (e.result.reason === SDK.ResultReason.RecognizedSpeech && e.result.text) insertAtCaret(ta, e.result.text);
    };
    rec.canceled = (_r, e) => { btn.title = "Dictation stopped — " + (e.errorDetails || "the microphone was refused"); stopActive(); };
    active = { rec, btn, ta, interim };
    btn.classList.add("listening");
    btn.setAttribute("aria-pressed", "true");
    rec.startContinuousRecognitionAsync();
  }

  function makeMic(ta) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "voice-mic-btn";
    btn.textContent = "🎤";
    btn.title = "Dictate (speech to text)";
    btn.setAttribute("aria-label", "Dictate comment");
    btn.setAttribute("aria-pressed", "false");
    const interim = document.createElement("span");
    interim.className = "voice-interim";
    interim.setAttribute("aria-live", "polite");
    window.AnnotateSpeechClient?.status().then((s) => {
      if (!s.configured) { btn.disabled = true; btn.title = SETUP_HINT; }
    }).catch(() => { btn.disabled = true; btn.title = SETUP_HINT; });
    btn.addEventListener("mousedown", (e) => e.preventDefault());
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (active && active.btn === btn) stopActive(); else start(ta, btn, interim);
    });
    return { btn, interim };
  }

  function attach(row) {
    if (row.querySelector(".voice-mic-btn")) return;
    const box = row.closest(".comment-card, .sel-composer");
    const ta = box && box.querySelector("textarea");
    if (!ta) return;
    const { btn, interim } = makeMic(ta);
    const submit = row.querySelector(".card-submit-btn");
    row.insertBefore(interim, row.firstChild ? row.firstChild.nextSibling : null);
    if (submit) row.insertBefore(btn, submit); else row.appendChild(btn);
  }

  function scan(root) {
    if (root.nodeType !== 1) return;
    if (root.matches(".card-submit-row, .sel-row")) attach(root);
    root.querySelectorAll(".card-submit-row, .sel-row").forEach(attach);
  }
  new MutationObserver((ms) => { for (const m of ms) for (const n of m.addedNodes) scan(n); })
    .observe(document.body, { childList: true, subtree: true });
  scan(document.body);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") stopActive(); });
})();
```

`voice.js` loads in `entry.js` *before* `speech-client.js`. That's fine, because it only touches `AnnotateSpeechClient` when a box is created or the mic is pressed, and both happen after boot.

In `script.js`'s `SETTINGS`, after the voice row, add:

```javascript
    { key: "dictationlang", attr: "dictationLang", label: "Dictation language", scope: "global",
      def: "auto",
      options: [["auto", "Browser's"], ["en-US", "English (US)"], ["en-GB", "English (UK)"],
                ["el-GR", "Greek"], ["fr-FR", "French"]] },
```

In `style.css`, append:

```css
.voice-interim { font-size: 12.5px; color: var(--text-dim); font-style: italic; margin-right: auto;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 50%; }
.voice-mic-btn.listening { background: #dc2626; color: #fff; border-color: #dc2626; border-radius: 50%; }
.voice-mic-btn[disabled] { opacity: .45; cursor: not-allowed; }
```

Check the existing `.voice-mic-btn` and `.card-submit-hint` rules first. The interim span sits where the hint is, so hide the hint while listening with `.listening ~ .card-submit-hint, .sel-row:has(.listening) .card-submit-hint { display: none; }`.

- [ ] **Step 4: Run the tests, then everything**

Run: the command from Step 2. Expected: 5 pass.
Then the full suite. `test_smoke_*` tests that named the old `SpeechRecognition` (`grep -rn "SpeechRecognition\|webkitSpeechRecognition" skills/annotate/tests`) must be updated to the new behaviour. Each is a source-string test: replace its assertion with one that `voice.js` uses `SpeechRecognizer` and `fromAuthorizationToken`. Expected afterwards: all green.

- [ ] **Step 5: Commit**

```bash
git add skills/annotate/static/voice.js skills/annotate/static/script.js skills/annotate/static/style.css skills/annotate/tests
git commit -m "feat(annotate): dictation goes through Azure, primed with the page's glossary, in every comment box"
```

---

### Task 4: the live check (controller, after merge)

Not a subagent task. Run it on this machine after the branch is merged and pushed:

1. Open a real annotate page, for example `/annotate` on the ABC-310 text, from the Mac.
2. Select a sentence and press **Explain**. Sound must start within about 10 s. The words light in step with the voice, and the page sentence lights yellow.
3. Press **Read as written** on another sentence. It must start within about 2 s.
4. Pause, go back one sentence, and set 1.2×. The highlight must stay on the word being heard.
5. Open a comment, press 🎤, and say "The taxon waits for EDR". Grey text, then solid text with "EDR" spelled as the glossary has it.
6. Repeat steps 2 and 5 in Safari (spec §9 risk).
7. Report the timings measured, and a screenshot of the karaoke card, through `@devdomains share` and SendUserFile.
