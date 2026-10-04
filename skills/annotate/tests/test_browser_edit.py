# skills/annotate/tests/test_browser_edit.py
"""Editing a section in place, driven in a real browser against the local
daemon: opening it with `e` or the menu's pencil, saving byte for byte with
If-Match, the conflict prompt when Claude wrote underneath, and the two
views. Sections open in Rich (test_browser_edit_rich.py drives it); a test
that types raw markdown switches to Source first. Every save is checked
against what the daemon stored, not against the page."""
from __future__ import annotations

import pytest

from skills.tests.harness import T, require_playwright, timeout_scale  # noqa: E402

require_playwright()

from skills.annotate.tests.test_browser_review import (  # noqa: E402,F401
    BUSY, SEL, _block_mark, _call, _put_block, _select, _submit_round, document, page)

EDITOR = SEL + "[data-editing] .ed-host"


def _wait_ready(page):
    page.wait_for_function("() => !!window.AnnotateEdit && !!window.AnnotateKeyboard", timeout=T(15000))


def _press_e(page, anchor):
    _wait_ready(page)
    page.evaluate("id => { document.activeElement?.blur?.(); getSelection().removeAllRanges();"
                  " AnnotateKeyboard.focusBlock(id); }", anchor)
    page.keyboard.press("e")


def _open(page, anchor):
    _press_e(page, anchor)
    page.wait_for_selector(EDITOR.format(anchor), timeout=T(10000))


def _stored(document, anchor):
    return _call(document["base"], "GET", f"/s/{document['sid']}/items/{anchor}")


def _source(page):
    """Flip the open editor to Source, the exact text."""
    if page.evaluate("() => AnnotateEdit.view()") != "source":
        page.evaluate("() => AnnotateEdit.setView('source')")
        page.wait_for_function("() => AnnotateEdit.editor()?.kind === 'source'", timeout=T(10000))


def _set_text(page, text):
    """Replace the editor's whole text, the way a reader's typing would:
    in Source, where what is typed is the markdown itself."""
    _source(page)
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.insert_text(text)
    got = page.evaluate("() => AnnotateEdit.editor().getText()")
    assert got == text, f"the editor holds {got!r}, not what was typed"


def _bar(page, act):
    page.click(f'.ed-bar button[data-act="{act}"]')


def _toast(page):
    page.wait_for_selector(".ed-toast", timeout=T(5000))
    return page.inner_text(".ed-toast")


def _rect(page, anchor):
    return page.eval_on_selector(SEL.format(anchor),
                                 "s => { const r = s.getBoundingClientRect(); return {top: r.top, width: r.width}; }")


# ── opening ─────────────────────────────────────────────────────────────────

def test_e_opens_the_focused_section_in_place_and_nothing_moves(page):
    before = _rect(page, "section-2")
    _open(page, "section-2")
    after = _rect(page, "section-2")
    assert abs(after["top"] - before["top"]) < 0.5, (before, after)
    assert abs(after["width"] - before["width"]) < 0.5, (before, after)
    assert page.eval_on_selector(SEL.format("section-2") + " .block-content",
                                 "c => getComputedStyle(c).display") == "none", \
        "the rendered text is still showing under the editor"
    text = page.evaluate("() => AnnotateEdit.editor().getText()")
    assert text.startswith("Paragraph one of block 2")
    assert page.evaluate("() => AnnotateEdit.isOpen('section-2')")
    assert page.__dict__["js_errors"] == []


def test_the_menu_pencil_opens_with_the_cursor_at_the_selected_words(page):
    _wait_ready(page)
    _select(page, "section-1", "long enough")
    page.click('.sel-menu button[data-act="edit"]')
    page.wait_for_selector(EDITOR.format("section-1"), timeout=T(10000))
    after = page.evaluate("""() => { const v = AnnotateEdit.editor().view, s = v.state.selection;
      return v.state.doc.textBetween(s.from, Math.min(s.from + 11, v.state.doc.content.size)); }""")
    assert after == "long enough", after


def test_the_pencil_on_a_whole_section_opens_at_the_start(page):
    _wait_ready(page)
    _block_mark(page, "section-3", "edit")
    page.wait_for_selector(EDITOR.format("section-3"), timeout=T(10000))
    assert page.evaluate("""() => { const v = AnnotateEdit.editor().view;
      return v.state.doc.textBetween(0, v.state.selection.from); }""") == ""


@pytest.mark.parametrize("kind,body", [
    ("choice", {"spec": {"question": "Which?", "options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}}),
    ("diagram", {"markdown": "a diagram"}),
    ("mockup", {"spec": {"html": "<p>hi</p>"}}),
])
def test_a_section_that_is_not_text_offers_no_pencil(page, document, kind, body):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-2",
          dict({"id": "section-2", "kind": kind, "title": "Not text"}, **body))
    page.wait_for_selector(SEL.format("section-2") + f'[data-kind="{kind}"]', timeout=T(10000))
    page.dblclick(SEL.format("section-2") + " .card-title")
    page.wait_for_selector(".sel-menu", timeout=T(3000))
    assert page.locator('.sel-menu button[data-act="edit"]').count() == 0
    page.keyboard.press("Escape")
    _press_e(page, "section-2")
    assert _toast(page) == "This section can't be edited as text"
    assert page.locator(".ed-host").count() == 0


def test_while_claude_works_e_says_so(page):
    _wait_ready(page)
    _block_mark(page, "section-4", "compact")
    _submit_round(page)
    page.wait_for_function(BUSY, timeout=T(5000))
    _press_e(page, "section-1")
    assert _toast(page) == "Claude is working — edit when it finishes"
    assert page.locator(".ed-host").count() == 0


# ── saving ──────────────────────────────────────────────────────────────────

BYTES = ("# Heading  \n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nA hard-wrapped\nline with two trailing  \n"
         "```py\nx = 1\n```\nno final newline")


def test_done_saves_byte_for_byte_and_keeps_the_other_fields(page, document):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-2",
          {"id": "section-2", "kind": "markdown", "title": "Kept title", "change_note": "a note",
           "code": [{"file": "skills/annotate/render.py", "line": 24, "snippet": "def render_block(blk: dict) -> dict:"}],
           "markdown": "Old words."})
    page.wait_for_selector(SEL.format("section-2") + '[data-version="2"]', timeout=T(10000))
    _open(page, "section-2")
    _set_text(page, BYTES)
    assert page.inner_text(".ed-bar .ed-state") == "Unsaved changes"
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-2")) as resp:
        _bar(page, "done")
    version = resp.value.json()["version"]
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))

    stored = _stored(document, "section-2")
    assert stored["body"]["markdown"] == BYTES
    assert stored["body"]["title"] == "Kept title"
    assert stored["body"]["change_note"] == "a note"
    assert stored["body"]["code"][0]["file"] == "skills/annotate/render.py"
    assert stored["version"] == version

    s = SEL.format("section-2")
    assert page.get_attribute(s, "data-version") == str(version)
    assert page.get_attribute(s, "data-editing") is None
    assert "no final newline" in page.inner_text(s + " .block-content")
    assert page.eval_on_selector(s + " .block-content", "c => getComputedStyle(c).display") != "none"
    assert page.__dict__["js_errors"] == []


