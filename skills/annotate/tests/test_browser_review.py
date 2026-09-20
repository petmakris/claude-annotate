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
import urllib.error
import urllib.request
from pathlib import Path

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


def test_the_progress_counter_follows_the_marks(page):
    assert page.text_content("#review-progress").strip() == f"0/{len(BLOCKS)}"
    page.eval_on_selector(
        "section.block:first-of-type",
        "el => window.AnnotateSubunits.toggleBlockMark(el.dataset.blockId, 'keep')")
    page.wait_for_function(
        f"() => document.getElementById('review-progress').textContent.trim() === '1/{len(BLOCKS)}'",
        timeout=5000)
    assert page.get_attribute("section.block:first-of-type", "data-review-state") == "touched"


def test_the_settings_panel_paints_and_persists(page):
    page.click("#settings-toggle")
    page.wait_for_selector("#settings-pop:not([hidden])")
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

    page.click("#settings-toggle")
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


def test_the_page_raises_nothing(page):
    page.wait_for_timeout(2500)          # a few poll ticks
    assert page.__dict__["js_errors"] == [], page.__dict__["js_errors"]
