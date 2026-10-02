"""annotate's page, driven in a real browser against a live daemon.

Everything else in this suite asserts against source strings: that a selector
exists, that a function is called, that a rule is in the stylesheet. None of it
can see the page. The bug that made this file necessary passed every one of
those checks — `openAnnotation` created a draft, saved it, and called
`renderComments` to draw its card, and `renderComments` pruned every empty
draft, which a just-opened comment is. Clicking the comment icon wrote a draft
to localStorage and deleted it again in the same tick. The page did not
flicker. It reached a user before a test did.

There were 19 browser suites once. They spawned annotate's own server, which no
longer exists, and were deleted with it (8ebf419) with a note that they were
repointable. This is that, repointed onto the daemon and rewritten around the
paths that actually broke rather than restored file by file.

Running it::

    pip install playwright && playwright install chromium
    python3 -m pytest skills/annotate/tests/test_browser_review.py -q

Without playwright the whole module skips, exactly as webcompanion's own
browser suite does, so `pytest skills` stays green on a machine that has not
installed a browser. It needs a webcompanion daemon on this machine; it
creates its own session, serves the page from THIS checkout, and deletes the
session afterwards, so it never touches a document anyone is reading.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
CONFIG = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))


def _daemon_url():
    if not CONFIG.is_file():
        pytest.skip("no webcompanion daemon configured on this machine")
    port = json.loads(CONFIG.read_text())["port"]
    url = f"http://127.0.0.1:{port}"
    try:
        urllib.request.urlopen(url + "/health", timeout=3).read()
    except (urllib.error.URLError, OSError):
        pytest.skip(f"webcompanion daemon is not answering on {url}")
    return url


def _call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


def _put_progress(document, steps, state="working", started=None, ended=None,
                  event_id="evt-browser"):
    """Write the trail the way skills/annotate/progress.py does."""
    started = started or int(time.time())
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__progress__", {
        "id": "__progress__", "kind": "progress", "state": state,
        "started_at": started, "ended_at": ended, "event_id": event_id,
        "steps": [{"t": started + i, "text": s} for i, s in enumerate(steps)],
    })


def _outbound_host() -> str:
    """This machine's real interface address — one `_is_owner` (server.py)
    cannot mistake for loopback. UDP `connect()` sends no packet; it only
    asks the kernel which local address would carry traffic to that
    destination, so this needs no network access to succeed."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


BLOCKS = ["section-1", "section-2", "section-3", "section-4"]


@pytest.fixture
def document(tmp_path):
    """A throwaway annotate document, served from this checkout."""
    base = _daemon_url()
    s = _call(base, "POST", "/api/sessions",
              {"kind": "annotate", "cwd": str(REPO), "title": "annotate browser suite"})
    sid = s["sid"]
    try:
        _call(base, "POST", f"/s/{sid}/api/assets",
              {"static_root": str(STATIC), "entry": "entry.js"})
        _call(base, "PUT", f"/s/{sid}/items/__doc__",
              {"response_id": "resp-browser-suite", "title": "annotate browser suite",
               "order": BLOCKS, "cwd": str(REPO), "glossary": []})
        for i, anchor in enumerate(BLOCKS, 1):
            _call(base, "PUT", f"/s/{sid}/items/{anchor}",
                  {"id": anchor, "kind": "markdown", "title": f"Block {i}",
                   "markdown": f"Paragraph one of block {i}, long enough to scroll past.\n\n"
                               f"Paragraph two of block {i}."})
        yield {"base": base, "sid": sid, "url": f"{base}/s/{sid}/"}
    finally:
        # DELETE /s/<sid>/?force=1 — the route `webcompanion forget` uses. An
        # earlier version of this posted to /api/sessions/delete, which does not
        # exist, inside a bare `except Exception: pass`. Every run then left its
        # session in the registry and said nothing; 28 of them accumulated
        # before anyone counted. A teardown that cannot fail out loud is not a
        # teardown, so the failure is reported even though it cannot fail the
        # test it belongs to.
        _call(base, "POST", f"/s/{sid}/api/finish")
        try:
            _call(base, "DELETE", f"/s/{sid}/?force=1")
        except Exception as e:                       # noqa: BLE001
            import warnings
            warnings.warn(f"browser suite leaked session {sid}: {e}")


def _serve_core_override(target):
    """Serve a local webcompanion core.js in place of the daemon's.

    The lock tests need the daemon's runtime to deliver `event-acked` to the
    page. A daemon that has not been restarted since that fix keeps serving
    the broken runtime, and every lock test then fails for a reason that is
    not annotate's. Point WC_CORE_JS at a fixed core.js to test annotate's
    half against it anyway; unset, the daemon's own runtime is used."""
    path = os.environ.get("WC_CORE_JS")
    if path:
        body = Path(path).read_text()
        target.route("**/_wc/core.js", lambda route: route.fulfill(
            status=200, content_type="application/javascript", body=body))


@pytest.fixture
def page(document):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page()
        _serve_core_override(pg)
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        try:
            pg.goto(document["url"])
            pg.wait_for_selector("section.block", timeout=15000)
            pg.wait_for_function("() => !!window.AnnotateSubunits", timeout=15000)
            # entry.js loads the rest in order after subunits.js; under a
            # loaded parallel run a test could act before the menu (or the
            # maximise control, loaded near the end) exists.
            pg.wait_for_function(
                "() => !!window.AnnotateSelection && !!window.AnnotateMaximize", timeout=15000)
            pg.__dict__["js_errors"] = errors
            yield pg
        finally:
            browser.close()


def test_the_comment_icon_opens_a_comment(page):
    """The one that got out. Every source-level check passed while this failed."""
    _block_mark(page, "section-1", "comment")
    page.wait_for_selector(".comment-card textarea", timeout=5000)
    assert page.eval_on_selector(
        ".comment-card textarea", "el => el === document.activeElement"), \
        "the card opened without taking the caret"

    page.fill(".comment-card textarea", "does this survive")
    page.wait_for_function(
        "() => (localStorage.getItem('annotate.drafts.resp-browser-suite') || '')"
        ".includes('does this survive')", timeout=5000)


def test_a_second_comment_is_refused_out_loud(page):
    """One editor at a time is the rule; refusing in silence was the bug."""
    _block_mark(page, "section-1", "comment")
    page.wait_for_selector(".comment-card textarea")
    page.fill(".comment-card textarea", "holding this open")

    _block_mark(page, "section-3", "comment")
    page.wait_for_selector(".comment-card.is-calling", timeout=3000)
    assert page.locator(".comment-card").count() == 1, "a second editor opened"


def test_the_keyboard_walks_the_document(page):
    page.keyboard.press("j")
    page.wait_for_selector("section.block[data-kb-focus]")
    first = page.get_attribute("section.block[data-kb-focus]", "data-block-id")
    page.keyboard.press("j")
    second = page.get_attribute("section.block[data-kb-focus]", "data-block-id")
    assert first != second, "j did not move the cursor"

    page.keyboard.press("c")
    page.wait_for_selector(".comment-card", timeout=5000)
    owner = page.eval_on_selector(
        ".comment-card", "el => el.closest('.inline-comments')"
        ".previousElementSibling.dataset.blockId")
    assert owner == second, "c commented on the wrong block"


def _open_settings(page):
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click('[data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'",
        timeout=3000)


def test_the_settings_panel_paints_and_persists(page):
    _open_settings(page)
    page.click('[data-setting="codefont"] [data-value="monaspace"]')
    page.click('[data-setting="textsize"] [data-value="large"]')
    page.wait_for_function(
        "() => document.body.dataset.codeFont === 'monaspace' "
        "&& document.body.dataset.textSize === 'large'", timeout=3000)

    family = page.evaluate(
        "() => getComputedStyle(document.body).getPropertyValue('--font-code')")
    assert "Monaspace" in family, f"the choice did not reach the token: {family}"

    page.reload()
    page.wait_for_selector("section.block")
    assert page.evaluate("() => document.body.dataset.codeFont") == "monaspace", \
        "a reader preference did not survive a reload"

    _open_settings(page)
    page.click("#settings-reset")
    page.wait_for_function(
        "() => document.body.dataset.codeFont === 'jetbrains' "
        "&& document.body.dataset.textSize === 'medium'", timeout=3000)


def test_the_prose_is_set_in_inter_and_nothing_offers_another(page):
    """One prose face. The panel's typeface row is gone, and a choice stored
    before it went has nothing left to reach the page through."""
    family = page.eval_on_selector(
        "main.prose p", "el => getComputedStyle(el).fontFamily")
    assert family.replace('"', "'").startswith(("'Inter'", "Inter")), \
        f"the prose is not set in Inter: {family}"
    page.evaluate("() => document.fonts.ready")
    assert page.evaluate("() => document.fonts.check('16px Inter')"), \
        "the Inter face did not load"

    _open_settings(page)
    rows = page.eval_on_selector_all(
        "#settings-groups .set-group",
        "els => els.map(e => e.dataset.setting)")
    labels = page.eval_on_selector_all(
        "#settings-groups .set-label", "els => els.map(e => e.textContent)")
    assert "prosefont" not in rows and "Prose font" not in labels, rows
    assert "codelayout" not in rows and "Code panes" not in labels, rows

    page.evaluate("() => localStorage.setItem('annotate.view:prosefont', 'serif')")
    page.reload()
    page.wait_for_selector("section.block")
    family = page.eval_on_selector(
        "main.prose p", "el => getComputedStyle(el).fontFamily")
    assert "Serif" not in family and "Inter" in family, family


def test_code_panes_scroll_rather_than_wrap(page):
    """No code pane in this fixture, so assert the rule the panes depend on."""
    wraps = page.evaluate(
        "() => { const s = [...document.styleSheets].flatMap(x => { try { return [...x.cssRules]; }"
        " catch (_) { return []; } });"
        " const r = s.find(r => r.selectorText === '.cp-line');"
        " return r && r.style.whiteSpace; }")
    assert wraps == "pre", f".cp-line is {wraps!r}, so long lines fold again"


# An authored anchor, not a resolved pane: the daemon resolves it against the
# document's cwd (this checkout) exactly as a real push's would be.
_CODE_PANE = {"file": "skills/annotate/render.py", "line": 24,
              "snippet": "def render_block(blk: dict) -> dict:"}


def test_a_code_card_stacks_its_code_under_the_prose(page, document):
    """Code never sits beside the prose. Measured, because a grid rule that
    still matches paints two columns while every source check passes."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-2",
          {"id": "section-2", "kind": "markdown", "title": "Block 2",
           "markdown": "Prose that cites a line of code.", "code": [_CODE_PANE]})
    page.wait_for_selector('[data-block-id="section-2"] .code-col .cp-row', timeout=10000)
    got = page.evaluate("""() => {
      const card = document.querySelector('[data-block-id="section-2"]');
      const body = card.querySelector('.card-body');
      const prose = body.querySelector(':scope > .block-content').getBoundingClientRect();
      const code = body.querySelector(':scope > .code-col').getBoundingClientRect();
      const cs = getComputedStyle(body);
      const inner = body.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      return { display: cs.display, cols: cs.gridTemplateColumns,
               proseW: prose.width, codeW: code.width, inner,
               codeTop: code.top, proseBottom: prose.bottom,
               codeLeft: code.left, proseLeft: prose.left,
               widen: document.querySelectorAll('.cp-widen').length,
               wideAttr: card.hasAttribute('data-code-wide') }; }""")
    assert got["display"] != "grid" or " " not in got["cols"].strip(), \
        f"the card body is still a grid of {got['cols']}"
    assert got["codeTop"] >= got["proseBottom"] - 0.5, \
        f"the code pane is not beneath the prose: {got}"
    assert abs(got["codeLeft"] - got["proseLeft"]) < 0.5, got
    assert abs(got["codeW"] - got["inner"]) < 0.5, \
        f"the code pane is {got['codeW']:.0f}px in a {got['inner']:.0f}px card body"
    assert abs(got["proseW"] - got["inner"]) < 0.5, got
    assert got["widen"] == 0, "a per-pane widen button is still rendered"
    assert not got["wideAttr"], "the card still carries data-code-wide"


_MEASURE_WIDTH = """() => {
  const main = document.querySelector('main.prose').getBoundingClientRect();
  const card = document.querySelector('section.block').getBoundingClientRect();
  const bar = document.querySelector('.page-header');
  return { width: document.body.dataset.width,
           main: main.width, card: card.width, cardLeft: card.left,
           view: document.documentElement.clientWidth,
           gutter: parseFloat(getComputedStyle(document.body)
             .getPropertyValue('--content-gutter')),
           barPad: parseFloat(getComputedStyle(bar).paddingLeft),
           barRight: bar.querySelector('.header-actions').getBoundingClientRect().right }; }"""


def test_the_width_stops_measure_what_they_claim(page):
    """Normal is a 1600px column and Wide is the whole viewport less the side
    gutters. On a 1920px screen those differ by 272px, and the bar above them
    must not move at all between the two."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    normal = page.evaluate(_MEASURE_WIDTH)
    assert normal["width"] == "normal"
    assert normal["main"] == 1600, f"Normal measures {normal['main']}px"

    _open_settings(page)
    rows = page.eval_on_selector_all('[data-setting="pagewidth"] [data-value]',
                                     "els => els.map(e => e.dataset.value)")
    assert rows == ["normal", "wide"], f"the panel offers {rows}"
    page.click('[data-setting="pagewidth"] [data-value="wide"]')
    page.keyboard.press("Escape")
    wide = page.evaluate(_MEASURE_WIDTH)
    assert wide["width"] == "wide"
    assert wide["main"] == wide["view"], \
        f"Wide measures {wide['main']}px on a {wide['view']}px viewport"
    assert wide["card"] == wide["view"] - 2 * wide["gutter"], wide
    # The bar is full width at every stop, so it shares Wide's left edge and
    # its controls sit where they sat at Normal.
    assert wide["barPad"] == wide["gutter"] == normal["barPad"], (normal, wide)
    assert wide["cardLeft"] == wide["barPad"], wide
    assert wide["barRight"] == normal["barRight"], (normal, wide)