def test_esc_is_done(page, document):
    _open(page, "section-1")
    _set_text(page, "Escaped words.")
    page.keyboard.press("Escape")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _stored(document, "section-1")["body"]["markdown"] == "Escaped words."


def test_discard_asks_in_the_bar_and_keep_editing_goes_back(page, document):
    _open(page, "section-1")
    original = page.evaluate("() => AnnotateEdit.editor().getText()")
    _set_text(page, "Words I will throw away.")
    _bar(page, "discard")
    assert "Discard your changes?" in page.inner_text(".ed-bar")
    assert page.locator(".ed-host").count() == 1
    _bar(page, "keep-editing")
    assert page.evaluate("() => AnnotateEdit.editor().getText()") == "Words I will throw away."
    _bar(page, "discard")
    _bar(page, "confirm-discard")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _stored(document, "section-1")["body"]["markdown"] == original
    assert "Paragraph one of block 1" in page.inner_text(SEL.format("section-1") + " .block-content")


def test_opening_a_second_section_saves_and_closes_the_first(page, document):
    _open(page, "section-1")
    _set_text(page, "First section, edited.")
    _press_e(page, "section-3")
    page.wait_for_selector(EDITOR.format("section-3"), timeout=T(10000))
    assert page.locator(".ed-host").count() == 1
    assert _stored(document, "section-1")["body"]["markdown"] == "First section, edited."
    assert "First section, edited." in page.inner_text(SEL.format("section-1") + " .block-content")


# ── a write from Claude while the editor is open ───────────────────────────

def _conflict(page, document):
    _open(page, "section-2")
    _set_text(page, "Mine, typed while Claude wrote.")
    _put_block(document, "section-2", "Theirs, written by Claude.", title="Block 2")
    page.wait_for_function(
        "() => !!document.querySelector('section.block[data-block-id=\"section-2\"]')._pendingBlock",
        timeout=T(10000))
    s = SEL.format("section-2")
    assert page.locator(s + " .ed-host .cm-editor").count() == 1, "the rewrite destroyed the editor"
    assert "Theirs" not in page.inner_text(s + " .block-content"), "the section re-rendered under the editor"
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-2")) as resp:
        _bar(page, "done")
    assert resp.value.status == 412
    page.wait_for_selector(".ed-bar.ed-bar--conflict", timeout=T(5000))
    assert "This section changed while you were editing. Nothing has been overwritten." \
        in page.inner_text(".ed-bar")


def test_a_conflict_take_theirs_saves_nothing_of_mine(page, document):
    _conflict(page, document)
    _bar(page, "take-theirs")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    s = SEL.format("section-2")
    assert "Theirs, written by Claude." in page.inner_text(s + " .block-content")
    stored = _stored(document, "section-2")
    assert stored["body"]["markdown"] == "Theirs, written by Claude."
    assert page.get_attribute(s, "data-version") == str(stored["version"])


def test_a_conflict_keep_mine_saves_over_the_new_version(page, document):
    _conflict(page, document)
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-2")) as resp:
        _bar(page, "keep-mine")
    assert resp.value.status == 200
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    stored = _stored(document, "section-2")
    assert stored["body"]["markdown"] == "Mine, typed while Claude wrote."
    assert page.get_attribute(SEL.format("section-2"), "data-version") == str(stored["version"])
    assert "Mine, typed" in page.inner_text(SEL.format("section-2") + " .block-content")


def test_a_conflict_shows_what_changed_as_a_word_diff(page, document):
    _conflict(page, document)
    _bar(page, "show-diff")
    page.wait_for_selector(".ed-diff", timeout=T(5000))
    dels = page.eval_on_selector_all(".ed-diff del", "es => es.map(e => e.textContent).join('|')")
    ins = page.eval_on_selector_all(".ed-diff ins", "es => es.map(e => e.textContent).join('|')")
    assert "Theirs" in dels and "Mine" in ins, (dels, ins)
    expected = page.evaluate("""() => AnnotateEditDiff.wordDiff('Theirs, written by Claude.',
      'Mine, typed while Claude wrote.').filter(x => x.op !== 'eq').length""")
    assert page.locator(".ed-diff del, .ed-diff ins").count() == expected


