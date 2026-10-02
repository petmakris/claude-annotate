# skills/annotate/tests/test_browser_rich.py
"""AnnotateRich in a bare page: no daemon, no annotate shell. The page's
markdown-it and the rich bundle (static/vendor/rich.min.js) are loaded into
the smallest page that can host them, and driven through mount()'s handle.

Every case asserts the exact saved string: the user's edit is final, and a
small edit saves as a small change, so untouched bytes never move. The
fixtures in data/rich are invented sections shaped like real pages: one
HTML section written on one line with data-annotate-id and style
attributes, and a page of markdown sections with lists, tables, a raw HTML
table, fenced code and a hard-wrapped paragraph."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

ANNOTATE = Path(__file__).resolve().parents[1]
STATIC = ANNOTATE / "static"
BUNDLE = STATIC / "vendor" / "rich.min.js"
DATA = Path(__file__).resolve().parent / "data" / "rich"
HTML = (DATA / "html-section.html.txt").read_text(newline="")
MD = json.loads((DATA / "markdown-page.json").read_text())

SLACK = ('<meta charset="utf-8"><span style="color: rgb(29, 28, 29); font-family: Slack-Lato, Slack-Fractions, appleLogo, sans-serif; '
         'font-size: 15px; font-style: normal; font-variant-ligatures: common-ligatures; font-weight: 400; background-color: rgb(248, 248, 248); display: inline !important;">'
         '<b data-stringify-type="bold">Heads up</b>: the <code data-stringify-type="code" class="c-mrkdwn__code">deploy</code> moved to '
         '<a target="_blank" class="c-link" data-stringify-link="https://example.com/x" delay="150" data-sk="tooltip_parent" href="https://example.com/x" rel="noopener noreferrer">Thursday</a>, '
         '<i data-stringify-type="italic">probably</i>.</span>'
         '<ul data-stringify-type="unordered-list" data-list-tree="true" class="p-rich_text_list p-rich_text_list__bullet" data-indent="0" data-border="0">'
         '<li data-stringify-indent="0" data-stringify-border="0" style="font-size: 15px">first <span style="font-weight:700">point</span></li>'
         '<li data-stringify-indent="0" data-stringify-border="0">second point</li></ul>')
SLACK_TEXT = "Heads up: the deploy moved to Thursday, probably.\nfirst point\nsecond point"
SLACK_MD = "**Heads up**: the `deploy` moved to [Thursday](https://example.com/x), *probably*.\n\n- first **point**\n- second point"
SLACK_HTML = ('<p><strong>Heads up</strong>: the <code>deploy</code> moved to <a href="https://example.com/x">Thursday</a>, '
              '<em>probably</em>.</p><ul><li>first <strong>point</strong></li><li>second point</li></ul>')
GDOCS = ('<meta charset="utf-8"><b style="font-weight:normal;" id="docs-internal-guid-1a2b3c4d-7fff-1234-5678-9abcdef01234">'
 '<p dir="ltr" style="line-height:1.38;margin-top:0pt;margin-bottom:0pt;"><span style="font-size:11pt;font-family:Arial,sans-serif;color:#000000;background-color:transparent;font-weight:400;font-style:normal;font-variant:normal;text-decoration:none;vertical-align:baseline;white-space:pre;white-space:pre-wrap;">Plain start </span>'
 '<span style="font-size:11pt;font-family:Arial,sans-serif;color:#000000;background-color:transparent;font-weight:700;font-style:normal;">bold bit</span>'
 '<span style="font-size:11pt;font-family:Arial,sans-serif;font-weight:400;font-style:italic;"> and italic</span>'
 '<span style="font-size:11pt;font-family:\'Courier New\',monospace;font-weight:400;"> mono</span></p>'
 '<ul style="margin-top:0;margin-bottom:0;padding-inline-start:48px;"><li dir="ltr" style="list-style-type:disc;font-size:11pt;" aria-level="1"><p dir="ltr" style="line-height:1.38;" role="presentation"><span style="font-size:11pt;font-weight:400;">first item</span></p></li></ul>'
 '<p dir="ltr"><a href="https://example.com/g" style="text-decoration:none;"><span style="font-size:11pt;color:#1155cc;text-decoration:underline;">a link</span></a></p></b><br class="Apple-interchange-newline">')
GTEXT = "Plain start bold bit and italic mono\nfirst item\na link"
CONFLUENCE = ('<meta charset="utf-8"><h2 id="Page-Overview" style="margin: 10px 0px 0px; padding: 0px; color: rgb(23, 43, 77);">Overview</h2>'
 '<p style="margin: 10px 0px 0px;">Some <strong>strong</strong> and <em>em</em> with <code style="font-family: SFMono-Medium;">inline</code> and '
 '<span class="confluence-link"><a href="https://example.com/c" data-linked-resource-id="12345" class="external-link" rel="nofollow">ref</a></span>.</p>'
 '<div class="table-wrap"><table class="confluenceTable" data-layout="default"><colgroup><col style="width: 120px;"><col></colgroup><tbody>'
 '<tr><th class="confluenceTh"><p>Key</p></th><th class="confluenceTh"><p>Value</p></th></tr>'
 '<tr><td class="confluenceTd"><p>k1</p></td><td class="confluenceTd"><p>v1 <span style="color: rgb(255,0,0);">red</span></p></td></tr></tbody></table></div>'
 '<div class="code panel pdl conf-macro output-block" data-macro-name="code"><div class="codeContent panelContent pdl"><pre class="syntaxhighlighter-pre" data-syntaxhighlighter-params="brush: java">int x = 1;\nreturn x;</pre></div></div>'
 '<div class="confluence-information-macro confluence-information-macro-note conf-macro" data-macro-name="note"><span class="aui-icon icon-hint"></span><div class="confluence-information-macro-body"><p>A note panel.</p></div></div>'
 '<ul class="inline-task-list" data-inline-tasks-content-id="9"><li data-inline-task-id="1" class="checked">done task</li></ul>')
CONFLUENCE_TEXT = "Overview\nSome strong..."


MOD = "ControlOrMeta"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.set_content('<!doctype html><meta charset="utf-8"><body></body>')
    pg.add_script_tag(path=str(STATIC / "markdown-it.min.js"))
    pg.add_script_tag(path=str(STATIC / "anchors.js"))
    pg.add_script_tag(path=str(BUNDLE))
    yield pg
    pg.close()
    assert not errors, errors


def mount(page, text, fmt=None):
    return page.evaluate("""([t, f]) => {
        document.body.innerHTML = '<div id=h></div>';
        const fmt = f || AnnotateRich.formatOf(t);
        window.ed = AnnotateRich.mount(document.getElementById('h'), {text: t, format: fmt});
        return fmt; }""", [text, fmt])


def select(page, word, collapse=None):
    """Select the first `word` in the document (or put the cursor at its
    start or end) and focus the editor."""
    assert page.evaluate("""([w, c]) => { const v = ed.view; let at = null;
        v.state.doc.descendants((n, p) => { if (at || !n.isText) return !at;
          const i = n.text.indexOf(w); if (i >= 0) at = [p + i, p + i + w.length]; return false; });
        if (!at) return false; const {TextSelection} = AnnotateRich.pm;
        const a = c === 'end' ? at[1] : at[0], b = c === 'start' ? at[0] : at[1];
        v.dispatch(v.state.tr.setSelection(TextSelection.create(v.state.doc, a, b))); v.focus(); return true; }""",
                         [word, collapse]), f"not found: {word}"


def edit_word(page, old, new):
    """Select the first `old` in the document and type `new` over it, as a reader would."""
    select(page, old)
    page.keyboard.insert_text(new)


def end_of_doc(page):
    page.evaluate("""() => { const v = ed.view; const {TextSelection} = AnnotateRich.pm;
        v.dispatch(v.state.tr.setSelection(TextSelection.atEnd(v.state.doc))); v.focus(); }""")


def saved(page):
    return page.evaluate("() => ed.getText()")


def stats(page):
    return page.evaluate("() => ed.stats()")


def paste(page, html, text):
    page.evaluate("""([h, t]) => { const dt = new DataTransfer(); dt.setData('text/html', h); dt.setData('text/plain', t);
        ed.view.dom.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); }""",
                  [html, text])


# ── HTML section ──────────────────────────────────────────────────────────

def test_html_untouched_save_is_byte_identical(page):
    assert mount(page, HTML) == "html"
    assert saved(page) == HTML


def test_html_one_word_edit_in_a_paragraph(page):
    mount(page, HTML)
    edit_word(page, "posted", "sent")
    assert saved(page) == HTML.replace("posted", "sent", 1)
    assert stats(page)["fresh"] == 0


def test_html_edit_inside_an_li_with_an_id(page):
    mount(page, HTML)
    edit_word(page, "Fill", "Populate")
    out = saved(page)
    assert out == HTML.replace("Fill", "Populate", 1)
    assert 'data-annotate-id="s-sku">Read the SKU from the catalogue, not from the cart. Populate it.' in out


def test_html_attributes_survive_edits_in_attributed_blocks(page):
    mount(page, HTML)
    edit_word(page, "Fill", "Populate")              # <li data-annotate-id>
    edit_word(page, "Add the line items", "Put the line items")  # <p data-annotate-id>
    edit_word(page, "This is a draft", "This is a sketch")      # <p style>
    out = saved(page)
    assert out == (HTML.replace("Fill", "Populate", 1).replace("Add the line items", "Put the line items", 1)
                   .replace("This is a draft", "This is a sketch", 1))
    assert out.count('data-annotate-id="') == HTML.count('data-annotate-id="') == 21
    assert out.count('style="') == HTML.count('style="') == 3


# ── markdown sections ─────────────────────────────────────────────────────

@pytest.mark.parametrize("key", sorted(MD))
def test_markdown_untouched_save_is_identical(page, key):
    assert mount(page, MD[key]) == "md"
    assert saved(page) == MD[key]


def test_markdown_one_word_edit(page):
    mount(page, MD["keep-out"])
    edit_word(page, "later", "follow-up")
    assert saved(page) == MD["keep-out"].replace("later", "follow-up", 1)
    assert stats(page)["fresh"] == 0


def test_markdown_edit_inside_a_list_item(page):
    mount(page, MD["applied"])
    edit_word(page, "stay as they were", "remain as they were")
    assert saved(page) == MD["applied"].replace("stay as they were", "remain as they were", 1)


def test_markdown_edit_inside_a_table_cell(page):
    mount(page, MD["columns"])
    edit_word(page, "tools ignore", "tools skip")
    assert saved(page) == MD["columns"].replace("tools ignore", "tools skip", 1)


def test_markdown_edit_inside_a_raw_html_table_cell(page):
    src = MD["sheet"]
    mount(page, src)
    edit_word(page, "Status of the seedling tray", "State of the seedling tray")
    out = saved(page)
    assert out == src.replace("Status of the seedling tray", "State of the seedling tray", 1)
    assert out.count('data-annotate-id="') == src.count('data-annotate-id="') == 2
    assert out.count('style="') == src.count('style="')


def test_markdown_edit_inside_a_fenced_code_block(page):
    mount(page, MD["applied"])
    edit_word(page, "String status,", "String state,")
    assert saved(page) == MD["applied"].replace("String status,", "String state,", 1)


def test_markdown_hard_wrapped_paragraph_keeps_every_newline(page):
    src = MD["wrapped"]
    mount(page, src)
    edit_word(page, "and markdown joins", "so markdown joins")
    out = saved(page)
    assert out == src.replace("and\nmarkdown joins", "so\nmarkdown joins", 1)
    assert out.count("\n") == src.count("\n")


def test_markdown_word_edit_inside_a_wrapped_line(page):
    src = MD["wrapped"]
    mount(page, src)
    edit_word(page, "where the column did", "where the margin did")
    assert saved(page) == src.replace("where the column did", "where the margin did", 1)


# ── typed structure ───────────────────────────────────────────────────────

BULLET = "A new bullet with **bold** and `code` typed."


def test_markdown_typed_bullet_then_heading(page):
    src = MD["verbatim"]
    mount(page, src)
    end_of_doc(page)
    page.keyboard.press("Enter")
    page.keyboard.type("- " + BULLET)
    assert saved(page) == src + "\n\n- " + BULLET
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("## A new heading")
    assert saved(page) == src + "\n\n- " + BULLET + "\n\n## A new heading"


def test_html_typed_bullet_then_heading(page):
    mount(page, HTML)
    end_of_doc(page)
    page.keyboard.press("Enter")
    page.keyboard.type("- " + BULLET)
    li = "<ul><li>A new bullet with <strong>bold</strong> and <code>code</code> typed.</li></ul>"
    assert saved(page) == HTML + li
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("## A new heading")
    assert saved(page) == HTML + li + "<h2>A new heading</h2>"


def test_markdown_deleting_a_block_drops_it_and_one_separator(page):
    src = MD["applied"]
    mount(page, src)
    page.evaluate("""() => { const v = ed.view, d = v.state.doc; const from = d.child(0).nodeSize;
        v.dispatch(v.state.tr.delete(from, from + d.child(1).nodeSize)); }""")
    first, second, rest = src.split("\n\n", 2)
    assert saved(page) == first + "\n\n" + rest


def test_a_comment_block_survives_untouched_and_edited_saves(page):
    src = "Intro words.\n\n<!-- a note for the author -->\n\nMore words.\n"
    mount(page, src)
    assert saved(page) == src
    edit_word(page, "More", "Other")
    assert saved(page) == src.replace("More", "Other")


def test_ids_the_stored_text_already_repeats_are_left_alone(page):
    src = '<p data-annotate-id="x">One.</p><p data-annotate-id="x">Two.</p><p>Three.</p>'
    mount(page, src)
    edit_word(page, "Three", "Four")
    assert saved(page) == src.replace("Three", "Four")


def test_enter_in_an_li_with_an_id_does_not_copy_the_id(page):
    mount(page, HTML)
    select(page, "Fill it.", "end")
    page.keyboard.press("Enter")
    page.keyboard.type("Split-off bullet")
    out = saved(page)
    assert out == HTML.replace("Fill it.</li>", "Fill it.</li><li>Split-off bullet</li>", 1)


# ── reference links ───────────────────────────────────────────────────────

REFS = 'See [the docs][1] and [faq].\n\nOther para here.\n\n[1]: https://example.com/docs "Docs"\n[faq]: https://example.com/faq\n'


def test_reference_definitions_stay_when_another_paragraph_is_edited(page):
    mount(page, REFS)
    edit_word(page, "Other", "Another")
    assert saved(page) == REFS.replace("Other", "Another")
    assert stats(page)["kept"] == 1


def test_reference_definitions_stay_when_a_paragraph_is_deleted(page):
    mount(page, REFS)
    page.evaluate("""() => { const v = ed.view, d = v.state.doc; const from = d.child(0).nodeSize;
        v.dispatch(v.state.tr.delete(from, from + d.child(1).nodeSize)); }""")
    assert saved(page) == REFS.replace("Other para here.\n\n", "")


def test_editing_a_reference_links_text_keeps_the_reference_form(page):
    mount(page, REFS)
    edit_word(page, "the", "our")
    assert saved(page) == REFS.replace("[the docs][1]", "[our docs][1]")



REFS_BETWEEN = ('See [the docs][1] here.\n\n[1]: https://example.com/docs "Docs"\n\nMiddle para.\n\n'
                'Tail [faq] para.\n\n[faq]: https://example.com/faq\n')


@pytest.mark.parametrize("i,gone", [(0, "See [the docs][1] here.\n\n"), (1, "Middle para.\n\n"), (2, "Tail [faq] para.\n\n")])
def test_deleting_any_paragraph_keeps_every_definition(page, i, gone):
    mount(page, REFS_BETWEEN)
    page.evaluate("""(i) => { const v = ed.view, d = v.state.doc; let pos = 0;
        for (let k = 0; k < i; k++) pos += d.child(k).nodeSize;
        v.dispatch(v.state.tr.delete(pos, pos + d.child(i).nodeSize)); }""", i)
    out = saved(page)
    assert out == REFS_BETWEEN.replace(gone, "", 1)
    assert '[1]: https://example.com/docs "Docs"\n' in out and out.endswith("[faq]: https://example.com/faq\n")

# ── moves, splits, empty paragraphs ───────────────────────────────────────

MOVES = "Alpha one\nwrapped here.\n\n* star item\n* second star\n\nGamma para.\n\nDelta *em*  end.\n"


def move(page, i, j):
    """Move top-level node i to before node j in one transaction, as a drag does."""
    page.evaluate("""([i, j]) => { const v = ed.view, d = v.state.doc;
        const posOf = (k) => { let p = 0; for (let q = 0; q < k; q++) p += d.child(q).nodeSize; return p; };
        const n = d.child(i), a = posOf(i); const tr = v.state.tr.delete(a, a + n.nodeSize);
        tr.insert(tr.mapping.map(posOf(j)), n); v.dispatch(tr); }""", [i, j])


def test_a_moved_paragraph_keeps_its_stored_bytes(page):
    mount(page, MOVES)
    move(page, 0, 3)
    assert saved(page) == "* star item\n* second star\n\nGamma para.\n\nAlpha one\nwrapped here.\n\nDelta *em*  end.\n"
    assert stats(page)["fresh"] == 0


def test_a_moved_html_block_keeps_its_style_as_stored(page):
    src = '<p data-annotate-id="a1" class="x">First</p>\n<ul><li data-annotate-id="b">one</li></ul>\n<p style="color:red">Third</p>'
    mount(page, src)
    move(page, 2, 0)
    assert saved(page) == ('<p style="color:red">Third</p>\n<p data-annotate-id="a1" class="x">First</p>\n'
                           '<ul><li data-annotate-id="b">one</li></ul>')


def test_a_fresh_html_write_keeps_style_as_stored(page):
    src = '<p>First</p>\n<p style="color:red;margin:0">Third</p>'
    mount(page, src)
    move(page, 1, 0)
    page.evaluate("() => { const v = ed.view; v.dispatch(v.state.tr.insertText('!', v.state.doc.child(0).nodeSize - 1)); }")
    assert saved(page) == '<p style="color:red;margin:0">Third!</p>\n<p>First</p>'
    assert stats(page)["fresh"] == 1


def test_enter_splitting_a_one_line_paragraph_stores_one_blank_line(page):
    src = "Alpha one two.\n\nBeta.\n"
    mount(page, src)
    select(page, "one", "end")
    page.keyboard.press("Enter")
    assert saved(page) == "Alpha one\n\ntwo.\n\nBeta.\n"


@pytest.mark.parametrize("word,where", [("one:", "end"), ("every", "start"), ("the column", "end")])
def test_enter_in_a_hard_wrapped_paragraph_stores_one_blank_line(page, word, where):
    src = MD["wrapped"]
    mount(page, src)
    select(page, word, where)
    page.keyboard.press("Enter")
    out = saved(page)
    if word == "the column":
        assert out == src.replace("the column did", "the column\n\ndid", 1)
    else:
        assert out == src.replace("one:\nevery", "one:\n\nevery", 1)
    assert "\n\n\n" not in out



def test_enter_twice_inside_a_fence_stores_the_blank_lines_as_typed(page):
    src = "```\na\nb\n```\n\nNext.\n"
    mount(page, src)
    select(page, "a", "end")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    assert saved(page) == "```\na\n\n\nb\n```\n\nNext.\n"
    assert stats(page)["fresh"] == 0

def test_empty_paragraphs_are_not_stored_as_blank_lines(page):
    src = "Alpha one two.\n\nBeta.\n"
    mount(page, src)
    end_of_doc(page)
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    assert saved(page) == src
    page.keyboard.type("Gamma.")
    assert saved(page) == "Alpha one two.\n\nBeta.\n\nGamma.\n"


# ── paste ─────────────────────────────────────────────────────────────────

def test_markdown_paste_from_slack_stores_clean_markdown(page):
    src = MD["verbatim"]
    mount(page, src)
    end_of_doc(page)
    page.keyboard.press("Enter")
    paste(page, SLACK, SLACK_TEXT)
    assert saved(page) == src + "\n\n" + SLACK_MD


def test_html_paste_from_slack_stores_clean_html(page):
    mount(page, HTML)
    select(page, 'it stays in "Backlog".', "end")
    page.keyboard.press("Enter")
    paste(page, SLACK, SLACK_TEXT)
    out = saved(page)
    first = out.index("</p>") + 4
    assert out == HTML[:first] + SLACK_HTML + HTML[first:]
    added = SLACK_HTML
    for bad in ("style", "class", "<span", "data-stringify", "<b>", "<i>", "target=", "<meta"):
        assert bad not in added



FOREIGN = ("style", "class", "<span", "<div", "data-", "id=", "dir=", "role=", "<colgroup", "<col", "docs-internal", "<b>", "<b ")


@pytest.mark.parametrize("fmt,base", [("md", "Start para.\n"), ("html", "<p>Start para.</p>")])
def test_google_docs_paste_keeps_only_the_bold_that_is_bold(page, fmt, base):
    mount(page, base, fmt)
    end_of_doc(page)
    page.keyboard.press("Enter")
    paste(page, GDOCS, GTEXT)
    out = saved(page)
    if fmt == "md":
        assert out == ("Start para.\n\nPlain start **bold bit** *and italic*` mono`\n\n- first item\n\n"
                       "[a link](https://example.com/g)\n")
    else:
        assert out == ('<p>Start para.</p><p>Plain start <strong>bold bit</strong><em> and italic</em><code> mono</code></p>'
                       '<ul><li>first item</li></ul><p><a href="https://example.com/g">a link</a></p>')
    for bad in FOREIGN:
        assert bad not in out


@pytest.mark.parametrize("fmt,base", [("md", "Start para.\n"), ("html", "<p>Start para.</p>")])
def test_confluence_paste_keeps_tables_code_and_panels_as_schema_structure(page, fmt, base):
    mount(page, base, fmt)
    end_of_doc(page)
    page.keyboard.press("Enter")
    paste(page, CONFLUENCE, CONFLUENCE_TEXT)
    out = saved(page)
    if fmt == "md":
        assert out == ("Start para.\n\n## Overview\n\nSome **strong** and *em* with `inline` and [ref](https://example.com/c).\n\n"
                       "| Key | Value |\n|---|---|\n| k1 | v1 red |\n\n```java\nint x = 1;\nreturn x;\n```\n\n"
                       "> A note panel.\n\n- done task\n")
    else:
        assert out == ('<p>Start para.</p><h2>Overview</h2><p>Some <strong>strong</strong> and <em>em</em> with <code>inline</code> '
                       'and <a href="https://example.com/c">ref</a>.</p><table><tbody><tr><th>Key</th><th>Value</th></tr>'
                       '<tr><td>k1</td><td>v1 red</td></tr></tbody></table><pre><code class="language-java">int x = 1;\nreturn x;</code></pre>'
                       '<blockquote><p>A note panel.</p></blockquote><ul><li>done task</li></ul>')
    for bad in FOREIGN:
        assert bad not in out.replace('class="language-java"', "")


def test_paste_joins_paragraphs_in_a_cell_with_line_breaks(page):
    mount(page, "Start.\n")
    end_of_doc(page)
    page.keyboard.press("Enter")
    paste(page, '<table><tr><th><p>A</p></th></tr><tr><td><p>one</p><p>two</p><ul><li>x</li><li>y</li></ul></td></tr></table>', "A")
    assert page.evaluate("() => ed.view.state.doc.child(1).toString()") == \
        'table(table_row(table_header("A")), table_row(table_cell("one", hard_break, "two", hard_break, "x", hard_break, "y")))'



CELLS = ('<div class="table-wrap"><table class="confluenceTable"><colgroup><col style="width:100px"></colgroup><tbody>'
         '<tr><th class="confluenceTh"><div class="tablesorter-header-inner">Key</div></th><th class="confluenceTh"><p>Val</p></th></tr>'
         '<tr><td class="confluenceTd">\n<p>one</p>\n<p>two</p>\n<ul><li>a</li><li>b<ul><li>b1</li></ul></li></ul>\n</td>'
         '<td class="confluenceTd"><p><strong>bold</strong> x</p><ol><li>n1</li></ol><p>tail</p></td></tr>'
         '<tr><td>in</td><td><table><tr><td>in1</td><td>in2</td></tr></table></td></tr></tbody></table></div>')


def test_a_pasted_table_cell_with_lines_stores_br_in_markdown_and_renders_the_breaks(page):
    mount(page, "Start para.\n")
    end_of_doc(page)
    page.keyboard.press("Enter")
    paste(page, CELLS, "Key Val")
    out = saved(page)
    assert out == ("Start para.\n\n| Key | Val |\n|---|---|\n| one<br>two<br>a<br>b<br>b1 | **bold** x<br>n1<br>tail |\n"
                   "| in | in1<br>in2 |\n")
    html = page.evaluate("(t) => markdownit({html: true}).render(t)", out)
    assert "<td>one<br>two<br>a<br>b<br>b1</td>" in html and "<td>in1<br>in2</td>" in html


def test_a_pasted_table_cell_with_lines_in_html(page):
    mount(page, "<p>Start para.</p>")
    end_of_doc(page)
    page.keyboard.press("Enter")
    paste(page, CELLS, "Key Val")
    assert saved(page) == ('<p>Start para.</p><table><tbody><tr><th>Key</th><th>Val</th></tr>'
                           '<tr><td>one<br>two<br>a<br>b<br>b1</td><td><strong>bold</strong> x<br>n1<br>tail</td></tr>'
                           '<tr><td>in</td><td>in1<br>in2</td></tr></tbody></table>')


def test_a_confluence_panel_keeps_its_title_in_bold(page):
    mount(page, "Start para.\n")
    end_of_doc(page)
    page.keyboard.press("Enter")
    paste(page, '<div class="confluence-information-macro confluence-information-macro-information"><p class="title">Heads up</p>'
                '<span class="aui-icon aui-icon-small aui-iconfont-info confluence-information-macro-icon"></span>'
                '<div class="confluence-information-macro-body"><p>Body one.</p><ul><li>pt</li></ul></div></div><p>After.</p>', "x")
    assert saved(page) == "Start para.\n\n> **Heads up**\n>\n> Body one.\n>\n> - pt\n\nAfter.\n"

# ── keys ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,mark", [("b", "**"), ("i", "*"), ("e", "`")])
def test_mod_keys_toggle_marks(page, key, mark):
    src = MD["keep-out"]
    mount(page, src)
    select(page, "later")
    page.keyboard.press(f"{MOD}+{key}")
    assert saved(page) == src.replace("A later", f"A {mark}later{mark}", 1)
    page.keyboard.press(f"{MOD}+{key}")
    assert saved(page) == src


def test_mod_z_undoes(page):
    src = MD["keep-out"]
    mount(page, src)
    edit_word(page, "later", "follow-up")
    assert saved(page) != src
    page.keyboard.press(f"{MOD}+z")
    assert saved(page) == src


def test_enter_on_an_empty_list_item_leaves_the_list(page):
    src = "- one\n- two\n"
    mount(page, src)
    select(page, "two", "end")
    page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.keyboard.type("after")
    assert saved(page) == "- one\n- two\n\nafter\n"


def test_tab_in_a_list_item_indents_it(page):
    mount(page, "- one\n- two\n")
    select(page, "two", "end")
    page.keyboard.press("Tab")
    assert saved(page) == "- one\n  - two\n"
    assert page.evaluate("() => ed.view.state.doc.child(0).child(0).childCount") == 2


def test_tab_in_a_table_cell_moves_to_the_next_cell_without_selecting(page):
    mount(page, "| a | b |\n|---|---|\n| 1 | 2 |\n")
    select(page, "a", "end")
    page.keyboard.press("Tab")
    assert page.evaluate("() => ed.view.state.selection.empty")
    page.keyboard.type("X")
    assert saved(page) == "| a | bX |\n|---|---|\n| 1 | 2 |\n"


def test_mod_k_asks_the_handle_for_a_link_and_set_link_applies_it(page):
    src = MD["keep-out"]
    mount(page, src)
    page.evaluate("() => { window.asked = 0; ed.onLinkRequest = (h) => { window.asked++; window.askedWith = h === ed; }; }")
    select(page, "later")
    page.keyboard.press(f"{MOD}+k")
    assert page.evaluate("() => [asked, askedWith]") == [1, True]
    assert page.evaluate("() => ed.linkAt()") is None
    page.evaluate("() => ed.setLink('https://example.com/l')")
    assert saved(page) == src.replace("A later", "A [later](https://example.com/l)", 1)
    select(page, "later", "start")
    assert page.evaluate("() => ed.linkAt().href") == "https://example.com/l"
    page.evaluate("() => ed.setLink(null)")
    assert saved(page) == src


def test_save_and_done_keys_call_back(page):
    page.evaluate("""() => { document.body.innerHTML = '<div id=h></div>'; window.calls = {save: 0, done: 0, change: 0};
        window.ed = AnnotateRich.mount(document.getElementById('h'), {text: 'Some words.', format: 'md',
          onSave: () => calls.save++, onDone: () => calls.done++, onChange: () => calls.change++}); }""")
    select(page, "words")
    page.keyboard.insert_text("text")
    page.keyboard.press(f"{MOD}+s")
    page.keyboard.press("Escape")
    assert page.evaluate("() => calls") == {"save": 1, "done": 1, "change": 1}


# ── Review Focus 1: inline HTML inside a markdown paragraph ───────────────

def test_inline_html_in_a_markdown_paragraph_is_kept_byte_for_byte(page):
    src = "Press <kbd>Esc</kbd> to close.<br>Then **save** the file."
    mount(page, src)
    edit_word(page, "close", "dismiss")
    assert saved(page) == src.replace("close", "dismiss")


def test_inline_span_and_sup_in_a_markdown_paragraph_are_kept(page):
    src = 'See <span style="color:red">this</span> note<sup>1</sup> and the rest.\n'
    mount(page, src)
    edit_word(page, "rest", "remainder")
    assert saved(page) == src.replace("rest", "remainder")


# ── Review Focus 2: emoji, non-BMP, CRLF, lone CR ────────────────────────

EMOJI_CRLF = "Ship it 🚀 now.\r\nNext line 😀 here.\r\n"


def test_emoji_crlf_untouched_is_identical(page):
    mount(page, EMOJI_CRLF)
    assert saved(page) == EMOJI_CRLF


def test_emoji_crlf_edit_is_byte_exact(page):
    mount(page, EMOJI_CRLF)
    edit_word(page, "now", "today")
    assert saved(page) == EMOJI_CRLF.replace("now", "today")


def test_emoji_crlf_blocks_edit_is_byte_exact(page):
    src = "# Title 🚀\r\n\r\nFirst 𝔘 para.\r\n\r\n- item 😀 one\r\n- item two\r\n"
    mount(page, src)
    assert saved(page) == src
    edit_word(page, "two", "deux")
    assert saved(page) == src.replace("two", "deux")
    assert stats(page)["kept"] == 2


LONE_CR = "First line 🚀\rsecond line\r\rNext para here.\r"


def test_lone_cr_untouched_is_identical(page):
    mount(page, LONE_CR)
    assert saved(page) == LONE_CR


def test_lone_cr_edit_is_byte_exact(page):
    mount(page, LONE_CR)
    edit_word(page, "Next", "Last")
    assert saved(page) == LONE_CR.replace("Next", "Last")
    assert stats(page)["kept"] == 1  # the blocks split on lone CRs: the first paragraph is untouched
    edit_word(page, "second", "2nd")
    assert saved(page) == LONE_CR.replace("Next", "Last").replace("second", "2nd")


# ── Review Focus 3: nested and task lists ─────────────────────────────────

LISTS = "1. First\n   - nested a\n   - nested b\n2. Second\n\n- [ ] todo one\n- [x] done two\n"


def test_nested_list_edit_keeps_markers_and_indentation(page):
    mount(page, LISTS)
    assert saved(page) == LISTS
    edit_word(page, "nested b", "nested bee")
    assert saved(page) == LISTS.replace("nested b", "nested bee")


def test_task_list_edit_keeps_the_checkbox(page):
    mount(page, LISTS)
    edit_word(page, "todo one", "todo uno")
    assert saved(page) == LISTS.replace("todo one", "todo uno")


# ── Review Focus 4: a large section ───────────────────────────────────────

def test_a_60kb_section_opens_and_saves_a_word_in_under_a_second(page):
    one = "\n\n".join(MD.values())
    big = one
    while len(big) < 60_000:
        big += "\n\n" + one
    ms = page.evaluate("""(t) => { document.body.innerHTML = '<div id=h></div>';
        const t0 = performance.now();
        window.ed = AnnotateRich.mount(document.getElementById('h'), {text: t, format: AnnotateRich.formatOf(t)});
        const v = ed.view; let at = null;
        v.state.doc.descendants((n, p) => { if (at || !n.isText) return !at;
          const i = n.text.indexOf('later'); if (i >= 0) at = [p + i, p + i + 5]; return false; });
        v.dispatch(v.state.tr.insertText('follow-up', at[0], at[1]));
        window.out = ed.getText();
        return performance.now() - t0; }""", big)
    assert page.evaluate("() => out") == big.replace("later", "follow-up", 1)
    assert ms < 1000, f"{ms:.0f} ms"


# ── canShow, formatOf ─────────────────────────────────────────────────────

def test_can_show_refuses_merged_cells(page):
    for fmt, text in [("html", '<table><tr><td colspan="2">a</td></tr><tr><td>b</td><td>c</td></tr></table>'),
                      ("md", 'Text\n\n<table><tr><td rowspan="2">a</td><td>b</td></tr><tr><td>c</td></tr></table>\n')]:
        assert page.evaluate("([t, f]) => AnnotateRich.canShow(t, f)", [text, fmt]) == "this section has a table with merged cells"



@pytest.mark.parametrize("fmt,text", [
    ("html", '<p>Intro words.</p>\n<table><tr><th>Step</th><th>Notes</th></tr><tr><td>one</td><td><ul><li>alpha</li><li>beta</li></ul></td></tr></table>'),
    ("html", '<table><tr><td>two</td><td><p>para a</p><p>para b</p></td></tr></table>'),
    ("md", "Intro.\n\n<table>\n<tr><td>\n\n- a\n- b\n\n</td></tr>\n</table>\n\nEnd.\n"),
])
def test_can_show_refuses_cells_that_hold_blocks(page, fmt, text):
    assert page.evaluate("([t, f]) => AnnotateRich.canShow(t, f)", [text, fmt]) == "this section couldn't be read as blocks"


def test_can_show_accepts_the_fixtures(page):
    assert page.evaluate("(t) => AnnotateRich.canShow(t, 'html')", HTML) is None
    for text in MD.values():
        assert page.evaluate("(t) => AnnotateRich.canShow(t, 'md')", text) is None


def test_format_of(page):
    f = lambda t: page.evaluate("(t) => AnnotateRich.formatOf(t)", t)  # noqa: E731
    assert f(HTML) == "html"
    assert f("\n  " + HTML) == "html"
    for text in MD.values():
        assert f(text) == "md"
    assert f("Text\n\n<table><tr><td>a</td></tr></table>\n") == "md"
    assert f("<div>\n\n**bold**\n\n</div>") == "md"
    assert f("") == "md"


# ── focusAt, setText, focus ───────────────────────────────────────────────

@pytest.mark.parametrize("key,word,before", [
    ("verbatim", "follow", "follow"), ("applied", "follow", "follow"), ("sheet", "reader", "reader"),
    # The cursor lands before the word; a word in *em* starts after its marker.
    ("survey", "readers", "*readers*")])
def test_focus_at_places_the_cursor_at_the_rendered_offset(page, key, word, before):
    src = MD[key]
    mount(page, src)
    off = page.evaluate("""([t, w]) => { const c = document.createElement('div'); c.className = 'block-content';
        c.innerHTML = window.markdownit({html: true}).render(t); return AnnotateAnchors.textOf(c).indexOf(w); }""", [src, word])
    assert off > 0
    page.evaluate("(o) => ed.focusAt(o)", off)
    assert page.evaluate("() => ed.isFocused()")
    page.keyboard.insert_text("X")
    assert saved(page) == src.replace(before, "X" + before, 1)


def test_focus_at_an_html_section(page):
    mount(page, HTML)
    off = page.evaluate("""(t) => { const c = document.createElement('div'); c.innerHTML = t;
        return AnnotateAnchors.textOf(c).indexOf('Fill'); }""", HTML)
    page.evaluate("(o) => ed.focusAt(o)", off)
    page.keyboard.insert_text("X")
    assert saved(page) == HTML.replace("Fill", "XFill", 1)


def test_focus_at_out_of_range_goes_to_the_start(page):
    mount(page, "Alpha.\n\nBeta.\n")
    page.evaluate("() => ed.focusAt(99999)")
    page.keyboard.insert_text("X")
    assert saved(page) == "XAlpha.\n\nBeta.\n"


def test_set_text_is_a_new_base(page):
    mount(page, "Alpha.\n")
    edit_word(page, "Alpha", "Beta")
    page.evaluate("() => ed.setText('Gamma  \\n\\n\\nDelta.\\n')")
    assert saved(page) == "Gamma  \n\n\nDelta.\n"
    edit_word(page, "Delta", "Epsilon")
    assert saved(page) == "Gamma  \n\n\nEpsilon.\n"


def test_mount_appends_one_rich_element_and_destroy_removes_it(page):
    mount(page, "Alpha.\n")
    assert page.evaluate("() => [...document.getElementById('h').children].map(c => c.className)") == ["block-content ed-rich"]
    assert page.evaluate("() => ed.isFocused()") is False
    page.evaluate("() => ed.focus()")
    assert page.evaluate("() => ed.isFocused()") is True
    page.evaluate("() => ed.destroy()")
    assert page.evaluate("() => document.getElementById('h').children.length") == 0


# ── paste: nothing that reaches out, nothing merged ───────────────────────

def test_paste_drops_images_unsafe_links_and_merged_cells(page):
    mount(page, "<p>Start para.</p>")
    select(page, "Start para.", "end")
    page.keyboard.press("Enter")
    paste(page, '<p>pic <img src="data:image/png;base64,AAAA"> and <img src="https://x.test/a.png" alt="a"> '
                '<a href="javascript:alert(1)">bad</a> <a href="https://x.test/ok">ok</a> '
                '<a href="mailto:a@x.test">mail</a></p>'
                '<table><tr><td colspan="2">wide</td></tr><tr><td rowspan="2">a</td><td>b</td></tr></table>',
          "pic and bad ok mail wide a b")
    out = saved(page)
    for bad in ("<img", "data:", "javascript:", "colspan", "rowspan"):
        assert bad not in out, (bad, out)
    assert '<a href="https://x.test/ok">ok</a>' in out
    assert '<a href="mailto:a@x.test">mail</a>' in out
    assert "bad" in out and "wide" in out


# ── canShow: content the model would drop or flatten ──────────────────────

@pytest.mark.parametrize("fmt,text", [
    ("html", "<p>Before.</p><details><summary>More</summary><p>Hidden words.</p></details>"),
    ("md", "Before.\n\n<dl><dt>Term</dt><dd>Meaning</dd></dl>\n\nAfter."),
    ("md", 'Before.\n\n<svg width="10" height="10"><circle cx="5" cy="5" r="4"/></svg>\n\nAfter.'),
    ("html", '<p>Before.</p><iframe src="https://x.test"></iframe>'),
    ("html", "<p>Before.</p><figure><img src=\"https://x.test/a.png\"><figcaption>Cap</figcaption></figure>"),
])
def test_can_show_refuses_content_the_model_cannot_hold(page, fmt, text):
    assert page.evaluate("([t, f]) => AnnotateRich.canShow(t, f)", [text, fmt]) == \
        "this section has content Rich editing can't show"