def test_a_page_with_no_width_attribute_reads_at_the_normal_column(page):
    """An export may carry no data-width at all; it must open at Normal's
    1600px, not at some older default."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    got = page.evaluate("""() => { delete document.body.dataset.width;
      return [getComputedStyle(document.body).getPropertyValue('--content-max').trim(),
              document.querySelector('main.prose').getBoundingClientRect().width]; }""")
    assert got == ["1600px", 1600], got


def test_a_width_stored_under_the_retired_key_is_swept(page):
    """The pre-rename `width` key named columns that no longer exist, and
    every value it could hold is narrower than Normal. It is removed on load
    rather than mapped, and the page opens on Normal."""
    rid = "resp-browser-suite"
    page.evaluate("(rid) => localStorage.setItem(`annotate.view:${rid}:width`, 'extra')", rid)
    page.reload()
    page.wait_for_selector("section.block")
    assert page.evaluate("() => document.body.dataset.width") == "normal"
    assert page.evaluate(
        "(rid) => localStorage.getItem(`annotate.view:${rid}:width`)", rid) is None


def test_the_dark_theme_holds_its_distances(page):
    """Source checks cannot see a colour. These are the numbers on screen.

    The card has to lift off the page, the code pane has to stay visible
    inside the card it sits in, and the prose has to be readable on it. Those
    are the three things a dark theme gets wrong, and none of them is
    detectable by reading CSS.
    """
    page.evaluate("() => localStorage.setItem('annotate.view:pagetheme', 'dark')")
    page.reload()
    page.wait_for_selector("section.block")
    assert page.evaluate("() => document.body.dataset.pageTheme") == "dark"

    got = page.evaluate("""() => {
      const cv = document.createElement('canvas').getContext('2d');
      const rgb = v => { cv.fillStyle = v; cv.fillRect(0, 0, 1, 1);
        const d = cv.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; };
      const lum = c => { const [r,g,b] = rgb(c).map(v => { v /= 255;
        return v <= 0.04045 ? v/12.92 : ((v+0.055)/1.055) ** 2.4; });
        return 0.2126*r + 0.7152*g + 0.0722*b; };
      const L = c => { const y = lum(c);
        return y > 0.008856 ? 116 * Math.cbrt(y) - 16 : 903.3 * y; };
      const ratio = (a, b) => { const x = lum(a), y = lum(b);
        return (Math.max(x,y) + 0.05) / (Math.min(x,y) + 0.05); };
      const g = (s, p) => getComputedStyle(document.querySelector(s))[p];
      const card = g('section.block', 'backgroundColor');
      return { lift: L(card) - L(g('body', 'backgroundColor')),
               pane: Math.abs(L(card) - L('#1a1b26')),
               prose: ratio(g('.block-content', 'color'), card),
               dim: ratio(getComputedStyle(document.body)
                 .getPropertyValue('--text-dim').trim(), card) }; }""")
    assert got["lift"] >= 6.0, f"the card does not lift off the page: {got['lift']:.1f} L*"
    assert got["pane"] >= 5, f"the code pane dissolves into the card: {got['pane']:.1f} L*"
    assert got["prose"] >= 7, f"prose on the card is {got['prose']:.1f}:1"
    assert got["dim"] >= 4.5, f"dim text on the card is {got['dim']:.1f}:1"


def test_a_diagram_fills_with_the_card_not_with_white(page):
    """Nine rules mixed their tint over a literal `white`. On a dark card each
    one punched a white hole and then wrote light text on it."""
    page.evaluate("() => localStorage.setItem('annotate.view:pagetheme', 'dark')")
    page.reload()
    page.wait_for_selector("section.block")
    # This fixture is prose-only, so assert the rule the shapes resolve through
    # rather than a shape that is not on the page.
    ground = page.evaluate(
        "() => getComputedStyle(document.body)"
        ".getPropertyValue('--diagram-ground').trim()")
    assert ground and ground.lower() not in ("#ffffff", "#fff", "white"), \
        f"diagrams still fill with white on a dark page: {ground!r}"


def test_the_page_raises_nothing(page, document):
    """Waits for a real update to land rather than for a fixed stretch of
    time: a block rewritten over the daemon has to travel the stream, the
    reconcile and the re-render, which is every path a runtime error could
    come from."""
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-2",
          {"id": "section-2", "kind": "markdown", "title": "Block 2",
           "markdown": "Rewritten while the page watched."})
    page.wait_for_function(
        "() => (document.querySelector('section.block[data-block-id=\"section-2\"]')"
        " || {}).textContent?.includes('Rewritten while the page watched')",
        timeout=10000)
    assert page.__dict__["js_errors"] == [], page.__dict__["js_errors"]


def test_the_menu_pushes_a_pane_and_comes_back(page):
    """The one genuinely new interaction. Everything else in the menu is an
    element that moved, and the module that owns it never noticed."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    assert page.eval_on_selector(
        "#menu-pop", "el => el.dataset.pane") == "root"

    page.click('[data-pane-to="help"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'help'")
    # Exactly one pane visible — the rule is a display swap, and a swap that
    # shows two is a panel twice as tall as it should be.
    assert page.eval_on_selector_all(
        ".menu-pane", "els => els.filter(e => e.offsetParent !== null).length") == 1

    page.click('.menu-pane[data-pane-name="help"] [data-pane-to="root"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'root'")

    # Closing and reopening must land on root, however it was closed.
    page.click('[data-pane-to="settings"]')
    page.keyboard.press("Escape")
    # state="hidden" rather than the selector "#menu-pop[hidden]": Playwright's
    # default wait state is "visible", and an element the [hidden] attribute
    # forces to display:none can never satisfy that — the selector-form wait
    # timed out forever even though the attribute was already set correctly.
    page.wait_for_selector("#menu-pop", state="hidden")
    page.click("#menu-toggle")
    assert page.eval_on_selector("#menu-pop", "el => el.dataset.pane") == "root", \
        "the menu remembered where you were last time"


def test_the_bar_is_three_controls_wide(page):
    """Measured, not asserted from source: a rule that does not match paints
    nothing, and a source test cannot tell the difference."""
    visible = page.eval_on_selector_all(
        ".header-actions > *",
        "els => els.filter(e => e.offsetParent !== null)"
        ".map(e => e.id || e.className)")
    # The search wrapper, the menu's icon-btn-wrap, and Done. The highlighter
    # is not armed, so it must not be painting.
    assert len(visible) == 3, f"the bar is painting {len(visible)} controls: {visible}"
    assert page.eval_on_selector(
        "#highlighter-toggle", "el => el.offsetParent === null"), \
        "the highlighter is visible while disarmed"


def test_arming_the_highlighter_brings_its_button_back(page):
    """A mode with no indicator is a bug. This is the whole escape clause."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click("#menu-highlighter")
    page.wait_for_function(
        "() => document.getElementById('highlighter-toggle')"
        ".getAttribute('aria-pressed') === 'true'", timeout=3000)
    assert page.eval_on_selector(
        "#highlighter-toggle", "el => el.offsetParent !== null"), \
        "the highlighter is armed and its button is still invisible"

    # And the proxy mirrors it rather than keeping a second copy of the truth.
    assert page.eval_on_selector(
        "#menu-highlighter", "el => el.getAttribute('aria-pressed')") == "true"


def test_the_two_slot_writers_land_in_their_slots(page):
    """Task 2 taught export.js and fullscreen.js to write to a slot instead of
    over the whole button, because a menu row is an icon AND a label. Nothing
    proved that at runtime — both modules are covered only by source-string
    assertions, and a wrong selector would silently eat one or the other.
    fullscreen.js's sync() runs at init, so its slot is already exercised by
    the time this page is ready."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")

    # Full screen: the icon went INTO the slot, and the label survived it.
    assert page.eval_on_selector(
        "#fullscreen-toggle", "el => !!el.querySelector('[data-icon] svg')"), \
        "fullscreen.js wrote its icon somewhere other than the slot"
    assert "Full screen" in page.text_content("#fullscreen-toggle"), \
        "fullscreen.js's icon write ate the row's label"

    # Share: click it and watch the LABEL change, not the whole row. The click
    # really does build and download the document, so the download is accepted
    # and discarded — expect_download also keeps the click from hanging.
    with page.expect_download() as dl:
        page.click("#export-btn")
    dl.value
    page.wait_for_function(
        "() => document.querySelector('#export-btn [data-label]')"
        ".textContent.trim() === 'Saved ✓'", timeout=10000)
    assert page.eval_on_selector(
        "#export-btn", "el => !!el.querySelector('svg')"), \
        "export.js's status write ate the row's icon"


def test_search_takes_the_bar_and_gives_it_back(page):
    page.click("#block-search")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching === '1'")
    title_hidden = page.eval_on_selector(
        ".header-title", "el => el.offsetParent === null")
    assert title_hidden, "the title did not step aside"

    # The field must actually be wide — a takeover that leaves it at 26px is
    # the defect this test exists for. `.header-search` has a 160ms width
    # transition, so sampled on the tick after data-searching flips it still
    # reads 26px on a page behaving perfectly; wait for the transition to
    # land rather than sampling mid-flight, exactly as a
    # transition-aware wait should.
    page.wait_for_function(
        "() => document.querySelector('.header-search')"
        ".getBoundingClientRect().width > 400", timeout=3000)
    width = page.eval_on_selector(
        ".header-search", "el => el.getBoundingClientRect().width")
    assert width > 400, f"the field took the bar and stayed narrow: {width}px"

    page.keyboard.press("Escape")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching !== '1'")
    assert page.eval_on_selector(
        ".header-title", "el => el.offsetParent !== null"), \
        "the title did not come back"


def test_the_status_block_does_not_overflow_the_menu(page):
    """Decision 5 folds the resume popover into the status block, which is
    the first thing in the menu — so a long project path breaking the panel's
    own layout is the redesign's centrepiece failing, not a cosmetic overflow.
    The fixture's cwd is this checkout's own path, which has no natural break
    point and is long enough to expose it."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.wait_for_function(
        "() => document.getElementById('menu-resume') "
        "&& !document.getElementById('menu-resume').hidden "
        "&& document.getElementById('resume-cwd').textContent.trim().length > 0",
        timeout=5000)

    overflow = page.evaluate("""() => {
      const pop = document.getElementById('menu-pop');
      const popRight = pop.getBoundingClientRect().right;
      const offenders = [...pop.querySelectorAll('*')]
        .map(el => ({ el, right: el.getBoundingClientRect().right }))
        .filter(o => o.right > popRight + 0.5)
        .map(o => (o.el.id || o.el.className || o.el.tagName) + ':' +
          (o.right - popRight).toFixed(1));
      return { scrollsX: pop.scrollWidth > pop.clientWidth + 1, offenders };
    }""")
    assert not overflow["scrollsX"], \
        f"#menu-pop scrolls horizontally: {overflow}"
    assert overflow["offenders"] == [], \
        f"something hangs past the panel's right edge: {overflow['offenders']}"


def test_a_live_query_gives_the_bar_back(page):
    """The bar must not stay taken over once you stop typing.

    Measured, because this is exactly the shape of bug a source check cannot
    see: the rule that hid Done was correct CSS, matched, and painted. Typing
    a filter and then clicking away left `doneVisible: False, menuVisible:
    False, activeElement: BODY` — submitting a round unreachable from behind a
    filter, recoverable only through the mouse-only ×.
    """
    page.click("#block-search")
    page.fill("#block-search", "block 2")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching === '1'")

    # Focus moves on, the query stays. blur() rather than a click on the
    # document: it lands activeElement on <body>, which is the state the
    # defect was measured in, without a stray click reaching a block.
    page.evaluate("() => document.getElementById('block-search').blur()")
    page.wait_for_function(
        "() => document.activeElement === document.body", timeout=3000)
    # The field has a 160ms width transition, so measure once it has landed
    # rather than mid-flight — same reason the takeover test above waits.
    page.wait_for_timeout(400)

    state = page.evaluate("""() => {
      const q = s => document.querySelector(s);
      return { done: q('#done-btn').offsetParent !== null,
               menu: q('#menu-toggle').offsetParent !== null,
               title: q('.header-title').offsetParent !== null,
               value: q('#block-search').value,
               fieldWidth: q('.header-search').getBoundingClientRect().width,
               filtered: !!q('.search-count') }; }""")
    assert state["done"], "Done is still hidden while a query is live"
    assert state["menu"], "the menu is still hidden while a query is live"
    assert state["value"] == "block 2", "the query did not survive losing focus"
    assert state["fieldWidth"] > 100, (
        "the field collapsed back to a magnifier while its query is still "
        f"filtering the document: {state['fieldWidth']}px")
    # `.search-count` ("Showing N of M blocks") is search.js's own proof that
    # a filter is running; it exists for a non-empty query and for nothing
    # else. Asserted instead of a hidden block because every block in this
    # fixture is the same sentence with one digit changed, so a fuzzy query
    # that excludes one of them would be a query tuned to Fuse, not to the bar.
    assert state["filtered"], "the filter stopped filtering"

    # Visible is not the same as reachable: a control can paint and still sit
    # under something. trial=True runs Playwright's full actionability check —
    # visible, stable, receives pointer events, enabled — and clicks nothing.
    page.click("#done-btn", trial=True)


def test_escape_lifts_the_filter_from_anywhere(page):
    """The keyboard way out, which did not exist. Esc was gated on the field
    having focus, and the takeover had just taken the field away."""
    page.click("#block-search")
    page.fill("#block-search", "block 2")
    page.wait_for_selector(".search-count", timeout=3000)
    page.evaluate("() => document.getElementById('block-search').blur()")
    page.wait_for_function(
        "() => document.activeElement === document.body", timeout=3000)

    page.keyboard.press("Escape")
    page.wait_for_function(
        "() => document.getElementById('block-search').value === ''", timeout=3000)
    assert page.evaluate(
        "() => !document.querySelector('.search-count')"), \
        "the query cleared but the document is still filtered"
    assert page.evaluate(
        "() => document.querySelector('.page-header').dataset.searching") == "0", \
        "the bar did not go back to rest"


def test_the_filtered_bar_fits_a_narrow_viewport(page):
    """`filtered` keeps the field at its query width AND brings Done and the
    menu back (test_a_live_query_gives_the_bar_back, above) — but the title
    stayed at its full min-content width while doing it, so on a phone the
    three together ran past the right edge. Measured in Chromium: +73px of
    document overflow at 320px wide, +40px at 375px, +16px at 414px, 0px at
    768px, with `#done-btn` itself landing off-screen (x=337 w=56 -> 393
    against a 375px viewport, i.e. 18px short of even starting on screen).

    `page.click('#done-btn', trial=True)` in the test above this one does NOT
    catch this: Playwright's actionability check scrolls the target into view
    before judging it clickable, so a Done that is only reachable by scrolling
    the whole page sideways still reads as passing. This test reads the
    rect and the document's own scrollWidth instead, with nothing scrolled
    for it first.
    """
    page.set_viewport_size({"width": 375, "height": 667})
    page.click("#block-search")
    page.fill("#block-search", "block 2")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching === '1'")
    page.evaluate("() => document.getElementById('block-search').blur()")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching === 'filtered'",
        timeout=3000)
    # The field has a 160ms width transition; land before measuring, same as
    # the takeover and live-query tests above.
    page.wait_for_timeout(400)

    state = page.evaluate("""() => {
      const doc = document.documentElement;
      const done = document.getElementById('done-btn').getBoundingClientRect();
      return { overflow: doc.scrollWidth - doc.clientWidth,
               doneRight: done.right,
               viewportWidth: window.innerWidth }; }""")
    assert state["overflow"] == 0, (
        f"the filtered header overflows the document by {state['overflow']}px "
        "at 375px wide")
    assert state["doneRight"] <= state["viewportWidth"], (
        f"Done's right edge ({state['doneRight']}px) is past the "
        f"{state['viewportWidth']}px viewport — off-screen, not just tight")


def test_the_watcher_state_reaches_the_menu_buttons_name(page):
    """The spec's own Risks section: "entry.js's watcher polling is the least
    test-covered thing being rewired. It has no browser test today. Adding one
    is in scope." This is that test, and it is also the only way to see the
    accessible-name bug — `aria-label` WINS over `title`, so a static
    aria-label="Menu" swallowed every state entry.js wrote, and a source check
    that greps for `btn.title =` reads as if the state were announced.

    The fixture's session has no watcher, so the stale path is simply the page
    as it loads. The live path is driven by rewriting what /poll reports:
    fetched for real and re-served with one field changed, so nothing else the
    payload carries is invented here.
    """
    page.wait_for_function(
        "() => document.getElementById('menu-toggle')"
        ".classList.contains('watcher-stale')", timeout=10000)
    stale = page.evaluate("""() => { const b = document.getElementById('menu-toggle');
      return { aria: b.getAttribute('aria-label'), title: b.title,
               live: b.classList.contains('watcher-live'),
               announces: document.getElementById('menu-status-title')
                 .getAttribute('aria-live') }; }""")
    assert not stale["live"], "an unwatched page painted the live dot"
    assert "nothing is watching" in stale["aria"], (
        "the menu button announces %r while the dot says unwatched — the dot "
        "is a colour, and its panel sibling is aria-hidden, so this name is "
        "the only way a screen reader can learn the state" % stale["aria"])
    assert stale["announces"] == "polite", (
        "the status line does not announce a change while the panel is open")

    def as_live(route):
        resp = route.fetch()
        try:
            data = resp.json()
        except Exception:                            # noqa: BLE001
            route.fulfill(response=resp)
            return
        data["watcher_seen_at"] = time.time()
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(data))

    page.route("**/poll", as_live)
    page.reload()
    page.wait_for_selector("section.block")
    page.wait_for_function(
        "() => document.getElementById('menu-toggle')"
        ".classList.contains('watcher-live')", timeout=10000)
    live = page.evaluate("""() => { const b = document.getElementById('menu-toggle');
      return { aria: b.getAttribute('aria-label'),
               stale: b.classList.contains('watcher-stale'),
               says: document.getElementById('menu-status-title').textContent }; }""")
    assert not live["stale"], "both watcher classes are on the button at once"
    assert "a session is watching" in live["aria"], (
        "the class flipped to live and the accessible name did not follow: "
        "%r" % live["aria"])
    assert live["says"] == "Watching", live["says"]


def test_switching_a_pane_takes_the_caret_with_it(page):
    """Pushing a pane used to write the attribute and nothing else, so the row
    you clicked went display:none under the caret and activeElement stayed on
    a hidden element — measured, and invisible to any source check.

    The panel is also a disclosure now rather than a `role="dialog"` that
    moved no focus and set no aria-modal, so the role it no longer claims is
    asserted here beside the behaviour that replaced it.
    """
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    assert page.eval_on_selector(
        "#menu-pop", "el => el.getAttribute('role')") is None, \
        "the panel still calls itself a dialog while behaving like a disclosure"

    page.click('.menu-pane[data-pane-name="root"] [data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'")
    landed = page.evaluate("""() => { const a = document.activeElement;
      return { hidden: a.offsetParent === null,
               where: a.closest('.menu-pane')
                 ? a.closest('.menu-pane').dataset.paneName : null,
               back: a.classList.contains('menu-back') }; }""")
    assert not landed["hidden"], "the caret is on an element nobody can see"
    assert landed["where"] == "settings" and landed["back"], \
        f"the caret did not follow the pane: {landed}"

    page.click('.menu-pane[data-pane-name="settings"] [data-pane-to="root"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'root'")
    back = page.evaluate(
        "() => document.activeElement.dataset.paneTo")
    assert back == "settings", \
        f"coming back did not land on the row that pushed the pane: {back!r}"


def test_a_pressed_menu_row_lights_the_icon_it_actually_has(page):
    """`.menu-item[aria-pressed="true"] > svg` is a child combinator, and the
    Full screen row's icon is a grandchild — it sits inside the [data-icon]
    slot fullscreen.js writes through. So the row lit its label and left its
    icon grey, which reads as a half-pressed control. Only a computed colour
    can see it: the selector is valid CSS that simply matches nothing.

    aria-pressed is set here rather than entered by going full screen, because
    the state under test is the stylesheet's, not the Fullscreen API's.
    """
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    got = page.evaluate("""() => {
      const b = document.getElementById('fullscreen-toggle');
      b.setAttribute('aria-pressed', 'true');
      const g = (el, p) => getComputedStyle(el)[p];
      return { label: g(b.querySelector('.menu-tile-label'), 'color'),
               icon: g(b.querySelector('[data-icon] svg'), 'color'),
               hl: (() => { const h = document.getElementById('menu-highlighter');
                 h.setAttribute('aria-pressed', 'true');
                 return g(h.querySelector('svg'), 'color'); })() }; }""")
    assert got["icon"] == got["label"], (
        "the pressed row's label is %s and its icon is %s" % (got["label"], got["icon"]))
    # And the bare-child rows still work, so this is a widening and not a swap.
    assert got["hl"] == got["label"], got


def test_full_screen_says_the_same_thing_twice(page):
    """The row announced "Exit full screen" while reading "Full screen". Two
    states of one control, disagreeing about which one you are in."""
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    at_rest = page.evaluate("""() => { const b = document.getElementById('fullscreen-toggle');
      return { label: b.querySelector('[data-label]').textContent.trim(),
               aria: b.getAttribute('aria-label') }; }""")
    assert at_rest["label"] == "Full screen", at_rest
    assert at_rest["label"] in at_rest["aria"], (
        "the visible label is not part of the accessible name: %s" % at_rest)

    page.click("#fullscreen-toggle")
    try:
        page.wait_for_function(
            "() => !!document.fullscreenElement", timeout=4000)
    except Exception:                                # noqa: BLE001
        pytest.skip("this browser refused fullscreen; the slot is covered by "
                    "test_smoke_menu_slots.py")
    got = page.evaluate("""() => { const b = document.getElementById('fullscreen-toggle');
      return { label: b.querySelector('[data-label]').textContent.trim(),
               aria: b.getAttribute('aria-label'),
               icon: !!b.querySelector('[data-icon] svg') }; }""")
    assert got["label"] == "Exit full", (
        "the row announces %r and still reads %r" % (got["aria"], got["label"]))
    assert got["icon"], "the label write ate the row's icon"


# ── Bare header icons and the tile menu ────────────────────────────────────
# The resting search field was 58px wide in a 26px slot (padding 5px 28px on a
# border-box input), so its #8a8f99 outline ran underneath #menu-toggle —
# measured at input x=1140-1198 against the menu button's x=1170-1196 — and
# read as one border wrapped round search and burger. Every source check
# passed while it did.

_RESOLVE = """
  const cv = document.createElement('canvas').getContext('2d');
  const rgb = v => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = v; cv.fillRect(0, 0, 1, 1);
    const d = cv.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3]].join(','); };
  const token = n => rgb(getComputedStyle(document.documentElement)
    .getPropertyValue(n).trim());