def test_a_section_claude_rewrote_while_open_shows_the_newer_text_on_discard(page, document):
    _open(page, "section-2")
    _put_block(document, "section-2", "Claude's newer words.", title="Block 2")
    page.wait_for_function(
        "() => !!document.querySelector('section.block[data-block-id=\"section-2\"]')._pendingBlock",
        timeout=T(10000))
    _bar(page, "discard")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert "Claude's newer words." in page.inner_text(SEL.format("section-2") + " .block-content")


# ── views ───────────────────────────────────────────────────────────────────

def test_rich_and_source_each_show_and_cmd_slash_toggles(page):
    _open(page, "section-1")
    host = ".ed-host"
    assert "ed-rich" in page.get_attribute(host, "class")
    page.click('.ed-bar button[data-view="source"]')
    page.wait_for_selector(host + ".ed-cm--source .cm-lineNumbers", timeout=T(10000))
    assert "Paragraph one of block 1" in page.evaluate("() => AnnotateEdit.editor().getText()")
    page.click('.ed-bar button[data-view="rich"]')
    page.wait_for_selector(host + ".ed-rich", timeout=T(10000))
    assert "Paragraph one of block 1" in page.inner_text(host)
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("ControlOrMeta+/")
    page.wait_for_selector(host + ".ed-cm--source", timeout=T(10000))
    assert page.get_attribute('.ed-bar button[data-view="source"]', "aria-pressed") == "true"
    page.keyboard.press("ControlOrMeta+/")
    page.wait_for_selector(host + ".ed-rich", timeout=T(10000))
    assert page.get_attribute('.ed-bar button[data-view="rich"]', "aria-pressed") == "true"


def test_the_source_view_colours_its_headings(page, document):
    _put_block(document, "section-1", "# A heading\n\nBody.", title="Block 1")
    page.wait_for_selector(SEL.format("section-1") + '[data-version="2"]', timeout=T(10000))
    _open(page, "section-1")
    _source(page)
    got = page.evaluate("""() => {
      const root = getComputedStyle(document.documentElement);
      const need = ['--text', '--n-300', '--n-400', '--n-700', '--pink', '--text-muted'];
      return need.filter(v => !root.getPropertyValue(v).trim()); }""")
    assert got == [], f"tokens the source view reads are undefined: {got}"


def test_typing_in_the_editor_fires_no_page_shortcut(page):
    _open(page, "section-1")
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.type("jkcdxre")
    assert page.locator(".comment-card").count() == 0
    assert page.locator("#round-dock").count() == 0
    assert "jkcdxre" in page.evaluate("() => AnnotateEdit.editor().getText()")


def test_export_strips_the_editor(page):
    _open(page, "section-1")
    html = page.evaluate("() => AnnotateExport.buildProse()")
    assert "ed-bar" not in html and "ed-host" not in html and "cm-editor" not in html
    assert "ed-rich" not in html and "ProseMirror" not in html
    assert "data-editing" not in html
    assert "Paragraph one of block 1" in html


def test_a_section_removed_while_open_keeps_the_text(page, document):
    from skills.annotate.tests.test_browser_review import _remove_block
    _open(page, "section-2")
    _set_text(page, "Words that outlive the section.")
    _remove_block(document, "section-2")
    page.wait_for_selector(".ed-bar.ed-bar--removed", timeout=T(10000))
    assert "This section was removed. Copy your text before closing" in page.inner_text(".ed-bar")
    assert page.evaluate("() => AnnotateEdit.editor().getText()") == "Words that outlive the section."
    _bar(page, "close")
    page.wait_for_selector(SEL.format("section-2"), state="detached", timeout=T(5000))


# ── your words: `mine`, the badge, and the `edit` mark ─────────────────────

ORIGINAL_1 = "Paragraph one of block 1, long enough to scroll past.\n\nParagraph two of block 1."
SHORT_1 = "Paragraph one of block 1, short to scroll past.\n\nParagraph two of block 1."


def _edit(page, anchor, text):
    _open(page, anchor)
    _set_text(page, text)
    with page.expect_response(lambda r: r.request.method == "PUT"
                              and r.url.endswith(f"/items/{anchor}")) as resp:
        _bar(page, "done")
    assert resp.value.status == 200
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))


def _mine_ranges(page):
    return page.evaluate("""() => { const h = CSS.highlights.get('annotate-mine');
      return h ? [...h].map(r => r.toString()) : []; }""")


def _badge(page, anchor):
    return page.eval_on_selector(SEL.format(anchor) + " .card-title",
                                 "t => getComputedStyle(t, '::after').content")


def _edit_marks(page):
    from skills.annotate.tests.test_browser_review import _round
    return [m for m in _round(page).values() if m.get("kind") == "edit"]


def test_an_edit_stores_the_new_words_as_mine(page, document):
    _edit(page, "section-1", SHORT_1)
    mine = _stored(document, "section-1")["body"]["mine"]
    assert [a["selected_text"] for a in mine] == ["short"]
    assert mine[0]["prefix"].endswith("Paragraph one of block 1, ")
    assert mine[0]["suffix"].startswith(" to scroll past.")
    assert page.__dict__["js_errors"] == []


def test_your_words_are_painted_and_badged_after_a_reload(page, document):
    _edit(page, "section-1", SHORT_1)
    page.reload()
    page.wait_for_selector(SEL.format("section-1") + "[data-mine]", timeout=T(15000))
    assert _mine_ranges(page) == ["short"]
    assert "✎ your words" in _badge(page, "section-1")
    assert page.get_attribute(SEL.format("section-2"), "data-mine") is None


def test_markdown_markers_are_not_frozen_as_your_words(page, document):
    _edit(page, "section-1", "Paragraph one of block 1, **bold words** to scroll past.\n\n"
                             "- `new item`\n\nParagraph two of block 1.")
    got = sorted(a["selected_text"] for a in _stored(document, "section-1")["body"]["mine"])
    assert got == ["bold words", "new item"], got


