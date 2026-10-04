"""Code is coloured after the page paints, in place, in a real browser.

The page used to wait for the highlighter — 3.2 MB of Shiki, every grammar
inlined — before it rendered a single block, so a document with no code in
it at all still paid for 40 grammars before the reader saw its first word.
Now the blocks render first, code shows plain, and each piece is coloured
where it stands once the engine and its grammar arrive: same section, same
rows, nothing rebuilt under the reader.

Runs against the worker's private webcompanion daemon and Chromium (skills/conftest.py).
It creates its own session, serves the page from THIS checkout, and deletes
the session afterwards.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from skills.tests.harness import T, require_playwright  # noqa: E402

require_playwright()


REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"

# Looked up rather than written down, so editing render.py cannot leave the
# anchor too far from its snippet to resolve.
RENDER_BLOCK_LINE = (Path(__file__).resolve().parents[1] / "render.py").read_text(
    encoding="utf-8").splitlines().index("def render_block(blk: dict) -> dict:") + 1

import sys  # noqa: E402

sys.path.insert(0, str(REPO))
from skills.annotate.render import render_block  # noqa: E402

CODE = ("private Amount adjust(BigDecimal quantity) {\n"
        "    return ofNullable(this.price).map(p -> p.multiply(quantity)).orElse(null);\n"
        "}\n")
BLOCKS = [
    {"id": "section-1", "kind": "markdown", "title": "Fence",
     "markdown": "A fence:\n\n```python\ndef load(sid: str) -> dict:\n    return get(sid)\n```\n"},
    {"id": "section-2", "kind": "markdown", "title": "Anchored", "markdown": "The entry point.",
     "code": [{"file": "skills/annotate/render.py", "line": RENDER_BLOCK_LINE,
               "snippet": "def render_block(blk: dict) -> dict:"}]},
    {"id": "section-3", "kind": "explain", "title": "Explain",
     "spec": {"file": "ValuedPosition.java", "lang": "java", "code": CODE,
              "notes": [{"line": 2, "span": "ofNullable", "label": "**empty** is unpriced"}]}},
    {"id": "section-4", "kind": "markdown", "title": "Prose", "markdown": "No code here."},
]

# Every section, as it first appears, is tagged; the tag must still be on it
# once its code is coloured. And whether the highlighter had loaded when the
# first block appeared.
INIT = """
window.__firstBlockSawShiki = null;
new MutationObserver(() => {
  for (const s of document.querySelectorAll('section.block')) {
    if (window.__firstBlockSawShiki === null) window.__firstBlockSawShiki = !!window.Shiki;
    if (!s.__tag) s.__tag = s.dataset.blockId;
  }
}).observe(document, {subtree: true, childList: true});
"""


def _call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


@pytest.fixture
def page(wc_daemon, browser_session):
    base = wc_daemon.base
    s = _call(base, "POST", "/api/sessions",
              {"kind": "annotate", "cwd": str(REPO), "title": "code colour"})
    sid = s["sid"]
    try:
        _call(base, "POST", f"/s/{sid}/api/assets",
              {"static_root": str(STATIC), "entry": "entry.js"})
        items = {"__doc__": {"response_id": "resp-colour", "title": "code colour",
                             "order": [b["id"] for b in BLOCKS], "cwd": str(REPO), "glossary": []}}
        items.update({b["id"]: render_block(b) for b in BLOCKS})
        _call(base, "PATCH", f"/s/{sid}/items?kind=annotate", {"items": items, "replace": True})
        pg = browser_session.new_page(viewport={"width": 1400, "height": 1000})
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(INIT)
        pg.goto(f"{base}/s/{sid}/")
        pg.wait_for_function(f"document.querySelectorAll('section.block').length === {len(BLOCKS)}",
                             timeout=T(30000))
        pg.__dict__.update(errors=errors, base=base, sid=sid)
        yield pg
        pg.context.close()
    finally:
        try:
            _call(base, "POST", f"/s/{sid}/api/finish")
            _call(base, "DELETE", f"/s/{sid}/?force=1")
        except Exception:  # noqa: BLE001 — cleanup is best effort
            pass


COLOURED = """() => ({
  fence: document.querySelectorAll('[data-block-id="section-1"] pre code.sk-fence span[style]').length,
  pane: document.querySelectorAll('[data-block-id="section-2"] .codepane .cp-line .sk').length,
  explain: document.querySelectorAll('[data-block-id="section-3"] .codepane.ex .cp-line .sk').length,
  plain: document.querySelectorAll('code.sk-fence[data-plain]').length,
})"""


def _wait_coloured(page):
    # CodePaint.pending() is the page's own word that nothing is left to colour.
    page.wait_for_function("window.CodePaint && !CodePaint.pending()", timeout=T(20000))
    got = page.evaluate(COLOURED)
    assert got["fence"] and got["pane"] and got["explain"], f"not pending, yet plain: {got}"


def test_the_blocks_render_before_the_highlighter_has_loaded(page):
    assert page.evaluate("window.__firstBlockSawShiki") is False, (
        "the first block appeared after Shiki had loaded: the page waited for the highlighter")


def test_every_code_surface_is_coloured_once_it_loads(page):
    _wait_coloured(page)
    got = page.evaluate(COLOURED)
    assert got["plain"] == 0, got
    assert not page.errors, page.errors


def test_colouring_keeps_the_sections_and_their_marks(page):
    _wait_coloured(page)
    kept = page.evaluate("""() => [...document.querySelectorAll('section.block')]
        .map((s) => s.__tag === s.dataset.blockId)""")
    assert all(kept), f"a section was rebuilt to colour its code: {kept}"
    # The explain pane's underline sits beside the line it marks, not in it,
    # so colouring the line leaves it in place.
    assert page.evaluate("""() => !!document.querySelector(
        '[data-block-id="section-3"] .ex-row .ex-uline')""")


def test_a_rewrite_in_a_new_language_lands_coloured(page):
    _wait_coloured(page)
    _call(page.base, "PATCH", f"/s/{page.sid}/items?kind=annotate", {"items": {
        "section-4": render_block({"id": "section-4", "kind": "markdown", "title": "Prose",
                                   "markdown": "Now with Rust:\n\n```rust\nfn main() { let x = 1; }\n```\n"})}})
    page.wait_for_function("""() => document.querySelectorAll(
        '[data-block-id="section-4"] pre code.sk-fence span[style]').length > 1""", timeout=T(20000))
    assert page.evaluate("document.querySelectorAll('code.sk-fence[data-plain]').length") == 0