"""


def _load_in_theme(page, theme):
    """Reload into a page theme, the way a reader gets one.

    Not named _set_theme: this module already has one further down, for the
    phone tests, and a second def of the same name silently replaced the
    first — every call here got the no-reload version and measured the
    header mid-transition from light to dark."""
    page.evaluate(
        "t => localStorage.setItem('annotate.view:pagetheme', t)", theme)
    page.reload()
    page.wait_for_selector("section.block")
    page.wait_for_function("() => !!window.AnnotateSubunits", timeout=15000)
    assert page.evaluate("() => document.body.dataset.pageTheme") == theme
    _no_transitions(page)


def _no_transitions(page):
    """These tests measure where colours LAND, not how they get there; the
    header and the tiles transition colour and background over 140ms, so a
    read straight after a hover or a theme change can sample mid-flight."""
    page.add_style_tag(
        content="*, *::before, *::after { transition: none !important; }")


def _header_at_rest(page):
    return page.evaluate("() => {" + _RESOLVE + """
      const q = s => document.querySelector(s);
      const cs = s => getComputedStyle(q(s));
      const box = s => { const r = q(s).getBoundingClientRect();
        return { x: r.left, right: r.right, w: r.width, h: r.height }; };
      const paint = s => { const c = cs(s);
        return { border: parseFloat(c.borderTopWidth) > 0
                   && c.borderTopStyle !== 'none'
                   && rgb(c.borderTopColor).split(',')[3] !== '0',
                 bg: rgb(c.backgroundColor), radius: c.borderTopLeftRadius,
                 color: rgb(c.color) }; };
      return { searching: q('.page-header').dataset.searching || '',
               wrap: { ...box('.header-search'), ...paint('.header-search') },
               input: { ...box('#block-search'), ...paint('#block-search') },
               menu: { ...box('#menu-toggle'), ...paint('#menu-toggle') },
               done: paint('#done-btn'),
               dim: token('--text-dim'), ground: rgb(cs('.page-header').backgroundColor),
               ring: rgb(getComputedStyle(q('#menu-toggle'), '::after').borderTopColor),
               transparent: rgb('transparent') }; }""")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_header_icons_are_bare_at_rest(page, theme):
    page.set_viewport_size({"width": 1280, "height": 800})
    _load_in_theme(page, theme)
    got = _header_at_rest(page)
    clear = got["transparent"]
    assert got["searching"] in ("", "0"), got["searching"]
    for name in ("wrap", "input", "menu"):
        assert not got[name]["border"], f"{name} paints a border at rest: {got[name]}"
        assert got[name]["bg"] == clear, f"{name} paints a background at rest: {got[name]}"
    # The field stays inside its own slot, so nothing of it reaches the menu.
    assert got["input"]["w"] <= got["wrap"]["w"] + 0.5, got
    assert got["input"]["right"] <= got["menu"]["x"], (
        "the resting search field runs under the menu button: "
        f"input ends at {got['input']['right']}, menu starts at {got['menu']['x']}")
    assert round(got["menu"]["w"]) == 28 and round(got["menu"]["h"]) == 28, got["menu"]
    assert round(got["wrap"]["w"]) == 28, got["wrap"]
    assert got["menu"]["radius"] == "7px", got["menu"]
    assert got["menu"]["color"] == got["dim"], got["menu"]
    # Done is the one framed control left.
    assert got["done"]["border"], "Done lost its frame"
    # The watcher dot's ring is the header's ground, now that no button
    # background sits behind it.
    assert got["ring"] == got["ground"], got


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_hovering_a_bare_icon_tints_it(page, theme):
    page.set_viewport_size({"width": 1280, "height": 800})
    _load_in_theme(page, theme)
    probe = "() => {" + _RESOLVE + """
      const q = s => document.querySelector(s);
      return { menu: rgb(getComputedStyle(q('#menu-toggle')).backgroundColor),
               menuColor: rgb(getComputedStyle(q('#menu-toggle')).color),
               search: rgb(getComputedStyle(q('#block-search')).backgroundColor),
               ground: rgb(getComputedStyle(q('.page-header')).backgroundColor),
               strong: token('--text-strong') }; }"""
    page.hover("#menu-toggle")
    on_menu = page.evaluate(probe)
    assert on_menu["menu"] != on_menu["ground"], on_menu
    assert on_menu["menu"].split(",")[3] == "255", on_menu
    assert on_menu["menuColor"] == on_menu["strong"], on_menu
    page.hover("#block-search")
    on_search = page.evaluate(probe)
    assert on_search["search"] == on_menu["menu"], (
        "the search trigger and the menu button hover differently", on_search, on_menu)


def test_an_open_search_field_is_a_real_field_again(page):
    page.set_viewport_size({"width": 1280, "height": 800})
    _no_transitions(page)
    page.click("#block-search")
    page.wait_for_function(
        "() => document.querySelector('.page-header').dataset.searching === '1'")
    got = page.evaluate("""() => { const c = getComputedStyle(document.getElementById('block-search'));
      return { border: c.borderTopWidth, style: c.borderTopStyle,
               padLeft: c.paddingLeft, bg: c.backgroundColor }; }""")
    assert got["border"] == "1px" and got["style"] == "solid", got
    assert got["padLeft"] == "28px", got
    assert got["bg"] != "rgba(0, 0, 0, 0)", got


TILES = ["composer-toggle", "menu-highlighter", "highlighter-clear",
         "fullscreen-toggle", "settings", "export-btn", "help"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_menu_root_is_a_grid_of_tiles(page, theme):
    page.set_viewport_size({"width": 1280, "height": 800})
    _load_in_theme(page, theme)
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    got = page.evaluate("""() => {
      const pane = document.querySelector('.menu-pane[data-pane-name="root"]');
      const grid = pane.querySelector('.menu-tiles');
      const tiles = grid ? [...grid.children].filter(e => e.offsetParent !== null) : [];
      const status = document.getElementById('menu-status').getBoundingClientRect();
      return { cols: grid ? getComputedStyle(grid).gridTemplateColumns.split(' ').length : 0,
               ids: tiles.map(t => t.id || t.dataset.paneTo),
               widths: tiles.map(t => Math.round(t.getBoundingClientRect().width)),
               tops: tiles.map(t => Math.round(t.getBoundingClientRect().top)),
               statusBottom: status.bottom,
               gridTop: grid ? grid.getBoundingClientRect().top : 0,
               headings: pane.querySelectorAll('.menu-sec').length,
               popW: document.getElementById('menu-pop').getBoundingClientRect().width,
               scrollsX: (p => p.scrollWidth > p.clientWidth + 1)(document.getElementById('menu-pop')) }; }""")
    assert got["cols"] == 4, got
    assert got["ids"] == TILES, got["ids"]
    assert all(68 <= w <= 76 for w in got["widths"]), got["widths"]
    assert len(set(got["tops"][:4])) == 1 and len(set(got["tops"][4:])) == 1, got["tops"]
    assert got["statusBottom"] <= got["gridTop"], "the status block is not on top"
    assert got["headings"] == 0, "the old section headings are still in the root pane"
    assert not got["scrollsX"], got


def test_a_tile_hover_lifts_its_icon(page):
    _no_transitions(page)
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    probe = "() => {" + _RESOLVE + """
      const t = document.getElementById('highlighter-clear');
      return { bg: rgb(getComputedStyle(t).backgroundColor),
               icon: rgb(getComputedStyle(t.querySelector('svg')).color),
               dim: token('--text-dim'), strong: token('--text-strong') }; }"""
    rest = page.evaluate(probe)
    assert rest["icon"] == rest["dim"], rest
    page.hover("#highlighter-clear")
    hot = page.evaluate(probe)
    assert hot["bg"] != rest["bg"], (rest, hot)
    assert hot["icon"] == hot["strong"], hot


def test_the_highlight_tile_is_a_lit_toggle(page):
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click("#menu-highlighter")
    page.wait_for_function(
        "() => document.getElementById('menu-highlighter')"
        ".getAttribute('aria-pressed') === 'true'", timeout=3000)
    got = page.evaluate("() => {" + _RESOLVE + """
      const t = document.getElementById('menu-highlighter');
      const c = getComputedStyle(t);
      return { icon: rgb(getComputedStyle(t.querySelector('svg')).color),
               label: rgb(getComputedStyle(t.querySelector('.menu-tile-label')).color),
               caption: t.querySelector('.menu-tile-label').textContent,
               bg: rgb(c.backgroundColor), accent: token('--accent'),
               clear: rgb('transparent'), text: t.textContent.trim() }; }""")
    assert got["icon"] == got["accent"] and got["label"] == got["accent"], got
    assert got["bg"] != got["clear"], "a pressed tile paints no tint"
    assert got["text"] == "Highlight", f"the tile grew a state word: {got['text']!r}"


def test_the_pane_tiles_and_the_comment_tile_still_work(page):
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click('.menu-tile[data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'")
    page.click('.menu-pane[data-pane-name="settings"] [data-pane-to="root"]')
    page.click('.menu-tile[data-pane-to="help"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'help'")
    page.click('.menu-pane[data-pane-name="help"] [data-pane-to="root"]')
    page.click("#composer-toggle")
    page.wait_for_selector("#general-composer:not([hidden])")
    page.keyboard.press("Escape")
    page.wait_for_selector("#general-composer", state="hidden")
    page.click("body", position={"x": 5, "y": 400})
    page.keyboard.press("g")
    page.wait_for_selector("#general-composer:not([hidden])")


def test_a_finished_trail_already_on_the_page_still_paints(document):
    """The load-time race a source-level test cannot see.

    progress.js's initial paint has to come from its own read at load time,
    not only from the `annotate:progress` broadcast, because compat.js
    returns early for `ev.initial` frames — a page loaded when a trail
    already exists gets no event at all. But that load-time read runs
    `writable()`, which reads `window.WebCompanion.writable`, and that flag
    starts false and is only flipped once core.js's `resolveWritable()`
    settles its `fetch("/api/whoami")` — kicked off fire-and-forget by
    script.js a few lines earlier, and never synchronous. If progress.js's
    own first read loses that race, `writable()` reads false for the
    session's OWNER, the panel is removed/never drawn, and — because no
    event is coming for an initial frame — it never appears at all.

    The write below happens before the page is ever navigated to, the way
    progress.py's `finish()` writes a closed trail, so the page loads onto a
    trail that already exists. The `/api/whoami` route is throttled so the
    race is exercised every run rather than only on a slow morning.
    """
    now = int(time.time())
    _put_progress(document, ["Read the failing test",
                             "Painted the panel from a load-time read"],
                  state="done", started=now - 12, ended=now)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page()
        try:
            # Deliberately slow, not just naturally raced: without this the
            # bug is real but timing-dependent, and a fast enough machine
            # would pass every run whether or not the fix is still there.
            def _slow_whoami(route):
                time.sleep(0.4)
                route.continue_()
            pg.route("**/api/whoami", _slow_whoami)

            pg.goto(document["url"])
            pg.wait_for_selector("#progress-panel", timeout=15000)
            state = pg.get_attribute("#progress-panel", "data-state")
            lines = pg.eval_on_selector_all(
                "#progress-panel .pg-line",
                "els => els.map(e => e.textContent)")
        finally:
            browser.close()

    assert state == "done", "the panel did not know the trail was finished"
    assert any("Painted the panel from a load-time read" in t for t in lines), lines


def test_narration_reaches_the_page_without_a_reload(page, document):
    """The whole point: the reader learns something during the silence."""
    _put_progress(document, ["Read your comment on section-1"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    assert "Read your comment on section-1" in page.text_content("#progress-panel")

    _put_progress(document, ["Read your comment on section-1",
                             "Looking for where the conversion happens"])
    page.wait_for_function(
        "() => document.querySelectorAll('#progress-panel .pg-line').length === 2",
        timeout=10000)


def test_the_newest_line_is_visible(page, document):
    """Measured, not assumed: with a max-height and no scroll management the
    current line is the one clipped off the bottom."""
    _put_progress(document, [f"step number {i}" for i in range(30)])
    page.wait_for_function(
        "() => document.querySelectorAll('#progress-panel .pg-line').length === 30",
        timeout=10000)
    visible = page.eval_on_selector(
        "#progress-feed",
        "el => { const last = el.querySelector('.pg-line:last-child');"
        " const f = el.getBoundingClientRect(), l = last.getBoundingClientRect();"
        " return l.bottom <= f.bottom + 1 && l.top >= f.top - 1; }")
    assert visible, "the newest narration line is scrolled out of sight"


def test_it_collapses_to_a_summary_when_the_work_is_done(page, document):
    started = 1700000000
    _put_progress(document, ["one", "two"], state="done",
                  started=started, ended=started + 260)
    page.wait_for_function(
        "() => document.querySelector('#progress-panel')?.dataset.state === 'done'",
        timeout=10000)
    head = page.text_content("#progress-panel .pg-now")
    assert "4 min 20 s" in head, f"the summary does not say how long it took: {head}"
    assert page.eval_on_selector(
        "#progress-feed", "el => el.offsetParent === null"), \
        "the feed is still open after the work finished"

    page.click("#progress-panel .pg-caret")
    assert page.eval_on_selector("#progress-feed", "el => el.offsetParent !== null"), \
        "the summary does not expand"


def test_a_progress_write_does_not_unlock_the_page(page, document):
    """compat.js clears the busy lock on any item change. For this anchor that
    rule is backwards — the first narration line would dismiss the ribbon the
    narration captions.

    The brief's version of this test hand-sets `body.is-busy`, which never
    touches compat.js's own `busyLocal` variable — the lock is reconstructed
    entirely client-side (compat.js:185), and a class written by the test
    would be cleared by ANY subsequent item change whether or not the fix
    under test exists, or left alone by a broken fix, either way proving
    nothing. This drives the real lock instead: open the page's own general
    composer and send through it, the same path `subunits.js`'s round submit
    and every block comment use, so `daemon.api.submit(...)` resolves and
    compat.js's `sending.then(() => setBusyLocal(true))` (compat.js:152) sets
    `busyLocal` and the class together. Only once that lock is real does the
    narration write below get to prove it survives."""
    page.keyboard.press("g")
    page.wait_for_selector("#general-composer:not([hidden])")
    page.fill("#general-input", "locking this page")
    page.click("#general-send")
    page.wait_for_function(
        "() => document.body.classList.contains('is-busy')", timeout=10000)

    _put_progress(document, ["still working"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    assert page.eval_on_selector(
        "body", "el => el.classList.contains('is-busy')"), \
        "a narration line unlocked the page"


def test_the_trail_never_becomes_a_block(page, document):
    before = page.eval_on_selector_all("section.block", "els => els.length")
    _put_progress(document, ["one"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    after = page.eval_on_selector_all("section.block", "els => els.length")
    assert before == after, "the progress item rendered as a block"


def test_a_read_only_reader_sees_no_trail_at_all(document):
    """The panel is not DRAWN for a guest. That is all this proves.

    The document is what the author chose to share and how it was produced is
    not, but the hide is client-side only: the daemon's `GET /s/<sid>/items`
    is unauthenticated and returns every item, `__`-prefixed anchors included,
    and compat.js fetches exactly that route on every page load — guest
    included. Measured from this machine's LAN address with no owner token,
    that request returns 200 with the `__progress__` body, steps and all. So
    the trail reaches a guest's browser and one `curl` reads it; what this
    test establishes is that nothing renders it, not that it was withheld.
    Gating `__`-prefixed anchors server-side would be a `webcompanion` change
    (spec decision 7, amended).

    The brief's version of this test fakes read-only by adding `body.
    read-only` and hand-firing `annotate:progress` from inside the OWNER's
    own page/context — that only proves the CSS rule `.read-only
    #progress-panel { display: none }` (or whatever selector), never
    progress.js's actual JS gate. That gate reads `window.WebCompanion.
    writable`, which core.js sets from `/api/whoami`'s `_is_owner()`
    (server.py) — and `_is_owner` treats ANY loopback connection as the
    owner unconditionally, token or none. A same-machine Playwright page
    talking to 127.0.0.1 is loopback, so nothing this test does to the DOM
    changes what `_is_owner` sees, and `window.WebCompanion.__forceReadOnly`
    is not a real flag progress.js or core.js reads at all.

    So this drives a genuinely non-owner page instead: a FRESH browser
    context (no cookies, no session/localStorage carried from the owner
    page) navigated to this machine's real outbound network address rather
    than 127.0.0.1 — a connection `_is_owner` cannot mistake for loopback —
    with no `#k=` token in the URL. Verified against the live daemon before
    trusting it: `curl http://<lan-ip>:<port>/api/whoami` on this machine
    returns `{"writable": false}` for that address and `{"writable": true}`
    for 127.0.0.1, so the two contexts really do differ in the one way that
    matters. If this machine's daemon only binds loopback (no LAN route),
    the guest connection cannot be made at all and the test skips rather
    than silently falling back to the weaker, CSS-only proof."""
    base, sid = document["base"], document["sid"]
    port = urlsplit(base).port
    try:
        host = _outbound_host()
    except OSError as e:
        pytest.skip(f"could not determine an outbound address to prove a genuine "
                    f"non-owner connection: {e}")
    guest_base = f"http://{host}:{port}"
    try:
        raw = urllib.request.urlopen(guest_base + "/api/whoami", timeout=3).read()
    except (urllib.error.URLError, OSError) as e:
        pytest.skip(f"{guest_base} is not reachable ({e}); this machine's daemon "
                    f"appears to bind loopback only, so a genuinely non-owner "
                    f"connection cannot be made here")
    if json.loads(raw).get("writable"):
        pytest.skip(f"{guest_base} still reports writable=true; this machine cannot "
                    f"produce a connection _is_owner treats as non-loopback")

    _put_progress(document, ["Read app/pricing/Normalizer.java"])

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            guest = browser.new_context()
            gp = guest.new_page()
            gp.goto(f"{guest_base}/s/{sid}/")
            gp.wait_for_selector("section.block", timeout=15000)
            gp.wait_for_function("() => !!window.AnnotateSubunits", timeout=15000)
            gp.wait_for_function(
                "() => window.WebCompanion && window.WebCompanion.writable === false",
                timeout=10000)
            hidden = gp.evaluate(
                "() => { const el = document.getElementById('progress-panel');"
                " return el === null || el.offsetParent === null; }")
        finally:
            browser.close()
    assert hidden, "the trail is rendered on a guest's page"


def _mount_lock_ribbon(page):
    """Build `.busy-banner` exactly as script.js's setBusy(true) does.

    Same tag, id, class, children and insertion point (script.js:3048-3075).
    The daemon-era client only reaches setBusy() from a poll-handler frame
    carrying `busy: true`, which a live general-composer submission does not
    produce on its own, and what is under test here is geometry — which does
    not care which line of JS appended the node.
    """
    page.evaluate("""() => {
      const banner = document.createElement('div');
      banner.id = 'busy-banner';
      banner.className = 'busy-banner';
      banner.setAttribute('role', 'status');
      banner.setAttribute('aria-live', 'polite');
      const spin = document.createElement('span');
      spin.className = 'busy-spinner';
      const label = document.createElement('span');
      label.className = 'bb-label';
      label.textContent = 'Claude is applying your round…';
      const timer = document.createElement('span');
      timer.className = 'bb-timer';
      timer.textContent = '0:42';
      banner.append(spin, label, timer);
      document.querySelector('.page-header').insertAdjacentElement('afterend', banner);
    }""")


def test_the_lock_ribbon_does_not_cover_the_panel_head(page, document):
    """Both are `position: sticky; top: 0` siblings in the same containing
    block, and the ribbon's `z-index: 20` beats the panel's 19 — so they do
    not stack, they overlap, and they coexist by construction: the panel
    exists only while Claude is working, which is exactly when the page is
    locked. Measured before the fix, in Chromium at scrollY 600: the ribbon
    occupied 0-45.4px and `.pg-head` 1-41.8px, and `elementFromPoint` at the
    head's own centre returned `busy-banner` — the current line, the step
    count, the elapsed timer and the caret were all behind it."""
    _put_progress(document, ["Read your round of feedback",
                             "Looking for where the conversion happens",
                             "Rewriting the block with what I found"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)
    _mount_lock_ribbon(page)
    page.evaluate("window.scrollTo(0, 600)")
    page.wait_for_timeout(200)

    hit = page.evaluate("""() => {
      const head = document.querySelector('.pg-head');
      const b = head.getBoundingClientRect();
      const el = document.elementFromPoint(Math.round((b.left + b.right) / 2),
                                          Math.round((b.top + b.bottom) / 2));
      return {id: el ? el.id : null,
              insidePanel: !!(el && el.closest('#progress-panel')),
              headTop: +b.top.toFixed(1), headBottom: +b.bottom.toFixed(1)};
    }""")
    assert hit["insidePanel"], \
        f"the panel head is occluded at its own centre by #{hit['id']}"

    # And the ribbon comes back the moment the trail closes, for whatever is
    # left of the lock — the panel is only a replacement while it is working.
    _put_progress(document, ["Read your round of feedback"], state="done",
                  started=int(time.time()) - 30, ended=int(time.time()))
    page.wait_for_function(
        "() => document.getElementById('progress-panel')"
        " && document.getElementById('progress-panel').dataset.state === 'done'",
        timeout=10000)
    assert page.eval_on_selector(
        ".busy-banner", "el => getComputedStyle(el).display !== 'none'"), \
        "the lock ribbon stays suppressed after the trail closed"


def test_only_the_current_line_is_a_live_region(page, document):
    """The feed is rebuilt from scratch on every repaint. With the live region
    on the panel (or on the feed), a screen reader re-announces the whole
    trail to deliver one new line — nine lines read out again for the tenth.
    The live region is the current line alone, announced atomically."""
    _put_progress(document, ["Read your round of feedback", "Reading the importer"])
    page.wait_for_selector("#progress-panel .pg-line", timeout=10000)

    aria = page.evaluate("""() => {
      const p = document.getElementById('progress-panel');
      const now = p.querySelector('.pg-now');
      const feed = document.getElementById('progress-feed');
      return {panelLive: p.getAttribute('aria-live'), panelRole: p.getAttribute('role'),
              nowLive: now.getAttribute('aria-live'), nowAtomic: now.getAttribute('aria-atomic'),
              feedLive: feed.getAttribute('aria-live'), nowText: now.textContent};
    }""")
    assert aria["panelLive"] is None and aria["panelRole"] != "status", \
        f"the whole panel is still a live region: {aria}"
    assert aria["nowLive"] == "polite" and aria["nowAtomic"] == "true", aria
    assert aria["feedLive"] == "off", aria
    assert aria["nowText"] == "Reading the importer"

    # A repaint that does not change the current line must not replace its
    # text node either: an identical `textContent =` write is still a mutation
    # a live region can announce.
    #
    # The second write has to differ from the first somewhere, or the daemon
    # stores the same bytes, sends nothing, and no repaint happens at all —
    # the assertion then passes on a page nothing ever touched. Moving
    # `started_at` changes the item while leaving the current line's text
    # alone, and the feed row tagged here is how we know the repaint landed:
    # paint() empties the feed and rebuilds it, so that node goes away.
    page.evaluate("""() => {
      const n = document.querySelector('#progress-panel .pg-now');
      n.__node = n.firstChild;
      window.__feedRow = document.querySelector('#progress-feed .pg-line');
    }""")
    _put_progress(document, ["Read your round of feedback", "Reading the importer"],
                  started=int(time.time()) - 90)
    page.wait_for_function(
        "() => window.__feedRow && !window.__feedRow.isConnected", timeout=10000)
    after = page.evaluate("""() => {
      const n = document.querySelector('#progress-panel .pg-now');
      return {same: n.__node === n.firstChild, text: n.textContent};
    }""")
    assert after["text"] == "Reading the importer", after
    assert after["same"], "an unchanged current line was rewritten, which re-announces it"


def _choice_block(anchor, question, labels):
    return {"id": anchor, "kind": "choice",
            "spec": {"question": question,
                     "options": [{"id": f"o{i}", "label": l}
                                 for i, l in enumerate(labels, 1)]}}


def _add_choices(page, document):
    base, sid = document["base"], document["sid"]
    _call(base, "PUT", f"/s/{sid}/items/choice-a",
          _choice_block("choice-a", "Which colour?", ["Red", "Blue"]))
    _call(base, "PUT", f"/s/{sid}/items/choice-b",
          _choice_block("choice-b", "Which size?", ["Small", "Large"]))
    _call(base, "PUT", f"/s/{sid}/items/__doc__",
          {"response_id": "resp-browser-suite", "title": "annotate browser suite",
           "order": BLOCKS + ["choice-a", "choice-b"], "cwd": str(REPO),
           "glossary": []})
    page.reload()
    page.wait_for_selector('section.block[data-block-id="choice-b"] .choice-option')


def test_several_choices_go_out_in_one_round(page, document):
    """Each choice block used to carry its own Submit, which sent that one
    answer and locked the page, so a page asking three questions took three
    round trips. A pick is now a round mark like any other, and the dock's one
    Submit sends every answer together."""
    _add_choices(page, document)

    posts = []
    page.on("request", lambda r: posts.append(r.post_data or "")
            if r.method == "POST" else None)

    page.click('section.block[data-block-id="choice-a"] .choice-option >> nth=1')
    page.click('section.block[data-block-id="choice-b"] .choice-option >> nth=0')
    page.fill('section.block[data-block-id="choice-b"] .choice-note', "but roomy")
    assert page.locator(".choice-submit-btn").count() == 0, \
        "a choice block still has its own Submit"
    page.wait_for_timeout(300)
    assert not [p for p in posts if "selected_options" in p], \
        "a pick reached Claude before the round was submitted"

    page.wait_for_selector("#round-submit:not([disabled])")
    assert page.inner_text("#round-submit") == "Submit round (2)"
    page.click("#round-submit")
    page.wait_for_function(
        "() => document.body.classList.contains('is-busy')", timeout=10000)

    sent = [p for p in posts if "selected_options" in p]
    assert len(sent) == 1, f"expected one submission, saw {len(sent)}"
    envelope = json.loads(json.loads(sent[0])["text"])
    assert envelope["type"] == "round"
    answers = {r["block_id"]: r for r in envelope["reactions"]}
    assert answers["choice-a"]["kind"] == "choice"
    assert answers["choice-a"]["selected_options"] == ["o2"]
    assert answers["choice-b"]["selected_options"] == ["o1"]
    assert answers["choice-b"]["text"] == "but roomy"


def test_a_pending_answer_survives_a_reload_and_leaves_with_its_row(page, document):
    """The answer lives in the round now, not in the cards, so the cards have
    to be painted from it: after a reload, and again when the dock's x takes
    the answer out of the round."""
    _add_choices(page, document)
    lit = 'section.block[data-block-id="choice-a"] .choice-option.selected'
    page.click('section.block[data-block-id="choice-a"] .choice-option >> nth=1')
    page.reload()
    page.wait_for_selector(lit, timeout=10000)
    assert page.locator(lit).count() == 1

    page.click("#round-dock .rd-head")
    page.click("#round-dock .rd-x")
    page.wait_for_function(f"() => !document.querySelector('{lit}')", timeout=3000)
    assert page.locator("#round-dock").count() == 0, "the dock outlived its last mark"


# ═══════════════════════════════════════════════════════════════════════════
# Accessibility, touch and contrast.
#
# Every test here measures the page it is about — a computed style, a rect, an
# accessible name, a contrast ratio worked out from the colours the browser
# actually painted — because each of these defects passed every source-level
# check in this suite. The default `page` fixture is a desktop mouse; the
# phone ones below open their own context, since touch and viewport are fixed
# when a context is created.
# ═══════════════════════════════════════════════════════════════════════════

from contextlib import contextmanager  # noqa: E402

_CONTRAST_JS = """
(() => {
  function rgb(s) {
    const m = s.match(/rgba?\\(([^)]+)\\)/);
    const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number);
    return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1};
  }
  function lum(c) {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  }
  function over(fg, bg) {
    return {r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a),
            b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1};
  }
  // Any CSS colour expression, resolved to rgb by the browser itself.
  function resolve(expr) {
    const probe = document.createElement('span');
    probe.style.color = expr;
    document.body.appendChild(probe);
    const v = getComputedStyle(probe).color;
    probe.remove();
    return rgb(v);
  }
  window.__contrast = (fgExpr, bgExpr, alpha) => {
    const bg = resolve(bgExpr);
    let fg = resolve(fgExpr);
    if (alpha !== undefined) fg = {...fg, a: fg.a * alpha};
    fg = over(fg, bg);
    const a = lum(fg), b = lum(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
})();
"""


@contextmanager
def _phone(document, width=390, touch=True):
    """A page in a phone-shaped, touch-capable context."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": width, "height": 800},
                                  has_touch=touch, is_mobile=touch)
        pg = ctx.new_page()
        try:
            pg.goto(document["url"])
            _decorated(pg)
            yield pg
        finally:
            browser.close()