def test_earlier_words_are_kept_and_carried_through_a_second_edit(page, document):
    _edit(page, "section-1", "Paragraph one of block 1, your exact words to scroll past.\n\n"
                             "Paragraph two of block 1.")
    _edit(page, "section-1", "Paragraph one of block 1, your precise words to scroll past.\n\n"
                             "Paragraph two of block 1. And more.")
    got = [a["selected_text"] for a in _stored(document, "section-1")["body"]["mine"]]
    assert got == ["your precise words", "And more."], got


def test_the_round_holds_one_edit_mark_and_a_second_edit_merges(page, document):
    _edit(page, "section-1", SHORT_1)
    [m] = _edit_marks(page)
    assert (m["scope"], m["block_id"]) == ("block", "section-1")
    assert (m["before"], m["after"]) == (ORIGINAL_1, SHORT_1)
    later = SHORT_1.replace("short", "brief")
    _edit(page, "section-1", later)
    [m] = _edit_marks(page)
    assert (m["before"], m["after"]) == (ORIGINAL_1, later)


def test_the_dock_row_shows_the_struck_and_added_words(page, document):
    _edit(page, "section-1", SHORT_1)
    page.wait_for_selector("#round-dock", timeout=T(5000))
    row = page.locator('#round-dock .rd-row:has(.rd-k[data-kind="edit"])')
    assert row.count() == 1
    assert row.locator(".rd-k").inner_text() == "✎"
    assert row.locator("del").all_inner_texts() == ["long enough"]
    assert row.locator("ins").all_inner_texts() == ["short"]
    assert "✎" in page.inner_text("#round-dock .rd-summary")


def test_the_submitted_reaction_carries_before_and_after(page, document):
    from skills.annotate.tests.test_browser_review import _envelope, _watch_submits
    _edit(page, "section-1", SHORT_1)
    posts = _watch_submits(page)
    _submit_round(page)
    [r] = _envelope(posts[0])["reactions"]
    assert (r["kind"], r["scope"], r["block_id"]) == ("edit", "block", "section-1")
    assert (r["before"], r["after"]) == (ORIGINAL_1, SHORT_1)


def _claude_rewrites(document, markdown, mine):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-1",
          {"id": "section-1", "kind": "markdown", "title": "Block 1",
           "markdown": markdown, "mine": mine})


def test_your_words_follow_a_claude_rewrite_or_drop_quietly(page, document):
    _edit(page, "section-1", SHORT_1)
    mine = _stored(document, "section-1")["body"]["mine"]
    _claude_rewrites(document, "Claude moved things. Now it is short and sweet.", mine)
    page.wait_for_function("() => document.querySelector('section.block[data-block-id=\"section-1\"]')"
                           ".textContent.includes('sweet')", timeout=T(10000))
    page.wait_for_function("() => (CSS.highlights.get('annotate-mine')?.size || 0) === 1", timeout=T(5000))
    assert _mine_ranges(page) == ["short"]
    _claude_rewrites(document, "Claude dropped them against the rule.", mine)
    page.wait_for_function("() => document.querySelector('section.block[data-block-id=\"section-1\"]')"
                           ".textContent.includes('against the rule')", timeout=T(10000))
    page.wait_for_function("() => (CSS.highlights.get('annotate-mine')?.size || 0) === 0", timeout=T(5000))
    assert page.get_attribute(SEL.format("section-1"), "data-mine") is None
    assert page.__dict__["js_errors"] == []


# ── the edit bar's keys, refusals, ⌘S, copy, attribution ───────────────────

def test_a_letter_on_the_bar_buttons_reaches_no_page_shortcut(page):
    _open(page, "section-1")
    _set_text(page, "Changed words.")
    _bar(page, "discard")
    assert page.evaluate("() => document.activeElement.dataset.act") == "keep-editing"
    for key in "dxce":
        page.keyboard.press(key)
    assert page.locator("#round-dock").count() == 0
    assert page.locator(".comment-card").count() == 0
    assert "Discard your changes?" in page.inner_text(".ed-bar")


def test_e_with_the_highlighter_on_says_turn_it_off(page):
    _wait_ready(page)
    page.evaluate("() => document.getElementById('highlighter-toggle').click()")
    page.wait_for_function("() => document.body.dataset.highlighter === 'on'", timeout=T(3000))
    _press_e(page, "section-1")
    assert _toast(page) == "Turn off the highlighter to edit"
    assert page.locator(".ed-host").count() == 0


def test_e_in_the_menu_of_a_section_that_is_not_text_says_so(page, document):
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-2",
          {"id": "section-2", "kind": "mockup", "title": "Not text", "spec": {"html": "<p>hi</p>"}})
    page.wait_for_selector(SEL.format("section-2") + '[data-kind="mockup"]', timeout=T(10000))
    _wait_ready(page)
    page.dblclick(SEL.format("section-2") + " .card-title")
    page.wait_for_selector(".sel-menu", timeout=T(3000))
    page.keyboard.press("e")
    assert _toast(page) == "This section can't be edited as text"


def test_cmd_s_rerenders_the_hidden_text(page, document):
    _open(page, "section-1")
    _set_text(page, "Saved mid-edit words.")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("() => document.querySelector('section.block[data-block-id=\"section-1\"]"
                           " .block-content').textContent.includes('Saved mid-edit words.')", timeout=T(3000))
    assert page.locator(".ed-host").count() == 1
    assert "Saved mid-edit words." in page.evaluate("() => AnnotateExport.buildProse()")


def test_the_conflict_bar_copies_your_text(page, document):
    page.evaluate("""() => { window.__copied = null;
      Object.defineProperty(navigator, 'clipboard', {configurable: true,
        value: {writeText: async (t) => { window.__copied = t; }}}); }""")
    _conflict(page, document)
    labels = page.eval_on_selector_all(".ed-bar button", "bs => bs.map(b => b.dataset.act)")
    assert labels.index("copy") == labels.index("take-theirs") + 1, labels
    _bar(page, "copy")
    page.wait_for_function("() => window.__copied !== null", timeout=T(3000))
    assert page.evaluate("() => window.__copied") == "Mine, typed while Claude wrote."


