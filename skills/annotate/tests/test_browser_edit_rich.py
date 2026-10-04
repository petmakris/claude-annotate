# skills/annotate/tests/test_browser_edit_rich.py
"""The Rich view: `e` turns the rendered section itself into the editor, and
a Rich | Source switch gives the exact stored text. Driven in a real browser
against the local daemon; every save is checked against what the daemon
stored, byte for byte, because the reader's edit is final and a small edit
must save as a small change."""
from __future__ import annotations

import pytest

from skills.tests.harness import T, require_playwright  # noqa: E402

require_playwright()

from skills.annotate.tests.test_browser_review import (  # noqa: E402,F401
    SEL, _call, _put_block, _select, document, page)

RICH = SEL + "[data-editing] .ed-rich"
ORIGINAL_1 = "Paragraph one of block 1, long enough to scroll past.\n\nParagraph two of block 1."
HINT = "⌘B bold · ⌘I italic · ⌘E code · ⌘K link · ## heading · - list · F6 bar · esc done"
FALLBACK = "Rich editing isn't available for this section — showing the source"


def _wait_ready(page):
    page.wait_for_function("() => !!window.AnnotateEdit && !!window.AnnotateKeyboard", timeout=T(15000))


def _press_e(page, anchor):
    _wait_ready(page)
    page.evaluate("id => { document.activeElement?.blur?.(); getSelection().removeAllRanges();"
                  " AnnotateKeyboard.focusBlock(id); }", anchor)
    page.keyboard.press("e")


def _open(page, anchor, view="rich"):
    _press_e(page, anchor)
    page.wait_for_function("v => window.AnnotateEdit?.editor()?.kind === v", arg=view, timeout=T(10000))


def _stored(document, anchor):
    return _call(document["base"], "GET", f"/s/{document['sid']}/items/{anchor}")


def _text(page):
    return page.evaluate("() => AnnotateEdit.editor().getText()")


def _bar(page, act):
    page.click(f'.ed-bar button[data-act="{act}"]')


def _toast(page):
    page.wait_for_selector(".ed-toast", timeout=T(5000))
    return page.inner_text(".ed-toast")


def _caret_before(page, needle, select=False):
    """Put the Rich caret before `needle` (or select it), as a click would."""
    page.evaluate("""([needle, select]) => {
      const v = AnnotateEdit.editor().view;
      let at = -1;
      v.state.doc.descendants((n, pos) => {
        if (at < 0 && n.isText && n.text.includes(needle)) at = pos + n.text.indexOf(needle);
      });
      if (at < 0) throw new Error('not in the editor: ' + needle);
      const TS = AnnotateRich.pm.TextSelection;
      v.dispatch(v.state.tr.setSelection(TS.create(v.state.doc, at, select ? at + needle.length : at)));
      v.focus();
    }""", [needle, select])


def _flip(page, to):
    page.keyboard.press("ControlOrMeta+/")
    page.wait_for_function("v => AnnotateEdit.editor()?.kind === v", arg=to, timeout=T(10000))


def _done(page, anchor):
    with page.expect_response(lambda r: r.request.method == "PUT"
                              and r.url.endswith(f"/items/{anchor}")) as resp:
        _bar(page, "done")
    assert resp.value.status == 200
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))


# ── opening ─────────────────────────────────────────────────────────────────

def test_e_opens_rich_in_place_and_the_card_does_not_move(page):
    _wait_ready(page)
    rect = "s => { const r = s.getBoundingClientRect(); return {top: r.top, width: r.width}; }"
    before = page.eval_on_selector(SEL.format("section-2"), rect)
    _open(page, "section-2")
    after = page.eval_on_selector(SEL.format("section-2"), rect)
    assert abs(after["top"] - before["top"]) <= 1, (before, after)
    assert abs(after["width"] - before["width"]) <= 1, (before, after)
    assert page.is_visible(RICH.format("section-2"))
    assert page.evaluate("() => AnnotateEdit.view()") == "rich"
    assert page.eval_on_selector(SEL.format("section-2") + " .block-content:not(.ed-rich)",
                                 "c => getComputedStyle(c).display") == "none"
    assert page.__dict__["js_errors"] == []


def test_the_bar_offers_rich_and_source_only_with_the_rich_hint(page):
    _open(page, "section-1")
    labels = page.eval_on_selector_all(".ed-bar .ed-seg button", "bs => bs.map(b => b.textContent)")
    assert labels == ["Rich", "Source"]
    bar = page.inner_text(".ed-bar")
    assert "Live" not in bar and "Split" not in bar
    assert page.inner_text(".ed-bar .ed-hint") == HINT
    assert page.get_attribute('.ed-bar .ed-seg button[data-view="rich"]', "aria-pressed") == "true"


