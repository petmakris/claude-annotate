# skills/annotate/tests/test_browser_anchors.py
"""AnnotateAnchors in a bare page: no daemon, no annotate shell. The module
is pure DOM + text, so it is tested against the smallest page that has the
shape it reads (section.block > .block-content)."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"

PAGE = """<!doctype html><main class="prose">
<section class="block" data-block-id="b1"><div class="card-head"><span class="card-title">T</span></div>
<div class="block-content"><p id="p1">The draft leaves it open. <b>EDR</b> confirms.</p>
<ol><li data-annotate-id="client-split" id="li1">Which clients. The draft leaves it open.</li></ol>
<span class="sel-chip">💬 a chip that is UI, not prose</span></div></section></main>"""


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content(PAGE)
        pg.add_script_tag(path=str(STATIC / "anchors.js"))
        yield pg
        b.close()


def _anchor(page, js_range):
    return page.evaluate(f"""() => {{
      const s = document.querySelector('section.block');
      const r = document.createRange(); {js_range}
      return AnnotateAnchors.anchorFor(s, r); }}""")


def test_prose_text_skips_ui_inside_the_content(page):
    t = page.evaluate("() => AnnotateAnchors.textOf(document.querySelector('.block-content'))")
    assert "a chip that is UI" not in t
    assert "The draft leaves it open. EDR confirms." in t


def test_an_anchor_carries_trimmed_text_context_and_step_id(page):
    a = _anchor(page, """const t = document.getElementById('li1').firstChild;
                         r.setStart(t, 14); r.setEnd(t, 40);""")
    assert a["selected_text"] == "The draft leaves it open."
    assert a["block_id"] == "b1"
    assert a["step_id"] == "client-split"
    assert a["prefix"].rstrip().endswith("Which clients.")
    assert len(a["prefix"]) <= 32 and len(a["suffix"]) <= 32


def test_an_element_bounded_range_still_anchors_to_its_words(page):
    a = _anchor(page, "r.selectNodeContents(document.getElementById('p1'));")
    assert a["selected_text"] == "The draft leaves it open. EDR confirms."
    assert "step_id" not in a


def test_whitespace_only_selection_is_no_anchor(page):
    a = _anchor(page, """const t = document.getElementById('p1').firstChild;
                         r.setStart(t, 25); r.setEnd(t, 26);""")
    assert a is None


def test_the_second_of_two_identical_phrases_is_found_by_its_context(page):
    out = page.evaluate("""() => {
      const s = document.querySelector('section.block');
      const t = document.getElementById('li1').firstChild;
      const r = document.createRange(); r.setStart(t, 15); r.setEnd(t, 24);
      const a = AnnotateAnchors.anchorFor(s, r);
      const span = AnnotateAnchors.locate(s, a);
      const text = AnnotateAnchors.textOf(AnnotateAnchors.contentOf(s));
      return {sel: a.selected_text, first: text.indexOf('the draft'.replace('t','T')), span};
    }""")
    assert out["sel"] == "The draft"
    assert out["span"][0] > out["first"], "located the first 'The draft', not the selected one"


def test_a_vanished_anchor_locates_nothing(page):
    span = page.evaluate("""() => AnnotateAnchors.locate(document.querySelector('section.block'),
        {block_id: 'b1', selected_text: 'words that are not there', prefix: '', suffix: ''})""")
    assert span is None


def test_paint_registers_one_highlight_per_kind(page):
    sizes = page.evaluate("""() => {
      const s = document.querySelector('section.block');
      const t = document.getElementById('p1').firstChild;
      const r = document.createRange(); r.setStart(t, 0); r.setEnd(t, 9);
      const a = AnnotateAnchors.anchorFor(s, r);
      AnnotateAnchors.paint([{section: s, anchor: a, kind: 'delete'}]);
      return ['delete','compact','comment'].map(k => CSS.highlights.get('annotate-' + k).size);
    }""")
    assert sizes == [1, 0, 0]


def test_offset_at_a_point_maps_into_prose_text(page):
    off = page.evaluate("""() => {
      const p = document.getElementById('p1').getBoundingClientRect();
      return AnnotateAnchors.offsetAt(document.querySelector('.block-content'), p.left + 2, p.top + p.height / 2);
    }""")
    assert off is not None and 0 <= off <= 2


def test_words_are_found_across_soft_wraps_and_double_spaces(page):
    """A strip mark stores its words whitespace-collapsed; markdown keeps the
    source "\\n" inside a <p>. The mark must still be found, and the range it
    gives back must cover the RAW words."""
    got = page.evaluate("""() => {
      const s = document.createElement('section');
      s.className = 'block'; s.dataset.blockId = 'wrap';
      s.innerHTML = '<div class="block-content"><p>Paragraph one\\nwraps  here, then more.</p></div>';
      document.querySelector('main').appendChild(s);
      const span = AnnotateAnchors.locate(s, {selected_text: 'one wraps here,', prefix: 'Paragraph ', suffix: ' then more.'});
      const r = AnnotateAnchors.rangeFor(s, {selected_text: 'one wraps here,', prefix: 'Paragraph ', suffix: ' then more.'});
      return {span, text: r && r.toString()}; }""")
    assert got["text"] == "one\nwraps  here,"
    assert got["span"] == [10, 26]