def test_your_own_save_is_not_counted_as_claudes_change(page, document):
    from skills.annotate.tests.test_browser_review import _ack
    _open(page, "section-1")
    _block_mark(page, "section-4", "compact")
    eid = _submit_round(page)
    page.wait_for_function(BUSY, timeout=T(5000))
    _set_text(page, "Saved while Claude worked.")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        page.keyboard.press("ControlOrMeta+s")
    _put_block(document, "section-3", "Claude's sweep.", title="Block 3")
    page.wait_for_function("() => document.querySelector('section.block[data-block-id=\"section-3\"]')"
                           ".textContent.includes(\"Claude's sweep.\")", timeout=T(10000))
    _ack(document, eid)
    page.wait_for_selector("#change-bar", timeout=T(10000))
    assert page.inner_text("#change-bar b") == "1 section changed"


# ── review fixes: over-marking, Keep mine, escapes, attribution ────────────

def _mine_of(document, anchor="section-1"):
    return [a["selected_text"] for a in _stored(document, anchor)["body"].get("mine", [])]


def test_words_you_delete_stop_being_yours(page, document):
    _edit(page, "section-1", ORIGINAL_1.replace("long enough", "roll"))
    assert _mine_of(document) == ["roll"]
    _edit(page, "section-1", ORIGINAL_1.replace("long enough ", ""))
    assert _mine_of(document) == []
    assert _mine_ranges(page) == []
    assert page.get_attribute(SEL.format("section-1"), "data-mine") is None


def test_keep_mine_marks_only_your_words_against_what_you_opened(page, document):
    _open(page, "section-1")
    _set_text(page, SHORT_1)
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-1",
          {"id": "section-1", "kind": "markdown", "title": "Block 1",
           "markdown": "Claude rewrote everything here.\n\nParagraph two of block 1."})
    _bar(page, "done")
    page.wait_for_selector('.ed-bar button[data-act="keep-mine"]', timeout=T(5000))
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        _bar(page, "keep-mine")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _mine_of(document) == ["short"]


def test_keep_mine_keeps_your_earlier_words(page, document):
    _edit(page, "section-1", SHORT_1.replace("Paragraph two", "My second"))
    assert _mine_of(document) == ["short", "My second"]
    _open(page, "section-1")
    _set_text(page, SHORT_1.replace("Paragraph two", "My second").replace("scroll", "glide"))
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/section-1",
          {"id": "section-1", "kind": "markdown", "title": "Block 1",
           "markdown": "Claude rewrote everything here.\n\nParagraph two of block 1."})
    _bar(page, "done")
    page.wait_for_selector('.ed-bar button[data-act="keep-mine"]', timeout=T(5000))
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        _bar(page, "keep-mine")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _mine_of(document) == ["short", "glide", "My second"]


def test_formatting_alone_does_not_make_words_yours(page, document):
    _edit(page, "section-1", ORIGINAL_1.replace("long enough", "**long enough**"))
    assert _mine_of(document) == []


def test_escaped_characters_and_entities_are_found(page, document):
    _edit(page, "section-1", ORIGINAL_1.replace("long enough", "a\\*b and x &amp; y"))
    assert _mine_of(document) == ["a*b and x & y"]


def test_the_dock_row_shows_words_without_markdown_markers(page, document):
    _edit(page, "section-1", ORIGINAL_1.replace("long enough", "**short and plain**"))
    page.wait_for_selector("#round-dock", timeout=T(5000))
    row = page.locator('#round-dock .rd-row:has(.rd-k[data-kind="edit"])')
    assert row.locator("ins").all_inner_texts() == ["short and plain"]


def test_claude_changing_only_the_title_of_your_section_is_still_a_change(page, document):
    from skills.annotate.tests.test_browser_review import _ack
    _open(page, "section-1")
    _block_mark(page, "section-4", "compact")
    eid = _submit_round(page)
    page.wait_for_function(BUSY, timeout=T(5000))
    _set_text(page, "Saved while Claude worked.")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-1")):
        page.keyboard.press("ControlOrMeta+s")
    _bar(page, "done")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    _put_block(document, "section-1", "Saved while Claude worked.", title="Claude's new title")
    page.wait_for_function("() => document.querySelector('section.block[data-block-id=\"section-1\"]"
                           " .card-title').textContent.includes(\"Claude's new title\")", timeout=T(10000))
    _ack(document, eid)
    page.wait_for_selector("#change-bar", timeout=T(10000))
    assert page.inner_text("#change-bar b") == "1 section changed"


# ── holds: a section the reader has open is theirs ──────────────────────────

import time  # noqa: E402

from skills.annotate.tests.test_browser_review import _serve_core_override  # noqa: E402


def _holds(document):
    try:
        return _stored(document, "__holds__")["body"] or {}
    except Exception:                                   # noqa: BLE001 — 404: no holds yet
        return {}


def _wait_holds(document, pred, what, timeout=8.0):
    end = time.time() + timeout * timeout_scale()
    while time.time() < end:
        h = _holds(document)
        if pred(h):
            return h
        time.sleep(0.1)
    raise AssertionError(f"{what}; __holds__ is {_holds(document)!r}")


def _put_hold(document, anchor, age_s=0, tab="tab-x"):
    now = int(time.time())
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__holds__",
          {anchor: {"opened_at": now - age_s, "heartbeat_at": now - age_s, "tab": tab}})