SHAPES = ("## A heading\n\nA paragraph with **bold**, *em*, `code` and a [link](https://x.test).\n\n"
          "- first item\n- second item\n\n1. one\n2. two\n\n> a quote\n\n"
          "```py\ndef f(x):\n    return x + 1  # add\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nThe end.")


def _layout(page, root_js):
    return page.evaluate("""(rootJs) => {
      const root = eval(rootJs);
      const top = root.getBoundingClientRect().top;
      return [...root.children].map(c => { const r = c.getBoundingClientRect(); const cs = getComputedStyle(c);
        return {tag: c.tagName, top: Math.round(r.top - top), h: Math.round(r.height), w: Math.round(r.width),
                font: cs.fontFamily + ' ' + cs.fontSize + ' ' + cs.lineHeight + ' ' + cs.fontWeight,
                color: cs.color}; });
    }""", root_js)


def test_rich_looks_exactly_like_the_rendered_section(page, document):
    _put_block(document, "section-2", SHAPES, title="Block 2")
    page.wait_for_selector(SEL.format("section-2") + '[data-version="2"]', timeout=T(10000))
    sel = SEL.format("section-2")
    before = _layout(page, f"document.querySelector('{sel} .block-content')")
    _open(page, "section-2")
    after = _layout(page, f"document.querySelector('{sel} .ed-rich .ProseMirror')")
    assert [b["tag"] for b in before] == [a["tag"] for a in after]
    for b, a in zip(before, after):
        assert abs(b["top"] - a["top"]) <= 1 and abs(b["h"] - a["h"]) <= 1 and abs(b["w"] - a["w"]) <= 1, (b, a)
        assert (b["font"], b["color"]) == (a["font"], a["color"]), (b, a)


def test_a_fenced_block_shows_the_pages_code_colours(page, document):
    _put_block(document, "section-2", "```py\ndef f(x):\n    return x + 1  # add\n```", title="Block 2")
    page.wait_for_selector(SEL.format("section-2") + '[data-version="2"]', timeout=T(10000))
    sel = SEL.format("section-2")
    tokens = "els => els.map(e => [e.textContent, getComputedStyle(e).color])"
    page_tokens = page.eval_on_selector_all(sel + " .block-content pre code.sk-fence span.sk", tokens)
    assert len(page_tokens) > 3, "the page painted no tokens; Shiki did not load"
    _open(page, "section-2")
    assert page.locator(sel + " .ed-rich pre code.sk-fence").count() == 1
    assert page.eval_on_selector_all(sel + " .ed-rich pre code.sk-fence span.sk", tokens) == page_tokens
    _caret_before(page, "return")
    page.keyboard.type("y = 2\n    ")
    page.wait_for_function(f"() => [...document.querySelectorAll('{sel} .ed-rich span.sk')]"
                           ".some(s => s.textContent === '2')", timeout=T(3000))


def test_the_pencil_puts_the_caret_at_the_selected_words(page, document):
    _wait_ready(page)
    _select(page, "section-1", "long enough")
    page.click('.sel-menu button[data-act="edit"]')
    page.wait_for_function("() => AnnotateEdit.editor()?.kind === 'rich'", timeout=T(10000))
    page.keyboard.type("X")
    _done(page, "section-1")
    assert _stored(document, "section-1")["body"]["markdown"] == ORIGINAL_1.replace("long enough", "Xlong enough")


def test_selecting_words_in_the_editor_opens_no_menu(page):
    _open(page, "section-1")
    _caret_before(page, "long enough", select=True)
    page.evaluate("""() => { const el = document.querySelector('.ed-rich .ProseMirror p');
      const b = el.getBoundingClientRect();
      el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true, clientX: b.left + 5, clientY: b.top + 5})); }""")
    page.wait_for_timeout(400)
    assert page.locator(".sel-menu").count() == 0


# ── saving ──────────────────────────────────────────────────────────────────

def test_a_word_typed_in_rich_saves_as_only_that_word(page, document):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        page.keyboard.press("ControlOrMeta+s")
    assert _stored(document, "section-1")["body"]["markdown"] == ORIGINAL_1.replace("long", "very long")
    assert page.locator(".ed-rich").count() == 1, "⌘S closed the editor"