def _set_theme(page, theme):
    page.evaluate("t => { document.body.dataset.pageTheme = t; }", theme)
    page.wait_for_timeout(50)


def _decorated(pg):
    """Wait until the selection menu is loaded: it is what acts on the prose.
    And until the cards are drawn: the menu can load before they are."""
    pg.wait_for_function("() => !!window.AnnotateSelection", timeout=15000)
    pg.wait_for_selector("section.block .card-title", timeout=15000)


def test_every_glyph_button_says_what_it_does_and_to_what(page):
    _select(page, "section-1", "long enough")
    menu = page.eval_on_selector_all(".sel-menu button", """bs => bs.map(b => ({
      act: b.dataset.act, label: b.getAttribute('aria-label') || ''}))""")
    assert menu, "the selection menu has no buttons"
    keys = {"comment": "c", "delete": "d", "compact": "x", "explain": "r", "edit": "e"}
    for b in menu:
        if b["act"] == "remove":
            continue
        if b["act"] == "voice-more":    # a disclosure: it opens Read as written
            assert "listen" in b["label"].lower(), f"the menu button does not say what it does: {b}"
            continue
        assert b["label"].lower().startswith(b["act"]) and f"({keys[b['act']]})" in b["label"], \
            f"the menu button does not name its action and key: {b}"


