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


def _put_progress(document, steps, state="working", started=None, ended=None):
    """Write the trail the way skills/annotate/progress.py does."""
    started = started or int(time.time())
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__progress__", {
        "id": "__progress__", "kind": "progress", "state": state,
        "started_at": started, "ended_at": ended, "event_id": "evt-browser",
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


@pytest.fixture
def page(document):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        try:
            pg.goto(document["url"])
            pg.wait_for_selector("section.block", timeout=15000)
            pg.wait_for_function("() => !!window.AnnotateSubunits", timeout=15000)
            pg.__dict__["js_errors"] = errors
            yield pg
        finally:
            browser.close()


def test_the_comment_icon_opens_a_comment(page):
    """The one that got out. Every source-level check passed while this failed."""
    page.hover("section.block:first-of-type .card-head")
    page.click('section.block:first-of-type .hover-actions button[data-type="comment"]')
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
    page.hover("section.block:first-of-type .card-head")
    page.click('section.block:first-of-type .hover-actions button[data-type="comment"]')
    page.wait_for_selector(".comment-card textarea")
    page.fill(".comment-card textarea", "holding this open")

    page.hover("section.block:nth-of-type(3) .card-head")
    page.click('section.block:nth-of-type(3) .hover-actions button[data-type="comment"]')
    page.wait_for_selector(".comment-card.is-calling", timeout=3000)
    assert page.locator(".comment-card").count() == 1, "a second editor opened"


def test_the_keyboard_walks_the_document(page):
    page.keyboard.press("j")
    page.wait_for_selector("section.block[data-kb-focus]")
    first = page.get_attribute("section.block[data-kb-focus]", "data-block-id")
    page.keyboard.press("j")
    second = page.get_attribute("section.block[data-kb-focus]", "data-block-id")
    assert first != second, "j did not move the cursor"

    # The cursor must reveal that block's controls — the whole non-hover path.
    # Waited for, not sampled: the strip has `transition: opacity 140ms`, so
    # reading the computed value on the tick after the keypress catches it
    # part-way and fails on a page that is behaving perfectly.
    page.wait_for_function(
        "() => { const el = document.querySelector("
        "'section.block[data-kb-focus] .hover-actions'); if (!el) return false;"
        " const cs = getComputedStyle(el);"
        " return cs.opacity === '1' && cs.pointerEvents === 'auto'; }", timeout=3000)

    page.keyboard.press("c")
    page.wait_for_selector(".comment-card", timeout=5000)
    owner = page.eval_on_selector(
        ".comment-card", "el => el.closest('.inline-comments')"
        ".previousElementSibling.dataset.blockId")
    assert owner == second, "c commented on the wrong block"


def test_the_settings_panel_paints_and_persists(page):
    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click('[data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'",
        timeout=3000)
    page.click('[data-setting="prosefont"] [data-value="serif"]')
    page.click('[data-setting="textsize"] [data-value="large"]')
    page.wait_for_function(
        "() => document.body.dataset.proseFont === 'serif' "
        "&& document.body.dataset.textSize === 'large'", timeout=3000)

    family = page.eval_on_selector(
        "main.prose p", "el => getComputedStyle(el).fontFamily")
    assert "Source Serif" in family, f"the choice did not reach the prose: {family}"

    page.reload()
    page.wait_for_selector("section.block")
    assert page.evaluate("() => document.body.dataset.proseFont") == "serif", \
        "a reader preference did not survive a reload"

    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click('[data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'",
        timeout=3000)
    page.click("#settings-reset")
    page.wait_for_function(
        "() => document.body.dataset.proseFont === 'bricolage' "
        "&& document.body.dataset.textSize === 'medium'", timeout=3000)


def test_code_panes_scroll_rather_than_wrap(page):
    """No code pane in this fixture, so assert the rule the panes depend on."""
    wraps = page.evaluate(
        "() => { const s = [...document.styleSheets].flatMap(x => { try { return [...x.cssRules]; }"
        " catch (_) { return []; } });"
        " const r = s.find(r => r.selectorText === '.cp-line');"
        " return r && r.style.whiteSpace; }")
    assert wraps == "pre", f".cp-line is {wraps!r}, so long lines fold again"


def test_the_width_stops_measure_what_they_claim(page):
    """The stop NAMES were reused, so only a measurement can tell them apart.

    "normal" is the column that used to be called "wide" (1180px) and "wide"
    is the one that used to be "extra" (1600px). Every source-level check
    here would pass just as happily with the two rules swapped.
    """
    measure = ("() => [document.body.dataset.width, getComputedStyle(document.body)"
               ".getPropertyValue('--content-max').trim()]")
    assert page.evaluate(measure) == ["normal", "1180px"]

    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click('[data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'",
        timeout=3000)
    rows = page.eval_on_selector_all('[data-setting="pagewidth"] [data-value]',
                                     "els => els.map(e => e.dataset.value)")
    assert rows == ["normal", "wide"], f"the panel offers {rows}"
    page.click('[data-setting="pagewidth"] [data-value="wide"]')
    assert page.evaluate(measure) == ["wide", "1600px"]


def test_a_width_chosen_before_the_rename_still_means_its_own_column(page):
    """A stored "wide" meant 1180px before the rename and 1600px after it.

    Read under the new key it would move a reader who chose the narrower
    column to the widest one — which is why the choice moved keys. Reset has
    to clear the old key too, or it falls straight back through it.
    """
    rid = "resp-browser-suite"
    for legacy, expected in (("extra", "wide"), ("wide", "normal"),
                             ("narrow", "normal"), ("normal", "normal")):
        page.evaluate(
            "([rid, v]) => { localStorage.removeItem(`annotate.view:${rid}:pagewidth`);"
            " localStorage.setItem(`annotate.view:${rid}:width`, v); }", [rid, legacy])
        page.reload()
        page.wait_for_selector("section.block")
        assert page.evaluate("() => document.body.dataset.width") == expected, \
            f"a stored {legacy!r} no longer opens on {expected!r}"

    page.click("#menu-toggle")
    page.wait_for_selector("#menu-pop:not([hidden])")
    page.click('[data-pane-to="settings"]')
    page.wait_for_function(
        "() => document.getElementById('menu-pop').dataset.pane === 'settings'",
        timeout=3000)
    page.click("#settings-reset")
    page.wait_for_function("() => document.body.dataset.width === 'normal'", timeout=3000)


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


def test_the_page_raises_nothing(page):
    page.wait_for_timeout(2500)          # a few poll ticks
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
    # land rather than sampling mid-flight, exactly as the j/k cursor test
    # waits out the hover-actions opacity transition above.
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
      return { label: g(b.querySelector('.menu-item-label'), 'color'),
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
    assert got["label"] == "Exit full screen", (
        "the row announces %r and still reads %r" % (got["aria"], got["label"]))
    assert got["icon"], "the label write ate the row's icon"


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

    _put_progress(document, ["Read montblanc/pricing/Normalizer.java"])

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
    page.evaluate("""() => {
      const n = document.querySelector('#progress-panel .pg-now');
      n.__node = n.firstChild;
    }""")
    _put_progress(document, ["Read your round of feedback", "Reading the importer"])
    page.wait_for_timeout(500)
    same = page.evaluate("""() => {
      const n = document.querySelector('#progress-panel .pg-now');
      return n.__node === n.firstChild;
    }""")
    assert same, "an unchanged current line was rewritten, which re-announces it"
