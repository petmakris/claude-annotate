# skills/annotate/tests/test_browser_editor.py
"""AnnotateEditor in a bare page: no daemon, no annotate shell. The bundle
(static/vendor/editor.min.js) is loaded into the smallest page that can host
it, a single <div id=host>, and driven through its public mount() handle."""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="browser suite: pip install playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

BUNDLE = Path(__file__).resolve().parents[1] / "static" / "vendor" / "editor.min.js"

PAGE = """<!doctype html><meta charset="utf-8"><body>
<div id="host" style="width:600px"></div>
<script>
  window.calls = {save: 0, done: 0, toggle: 0, change: []};
  window.pageKeys = [];
  document.addEventListener('keydown', (e) => window.pageKeys.push(e.key));
</script></body>"""

SAMPLES = [
    "Line one  \nline two (trailing two spaces kept)\n",
    "| a | b |\n|---|---|\n| 1 | 2 |\n",
    "```py\nx = 1\n```\n",
    "a hard-wrapped\nparagraph that\nstays wrapped",
    "crlf\r\nline\r\n",
    "> ⚠ a callout about ABC-310\n> second line\n\n# Heading\n\n- item **bold** *em* `code`\n",
    "",
    "a\rb\rc",                                   # lone CR line endings
    "a\rb\r",
    "inside\u2028one line\n",                    # U+2028 is not a break for CodeMirror
    "next\u0085line\n",                          # nor is U+0085 (NEL)
]


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    pg.set_content(PAGE)
    pg.add_script_tag(path=str(BUNDLE))
    yield pg
    pg.close()


def _mount(page, doc):
    page.evaluate(
        """(doc) => {
          window.ed = AnnotateEditor.mount(document.getElementById('host'), {
            doc,
            onSave: () => calls.save++,
            onDone: () => calls.done++,
            onToggleMode: () => calls.toggle++,
            onChange: (t) => calls.change.push(t),
          });
        }""",
        doc,
    )


def _text(page):
    return page.evaluate("() => ed.getText()")


@pytest.mark.parametrize("doc", SAMPLES, ids=range(len(SAMPLES)))
def test_get_text_returns_the_document_byte_for_byte(page, doc):
    _mount(page, doc)
    assert _text(page) == doc


def test_crlf_survives_a_typed_newline(page):
    _mount(page, "crlf\r\nline\r\n")
    page.evaluate("() => ed.focusAt(4)")
    page.keyboard.press("Enter")
    page.keyboard.type("new")
    assert _text(page) == "crlf\r\nnew\r\nline\r\n"


def test_typing_at_the_focused_offset_inserts_there(page):
    _mount(page, "hello world\n")
    page.evaluate("() => ed.focusAt(0)")
    page.keyboard.type("X")
    assert _text(page) == "Xhello world\n"
    page.evaluate("() => ed.focusAt(6)")
    page.keyboard.type("Y")
    assert _text(page) == "XhelloY world\n"
    assert page.evaluate("() => calls.change.at(-1)") == "XhelloY world\n"


def test_focus_at_clamps_out_of_range_offsets(page):
    _mount(page, "abc")
    page.evaluate("() => ed.focusAt(999)")
    page.keyboard.type("Z")
    assert _text(page) == "abcZ"


def test_mod_b_wraps_the_selection_in_double_asterisks(page):
    _mount(page, "make this bold\n")
    page.evaluate("""() => { ed.focusAt(5);
      ed.view.dispatch({selection: {anchor: 5, head: 9}}); }""")
    page.keyboard.press("ControlOrMeta+b")
    assert _text(page) == "make **this** bold\n"


def test_mod_i_and_mod_e_wrap_in_their_markers(page):
    _mount(page, "a b\n")
    page.evaluate("() => { ed.focusAt(0); ed.view.dispatch({selection: {anchor: 0, head: 1}}); }")
    page.keyboard.press("ControlOrMeta+i")
    assert _text(page) == "*a* b\n"
    page.evaluate("() => ed.view.dispatch({selection: {anchor: 4, head: 5}})")
    page.keyboard.press("ControlOrMeta+e")
    assert _text(page) == "*a* `b`\n"


def test_mod_k_inserts_a_link(page):
    _mount(page, "site\n")
    page.evaluate("() => { ed.focusAt(0); ed.view.dispatch({selection: {anchor: 0, head: 4}}); }")
    page.keyboard.press("ControlOrMeta+k")
    assert _text(page) == "[site](https://)\n"


def test_save_done_and_toggle_keys_call_back(page):
    _mount(page, "x\n")
    page.evaluate("() => ed.focusAt(0)")
    page.keyboard.press("ControlOrMeta+s")
    page.keyboard.press("ControlOrMeta+/")
    page.keyboard.press("Escape")
    assert page.evaluate("() => calls") == {"save": 1, "done": 1, "toggle": 1, "change": []}
    assert _text(page) == "x\n"


def test_page_shortcuts_never_see_keys_typed_in_the_editor(page):
    _mount(page, "")
    page.evaluate("() => ed.focusAt(0)")
    page.keyboard.type("jkcdxre")
    page.keyboard.press("ControlOrMeta+s")
    page.keyboard.press("Escape")
    assert _text(page) == "jkcdxre"
    assert page.evaluate("() => pageKeys") == []
    # the listener itself works: a key outside the editor reaches it
    page.evaluate("() => document.activeElement.blur()")
    page.keyboard.press("e")
    assert page.evaluate("() => pageKeys") == ["e"]


def test_undo_restores_the_original(page):
    _mount(page, "abc\n")
    page.evaluate("() => ed.focusAt(3)")
    page.keyboard.type("def")
    page.keyboard.press("ControlOrMeta+z")
    assert _text(page) == "abc\n"


def test_mount_without_a_mode_is_the_source_view(page):
    _mount(page, "# Title\n\n> ⚠ careful ABC-310\n\n**b**\n")
    assert page.locator("#host .cm-lineNumbers").count() == 1
    assert page.locator("#host .cm-src-bq--warn").count() == 1


def test_the_bundle_carries_no_live_preview(page):
    text = BUNDLE.read_text()
    assert "cm-lp-" not in text
    assert page.evaluate("() => typeof AnnotateEditor.mount") == "function"
    _mount(page, "x\n")
    assert page.evaluate("() => typeof ed.setMode") == "undefined"


def test_destroy_removes_the_editor_dom_and_the_key_guard(page):
    _mount(page, "abc\n")
    assert page.locator("#host .cm-editor").count() == 1
    page.evaluate("() => ed.destroy()")
    assert page.locator("#host .cm-editor").count() == 0
    page.evaluate("""() => { const i = document.createElement('input'); i.id = 'inp';
      document.getElementById('host').append(i); i.focus(); }""")
    page.keyboard.press("e")
    assert page.evaluate("() => pageKeys") == ["e"]


def test_focus_at_counts_offsets_in_get_text_so_crlf_is_two(page):
    _mount(page, "crlf\r\nline\r\nend\r\n")
    page.evaluate("() => ed.focusAt(12)")  # raw offset of "end"
    page.keyboard.type("X")
    assert _text(page) == "crlf\r\nline\r\nXend\r\n"
    assert page.evaluate("() => calls.change.at(-1)") == "crlf\r\nline\r\nXend\r\n"


def test_lone_cr_survives_a_typed_newline_and_focus_at(page):
    _mount(page, "a\rb\rc")
    page.evaluate("() => ed.focusAt(4)")  # raw offset of "c"
    page.keyboard.type("X")
    page.keyboard.press("Enter")
    assert _text(page) == "a\rb\rX\rc"