def test_open_and_done_untouched_writes_nothing(page, document):
    puts = []
    page.on("request", lambda r: puts.append(r.url) if r.method == "PUT" and r.url.endswith("/items/section-1") else None)
    version = _stored(document, "section-1")["version"]
    _open(page, "section-1")
    assert _text(page) == ORIGINAL_1
    _bar(page, "done")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert puts == []
    assert _stored(document, "section-1")["version"] == version


# ── switching ───────────────────────────────────────────────────────────────

def test_rich_to_source_carries_the_edit(page):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    _flip(page, "source")
    assert page.locator(".ed-host .cm-editor").count() == 1
    assert page.evaluate("() => AnnotateEdit.view()") == "source"
    cm = page.evaluate("() => AnnotateEdit.editor().view.state.doc.toString()")
    assert cm == ORIGINAL_1.replace("long", "very long")
    assert page.get_attribute('.ed-bar .ed-seg button[data-view="source"]', "aria-pressed") == "true"


def test_the_caret_keeps_its_place_across_a_switch(page):
    _open(page, "section-1")
    _caret_before(page, "two of block")
    _flip(page, "source")
    head = page.evaluate("() => AnnotateEdit.editor().view.state.selection.main.head")
    at = ORIGINAL_1.index("two of block")
    assert at - 1 <= head <= at, (head, at)
    page.evaluate("""at => { const v = AnnotateEdit.editor().view;
      v.dispatch({selection: {anchor: at}}); v.focus(); }""", ORIGINAL_1.index("enough"))
    _flip(page, "rich")
    after = page.evaluate("""() => { const v = AnnotateEdit.editor().view, f = v.state.selection.from;
      return v.state.doc.textBetween(f, f + 6); }""")
    assert after == "enough", after


def test_edits_in_both_views_are_both_saved(page, document):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    _flip(page, "source")
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.insert_text(" Typed in source.")
    _flip(page, "rich")
    assert page.is_visible(".ed-rich")
    _done(page, "section-1")
    assert _stored(document, "section-1")["body"]["markdown"] == \
        ORIGINAL_1.replace("long", "very long") + " Typed in source."


def test_edits_in_both_views_then_discard_store_nothing(page, document):
    version = _stored(document, "section-1")["version"]
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    _flip(page, "source")
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.insert_text(" Typed in source.")
    _flip(page, "rich")
    _bar(page, "discard")
    _bar(page, "confirm-discard")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    stored = _stored(document, "section-1")
    assert stored["body"]["markdown"] == ORIGINAL_1
    assert stored["version"] == version


MERGED = ('Before the table.\n\n<table><tr><td colspan="2">wide</td></tr>'
          '<tr><td>a</td><td>b</td></tr></table>\n\nAfter the table.')


def test_a_section_rich_cannot_show_opens_in_source_and_says_why(page, document):
    _put_block(document, "section-2", MERGED, title="Block 2")
    page.wait_for_selector(SEL.format("section-2") + '[data-version="2"]', timeout=T(10000))
    _open(page, "section-2", view="source")
    assert FALLBACK in page.inner_text(".ed-bar")
    assert _text(page) == MERGED
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("ControlOrMeta+/")
    assert "merged cells" in _toast(page)
    assert page.evaluate("() => AnnotateEdit.view()") == "source"


def test_source_to_rich_is_refused_when_the_text_cannot_be_shown(page):
    _open(page, "section-1")
    _flip(page, "source")
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.insert_text('\n\n<table><tr><td rowspan="2">x</td></tr></table>')
    page.keyboard.press("ControlOrMeta+/")
    assert "merged cells" in _toast(page)
    assert page.evaluate("() => AnnotateEdit.view()") == "source"


def test_the_rich_bundle_failing_opens_source_and_says_so(page):
    page.route("**/vendor/rich.min.js", lambda route: route.fulfill(status=404, body="nope"))
    _open(page, "section-1", view="source")
    assert "Rich editing could not load (HTTP 404)" in page.inner_text(".ed-bar")
    assert _text(page) == ORIGINAL_1


# ── the bar: ⌘K, What will be saved, F6 ─────────────────────────────────────

def test_cmd_k_asks_for_the_link_in_the_bar(page, document):
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.type), d.dismiss()))
    _open(page, "section-1")
    _caret_before(page, "scroll", select=True)
    page.keyboard.press("ControlOrMeta+k")
    page.wait_for_selector(".ed-bar input.ed-link", timeout=T(3000))
    assert page.evaluate("() => document.activeElement.classList.contains('ed-link')")
    page.keyboard.type("https://x.test")
    page.keyboard.press("Enter")
    page.wait_for_selector(".ed-bar input.ed-link", state="detached", timeout=T(3000))
    assert page.evaluate("() => AnnotateEdit.editor().isFocused()")
    _done(page, "section-1")
    assert _stored(document, "section-1")["body"]["markdown"] == \
        ORIGINAL_1.replace("scroll", "[scroll](https://x.test)")
    assert dialogs == []