def test_card_titles_are_headings(page):
    n = page.locator("section.block").count()
    assert page.get_by_role("heading", level=2).count() == n


def test_the_card_head_wraps_on_a_phone(document):
    with _phone(document) as pg:
        pg.evaluate("""() => { document.querySelector('.card-title').textContent =
          'A title long enough to need more than one line at phone width, easily'; }""")
        w = pg.eval_on_selector(".card-title", "el => el.getBoundingClientRect().width")
        assert w > 250, f"the title is squeezed into a {w:.0f}px column"


def test_dim_text_links_and_control_borders_meet_contrast(page):
    page.evaluate(_CONTRAST_JS)
    got = {}
    for theme in ("light", "dark"):
        _set_theme(page, theme)
        got[theme] = page.evaluate("""() => ({
          dim: window.__contrast('var(--text-dim)', 'var(--surface)'),
          dimSoft: window.__contrast('var(--text-dim)', 'var(--surface-soft)'),
          link: window.__contrast(getComputedStyle(document.querySelector(
            'main.prose')).getPropertyValue('--link') || 'red', 'var(--surface)'),
          control: window.__contrast(getComputedStyle(document.querySelector(
            'main.prose')).getPropertyValue('--control-border') || 'white', 'var(--surface)'),
        })""")
    for theme, r in got.items():
        assert r["dim"] >= 4.5 and r["dimSoft"] >= 4.5, (theme, r)
        assert r["link"] >= 4.5, (theme, r)
        assert r["control"] >= 3, (theme, r)


def test_the_round_drawer_works_from_the_keyboard(page):
    _block_mark(page, "section-1", "compact")
    page.wait_for_selector("#round-dock")
    toggle = page.locator("#round-dock .rd-toggle")
    assert toggle.count() == 1, "the drawer has no toggle button"
    assert toggle.evaluate("el => el.tagName") == "BUTTON"
    assert toggle.get_attribute("aria-expanded") == "false"
    assert page.locator(f"#{toggle.get_attribute('aria-controls')}").count() == 1
    toggle.focus()
    page.keyboard.press("Enter")
    page.wait_for_function(
        "() => document.getElementById('round-dock').dataset.open === 'true'", timeout=3000)
    assert toggle.get_attribute("aria-expanded") == "true"
    jump = page.locator("#round-dock .rd-row >> nth=0 >> .rd-body")
    assert jump.evaluate("el => el.tabIndex") == 0, "a drawer row is not reachable by Tab"
    assert jump.get_attribute("role") == "button"

    page.evaluate("() => document.activeElement.blur()")
    page.keyboard.press("s")
    assert page.evaluate("() => document.activeElement.id") == "round-submit", \
        "s does not take the caret to Submit"


def test_marks_are_announced(page):
    status = page.locator("#a11y-status")
    assert status.count() == 1, "there is no status region"
    assert status.get_attribute("role") == "status"
    _block_mark(page, "section-1", "compact")
    page.wait_for_function(
        "() => /1/.test(document.getElementById('a11y-status').textContent)", timeout=3000)


def test_adding_a_comment_to_the_round_keeps_the_caret(page):
    _block_mark(page, "section-1", "comment")
    page.wait_for_selector(".comment-card textarea")
    page.fill(".comment-card textarea", "keep the caret")
    page.focus(".comment-card .card-submit-btn")
    page.keyboard.press("Enter")
    page.wait_for_function("() => !document.querySelector('.comment-card')", timeout=3000)
    where = page.evaluate("""() => ({
      tag: document.activeElement.tagName,
      block: document.activeElement.closest('section.block')?.dataset.blockId})""")
    assert where["block"] == "section-1", f"the caret fell to {where}"
    assert page.evaluate(
        "() => document.activeElement.classList.contains('card-chevron')"), \
        f"the caret did not land on the fold button: {where}"
    # Written on the next frame (a11y.js clears, then sets, so a repeat of the
    # same sentence is announced again), so waited for rather than sampled.
    page.wait_for_function(
        "() => /round/i.test(document.getElementById('a11y-status')?.textContent || '')",
        timeout=3000)


def test_a_choice_group_is_named_and_single_select_is_one_tab_stop(page, document):
    _add_choices(page, document)
    group = page.locator('section.block[data-block-id="choice-a"] .choice-options')
    labelled = group.get_attribute("aria-labelledby")
    assert labelled and page.locator(f"#{labelled}").inner_text() == "Which colour?"
    stops = group.evaluate(
        "g => [...g.querySelectorAll('.choice-option')].map(o => o.tabIndex)")
    assert stops.count(0) == 1, f"single-select has {stops.count(0)} tab stops"
    page.focus('section.block[data-block-id="choice-a"] .choice-option[tabindex="0"]')
    page.keyboard.press("ArrowDown")
    sel = group.evaluate("g => [...g.querySelectorAll('.choice-option')]"
                         ".map(o => o.getAttribute('aria-checked'))")
    assert sel == ["false", "true"], f"ArrowDown moved without selecting: {sel}"
    assert page.evaluate(
        "() => document.activeElement.getAttribute('aria-checked')") == "true"


# ── The review round's lifecycle ──────────────────────────────────────────
#
# A round goes out once, locks the page until Claude answers it, and then
# clears. Each test below pins one way that went wrong in a real browser:
# a reload, a second tab, an answer that rewrote nothing, a block write that
# arrived before the answer, or a load that raced the module which paints the
# marks.

SEL = 'section.block[data-block-id="{}"]'


def _put_block(document, anchor, markdown, title=None):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/{anchor}",
          {"id": anchor, "kind": "markdown", "title": title or anchor,
           "markdown": markdown})


def _put_doc(document, order, response_id="resp-browser-suite"):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__doc__",
          {"response_id": response_id, "title": "annotate browser suite",
           "order": order, "cwd": str(REPO), "glossary": []})


def _remove_block(document, anchor):
    """What a push that drops a block does: gone from `order` AND from the
    store. The page renders any stored item, ordered or not."""
    _put_doc(document, [a for a in BLOCKS if a != anchor])
    _call(document["base"], "DELETE", f"/s/{document['sid']}/items/{anchor}")


def _ack(document, event_id):
    subprocess.run(["webcompanion", "ack", "--sid", document["sid"],
                    "--event-id", str(event_id)], check=True,
                   capture_output=True, timeout=20)


def _watch_submits(page):
    """Every submit POST the page makes, in order."""
    posts = []
    page.on("request", lambda r: posts.append(r)
            if r.method == "POST" and r.url.endswith("/api/submit") else None)
    return posts


def _envelope(request):
    return json.loads(json.loads(request.post_data)["text"])


def _block_mark(page, anchor, kind):
    """Whole-section mark, the way a reader makes one now: double-click the
    title, then pick from the menu."""
    page.dblclick(SEL.format(anchor) + " .card-title")
    page.wait_for_selector(".sel-menu", timeout=3000)
    page.click(f'.sel-menu button[data-act="{kind}"]')


def _submit_round(page):
    """Press Submit and return the event id the daemon gave the round."""
    page.wait_for_selector("#round-submit:not([disabled])", timeout=5000)
    with page.expect_response(lambda r: r.url.endswith("/api/submit")) as resp:
        page.click("#round-submit")
    return resp.value.json()["event_id"]


def _comment_on_block(page, anchor, text):
    _block_mark(page, anchor, "comment")
    page.fill(".comment-card textarea", text)
    page.click(".comment-card .card-submit-btn")


BUSY = "() => document.body.classList.contains('is-busy')"
SETTLED = ("() => !document.body.classList.contains('is-busy')"
           " && !document.getElementById('round-dock')")


def test_a_reload_mid_round_cannot_send_it_again(page, document):
    """The lock lived only in memory, so a reload handed back an armed Submit
    for a round that was already queued. Pressing it applied the round twice,
    and its marks never cleared."""
    _block_mark(page, "section-1", "compact")
    eid = _submit_round(page)
    page.wait_for_function(BUSY)

    page.reload()
    page.wait_for_selector("section.block")
    posts = _watch_submits(page)
    page.wait_for_function(BUSY, timeout=5000)
    page.wait_for_selector("#round-submit[disabled]", timeout=5000)

    # The narration trail closing on this event is Claude saying it is done,
    # and it is the one signal a reloaded page can still read.
    _put_progress(document, ["Applied your round"], state="done",
                  ended=int(time.time()), event_id=eid)
    page.wait_for_function(SETTLED, timeout=10000)
    assert posts == [], "the reloaded page submitted the round again"