def test_opening_writes_a_hold_and_closing_removes_it(page, document):
    _open(page, "section-1")
    tab = page.evaluate("() => AnnotateEdit.tab")
    assert tab
    h = _wait_holds(document, lambda h: "section-1" in h, "opening wrote no hold")
    assert h["section-1"]["tab"] == tab
    assert abs(h["section-1"]["opened_at"] - time.time()) < 30
    assert h["section-1"]["heartbeat_at"] >= h["section-1"]["opened_at"]
    page.keyboard.press("Escape")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    _wait_holds(document, lambda h: "section-1" not in h, "closing left the hold")


def test_the_hold_heartbeats(page, document):
    _wait_ready(page)
    page.evaluate("() => AnnotateEdit.setHeartbeatMs(200)")
    _open(page, "section-1")
    first = _wait_holds(document, lambda h: "section-1" in h, "no hold")["section-1"]
    _wait_holds(document, lambda h: h.get("section-1", {}).get("heartbeat_at", 0) > first["heartbeat_at"],
                "heartbeat_at never moved", timeout=5)
    assert _holds(document)["section-1"]["opened_at"] == first["opened_at"]


def test_pagehide_releases_the_hold_with_a_keepalive_request(page, document):
    _open(page, "section-1")
    _wait_holds(document, lambda h: "section-1" in h, "no hold")
    page.evaluate("""() => { window.__kept = [];
      const f = window.fetch;
      window.fetch = function (u, init) {
        if (String(u).includes("__holds__") && init && init.method === "PUT") window.__kept.push(!!init.keepalive);
        return f.apply(this, arguments); }; }""")
    page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: false}))")
    _wait_holds(document, lambda h: "section-1" not in h, "pagehide left the hold")
    assert page.evaluate("() => window.__kept") == [True]


def test_a_section_held_in_another_tab_does_not_open(page, document):
    _put_hold(document, "section-1")
    _press_e(page, "section-1")
    assert _toast(page) == "Being edited in another tab"
    assert page.locator(".ed-host").count() == 0
    # A hold whose heartbeat is over 30 minutes old is a dead tab's.
    _put_hold(document, "section-1", age_s=31 * 60)
    _open(page, "section-1")
    assert _holds(document)["section-1"]["tab"] == page.evaluate("() => AnnotateEdit.tab")


def test_a_second_tab_sees_the_first_tabs_hold(page, document):
    _open(page, "section-2")
    _wait_holds(document, lambda h: "section-2" in h, "no hold")
    other = page.context.browser.new_page()     # a tab of its own: its own sessionStorage
    _serve_core_override(other)
    other.goto(document["url"])
    other.wait_for_selector("section.block", timeout=T(15000))
    _press_e(other, "section-2")
    assert _toast(other) == "Being edited in another tab"
    assert other.locator(".ed-host").count() == 0
    # Another section is free.
    _open(other, "section-3")
    h = _holds(document)
    assert h["section-2"]["tab"] != h["section-3"]["tab"]


BEFOREUNLOAD = """() => { const e = new Event('beforeunload', {cancelable: true});
  window.dispatchEvent(e); return e.defaultPrevented; }"""


def test_beforeunload_warns_only_while_there_are_unsaved_changes(page, document):
    _open(page, "section-1")
    assert page.evaluate(BEFOREUNLOAD) is False
    _set_text(page, "changed, not saved")
    assert page.evaluate(BEFOREUNLOAD) is True
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("() => document.querySelector('.ed-bar .ed-state')?.textContent === 'Editing'",
                           timeout=T(5000))
    assert page.evaluate(BEFOREUNLOAD) is False


def test_submit_waits_for_unsaved_edits(page, document):
    _wait_ready(page)
    _block_mark(page, "section-4", "compact")
    page.wait_for_selector("#round-submit:not([disabled])", timeout=T(5000))
    _open(page, "section-1")
    _set_text(page, "changed, not saved")
    page.wait_for_selector("#round-submit[disabled]", timeout=T(5000))
    assert page.inner_text("#round-submit") == "Save or discard your edit"
    page.keyboard.press("ControlOrMeta+s")
    page.wait_for_selector("#round-submit:not([disabled])", timeout=T(5000))
    # Discarding unsaved words frees it too.
    _set_text(page, "changed again")
    page.wait_for_selector("#round-submit[disabled]", timeout=T(5000))
    _bar(page, "discard")
    _bar(page, "confirm-discard")
    page.wait_for_selector("#round-submit:not([disabled])", timeout=T(5000))


def test_a_holds_write_is_not_a_block_change(page, document):
    _wait_ready(page)
    page.evaluate("""() => { window.__holdsEv = 0;
      document.addEventListener('annotate:holds', () => window.__holdsEv++); }""")
    _put_hold(document, "section-3")
    page.wait_for_function("() => window.__holdsEv > 0", timeout=T(5000))
    assert page.locator('section.block[data-block-id="__holds__"]').count() == 0


def test_a_push_while_the_editor_is_open_keeps_the_readers_section(page, document, tmp_path, capsys,
                                                                    monkeypatch, wc_config):
    """End to end: the page's own hold, then Claude's real push."""
    import json
    from skills.annotate import push as push_mod
    monkeypatch.setenv("CLAUDE_ANNOTATE_STATE_DIR", str(tmp_path / "state"))
    _open(page, "section-1")
    _wait_holds(document, lambda h: "section-1" in h, "no hold")
    slug = next(r["slug"] for r in _call(document["base"], "GET", "/api/sessions?scope=all")
                if r["sid"] == document["sid"])
    blocks = tmp_path / "blocks.json"
    blocks.write_text(json.dumps({"response_id": "resp-browser-suite", "title": "annotate browser suite",
                                  "blocks": [{"id": f"section-{i}", "title": f"Block {i}",
                                              "markdown": f"Claude rewrote block {i}."}
                                             for i in range(1, 5)]}))
    assert push_mod.main(["--blocks", str(blocks), "--cwd", str(tmp_path), "--slug", slug]) == 0
    assert "held by the reader: section-1" in capsys.readouterr().err
    assert _stored(document, "section-1")["body"]["markdown"].startswith("Paragraph one of block 1")
    assert _stored(document, "section-2")["body"]["markdown"] == "Claude rewrote block 2."
    # The editor is still open on the reader's text, and saving needs no conflict.
    _set_text(page, "My own words.")
    _bar(page, "done")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _stored(document, "section-1")["body"]["markdown"] == "My own words."