def test_esc_in_the_link_field_cancels_and_returns_to_the_text(page):
    _open(page, "section-1")
    _caret_before(page, "scroll", select=True)
    page.keyboard.press("ControlOrMeta+k")
    page.wait_for_selector(".ed-bar input.ed-link", timeout=T(3000))
    page.keyboard.type("https://nope.test")
    page.keyboard.press("Escape")
    page.wait_for_selector(".ed-bar input.ed-link", state="detached", timeout=T(3000))
    assert page.locator(".ed-rich").count() == 1, "Esc in the field closed the editor"
    assert page.evaluate("() => AnnotateEdit.editor().isFocused()")
    assert _text(page) == ORIGINAL_1


def test_what_will_be_saved_shows_the_one_change_and_hides_again(page):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    _bar(page, "check")
    page.wait_for_selector(".ed-check", timeout=T(3000))
    assert page.locator(".ed-check del, .ed-check ins").count() == 1
    assert page.inner_text(".ed-check ins").strip() == "very"
    _bar(page, "check")
    page.wait_for_selector(".ed-check", state="detached", timeout=T(3000))


def test_f6_moves_between_the_text_and_the_bar(page):
    _open(page, "section-1")
    page.evaluate("() => AnnotateEdit.editor().focus()")
    page.keyboard.press("F6")
    assert page.evaluate("() => document.querySelector('.ed-bar button') === document.activeElement")
    page.keyboard.press("F6")
    assert page.evaluate("() => AnnotateEdit.editor().isFocused()")


# ── review fixes: the link field, the unsaved state, ⌘S in the bar ──────────

def test_an_abandoned_link_field_does_not_steal_typing(page, document):
    _open(page, "section-1")
    _caret_before(page, "scroll", select=True)
    page.keyboard.press("ControlOrMeta+k")
    page.wait_for_selector(".ed-bar input.ed-link", timeout=T(3000))
    page.click(".ed-rich p >> nth=1")
    page.wait_for_selector(".ed-bar input.ed-link", state="detached", timeout=T(3000))
    page.keyboard.type(" one")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        page.keyboard.press("ControlOrMeta+s")
    page.keyboard.type("zebrafish")
    assert "zebrafish" in _text(page)
    assert page.locator(".ed-link").count() == 0


def test_one_keystroke_is_unsaved_at_once(page):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.press("Q")
    got = page.evaluate("() => [AnnotateEdit.unsaved(), document.body.classList.contains('has-edit-draft')]")
    assert got == [True, True]


def test_cmd_s_in_the_link_field_saves(page, document):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    _caret_before(page, "scroll", select=True)
    page.keyboard.press("ControlOrMeta+k")
    page.wait_for_selector(".ed-bar input.ed-link", timeout=T(3000))
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        page.keyboard.press("ControlOrMeta+s")
    assert _stored(document, "section-1")["body"]["markdown"] == ORIGINAL_1.replace("long", "very long")


def test_the_words_to_link_stay_marked_while_the_field_has_focus(page):
    _open(page, "section-1")
    _caret_before(page, "scroll", select=True)
    page.keyboard.press("ControlOrMeta+k")
    page.wait_for_selector(".ed-bar input.ed-link:focus", timeout=T(3000))
    assert page.eval_on_selector_all(".ed-rich .ed-sel-held", "es => es.map(e => e.textContent).join('')") == "scroll"
    page.keyboard.press("Escape")
    page.wait_for_selector(".ed-bar input.ed-link", state="detached", timeout=T(3000))
    assert page.locator(".ed-rich .ed-sel-held").count() == 0


def test_a_rich_edit_meets_a_conflict_and_keep_mine_stores_it(page, document):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    _put_block(document, "section-1", "Claude wrote this meanwhile.", title="Block 1")
    page.wait_for_function(
        "() => !!document.querySelector('section.block[data-block-id=\"section-1\"]')._pendingBlock", timeout=T(10000))
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_selector(".ed-bar.ed-bar--conflict", timeout=T(5000))
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")) as resp:
        _bar(page, "keep-mine")
    assert resp.value.status == 200
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _stored(document, "section-1")["body"]["markdown"] == ORIGINAL_1.replace("long", "very long")