def test_a_second_tab_sees_the_round_in_flight(document):
    """Two tabs share the marks, so the round one of them sent has to lock
    the other as well, and clear there when it is answered."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context()
        _serve_core_override(ctx)
        try:
            a, b = ctx.new_page(), ctx.new_page()
            for pg in (a, b):
                pg.goto(document["url"])
                pg.wait_for_selector("section.block")
                pg.wait_for_function("() => !!window.AnnotateSubunits")
            _block_mark(a, "section-1", "compact")
            b.wait_for_selector("#round-dock", timeout=5000)
            b_posts = _watch_submits(b)
            eid = _submit_round(a)
            b.wait_for_selector("#round-submit[disabled]", timeout=5000)

            _ack(document, eid)
            for pg in (a, b):
                pg.wait_for_function(SETTLED, timeout=10000)
            assert b_posts == [], "the second tab sent the round again"
        finally:
            browser.close()


def test_an_answer_that_rewrites_nothing_still_unlocks(page, document):
    """An answer can arrive with no block written. The ack is then the only
    thing that moves, and the page has to hear it."""
    _block_mark(page, "section-1", "compact")
    eid = _submit_round(page)
    page.wait_for_function(BUSY)
    _ack(document, eid)
    page.wait_for_function(SETTLED, timeout=10000)


def test_a_block_write_mid_round_keeps_the_lock(page, document):
    """Claude writes blocks while it works. The first write is not the
    answer, and unlocking on it re-armed Submit mid-round."""
    _comment_on_block(page, "section-1", "tighten this")
    _submit_round(page)
    page.wait_for_function(BUSY)

    _put_block(document, "section-3", "Rewritten while the round is still out.")
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format('section-3')}')"
        ".textContent.includes('still out')", timeout=10000)
    page.wait_for_timeout(300)
    assert page.evaluate(BUSY), "a block write unlocked the page before the answer"
    assert page.is_disabled("#round-submit"), "Submit re-armed mid-round"


def test_marks_come_back_on_every_load(page, document):
    """The module that paints marks can load after the blocks render. When
    it did, the dock, the per-paragraph controls and a pending delete all
    went missing, on most loads."""
    _block_mark(page, "section-2", "delete")
    _select(page, "section-1", "Paragraph one")
    _menu(page, "compact")
    painted = "() => CSS.highlights.get('annotate-compact')?.size === 1"
    page.wait_for_function(painted, timeout=3000)
    for i in range(8):
        page.reload()
        page.wait_for_selector("section.block")
        try:
            page.wait_for_selector(
                f'{SEL.format("section-2")}[data-block-mark="delete"]', timeout=3000)
            page.wait_for_function(painted, timeout=3000)
            page.wait_for_selector("#round-dock", timeout=3000)
        except Exception as e:                              # noqa: BLE001
            raise AssertionError(f"load {i + 1}: marks not painted ({e})") from None


def test_removing_the_block_under_an_open_comment_frees_the_editor(page, document):
    """The card went away with its block, but the draft stayed, and one open
    draft blocks every other comment until a reload."""
    _block_mark(page, "section-3", "comment")
    page.fill(".comment-card textarea", "about to vanish")
    _remove_block(document, "section-3")
    page.wait_for_selector(SEL.format("section-3"), state="detached", timeout=10000)
    page.wait_for_function(
        "() => !document.body.classList.contains('is-editing')", timeout=3000)
    _block_mark(page, "section-1", "comment")
    page.wait_for_selector(".comment-card textarea", timeout=3000)


def test_a_new_response_starts_with_a_clean_round(page, document):
    """A second response in the same session reuses the section ids. Marks
    made on the first one must not ride over onto the second."""
    _block_mark(page, "section-2", "delete")
    page.wait_for_selector("#round-dock")
    _put_block(document, "section-2", "A different section two.")
    _put_doc(document, BLOCKS, response_id="resp-two")
    page.wait_for_function(
        "() => document.body.dataset.responseId === 'resp-two'", timeout=10000)
    page.wait_for_selector("#round-dock", state="detached", timeout=3000)
    assert page.get_attribute(SEL.format("section-2"), "data-block-mark") is None
    left = page.evaluate(
        "() => localStorage.getItem('annotate.round.resp-browser-suite')")
    assert not left or left == "{}", f"the old round is still stored: {left}"


def test_a_rewritten_choice_keeps_the_readers_place(page, document):
    """A choice block is rebuilt whole when Claude rewrites it. The reader
    typing in its note kept typing into nothing, and an answer naming an
    option the new block no longer has stayed in the round."""
    _add_choices(page, document)
    card = SEL.format("choice-a")
    page.click(f"{card} .choice-option >> nth=1")               # o2, Blue
    page.click(f"{card} .choice-note")
    page.keyboard.type("first line")
    page.keyboard.press("Shift+Enter")
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/choice-a", {
        "id": "choice-a", "kind": "choice",
        "spec": {"question": "Which colour?",
                 "options": [{"id": "o1", "label": "Red"},
                             {"id": "o3", "label": "Green"}]}})
    page.wait_for_function(
        f"() => document.querySelector('{card}').textContent.includes('Green')",
        timeout=10000)
    state = page.evaluate(f"""() => {{
      const note = document.querySelector('{card} .choice-note');
      const round = JSON.parse(localStorage.getItem(
        'annotate.round.resp-browser-suite') || '{{}}');
      return {{ focused: document.activeElement === note, value: note.value,
                mark: round['choice-a::__choice__'] || null }};
    }}""")
    assert state["focused"], "the rewrite took the caret out of the note"
    assert state["value"] == "first line\n", state
    assert state["mark"] and "o2" not in state["mark"]["selected_options"], state


def test_a_rewritten_paragraph_keeps_its_comment(page, document):
    """A paragraph comment is anchored by the paragraph's text. When Claude
    rewrote that text, the comment the reader typed was deleted in silence."""
    _select(page, "section-1", "Paragraph one of block 1")
    _menu(page, "comment")
    page.fill(".sel-composer textarea", "why is this true?")
    page.press(".sel-composer textarea", "Enter")
    page.wait_for_selector("#round-dock")
    _put_block(document, "section-1",
               "A reworded first paragraph.\n\nParagraph two of block 1.")
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format('section-1')}')"
        ".textContent.includes('reworded')", timeout=10000)
    page.wait_for_timeout(300)
    stored = page.evaluate(
        "() => localStorage.getItem('annotate.round.resp-browser-suite') || ''")
    assert "why is this true?" in stored, "the reader's comment was dropped"
    assert page.locator("#round-dock").count() == 1


def test_the_page_says_it_is_waiting_and_then_that_it_was_answered(page, document):
    """The busy ribbon, and the general box's status line, both read the
    lock through a handler that never saw it go up."""
    page.keyboard.press("g")
    page.wait_for_selector("#general-composer:not([hidden])")
    page.fill("#general-input", "a general question")
    with page.expect_response(lambda r: r.url.endswith("/api/submit")) as resp:
        page.click("#general-send")
    eid = resp.value.json()["event_id"]
    page.wait_for_selector("#busy-banner", timeout=5000)
    _ack(document, eid)
    page.wait_for_selector("#busy-banner", state="detached", timeout=10000)
    page.wait_for_function(
        "() => document.getElementById('general-status').textContent === 'responded'",
        timeout=3000)


def test_an_answered_round_says_what_changed(page, document):
    """The change bar is computed on the lock's falling edge, which the page
    never saw."""
    _comment_on_block(page, "section-2", "shorter please")
    eid = _submit_round(page)
    page.wait_for_function(BUSY)
    _put_block(document, "section-2", "Shorter.")
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format('section-2')}')"
        ".textContent.includes('Shorter.')", timeout=10000)
    _ack(document, eid)
    page.wait_for_selector("#change-bar", timeout=10000)


def test_one_press_is_one_round(page, document):
    """Two clicks in the same tick used to be able to fire two rounds."""
    _block_mark(page, "section-1", "compact")
    page.wait_for_selector("#round-submit:not([disabled])")
    posts = _watch_submits(page)
    page.evaluate("() => { const b = document.getElementById('round-submit');"
                  " b.click(); b.click(); }")
    page.wait_for_function(BUSY)
    page.wait_for_timeout(300)
    assert len(posts) == 1, f"{len(posts)} rounds went out for one press"


def test_nothing_can_be_sent_while_claude_is_busy(page, document):
    page.keyboard.press("g")
    page.wait_for_selector("#general-composer:not([hidden])")
    page.fill("#general-input", "locking the page")
    page.click("#general-send")
    page.wait_for_function(BUSY)
    _block_mark(page, "section-1", "compact")
    page.wait_for_selector("#round-dock")
    assert page.is_disabled("#round-submit"), "Submit is live while Claude is busy"
    _block_mark(page, "section-2", "comment")
    events = page.eval_on_selector(".comment-card",
                                   "el => getComputedStyle(el).pointerEvents")
    assert events == "none", "an open comment card still takes input while busy"


def test_a_removed_blocks_marks_never_go_out(page, document):
    _block_mark(page, "section-2", "delete")
    _block_mark(page, "section-1", "compact")
    _remove_block(document, "section-2")
    page.wait_for_selector(SEL.format("section-2"), state="detached", timeout=10000)
    posts = _watch_submits(page)
    _submit_round(page)
    ids = [r["block_id"] for r in _envelope(posts[0])["reactions"]]
    assert ids == ["section-1"], ids


def test_compact_goes_out_as_compact(page, document):
    _block_mark(page, "section-2", "compact")
    posts = _watch_submits(page)
    _submit_round(page)
    kinds = [r["kind"] for r in _envelope(posts[0])["reactions"]]
    assert kinds == ["compact"], kinds


def test_a_second_click_takes_a_mark_back(page, document):
    _select(page, "section-1", "long enough")
    _menu(page, "delete")
    page.wait_for_selector("#round-dock")
    _select(page, "section-1", "long enough")
    _menu(page, "delete")
    page.wait_for_selector("#round-dock", state="detached", timeout=3000)
    assert _round(page) == {}


def test_a_mark_removed_from_the_dock_stays_removed(page, document):
    _block_mark(page, "section-1", "compact")
    page.click("#round-dock .rd-head")
    page.click("#round-dock .rd-x")
    page.wait_for_selector("#round-dock", state="detached")
    page.reload()
    page.wait_for_selector("section.block")
    page.wait_for_function("() => !!window.AnnotateSubunits")
    page.wait_for_timeout(500)
    assert page.locator("#round-dock").count() == 0, "the removed mark came back"


def test_the_second_of_two_identical_lines_says_which_it_is(page, document):
    """Two list items with the same text are told apart on the wire by the
    words around them. The second one must carry its own."""
    _put_block(document, "section-1", "- Done\n- Other\n- Done")
    page.wait_for_function(
        f"() => document.querySelectorAll('{SEL.format('section-1')} li').length === 3",
        timeout=10000)
    _select(page, "section-1", "Done", nth=1)
    _menu(page, "delete")
    posts = _watch_submits(page)
    _submit_round(page)
    r = _envelope(posts[0])["reactions"][0]
    assert r["selected_text"] == "Done"
    # The first "Done" and the line between are what precede the second one.
    assert r["prefix"].endswith("Done\nOther\n"), r


# ── Words the reader wrote survive their block; old documents' state is swept ─

def test_a_comment_on_a_removed_block_moves_to_the_general_box(page, document):
    """A pending comment is words the reader wrote. When Claude removes the
    whole block it was on, the round cannot send it anywhere, and it used to
    vanish from the dock without a word. It lands in the general box instead,
    where it is one press away from being sent."""
    _comment_on_block(page, "section-2", "keep the retry budget")
    page.wait_for_selector("#round-dock")
    _remove_block(document, "section-2")
    page.wait_for_function(
        "() => !document.querySelector('section.block[data-block-id=\"section-2\"]')",
        timeout=10000)
    page.wait_for_function(
        "() => document.getElementById('general-input').value"
        ".includes('keep the retry budget')", timeout=5000)
    assert "removed" in page.inner_text("#general-status")
    assert not page.query_selector("#round-dock"), "the dock still lists it"
    page.reload()
    page.wait_for_selector("section.block")
    assert "keep the retry budget" in page.eval_on_selector(
        "#general-input", "el => el.value"), "the moved comment did not persist"


def test_an_open_comment_on_a_removed_block_moves_to_the_general_box(page, document):
    """The same words, one step earlier: typed into a card, not yet added."""
    _block_mark(page, "section-3", "comment")
    page.fill(".comment-card textarea", "half-written thought")
    _remove_block(document, "section-3")
    page.wait_for_function(
        "() => document.getElementById('general-input').value"
        ".includes('half-written thought')", timeout=10000)


def test_state_of_documents_not_opened_for_a_month_is_swept(page):
    """Collapse, view and highlighter keys are per response and were
    never removed. A response not opened for 30 days loses them; the current
    one and the global settings keep theirs."""
    old = 1000 * (int(time.time()) - 31 * 24 * 3600)
    page.evaluate("""(old) => {
      localStorage.setItem('annotate.collapsed:resp-gone:section-1', '1');
      localStorage.setItem('annotate.read:resp-gone:section-1', '[]');
      localStorage.setItem('annotate.view:resp-gone:highlighter', 'on');
      localStorage.setItem('annotate.collapsed:resp-browser-suite:section-1', '1');
      localStorage.setItem('annotate.view:codefont', 'monaspace');
      localStorage.setItem('annotate.view:prosefont', 'serif');
      localStorage.setItem('annotate.view:resp-browser-suite:codelayout', 'wide');
      localStorage.setItem('annotate.codewide:resp-browser-suite:section-1', '1');
      localStorage.setItem('annotate.flavour.section-1', 'compact');
      localStorage.setItem('annotate.view.section-2', 'decisions');
      localStorage.setItem('annotate.opened',
        JSON.stringify({'resp-gone': old}));
    }""", old)
    page.reload()
    page.wait_for_selector("section.block")
    left = page.evaluate("() => Object.keys(localStorage)"
                         ".filter(k => k.startsWith('annotate.')).sort()")
    assert not [k for k in left if "resp-gone" in k], left
    assert "annotate.collapsed:resp-browser-suite:section-1" in left
    assert "annotate.view:codefont" in left
    # Settings and state for controls that no longer exist are retired.
    assert "annotate.view:prosefont" not in left
    assert "annotate.view:resp-browser-suite:codelayout" not in left
    assert "annotate.codewide:resp-browser-suite:section-1" not in left
    # The retired diagram-choice keys, shared by every document, are gone.
    assert "annotate.flavour.section-1" not in left
    assert "annotate.view.section-2" not in left


# ── A diagram's layout choice belongs to its own document ───────────────────

def _flow_block(anchor):
    svg = lambda label: (f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40">'
                         f'<text x="10" y="25">{label}</text></svg>')
    return {"id": anchor, "kind": "flowchart", "title": "Flow",
            "flavours": ["layered", "compact"], "svg": svg("layered"),
            "svgs": {"layered": svg("layered"), "compact": svg("compact")}}


def test_a_layout_choice_stays_in_its_own_document(document):
    """The choice was saved as `annotate.flavour.<block id>`, and every
    document's first block is section-1, so picking Compact in one document
    opened every other document's first diagram on Compact too."""
    base = document["base"]
    _call(base, "PUT", f"/s/{document['sid']}/items/section-1", _flow_block("section-1"))
    other = _call(base, "POST", "/api/sessions",
                  {"kind": "annotate", "cwd": str(REPO), "title": "other document"})["sid"]
    try:
        _call(base, "POST", f"/s/{other}/api/assets",
              {"static_root": str(STATIC), "entry": "entry.js"})
        _call(base, "PUT", f"/s/{other}/items/__doc__",
              {"response_id": "resp-other-document", "title": "other document",
               "order": ["section-1"], "cwd": str(REPO), "glossary": []})
        _call(base, "PUT", f"/s/{other}/items/section-1", _flow_block("section-1"))
        pressed = '.flow-flavours [aria-pressed="true"]'
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            pg = browser.new_page()
            try:
                pg.goto(document["url"])
                pg.wait_for_selector(".flow-flavours")
                pg.click('.flow-flavours [data-flavour="compact"]')
                pg.goto(f"{base}/s/{other}/")
                pg.wait_for_selector(".flow-flavours")
                assert pg.get_attribute(pressed, "data-flavour") == "layered", \
                    "another document's layout choice was applied here"
                pg.goto(document["url"])
                pg.wait_for_selector(".flow-flavours")
                assert pg.get_attribute(pressed, "data-flavour") == "compact", \
                    "the document lost its own layout choice"
            finally:
                browser.close()
    finally:
        _call(base, "POST", f"/s/{other}/api/finish")
        _call(base, "DELETE", f"/s/{other}/?force=1")


def test_an_authored_list_item_can_be_commented(page, document):
    """The compact triage block makes every item a data-annotate-id region
    (references/pushing.md). A comment on words inside one names the item by
    its id, so it survives a rewrite of those words."""
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-1", {
        "id": "section-1", "kind": "markdown", "title": "Block 1",
        "markdown": 'Intro.\n\n<ol><li data-annotate-id="client-split">'
                    "<strong>Which clients take the flow.</strong> Sources disagree.</li>"
                    '<li data-annotate-id="one-or-two">Two workflows, or one.</li></ol>'})
    page.reload()
    item = page.locator('[data-annotate-id="client-split"]')
    item.wait_for(timeout=10000)
    page.wait_for_function("() => !!window.AnnotateSubunits", timeout=15000)
    page.wait_for_function("() => !!window.AnnotateSelection", timeout=15000)
    _select(page, "section-1", "Which clients take the flow.")
    _menu(page, "comment")
    page.locator(".sel-composer textarea").fill("Mario decides this")
    page.locator(".sel-composer textarea").press("Enter")
    marks = json.loads(page.evaluate(
        "() => localStorage.getItem('annotate.round.resp-browser-suite')") or "{}")
    [m] = marks.values()
    assert m["step_id"] == "client-split"
    assert m["selected_text"].startswith("Which clients take the flow.")
    assert m["text"] == "Mario decides this"


def _anchor_of(page, anchor, needle):
    """Anchor for the first occurrence of `needle` in a block, built the way
    the selection menu will build it."""
    return page.evaluate("""([sel, needle]) => {
      const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s);
      const i = AnnotateAnchors.textOf(root).indexOf(needle);
      return AnnotateAnchors.anchorFor(s, AnnotateAnchors.rangeFrom(root, i, i + needle.length));
    }""", [SEL.format(anchor), needle])


def _round(page):
    return json.loads(page.evaluate(
        "() => localStorage.getItem('annotate.round.resp-browser-suite')") or "{}")


def test_a_span_mark_goes_into_the_round_with_its_context(page):
    a = _anchor_of(page, "section-1", "long enough")
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'compact')", a)
    [m] = _round(page).values()
    assert m["scope"] == "unit" and m["kind"] == "compact"
    assert m["selected_text"] == "long enough"
    assert m["prefix"].endswith("Paragraph one of block 1, ")
    assert m["suffix"].startswith(" to scroll past.")
    assert page.evaluate("() => CSS.highlights.get('annotate-compact').size") == 1


def test_the_same_kind_on_the_same_span_takes_the_mark_back(page):
    a = _anchor_of(page, "section-1", "long enough")
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')", a)
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')", a)
    assert _round(page) == {}
    assert page.evaluate("() => CSS.highlights.get('annotate-delete').size") == 0


def test_an_overlapping_mark_replaces_the_old_one(page):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')",
                  _anchor_of(page, "section-1", "long enough to scroll"))
    b = _anchor_of(page, "section-1", "enough to scroll past")
    assert [x["m"]["kind"] for x in page.evaluate("b => AnnotateSubunits.overlapping(b)", b)] == ["delete"]
    page.evaluate("b => AnnotateSubunits.setSpanMark(b, 'compact')", b)
    marks = list(_round(page).values())
    assert [(m["kind"], m["selected_text"]) for m in marks] == [("compact", "enough to scroll past")]


def test_span_marks_survive_a_reload_and_repaint(page):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'comment', 'why?')",
                  _anchor_of(page, "section-2", "Paragraph two"))
    page.reload()
    page.wait_for_function("() => !!window.AnnotateSubunits")
    page.wait_for_function("() => CSS.highlights.get('annotate-comment')?.size === 1", timeout=5000)


def test_a_rewritten_block_drops_a_delete_and_moves_a_comment_to_the_section(page, document):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')",
                  _anchor_of(page, "section-3", "Paragraph one"))
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'comment', 'keep this point')",
                  _anchor_of(page, "section-3", "Paragraph two"))
    _put_block(document, "section-3", "Entirely new words.", title="Block 3")
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format('section-3')}').textContent.includes('Entirely new')",
        timeout=10000)
    page.wait_for_timeout(300)
    page.evaluate("() => AnnotateSubunits.renderDock()")
    marks = list(_round(page).values())
    assert [m["kind"] for m in marks] == ["comment"]
    assert marks[0]["scope"] == "block"
    assert "Paragraph two" in marks[0]["text"] and "keep this point" in marks[0]["text"]


def test_a_mark_is_found_by_the_point_it_is_painted_at(page):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')",
                  _anchor_of(page, "section-1", "long enough"))
    hit = page.evaluate("""(sel) => {
      const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFor(s, Object.values(JSON.parse(
          localStorage.getItem('annotate.round.resp-browser-suite')))[0]);
      const b = r.getBoundingClientRect();
      return AnnotateSubunits.spanMarkAt(s, b.left + 3, b.top + b.height / 2)?.m.kind;
    }""", SEL.format("section-1"))
    assert hit == "delete"