def test_a_hold_this_tab_failed_to_release_goes_on_the_next_load(page, document):
    _wait_ready(page)
    tab = page.evaluate("() => AnnotateEdit.tab")
    now = int(time.time())
    # The release on pagehide never landed; another tab's hold is its own.
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__holds__", {
        "section-1": {"opened_at": now, "heartbeat_at": now, "tab": tab},
        "section-2": {"opened_at": now, "heartbeat_at": now, "tab": "tab-x"}})
    page.reload()
    page.wait_for_selector("section.block", timeout=T(15000))
    _wait_ready(page)
    assert page.evaluate("() => AnnotateEdit.tab") == tab
    h = _wait_holds(document, lambda h: "section-1" not in h, "the reloaded tab kept its dead hold")
    assert h["section-2"]["tab"] == "tab-x"


def test_a_hold_another_tab_took_is_said_in_the_bar(page, document):
    _wait_ready(page)
    page.evaluate("() => AnnotateEdit.setHeartbeatMs(200)")
    _open(page, "section-1")
    _wait_holds(document, lambda h: "section-1" in h, "no hold")
    _put_hold(document, "section-1", tab="tab-x")
    page.wait_for_function("""() => (document.querySelector('.ed-bar')?.textContent || '')
      .includes("Another tab took this section — your saves still won't overwrite it")""", timeout=T(5000))


def test_a_duplicated_tab_takes_a_new_name_and_releases_nothing(page, document):
    """A duplicate inherits sessionStorage, so the tab's name: it must not
    release the original's live hold as if it were its own leftover."""
    ctx = page.context.browser.new_context()
    try:
        first = ctx.new_page()
        _serve_core_override(first)
        first.goto(document["url"])
        first.wait_for_selector("section.block", timeout=T(15000))
        _open(first, "section-1")
        tab = first.evaluate("() => AnnotateEdit.tab")
        _wait_holds(document, lambda h: h.get("section-1", {}).get("tab") == tab, "no hold")
        dup = ctx.new_page()
        _serve_core_override(dup)
        dup.add_init_script(f"sessionStorage.setItem('annotate.edit.tab', {tab!r})")
        dup.goto(document["url"])
        dup.wait_for_selector("section.block", timeout=T(15000))
        _wait_ready(dup)
        dup.wait_for_function(f"() => AnnotateEdit.tab !== {tab!r}", timeout=T(5000))
        time.sleep(0.5)
        assert _holds(document).get("section-1", {}).get("tab") == tab, "the duplicate released a live hold"
    finally:
        ctx.close()


# ── final review: the dock, drafts, focus, screen readers, export, voice, search ──

def test_an_edit_row_cannot_be_removed_and_the_foot_says_it_is_saved(page, document):
    _edit(page, "section-1", SHORT_1)
    _block_mark(page, "section-4", "compact")
    page.wait_for_selector('#round-dock .rd-row:has(.rd-k[data-kind="edit"])', state="attached", timeout=T(5000))
    page.evaluate("document.getElementById('round-dock').dataset.open='true'")
    assert page.locator('#round-dock .rd-row:has(.rd-k[data-kind="edit"]) .rd-x').count() == 0
    assert page.locator('#round-dock .rd-row:has(.rd-k[data-kind="compact"]) .rd-x').count() == 1
    foot = page.inner_text("#round-dock .rd-foot")
    assert "Your edits are already saved; submitting tells Claude." in foot
    assert "Nothing has reached Claude yet" not in foot


DRAFT = "Words typed on a phone that went to sleep."


def _draft_keys(page):
    return page.evaluate("() => Object.keys(localStorage).filter(k => k.startsWith('annotate.edit.draft.'))")


def _second_tab(page, document):
    """The same browser's localStorage in a tab of its own; the first tab's
    hold is cleared, as if the phone had killed it. (Playwright gives a page
    made by browser.new_page() no way to open a sibling, so the storage is
    copied into a fresh context.)"""
    import json
    saved = page.evaluate("() => Object.fromEntries(Object.keys(localStorage).map(k => [k, localStorage.getItem(k)]))")
    other = page.context.browser.new_context().new_page()
    other.add_init_script("(() => { const s = %s; for (const k in s) localStorage.setItem(k, s[k]); })()"
                          % json.dumps(saved))
    _serve_core_override(other)
    _call(document["base"], "PUT", f"/s/{document['sid']}/items/__holds__", {})
    other.goto(document["url"])
    other.wait_for_selector("section.block", timeout=T(15000))
    _wait_ready(other)
    return other


def test_unsaved_text_is_kept_as_a_draft_and_offered_on_the_next_open(page, document):
    _open(page, "section-2")
    _set_text(page, DRAFT)
    page.wait_for_function("() => Object.keys(localStorage).some(k => k.startsWith('annotate.edit.draft.'))",
                           timeout=T(5000))
    other = _second_tab(page, document)
    _open(other, "section-2")
    other.wait_for_selector('.ed-bar button[data-act="restore-draft"]', timeout=T(5000))
    assert "Restore your unsaved text" in other.inner_text(".ed-bar")
    assert "Discard it" in other.inner_text(".ed-bar")
    assert other.evaluate("() => AnnotateEdit.editor().getText()").startswith("Paragraph one of block 2")
    _bar(other, "restore-draft")
    assert other.evaluate("() => AnnotateEdit.editor().getText()") == DRAFT
    _bar(other, "done")
    other.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _stored(document, "section-2")["body"]["markdown"] == DRAFT
    assert _draft_keys(other) == [], "the save left the draft behind"