def test_a_rich_edit_survives_a_reload_as_a_draft(page, document):
    _open(page, "section-1")
    _caret_before(page, "long enough")
    page.keyboard.type("very ")
    page.wait_for_function("() => Object.keys(localStorage).some(k => k.startsWith('annotate.edit.draft.'))",
                           timeout=T(5000))
    page.reload()
    page.wait_for_selector("section.block", timeout=T(15000))
    _open(page, "section-1")
    page.wait_for_selector('.ed-bar button[data-act="restore-draft"]', timeout=T(5000))
    _bar(page, "restore-draft")
    page.wait_for_function("() => AnnotateEdit.editor()?.kind === 'rich'", timeout=T(5000))
    assert _text(page) == ORIGINAL_1.replace("long", "very long")
    _done(page, "section-1")
    assert _stored(document, "section-1")["body"]["markdown"] == ORIGINAL_1.replace("long", "very long")


# ── final review: `mine` and the dock for words typed in Rich ───────────────

HTML_S = ('<p data-annotate-id="intro">The quick brown fox jumps.</p>\n'
          '<ul><li data-annotate-id="a">First item here</li><li>Second item here</li></ul>')
MD_S = "The quick brown fox jumps.\n\n- First item here\n- Second item here"


def _rich_edit(page, document, base, old, new):
    _put_block(document, "section-2", base, title="Block 2")
    page.wait_for_selector(SEL.format("section-2") + '[data-version="2"]', timeout=T(10000))
    _open(page, "section-2")
    _caret_before(page, old, select=True)
    page.keyboard.type(new)
    _done(page, "section-2")
    return _stored(document, "section-2")["body"]


@pytest.mark.parametrize("base,old,new,mine", [
    (HTML_S, "jumps", "leaps", ["leaps."]),
    (HTML_S, "Second item here", "Second item there", ["there"]),
    (HTML_S, "The", "A", ["A"]),
    (HTML_S, "quick", "slow", ["slow"]),
    (MD_S, "jumps", "leaps", ["leaps."]),
    (MD_S, "Second item here", "Second item there", ["there"]),
    (MD_S, "The", "A", ["A"]),
], ids=["html-last", "html-li-last", "html-first", "html-mid", "md-last", "md-li-last", "md-first"])
def test_words_typed_in_rich_are_stored_as_yours(page, document, base, old, new, mine):
    body = _rich_edit(page, document, base, old, new)
    assert body["markdown"] == base.replace(old, new, 1)
    assert [a["selected_text"] for a in body.get("mine", [])] == mine


@pytest.mark.parametrize("base", [HTML_S, MD_S], ids=["html", "md"])
def test_the_dock_row_shows_rich_words_without_tags(page, document, base):
    _rich_edit(page, document, base, "jumps", "leaps")
    page.wait_for_selector("#round-dock", state="attached", timeout=T(5000))
    row = page.locator('#round-dock .rd-row:has(.rd-k[data-kind="edit"])')
    assert row.locator("del").all_inner_texts() == ["jumps."]
    assert row.locator("ins").all_inner_texts() == ["leaps."]


def test_bolding_a_word_in_html_is_formatting_not_yours(page, document):
    _put_block(document, "section-2", HTML_S, title="Block 2")
    page.wait_for_selector(SEL.format("section-2") + '[data-version="2"]', timeout=T(10000))
    _open(page, "section-2")
    _caret_before(page, "brown", select=True)
    page.keyboard.press("ControlOrMeta+b")
    _done(page, "section-2")
    body = _stored(document, "section-2")["body"]
    assert "<strong>brown</strong>" in body["markdown"]
    assert body.get("mine", []) == []


@pytest.mark.parametrize("text", [
    "<p>Before.</p><details><summary>More</summary><p>Hidden words.</p></details>",
    "Before.\n\n<dl><dt>Term</dt><dd>Meaning</dd></dl>\n\nAfter.",
    'Before.\n\n<svg width="10" height="10"><circle cx="5" cy="5" r="4"/></svg>\n\nAfter.',
], ids=["details", "dl", "svg"])
def test_content_rich_cannot_hold_opens_in_source(page, document, text):
    _put_block(document, "section-2", text, title="Block 2")
    page.wait_for_selector(SEL.format("section-2") + '[data-version="2"]', timeout=T(10000))
    _open(page, "section-2", view="source")
    assert FALLBACK in page.inner_text(".ed-bar")
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("ControlOrMeta+/")
    assert "can't show" in _toast(page)