def test_a_span_mark_on_a_soft_wrapped_paragraph_survives_a_reload(page, document):
    _put_block(document, "section-4", "Paragraph one\nwraps here.", title="Block 4")
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format('section-4')}').textContent.includes('wraps here')",
        timeout=10000)
    page.wait_for_timeout(300)
    a = page.evaluate("""(sel) => {
      const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s);
      const t = AnnotateAnchors.textOf(root);
      const i = t.indexOf('one'), e = t.indexOf('wraps') + 5;
      return AnnotateAnchors.anchorFor(s, AnnotateAnchors.rangeFrom(root, i, e));
    }""", SEL.format("section-4"))
    assert a["selected_text"] == "one\nwraps"
    # what a strip mark stores: the same words, whitespace collapsed
    a["selected_text"] = "one wraps"
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')", a)
    page.reload()
    page.wait_for_function("() => !!window.AnnotateSubunits")
    page.wait_for_selector(SEL.format("section-4"))
    page.wait_for_timeout(500)
    page.evaluate("() => AnnotateSubunits.renderDock()")
    assert [m["selected_text"] for m in _round(page).values()] == ["one wraps"]
    page.wait_for_function("() => CSS.highlights.get('annotate-delete')?.size === 1", timeout=5000)


def _release(page, x=None, y=None):
    """A mouseup where a drag would end. `page.mouse.up()` without a matching
    down is not a reliable mouseup in Chromium, so the event is dispatched on
    the element under the point (or <body>) with its coordinates."""
    page.evaluate("""([x, y]) => {
      const el = (x === null ? null : document.elementFromPoint(x, y)) || document.body;
      el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, clientX: x || 0, clientY: y || 0}));
    }""", [x, y])


def _select(page, anchor, needle, nth=0):
    """Select the nth occurrence of `needle` in a block, as a drag would,
    then release the mouse over it so the page sees a real mouseup."""
    box = page.evaluate("""([sel, needle, nth]) => {
      const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s);
      const text = AnnotateAnchors.textOf(root);
      let i = -1; for (let k = 0; k <= nth; k++) i = text.indexOf(needle, i + 1);
      const r = AnnotateAnchors.rangeFrom(root, i, i + needle.length);
      const sel2 = getSelection(); sel2.removeAllRanges(); sel2.addRange(r);
      const b = r.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + b.height / 2};
    }""", [SEL.format(anchor), needle, nth])
    _release(page, box["x"], box["y"])
    page.wait_for_selector(".sel-menu", timeout=3000)


def _menu(page, kind):
    page.click(f'.sel-menu button[data-act="{kind}"]')


def test_selecting_words_opens_the_menu_and_delete_marks_exactly_them(page):
    _select(page, "section-1", "long enough")
    labels = page.eval_on_selector_all(".sel-menu button", "bs => bs.map(b => b.dataset.act)")
    assert labels == ["comment", "delete", "compact", "explain", "voice-more", "edit"]
    _menu(page, "delete")
    [m] = _round(page).values()
    assert (m["kind"], m["selected_text"]) == ("delete", "long enough")
    assert page.locator(".sel-menu").count() == 0


def test_a_plain_click_on_prose_opens_nothing(page):
    page.click(SEL.format("section-1") + " .block-content p")
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0


def test_the_keys_act_on_the_selection(page):
    _select(page, "section-2", "Paragraph two")
    page.keyboard.press("x")
    [m] = _round(page).values()
    assert m["kind"] == "compact"


def test_comment_opens_a_box_quoting_the_selection_and_pins_it(page):
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    box = page.locator(".sel-composer")
    assert "long enough" in box.locator(".sel-quote").inner_text()
    box.locator("textarea").fill("is it though?")
    box.locator("textarea").press("Enter")
    [m] = _round(page).values()
    assert (m["kind"], m["text"], m["selected_text"]) == ("comment", "is it though?", "long enough")
    assert page.locator(".sel-chip").count() == 1


def test_a_title_double_click_scopes_the_whole_section(page):
    page.dblclick(SEL.format("section-2") + " .card-title")
    page.wait_for_selector(".sel-menu", timeout=3000)
    page.wait_for_timeout(150)          # the second mouseup of the double-click
    assert page.locator(".sel-menu").count() == 1
    assert "Whole section" in page.inner_text(".sel-menu")
    assert page.locator(SEL.format("section-2") + "[data-sel-scope]").count() == 1
    _menu(page, "delete")
    assert page.locator(SEL.format("section-2") + '[data-block-mark="delete"]').count() == 1


def test_a_selection_across_two_sections_is_refused(page):
    page.evaluate("""() => {
      const a = document.querySelectorAll('section.block .block-content p');
      const r = document.createRange(); r.setStart(a[0].firstChild, 0); r.setEnd(a[2].firstChild, 5);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""")
    _release(page)
    page.wait_for_selector(".sel-menu", timeout=3000)
    assert "Select within one section" in page.inner_text(".sel-menu")
    assert page.locator(".sel-menu button[data-act]").count() == 0


def test_the_menu_says_what_a_new_mark_replaces(page):
    _select(page, "section-1", "long enough to scroll")
    _menu(page, "delete")
    _select(page, "section-1", "enough to scroll past")
    assert "Replaces a delete" in page.inner_text(".sel-menu")


def test_clicking_a_mark_opens_its_state_and_can_remove_it(page):
    _select(page, "section-1", "long enough")
    _menu(page, "compact")
    page.evaluate("() => getSelection().removeAllRanges()")
    pos = page.evaluate("""(sel) => {
      const s = document.querySelector(sel);
      const m = Object.values(JSON.parse(localStorage.getItem('annotate.round.resp-browser-suite')))[0];
      const b = AnnotateAnchors.rangeFor(s, m).getBoundingClientRect();
      return {x: b.left + 4, y: b.top + b.height / 2}; }""", SEL.format("section-1"))
    page.mouse.click(pos["x"], pos["y"])
    page.wait_for_selector(".sel-menu", timeout=3000)
    assert "Marked compact" in page.inner_text(".sel-menu")
    _menu(page, "remove")
    assert _round(page) == {}


def test_no_menu_while_the_reading_highlighter_is_on(page):
    page.evaluate("() => { document.body.dataset.highlighter = 'on'; }")
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFrom(AnnotateAnchors.contentOf(s), 0, 9);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format("section-1"))
    _release(page)
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0


def test_the_menu_paints_with_no_page_errors(page):
    _select(page, "section-3", "Paragraph one")
    assert page.__dict__["js_errors"] == []


def test_registered_actions_join_the_menu_after_a_divider(page):
    page.evaluate("""() => AnnotateSelection.registerAction((t, menu) => {
      const b = document.createElement('button'); b.dataset.act = 'probe'; b.textContent = 'Probe';
      menu.appendChild(b); })""")
    _select(page, "section-1", "long enough")
    acts = page.eval_on_selector_all(".sel-menu > *", "els => els.map(e => e.dataset.act || e.className)")
    # speech.js registers first; every registered action follows the one divider.
    assert acts == ["comment", "delete", "compact", "sel-sep", "explain", "voice-more", "edit", "probe"]


# ── review fixes for the selection menu ─────────────────────────────────────

def _menu_is_on_top(page):
    return page.evaluate("""() => { const m = document.querySelector('.sel-menu');
      const b = m.getBoundingClientRect();
      const el = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      return !!(el && el.closest('.sel-menu')); }""")


def test_the_menu_shows_in_a_maximised_card_and_esc_closes_only_the_menu(page):
    page.evaluate("(sel) => AnnotateMaximize.open(document.querySelector(sel))", SEL.format("section-2"))
    page.wait_for_selector(SEL.format("section-2") + ".is-maximized")
    page.dblclick(SEL.format("section-2") + " .card-title")
    page.wait_for_selector(".sel-menu", timeout=3000)
    page.wait_for_timeout(150)
    assert _menu_is_on_top(page), "the menu paints under the maximised card"
    page.keyboard.press("Escape")
    assert page.locator(".sel-menu").count() == 0
    assert page.locator(SEL.format("section-2") + ".is-maximized").count() == 1, \
        "Esc closed the menu and un-maximised the card"