def test_a_draft_can_be_discarded(page, document):
    _open(page, "section-2")
    _set_text(page, DRAFT)
    page.wait_for_function("() => Object.keys(localStorage).some(k => k.startsWith('annotate.edit.draft.'))",
                           timeout=T(5000))
    other = _second_tab(page, document)
    _open(other, "section-2")
    other.wait_for_selector('.ed-bar button[data-act="discard-draft"]', timeout=T(5000))
    _bar(other, "discard-draft")
    assert other.locator('.ed-bar button[data-act="restore-draft"]').count() == 0
    assert other.evaluate("() => AnnotateEdit.editor().getText()").startswith("Paragraph one of block 2")
    assert _draft_keys(other) == []


def test_discarding_in_the_editor_clears_the_draft(page, document):
    _open(page, "section-2")
    _set_text(page, DRAFT)
    page.wait_for_function("() => Object.keys(localStorage).some(k => k.startsWith('annotate.edit.draft.'))",
                           timeout=T(5000))
    _bar(page, "discard")
    _bar(page, "confirm-discard")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert _draft_keys(page) == []


def test_take_theirs_after_a_cmd_s_leaves_no_stale_edit_mark(page, document):
    _open(page, "section-2")
    _set_text(page, "My first saved words.")
    with page.expect_response(lambda r: r.request.method == "PUT" and r.url.endswith("/items/section-2")):
        page.keyboard.press("ControlOrMeta+s")
    page.wait_for_function("() => document.querySelector('.ed-bar .ed-state')?.textContent === 'Editing'",
                           timeout=T(5000))
    _set_text(page, "My second unsaved words.")
    _put_block(document, "section-2", "Theirs, from another tab.", title="Block 2")
    page.wait_for_function(
        "() => !!document.querySelector('section.block[data-block-id=\"section-2\"]')._pendingBlock", timeout=T(10000))
    _bar(page, "done")
    page.wait_for_selector(".ed-bar--conflict", timeout=T(5000))
    _bar(page, "take-theirs")
    page.wait_for_selector(".ed-host", state="detached", timeout=T(5000))
    assert [m["after"] for m in _edit_marks(page)] in ([], ["Theirs, from another tab."])


def test_f6_moves_focus_between_the_editor_and_the_bar(page):
    _open(page, "section-2")
    page.evaluate("() => AnnotateEdit.editor().view.focus()")
    page.keyboard.press("F6")
    first = page.evaluate("() => document.querySelector('.ed-bar button') === document.activeElement")
    assert first, page.evaluate("() => document.activeElement.outerHTML.slice(0, 120)")
    page.keyboard.press("F6")
    assert page.evaluate("() => AnnotateEdit.editor().isFocused()")


def test_the_bar_state_is_a_live_region_and_the_text_is_labelled(page, document):
    _open(page, "section-2")
    st = page.evaluate("""() => { const s = document.querySelector('.ed-bar .ed-state');
      return [s.getAttribute('role'), s.getAttribute('aria-live')]; }""")
    assert st == ["status", "polite"]
    assert page.get_attribute(".ed-host [role=textbox]", "aria-label") == "Section text"
    page.keyboard.type("x")
    assert page.get_attribute(".ed-host [role=textbox]", "aria-label") == "Section text"
    _source(page)
    assert page.get_attribute(".ed-host .cm-content", "aria-label") == "Section text (markdown)"
    # The conflict's words are announced from the same region.
    _put_block(document, "section-2", "Theirs.", title="Block 2")
    page.wait_for_function(
        "() => !!document.querySelector('section.block[data-block-id=\"section-2\"]')._pendingBlock", timeout=T(10000))
    _bar(page, "done")
    page.wait_for_selector(".ed-bar--conflict", timeout=T(5000))
    live = page.evaluate("() => [...document.querySelectorAll('.ed-bar [aria-live]')].map(e => e.textContent)")
    assert live == ["This section changed while you were editing. Nothing has been overwritten."]


def test_export_drops_the_your_words_badge(page, document):
    _edit(page, "section-1", SHORT_1)
    page.wait_for_selector(SEL.format("section-1") + "[data-mine]", timeout=T(5000))
    html = page.evaluate("() => AnnotateExport.buildProse()")
    assert "data-mine" not in html


def test_read_aloud_on_a_section_in_the_editor_says_close_it(page):
    _open(page, "section-2")
    page.evaluate("() => { document.activeElement?.blur?.(); AnnotateKeyboard.focusBlock('section-2'); }")
    page.keyboard.press("r")
    assert _toast(page) == "Close the editor to listen"
    assert page.locator(".sp-card, .sp-head").count() == 0
    page.evaluate("""() => AnnotateSpeech.play({section: document.querySelector(
      'section.block[data-block-id="section-2"]'), anchor: null, range: null, whole: true}, 'read')""")
    assert page.locator(".sp-head").count() == 0


def test_search_skips_the_hidden_text_of_a_section_in_the_editor(page):
    _open(page, "section-2")
    _set_text(page, "Quokka words only.")
    page.fill("#block-search", "long enough to scroll")
    page.wait_for_selector(SEL.format("section-2") + ".search-hidden", state="attached", timeout=T(5000))
    assert page.locator(SEL.format("section-1") + ".search-hidden").count() == 0
    page.fill("#block-search", "Quokka")
    page.wait_for_selector(SEL.format("section-1") + ".search-hidden", state="attached", timeout=T(5000))
    assert page.locator(SEL.format("section-2") + ".search-hidden").count() == 0
    assert page.locator(".ed-host mark.search-hit").count() == 0, "search wrote into the editor's DOM"
    assert page.evaluate("() => AnnotateEdit.editor().getText()") == "Quokka words only."
