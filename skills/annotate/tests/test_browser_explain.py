"""The `explain` pane, measured in a real browser.

Every source-level check on this kind can pass while the underline sits three
characters left of the span it is measuring, because nothing in a string
comparison knows how wide a `ch` is. The whole premise of the kind is that a
label points at exactly the code it is about, so that alignment is the thing
worth driving a browser for.

The span rect is taken from a DOM Range over the rendered characters, NOT
recomputed from col/len — a test that re-derives the renderer's own formula
agrees with it whatever either of them does.

Same shape as test_browser_review.py: skips without playwright, skips without
a daemon, makes its own session and deletes it.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

from skills.annotate.explain import compile_spec  # noqa: E402
from skills.annotate.render import render_block  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
CONFIG = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))

CODE = (
    "private Amount adjustMarketValue(BigDecimal quantity, BigDecimal lotSize) {\n"
    "    return ofNullable(this.priceInReferenceCurrency)\n"
    "        .map(p -> p.multiply(quantity.multiply(lotSize)))\n"
    "        .orElse(null);\n"
    "}\n"
)

LADDER = {
    "id": "section-1", "kind": "explain", "title": "Ladder",
    "spec": {
        "project": "portfolios", "file": "ValuedPosition.java", "line": 261,
        "lang": "java", "code": CODE,
        "notes": [
            {"line": 2, "span": "ofNullable", "label": "**empty ⇒ unpriced** — it leaves the sum."},
            {"line": 2, "span": "priceInReferenceCurrency",
             # The backticks are load-bearing: an inline identifier is what
             # the page's own `main.prose code` rule tries to paint a chip on.
             "label": "**reference currency** — already FX-converted by `toReference`; CHF here."},
        ],
    },
}

BADGES = {
    "id": "section-2", "kind": "explain", "title": "Badges",
    "spec": {
        "file": "ValuedPosition.java", "lang": "java", "code": CODE,
        "notes": [
            {"line": 2, "span": "return", "label": "**one** a"},
            {"line": 2, "span": "ofNullable", "label": "**two** b"},
            {"line": 2, "span": "priceInReferenceCurrency", "label": "**three** c"},
        ],
    },
}

RANGE = {
    "id": "section-3", "kind": "explain", "title": "Range",
    "spec": {
        "file": "ValuedPosition.java", "lang": "java", "code": CODE,
        "notes": [{"lines": [2, 4], "label": "**one computation, three lines**"}],
    },
}

ORDER = [LADDER["id"], BADGES["id"], RANGE["id"]]


def _daemon_url():
    if not CONFIG.is_file():
        pytest.skip("no webcompanion daemon configured on this machine")
    url = f"http://127.0.0.1:{json.loads(CONFIG.read_text())['port']}"
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


@pytest.fixture(scope="module")
def page():
    base = _daemon_url()
    s = _call(base, "POST", "/api/sessions",
              {"kind": "annotate", "cwd": str(REPO), "title": "explain browser suite"})
    sid = s["sid"]
    try:
        _call(base, "POST", f"/s/{sid}/api/assets",
              {"static_root": str(STATIC), "entry": "entry.js"})
        _call(base, "PUT", f"/s/{sid}/items/__doc__",
              {"response_id": "resp-explain-suite", "title": "explain browser suite",
               "order": ORDER, "cwd": str(REPO), "glossary": []})
        for blk in (LADDER, BADGES, RANGE):
            # Through the real push renderer, so the test exercises the same
            # compile step a push does rather than a hand-built body.
            _call(base, "PUT", f"/s/{sid}/items/{blk['id']}", render_block(blk))
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            pg = browser.new_page(viewport={"width": 1400, "height": 1000})
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            try:
                pg.goto(f"{base}/s/{sid}/")
                pg.wait_for_selector(".codepane.ex .ex-uline", timeout=15000)
                pg.__dict__["js_errors"] = errors
                yield pg
            finally:
                browser.close()
    finally:
        _call(base, "POST", f"/s/{sid}/api/finish")
        try:
            _call(base, "DELETE", f"/s/{sid}/?force=1")
        except Exception as e:                       # noqa: BLE001
            import warnings
            warnings.warn(f"explain browser suite leaked session {sid}: {e}")


# Measures the rendered characters [col, col+len) of a row with a DOM Range
# and hands back both rects, so the assertion compares the underline against
# the glyphs rather than against the arithmetic that placed it.
SPAN_VS_UNDERLINE = """
([blockId, rowIdx, markIdx, col, len]) => {
  const pane = document.querySelector(`[data-block-id="${blockId}"] .codepane.ex`);
  const row = pane.querySelectorAll('.ex-row')[rowIdx];
  const line = row.querySelector('.cp-line');
  const walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
  const nodes = []; let n;
  while ((n = walker.nextNode())) nodes.push(n);
  const locate = (off) => {
    let acc = 0;
    for (const node of nodes) {
      const l = node.nodeValue.length;
      if (off <= acc + l) return [node, off - acc];
      acc += l;
    }
    const last = nodes[nodes.length - 1];
    return [last, last.nodeValue.length];
  };
  const r = document.createRange();
  const [sn, so] = locate(col);
  const [en, eo] = locate(col + len);
  r.setStart(sn, so); r.setEnd(en, eo);
  const s = r.getBoundingClientRect();
  const u = row.querySelectorAll('.ex-uline')[markIdx].getBoundingClientRect();
  const rowRect = row.getBoundingClientRect();
  return {sl: s.left, sr: s.right, ul: u.left, ur: u.right,
          ub: u.bottom, rb: rowRect.bottom, text: r.toString()};
}
"""


def test_no_js_errors(page):
    assert page.js_errors == [], page.js_errors


@pytest.mark.parametrize("mark_idx", [0, 1])
def test_every_underline_sits_on_the_characters_it_measures(page, mark_idx):
    view = compile_spec(LADDER["spec"])
    mark = view["groups"][0]["marks"][mark_idx]
    m = page.evaluate(SPAN_VS_UNDERLINE,
                      ["section-1", 1, mark_idx, mark["col"], mark["len"]])

    # The Range really covers the quoted span — if this drifts, the rest of
    # the assertion is comparing the underline against the wrong characters.
    expected = ["ofNullable", "priceInReferenceCurrency"][mark_idx]
    assert m["text"] == expected, m

    assert abs(m["sl"] - m["ul"]) <= 0.4, (
        f"underline starts {m['ul'] - m['sl']:.2f}px off its span: {m}")
    assert abs(m["sr"] - m["ur"]) <= 0.4, (
        f"underline ends {m['ur'] - m['sr']:.2f}px off its span: {m}")
    # And under the glyphs, not through them or in the next row.
    assert 0 < m["rb"] - m["ub"] < 6, f"underline is not sitting under its row: {m}"


def test_two_marks_render_a_ladder_and_three_render_badges(page):
    # The switch is made in explain.py from the note count; this is the end of
    # that wire, in the DOM.
    lad = page.locator('[data-block-id="section-1"] .ex-lad-row')
    assert lad.count() == 2
    assert page.locator('[data-block-id="section-1"] .ex-notes').count() == 0

    assert page.locator('[data-block-id="section-2"] .ex-lad-row').count() == 0
    assert page.locator('[data-block-id="section-2"] .ex-note').count() == 3
    # Underlines survive the switch: position is still stated on the line.
    assert page.locator('[data-block-id="section-2"] .ex-uline').count() == 3


def test_the_ladder_elbow_starts_at_its_own_span_column(page):
    # The stem's -1px margin is what keeps gaps expressible in whole `ch`.
    # If it ever starts consuming width, this drifts one pixel per stem.
    view = compile_spec(LADDER["spec"])
    for i, mark in enumerate(view["groups"][0]["marks"]):
        # Labels are emitted rightmost-first, so row 0 is the LAST mark.
        row_idx = len(view["groups"][0]["marks"]) - 1 - i
        got = page.evaluate(
            """([rowIdx, col, len]) => {
              const pane = document.querySelector('[data-block-id="section-1"] .codepane.ex');
              const elbow = pane.querySelectorAll('.ex-lad-row')[rowIdx]
                                .querySelector('.ex-elbow');
              const u = pane.querySelectorAll('.ex-uline')[%d].getBoundingClientRect();
              return {e: elbow.getBoundingClientRect().left, u: u.left};
            }""" % i,
            [row_idx, mark["col"], mark["len"]])
        assert abs(got["e"] - got["u"]) <= 1.5, (
            f"elbow for mark {i} is {got['e'] - got['u']:.2f}px off its underline")


def test_a_range_bracket_spans_exactly_its_rows(page):
    got = page.evaluate("""() => {
      const pane = document.querySelector('[data-block-id="section-3"] .codepane.ex');
      const rows = pane.querySelectorAll('.ex-range-code .ex-row');
      const brk = pane.querySelector('.ex-brk').getBoundingClientRect();
      return {n: rows.length,
              top: rows[0].getBoundingClientRect().top,
              bottom: rows[rows.length - 1].getBoundingClientRect().bottom,
              bt: brk.top, bb: brk.bottom};
    }""")
    assert got["n"] == 3, f"the range should hold lines 2-4, got {got['n']} rows"
    assert abs(got["bt"] - got["top"]) <= 3, got
    assert abs(got["bb"] - got["bottom"]) <= 3, got


def _rel_lum(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _rel_lum(a), _rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _rgb(css):
    return tuple(int(n) for n in css[css.index("(") + 1:css.index(")")].split(",")[:3])


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _hue(rgb):
    """CIELAB hue angle, which is what 'a different colour from the syntax'
    actually means — sRGB distance says a dark brown and a mid orange are
    far apart when they are the same colour at two brightnesses."""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(v) for v in rgb)
    X = (r*.4124 + g*.3576 + b*.1805) / .95047
    Y = r*.2126 + g*.7152 + b*.0722
    Z = (r*.0193 + g*.1192 + b*.9505) / 1.08883
    f = lambda t: t ** (1/3) if t > 0.008856 else 7.787*t + 16/116
    fx, fy, fz = f(X), f(Y), f(Z)
    return math.degrees(math.atan2(200*(fy-fz), 500*(fx-fy))) % 360


@pytest.mark.parametrize("theme", ["daylight", "midnight", "parchment", "contrast"])
def test_the_label_is_ink_on_the_code_in_every_pane_theme(page, theme):
    """There is no card, so the ink alone has to do three things at once.

    It has to be legible on the code's own ground, it has to sit in the one
    arc of the wheel the syntax leaves free (70° of warm gold around 91°),
    and it must not drift toward the number token, which is the nearest
    thing to it in that arc. All three are properties of rendered pixels in
    a particular theme, so a fifth theme added later gets them wrong
    silently unless something measures — which is this.
    """
    page.evaluate("t => { if (t === 'daylight') delete document.body.dataset.paneTheme;"
                  "       else document.body.dataset.paneTheme = t; }", theme)
    got = page.evaluate("""() => {
      const pane = document.querySelector('[data-block-id="section-1"] .codepane.ex');
      const lbl = pane.querySelector('.ex-lbl');
      // Read the number token off the THEME rather than hunting for a node
      // that happens to carry it: the first version of this grabbed an
      // .hljs-params span, which parchment paints in its accent blue, and
      // compared the ink against the wrong colour entirely.
      const ps = getComputedStyle(pane);
      return {ground: ps.backgroundColor,
              bg: getComputedStyle(lbl).backgroundColor,
              fg: getComputedStyle(lbl).color,
              strong: getComputedStyle(lbl.querySelector('b')).color,
              rail: getComputedStyle(pane.querySelector('.ex-uline')).backgroundColor,
              codeText: getComputedStyle(pane.querySelector('.cp-line')).color,
              number: ps.getPropertyValue('--cp-number').trim() || null};
    }""")
    ground = _rgb(got["ground"])

    # No card: whatever is behind the label is the code's own ground.
    assert got["bg"] in ("rgba(0, 0, 0, 0)", "transparent") or _rgb(got["bg"]) == ground, \
        f"{theme}: the label grew a background again — {got}"

    assert _contrast(_rgb(got["fg"]), ground) >= 7.0, f"{theme}: body ink — {got}"
    assert _contrast(_rgb(got["strong"]), ground) >= 4.5, f"{theme}: lead-in ink — {got}"
    assert _contrast(_rgb(got["rail"]), ground) >= 3.0, f"{theme}: rail — {got}"

    # The chromatic parts sit in the free arc; the BODY deliberately does
    # not, because a whole paragraph of that gold reads as a sixth syntax
    # colour. It is a warm grey — near-neutral, and that is the assertion.
    for part in ("strong", "rail"):
        h = _hue(_rgb(got[part]))
        assert 70 <= h <= 110, f"{theme}: {part} left the free warm arc at {h:.0f}° — {got}"
    body = _rgb(got["fg"])
    assert 2 <= max(body) - min(body) <= 26, (
        f"{theme}: body ink should be a WARM GREY — neutral enough not to be a "
        f"token, warm enough to belong to the lead-in — got {got['fg']}")
    # "Recedes" is relative to the CODE TEXT it sits beside, which is the
    # only thing it competes with for attention.
    assert _contrast(body, ground) < _contrast(_rgb(got["codeText"]), ground), (
        f"{theme}: the body ink is not quieter than the code beside it — {got}")

    # And the lead-in still keeps its distance from the number token, which
    # is the nearest thing to it on the wheel.
    if got["number"]:
        d = abs(_hue(_hex(got["number"])) - _hue(_rgb(got["strong"])))
        assert min(d, 360 - d) >= 20, (
            f"{theme}: the lead-in has drifted onto the number token — {got}")


def test_an_identifier_in_a_label_is_not_a_filled_chip(page):
    """`main.prose :not(pre) > code` (0,2,2) paints every inline code span
    with --surface. A bare `.ex-lbl code` is (0,1,1) and loses to it, so the
    chips rendered as pale boxes on the code ground — a miniature of the
    card this kind exists without. Only a computed style can see which rule
    won; the source looks correct either way."""
    page.evaluate("() => { delete document.body.dataset.paneTheme; }")
    bg = page.evaluate("""() => {
      const c = document.querySelector('[data-block-id="section-1"] .ex-lbl code');
      return c ? getComputedStyle(c).backgroundColor : null;
    }""")
    if bg is None:
        pytest.skip("no inline code in this fixture's labels")
    assert bg in ("rgba(0, 0, 0, 0)", "transparent"), \
        f"the page's inline-code rule is painting a chip behind it: {bg}"


def test_the_pane_never_grows_a_second_code_column(page):
    # `explain` carries its own snippet; the side column would restate the
    # very split this kind exists to delete. render.py drops the anchor.
    for bid in ORDER:
        assert page.locator(f'[data-block-id="{bid}"] .code-col').count() == 0


def test_labels_are_emitted_rightmost_first(page):
    # The compiler stacking order: the label for the RIGHTMOST span is closest
    # to the line, so the stems of the ones left of it have somewhere to run.
    got = page.locator('[data-block-id="section-1"] .ex-lbl b').all_inner_texts()
    assert got == ["reference currency", "empty ⇒ unpriced"], got


def test_label_markdown_is_rendered_and_nothing_else_is(page):
    # The restricted subset is rendered server-side; anything else is text.
    assert page.locator('[data-block-id="section-1"] .ex-lbl b').count() == 2
    assert "empty ⇒ unpriced — it leaves the sum." in page.locator(
        '[data-block-id="section-1"] .ex-lbl').nth(1).inner_text()