def test_a_drag_that_ends_on_a_link_still_opens_the_menu(page, document):
    _put_block(document, "section-1", "See [the spec](https://example.com) for details.")
    page.wait_for_selector(SEL.format("section-1") + " .block-content a", timeout=10000)
    page.wait_for_timeout(300)
    pos = page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s); const t = AnnotateAnchors.textOf(root);
      const i = t.indexOf('See the spec');
      const r = AnnotateAnchors.rangeFrom(root, i, i + 'See the spec'.length);
      getSelection().removeAllRanges(); getSelection().addRange(r);
      const b = s.querySelector('.block-content a').getBoundingClientRect();
      return {x: b.left + b.width / 2, y: b.top + b.height / 2}; }""", SEL.format("section-1"))
    _release(page, pos["x"], pos["y"])
    page.wait_for_selector(".sel-menu", timeout=3000)
    _menu(page, "delete")
    [m] = _round(page).values()
    assert m["selected_text"] == "See the spec"


def test_a_changed_selection_closes_the_stale_menu(page):
    _select(page, "section-1", "long enough")
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFrom(AnnotateAnchors.contentOf(s), 0, 9);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format("section-2"))
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0


def test_a_comment_with_text_in_it_is_not_replaced(page):
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    page.locator(".sel-composer textarea").fill("half a thought")
    _select(page, "section-2", "Paragraph two")
    _menu(page, "comment")
    assert page.locator(".sel-composer").count() == 1
    assert page.locator(".sel-composer textarea").input_value() == "half a thought"
    assert "long enough" in page.inner_text(".sel-composer .sel-quote")
    assert page.eval_on_selector(".sel-composer textarea", "el => el === document.activeElement")
    assert page.locator(".sel-composer.sel-flash").count() == 1


def test_an_empty_comment_box_is_replaced(page):
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    _select(page, "section-2", "Paragraph two")
    _menu(page, "comment")
    assert page.locator(".sel-composer").count() == 1
    assert "Paragraph two" in page.inner_text(".sel-composer .sel-quote")


def test_the_menu_stays_in_the_viewport_for_a_selection_taller_than_it(page, document):
    _put_block(document, "section-1", "\n\n".join(f"Line {i} of a long section." for i in range(40)))
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format('section-1')}').textContent.includes('Line 39')",
        timeout=10000)
    page.set_viewport_size({"width": 1000, "height": 400})
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      s.querySelectorAll('.block-content p')[20].scrollIntoView({block: 'center'});
      const root = AnnotateAnchors.contentOf(s); const t = AnnotateAnchors.textOf(root);
      const r = AnnotateAnchors.rangeFrom(root, 0, t.length);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format("section-1"))
    _release(page, 300, 200)
    page.wait_for_selector(".sel-menu", timeout=3000)
    b = page.eval_on_selector(".sel-menu", "m => { const r = m.getBoundingClientRect(); return {top: r.top, bottom: r.bottom}; }")
    assert 0 <= b["top"] and b["bottom"] <= 400, b


def test_the_refusal_menu_swallows_the_action_keys(page):
    page.click("body", position={"x": 5, "y": 5})
    page.keyboard.press("j")
    page.evaluate("""() => {
      const a = document.querySelectorAll('section.block .block-content p');
      const r = document.createRange(); r.setStart(a[0].firstChild, 0); r.setEnd(a[2].firstChild, 5);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""")
    _release(page)
    page.wait_for_selector(".sel-menu", timeout=3000)
    for k in ("c", "d", "x"):
        page.keyboard.press(k)
    page.wait_for_timeout(200)
    assert page.locator(".comment-card").count() == 0
    assert page.locator("[data-block-mark]").count() == 0


def test_d_does_not_mark_the_focused_block_from_inside_the_header(page):
    page.click("body", position={"x": 5, "y": 5})
    page.keyboard.press("j")
    assert page.evaluate("""() => {
      const b = [...document.querySelectorAll('.page-header button')].find(b => b.offsetParent);
      b.focus(); return document.activeElement === b; }""")
    page.keyboard.press("d")
    page.wait_for_timeout(150)
    assert page.locator("[data-block-mark]").count() == 0


def test_a_triple_click_that_spills_into_the_next_section_is_trimmed(page):
    page.evaluate("""() => {
      const [s1, s2] = document.querySelectorAll('main.prose section.block');
      const ps = s1.querySelectorAll('.block-content p'); const last = ps[ps.length - 1];
      const w = document.createTreeWalker(s2, NodeFilter.SHOW_TEXT); const first = w.nextNode();
      const r = document.createRange(); r.setStart(last.firstChild, 0); r.setEnd(first, 0);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""")
    _release(page)
    page.wait_for_selector(".sel-menu", timeout=3000)
    assert "Select within one section" not in page.inner_text(".sel-menu")
    _menu(page, "delete")
    [m] = _round(page).values()
    assert (m["block_id"], m["selected_text"]) == ("section-1", "Paragraph two of block 1.")


def test_the_menu_keys(page):
    page.click("body", position={"x": 5, "y": 5})
    page.keyboard.press("j")
    focused = page.evaluate("AnnotateKeyboard.focusedId()")
    page.keyboard.press("d")
    assert page.locator(SEL.format(focused) + '[data-block-mark="delete"]').count() == 1
    _select(page, "section-3", "Paragraph one")
    page.keyboard.press("Escape")
    assert page.locator(".sel-menu").count() == 0
    _select(page, "section-3", "Paragraph one")
    page.keyboard.press("c")
    page.wait_for_selector(".sel-composer", timeout=3000)
    page.wait_for_timeout(150)
    assert page.locator(".comment-card").count() == 0


def test_a_mark_saved_by_the_old_sentence_strip_still_counts(page):
    page.evaluate("""() => localStorage.setItem('annotate.round.resp-browser-suite', JSON.stringify({
      'section-1::Paragraph two of block 1.::0': {scope: 'unit', block_id: 'section-1', kind: 'delete',
        selected_text: 'Paragraph two of block 1.', ordinal: 0}}))""")
    page.reload()
    page.wait_for_function("() => CSS.highlights.get('annotate-delete')?.size === 1", timeout=5000)
    [(key, m)] = _round(page).items()
    assert "::__span__::" in key and "ordinal" not in m
    assert m["prefix"] == "" and m["suffix"] == ""


def test_an_old_strip_mark_on_a_soft_wrapped_paragraph_still_paints(page, document):
    """The strip stored a sentence's words with its whitespace collapsed; the
    paragraph's source still has the line break."""
    _put_block(document, "section-2", "Paragraph\nwrapped here.")
    page.evaluate("""() => localStorage.setItem('annotate.round.resp-browser-suite', JSON.stringify({
      'section-2::Paragraph wrapped here.::0': {scope: 'unit', block_id: 'section-2', kind: 'compact',
        selected_text: 'Paragraph wrapped here.', ordinal: 0}}))""")
    page.reload()
    page.wait_for_function("() => CSS.highlights.get('annotate-compact')?.size === 1", timeout=5000)
    [(key, m)] = _round(page).items()
    assert key.startswith("section-2::__span__::") and "ordinal" not in m


def test_a_mark_in_the_last_section_survives_a_reload(page):
    """Pruning waits for the whole document: a mark on the last block is not
    taken for an orphan while the blocks before it are still being drawn."""
    a = _anchor_of(page, "section-4", "Paragraph two")
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')", a)
    for _ in range(3):
        page.reload()
        page.wait_for_function("() => CSS.highlights.get('annotate-delete')?.size === 1",
                               timeout=5000)
        page.wait_for_timeout(300)
        assert [m["block_id"] for m in _round(page).values()] == ["section-4"]


@pytest.mark.parametrize("late", [False, True], ids=["in-order", "blocks-first"])
def test_a_mark_on_a_block_gone_from_the_document_is_pruned_on_load(page, document, late):
    """Pruning does run once the page is drawn. `late` holds subunits.js back
    until the blocks have rendered, so their "annotate:rendered" has gone by
    before the module that listens for it exists."""
    a = _anchor_of(page, "section-4", "Paragraph two")
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')", a)
    _remove_block(document, "section-4")
    if late:
        def hold(route):
            resp = route.fetch()
            time.sleep(1.0)
            route.fulfill(response=resp)
        page.route("**/subunits.js*", hold)
        page.add_init_script("""document.addEventListener('annotate:rendered', () => {
          window.__renderedBeforeSubunits = !window.AnnotateSubunits; }, {once: true});""")
    page.reload()
    page.wait_for_selector(SEL.format("section-3"), timeout=5000)
    page.wait_for_function("() => !!window.AnnotateSubunits", timeout=15000)
    if late:
        assert page.evaluate("() => window.__renderedBeforeSubunits") is True, \
            "the blocks did not render first; this variant tests nothing"
    page.wait_for_function(
        "() => !localStorage.getItem('annotate.round.resp-browser-suite')", timeout=5000)


_PHONE_SELECT_JS = """([sel, needle]) => { const s = document.querySelector(sel);
  const root = AnnotateAnchors.contentOf(s);
  const i = AnnotateAnchors.textOf(root).indexOf(needle);
  const r = AnnotateAnchors.rangeFrom(root, i, i + needle.length);
  getSelection().removeAllRanges(); getSelection().addRange(r); }"""


def test_on_a_phone_the_menu_is_a_bottom_sheet_quoting_the_selection(document):
    with _phone(document) as pg:
        pg.evaluate(_PHONE_SELECT_JS, [SEL.format("section-1"), "long enough"])
        pg.wait_for_selector(".sel-menu.sel-sheet", timeout=8000)
        box = pg.eval_on_selector(".sel-sheet", "e => e.getBoundingClientRect().toJSON()")
        assert abs(box["bottom"] - 800) <= 1 and box["width"] >= 380
        assert "long enough" in pg.inner_text(".sel-sheet .sel-quote")
        sizes = pg.eval_on_selector_all(".sel-sheet button[data-act]",
                                        "bs => bs.map(b => b.getBoundingClientRect().height)")
        assert min(sizes) >= 44, "touch targets under 44px"
        pg.click('.sel-sheet button[data-act="delete"]')
        assert pg.locator(".sel-sheet").count() == 0


def test_on_a_phone_a_selected_title_word_opens_the_whole_section_sheet(document):
    with _phone(document) as pg:
        pg.evaluate("""(sel) => { const t = document.querySelector(sel + ' .card-title');
          const n = t.firstChild; const r = document.createRange();
          r.setStart(n, 0); r.setEnd(n, Math.min(3, n.length));
          getSelection().removeAllRanges(); getSelection().addRange(r); }""",
                    SEL.format("section-1"))
        pg.wait_for_selector(".sel-menu.sel-sheet", timeout=8000)
        pg.wait_for_timeout(700)  # the sheet must outlive the selection it just cleared
        assert pg.locator(".sel-sheet").count() == 1
        assert "Whole section" in pg.inner_text(".sel-sheet .sel-state")
        assert pg.inner_text(".sel-sheet .sel-quote").strip()
        pg.click('.sel-sheet button[data-act="delete"]')
        assert pg.get_attribute(SEL.format("section-1"), "data-block-mark") == "delete"


def test_on_a_phone_the_sheet_sits_at_the_bottom_of_a_maximised_card(document):
    with _phone(document) as pg:
        pg.wait_for_function("() => !!window.AnnotateMaximize", timeout=15000)
        pg.evaluate("(sel) => AnnotateMaximize.open(document.querySelector(sel))", SEL.format("section-1"))
        pg.wait_for_selector(SEL.format("section-1") + ".is-maximized")
        pg.evaluate(_PHONE_SELECT_JS, [SEL.format("section-1"), "long enough"])
        pg.wait_for_selector(".sel-menu.sel-sheet", timeout=8000)
        assert pg.evaluate("() => !!document.querySelector('.is-maximized .sel-sheet')")
        box = pg.eval_on_selector(".sel-sheet", "e => e.getBoundingClientRect().toJSON()")
        assert abs(box["bottom"] - 800) <= 1 and box["width"] >= 380, box
        assert _menu_is_on_top(pg), "the sheet paints under the maximised card"


def _select_title_word(pg, anchor="section-1"):
    pg.evaluate("""(sel) => { const t = document.querySelector(sel + ' .card-title');
      const n = t.firstChild; const r = document.createRange();
      r.setStart(n, 0); r.setEnd(n, Math.min(3, n.length));
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format(anchor))
    pg.wait_for_selector(".sel-menu.sel-sheet", timeout=8000)


def test_on_a_phone_a_sheet_without_a_live_selection_can_be_dismissed(document):
    with _phone(document) as pg:
        _select_title_word(pg)
        pg.wait_for_timeout(600)
        pg.evaluate("""(sel) => document.querySelector(sel + ' .block-content p')
          .dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}))""", SEL.format("section-1"))
        assert pg.locator(".sel-sheet").count() == 0, "a touch outside left the sheet up"
        _select_title_word(pg)
        box = pg.eval_on_selector(".sel-sheet .sel-close", "e => e.getBoundingClientRect().toJSON()")
        assert box["width"] >= 44 and box["height"] >= 44
        assert pg.get_attribute(".sel-sheet .sel-close", "aria-label") == "Close"
        pg.click(".sel-sheet .sel-close")
        assert pg.locator(".sel-sheet").count() == 0
        pg.evaluate("""([a, b]) => { const x = AnnotateAnchors.contentOf(document.querySelector(a));
          const y = AnnotateAnchors.contentOf(document.querySelector(b));
          const r = AnnotateAnchors.rangeFrom(x, 0, 5);
          r.setEnd(AnnotateAnchors.rangeFrom(y, 0, 5).endContainer, 5);
          getSelection().removeAllRanges(); getSelection().addRange(r); }""",
                    [SEL.format("section-1"), SEL.format("section-2")])
        pg.wait_for_selector(".sel-sheet", timeout=8000)
        assert "one section" in pg.inner_text(".sel-sheet")
        pg.click(".sel-sheet .sel-close")
        assert pg.locator(".sel-sheet").count() == 0


def test_on_a_phone_a_press_on_the_sheet_survives_the_selection_collapsing(document):
    with _phone(document) as pg:
        pg.evaluate(_PHONE_SELECT_JS, [SEL.format("section-1"), "long enough"])
        pg.wait_for_selector(".sel-sheet", timeout=8000)
        pg.evaluate("""() => { document.querySelector('.sel-sheet button[data-act="delete"]')
          .dispatchEvent(new PointerEvent('pointerdown', {bubbles: true}));
          getSelection().removeAllRanges(); }""")
        pg.wait_for_timeout(500)
        assert pg.locator(".sel-sheet").count() == 1
        assert pg.eval_on_selector(".sel-sheet", "e => getComputedStyle(e).userSelect") == "none"


def test_on_desktop_the_menu_is_not_a_sheet(page):
    _select(page, "section-1", "long enough")
    assert page.locator(".sel-menu").count() == 1
    assert page.locator(".sel-menu.sel-sheet").count() == 0
    assert page.locator(".sel-menu .sel-close").count() == 0


# ── Final review: the reader's words and marks are never lost or changed ────

_PAINTED = """(kind) => { const h = CSS.highlights.get('annotate-' + kind);
  return h ? [...h].map(r => r.toString()) : []; }"""


def _wait_rendered(page, anchor, needle):
    page.wait_for_function(
        f"() => document.querySelector('{SEL.format(anchor)}').textContent.includes({json.dumps(needle)})",
        timeout=10000)
    page.wait_for_timeout(300)


def _click_mark(page, anchor):
    page.evaluate("() => getSelection().removeAllRanges()")
    pos = page.evaluate("""(sel) => {
      const s = document.querySelector(sel);
      const m = Object.values(JSON.parse(localStorage.getItem('annotate.round.resp-browser-suite')))
        .find(m => m.block_id === s.dataset.blockId && m.selected_text);
      const b = AnnotateAnchors.rangeFor(s, m).getBoundingClientRect();
      return {x: b.left + 4, y: b.top + b.height / 2}; }""", SEL.format(anchor))
    page.mouse.click(pos["x"], pos["y"])
    page.wait_for_selector(".sel-menu", timeout=3000)


def test_a_search_keeps_the_painted_marks(page):
    """Search splits text nodes to wrap its hits; the ranges behind the
    highlights collapsed with them and nothing painted them again."""
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'delete')",
                  _anchor_of(page, "section-1", "long enough"))
    assert page.evaluate(_PAINTED, "delete") == ["long enough"]
    page.fill("#block-search", "enough")
    page.wait_for_selector("mark.search-hit", timeout=3000)
    assert page.evaluate(_PAINTED, "delete") == ["long enough"]
    page.fill("#block-search", "")
    page.wait_for_function("() => !document.querySelector('mark.search-hit')", timeout=3000)
    assert page.evaluate(_PAINTED, "delete") == ["long enough"]


def _open_span_box(page, text):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'compact')",
                  _anchor_of(page, "section-4", "Paragraph two"))
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    page.locator(".sel-composer textarea").fill(text)


def test_a_half_written_span_comment_holds_the_round(page):
    _open_span_box(page, "half a thought")
    assert page.eval_on_selector("#round-submit", "b => b.disabled")
    page.locator(".sel-composer textarea").fill("")
    assert not page.eval_on_selector("#round-submit", "b => b.disabled")
    page.locator(".sel-composer textarea").fill("whole thought")
    page.locator(".sel-composer textarea").press("Enter")
    assert not page.eval_on_selector("#round-submit", "b => b.disabled")


def test_a_rewrite_that_keeps_the_words_keeps_the_open_box(page, document):
    _open_span_box(page, "draft words")
    _put_block(document, "section-1",
               "Paragraph one of block 1, long enough to scroll past.\n\nA new paragraph.",
               title="Block 1")
    _wait_rendered(page, "section-1", "A new paragraph")
    page.wait_for_selector(SEL.format("section-1") + " .sel-composer textarea", timeout=3000)
    assert page.locator(".sel-composer textarea").input_value() == "draft words"
    assert "long enough" in page.inner_text(".sel-composer .sel-quote")


def test_a_rewrite_that_drops_the_words_moves_the_box_to_the_section(page, document):
    _open_span_box(page, "draft words")
    _put_block(document, "section-1", "Entirely new words.", title="Block 1")
    _wait_rendered(page, "section-1", "Entirely new")
    page.wait_for_selector(".comment-card textarea", timeout=3000)
    # The words survive exactly, with what they were about in front of them.
    assert page.locator(".comment-card textarea").input_value() == \
        'On the passage that read "long enough": draft words'
    assert page.locator(".sel-composer").count() == 0


def test_editing_a_span_comment_starts_from_its_words(page):
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    page.locator(".sel-composer textarea").fill("first")
    page.locator(".sel-composer textarea").press("Enter")
    assert page.evaluate("() => document.activeElement?.classList.contains('card-chevron')"
                         " && document.activeElement.closest('section').dataset.blockId") == "section-1"
    _click_mark(page, "section-1")
    _menu(page, "comment")
    ta = page.locator(".sel-composer textarea")
    assert ta.input_value() == "first"
    assert page.eval_on_selector(".sel-composer textarea",
                                 "t => t === document.activeElement && t.selectionStart === t.value.length")
    page.locator(".sel-composer .sel-cancel").click()
    assert page.evaluate("() => document.activeElement?.classList.contains('card-chevron')")
    [m] = _round(page).values()
    assert m["text"] == "first"


def test_a_keyboard_selection_opens_the_menu_and_the_menu_is_keyboard_driven(page):
    # No click first: its mouseup's deferred handler can land after the keys
    # in a throttled headless page and reopen the menu out from under them.
    page.keyboard.press("j")
    focused = page.evaluate("AnnotateKeyboard.focusedId()")
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const root = AnnotateAnchors.contentOf(s);
      const r = AnnotateAnchors.rangeFrom(root, 0, 9);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format(focused))
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_selector(".sel-menu", timeout=3000)
    first = page.evaluate("() => document.activeElement.dataset.act")
    assert page.evaluate("() => !!document.activeElement.closest('.sel-menu')")
    assert first == "comment"
    page.keyboard.press("ArrowRight")
    assert page.evaluate("() => document.activeElement.dataset.act") == "delete"
    page.keyboard.press("ArrowLeft")
    assert page.evaluate("() => document.activeElement.dataset.act") == "comment"
    page.keyboard.press("Escape")
    assert page.locator(".sel-menu").count() == 0
    assert page.evaluate("() => !document.activeElement.closest('.sel-menu')")
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_selector(".sel-menu", timeout=3000)
    words = page.evaluate("() => getSelection().toString().trim()")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("Enter")
    [m] = _round(page).values()
    assert m["kind"] == "delete" and m["block_id"] == focused
    assert m["selected_text"] == words


def test_select_all_selects_the_page(page):
    page.click(SEL.format("section-2") + " .block-content p")
    # Let the click's deferred mouseup handler run first: it is the click's,
    # and in a throttled headless page it can otherwise land after the keys.
    page.wait_for_function("() => new Promise(r => setTimeout(() => r(true), 0))")
    assert page.locator(".sel-menu").count() == 0
    page.keyboard.press("ControlOrMeta+a")
    page.wait_for_timeout(200)
    text = page.evaluate("() => getSelection().toString()")
    assert "block 1" in text and "block 4" in text
    assert page.locator(".sel-menu").count() == 0


def test_no_keyboard_menu_from_a_text_field(page):
    page.click("#block-search")
    page.keyboard.type("abc")
    page.keyboard.press("Shift+ArrowLeft")
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0


def test_the_dark_round_submit_is_readable(page):
    page.evaluate("a => AnnotateSubunits.setSpanMark(a, 'compact')",
                  _anchor_of(page, "section-1", "long enough"))
    _load_in_theme(page, "dark")
    page.wait_for_selector("#round-submit")
    c = page.eval_on_selector("#round-submit", "b => [getComputedStyle(b).color, getComputedStyle(b).backgroundColor]")
    shot = os.environ.get("ANNOTATE_DARK_SUBMIT_SHOT")
    if shot:
        page.locator("#round-dock").screenshot(path=shot)
    assert c[0] != c[1], c


def test_reselecting_marked_words_says_marked_and_can_remove(page):
    _select(page, "section-1", "long enough")
    _menu(page, "delete")
    _select(page, "section-1", "long enough")
    text = page.inner_text(".sel-menu")
    assert "Marked delete" in text and "Replaces" not in text
    _menu(page, "remove")
    assert _round(page) == {}


def test_replacing_a_comment_says_it_is_yours(page):
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    page.locator(".sel-composer textarea").fill("mine")
    page.locator(".sel-composer textarea").press("Enter")
    _select(page, "section-1", "enough to scroll")
    assert "Replaces your comment" in page.inner_text(".sel-menu")


def test_a_picture_block_is_not_selectable_in_its_body(page):
    page.evaluate("() => document.querySelector('section.block[data-block-id=\"section-2\"]').dataset.kind = 'sequence'")
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFrom(AnnotateAnchors.contentOf(s), 0, 9);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format("section-2"))
    _release(page)
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0


def test_a_comment_chip_can_be_removed(page):
    _select(page, "section-1", "long enough")
    _menu(page, "comment")
    page.locator(".sel-composer textarea").fill("gone soon")
    page.locator(".sel-composer textarea").press("Enter")
    page.click('.sel-chip button[aria-label="Remove comment"]')
    assert _round(page) == {}
    assert page.locator(".sel-chip").count() == 0


def test_tab_leaves_the_keyboard_menu(page):
    page.keyboard.press("j")
    focused = page.evaluate("AnnotateKeyboard.focusedId()")
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFrom(AnnotateAnchors.contentOf(s), 0, 9);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format(focused))
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_selector(".sel-menu", timeout=3000)
    assert page.eval_on_selector_all(".sel-menu button", "bs => bs.map(b => b.tabIndex)") == [0, -1, -1, -1, -1, -1]
    page.keyboard.press("Tab")
    assert page.locator(".sel-menu").count() == 0
    assert page.evaluate("() => !document.activeElement.closest('.sel-menu')")


def _keyboard_select(page):
    page.keyboard.press("j")
    focused = page.evaluate("AnnotateKeyboard.focusedId()")
    page.evaluate("""(sel) => { const s = document.querySelector(sel);
      const r = AnnotateAnchors.rangeFrom(AnnotateAnchors.contentOf(s), 0, 9);
      getSelection().removeAllRanges(); getSelection().addRange(r); }""", SEL.format(focused))
    return focused


def test_shift_tab_leaves_the_keyboard_menu(page):
    _keyboard_select(page)
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_selector(".sel-menu", timeout=3000)
    assert page.evaluate("() => !!document.activeElement.closest('.sel-menu')")
    page.keyboard.press("Shift+Tab")
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0
    assert page.evaluate("() => !document.activeElement.closest('.sel-menu')")


def test_a_shift_press_alone_does_not_reopen_the_menu(page):
    _keyboard_select(page)
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_selector(".sel-menu", timeout=3000)
    page.keyboard.press("Escape")
    assert page.locator(".sel-menu").count() == 0
    page.keyboard.press("Shift")
    page.wait_for_timeout(200)
    assert page.locator(".sel-menu").count() == 0
