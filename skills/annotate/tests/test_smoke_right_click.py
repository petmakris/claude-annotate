"""A right-click acts on the paragraph under the pointer, with no selection first.

Inside a selection it acts on the selection. On a part's title it acts on the
whole part. Elsewhere in a part's prose it selects the paragraph, list item,
heading, code block, quote or table under the pointer and opens the menu on
that. Before this, Chrome selected the one word under the pointer and the
menu opened on that word.
"""
from pathlib import Path

SELECTION_JS = (Path(__file__).resolve().parents[1] / "static" / "selection.js").read_text()


def _handler(event):
    i = SELECTION_JS.index(f'document.addEventListener("{event}"')
    return SELECTION_JS[i:SELECTION_JS.index("\n  });", i)]


def test_a_right_click_opens_the_menu_on_the_paragraph_under_the_pointer():
    body = _handler("contextmenu")
    assert "el.closest(UNIT)" in body
    assert "range.selectNodeContents(unit)" in body
    assert "openForSelection(range)" in body
    assert "ev.preventDefault()" in body


def test_the_paragraph_is_what_the_read_aloud_card_sits_after_plus_a_heading():
    assert 'const UNIT = "li, p, pre, blockquote, table, h1, h2, h3, h4, h5, h6";' in SELECTION_JS


def test_a_right_click_inside_a_selection_keeps_the_selection():
    # Chrome selects the word under the pointer on a right-click, so the
    # selection is read on mousedown, before Chrome replaces it.
    down = _handler("mousedown")
    assert "ev.button !== 2" in down
    assert "before =" in down
    body = _handler("contextmenu")
    assert "under(kept, ev.clientX, ev.clientY)" in body
    assert "openForSelection(kept)" in body


def test_a_right_click_on_a_title_opens_the_whole_part():
    body = _handler("contextmenu")
    assert "if (inTitle(el)) { ev.preventDefault(); return openWhole(section); }" in body


def test_a_link_a_control_or_a_phone_keeps_the_browsers_own_menu():
    body = _handler("contextmenu")
    assert "el.closest(IGNORE)" in body
    assert "touch.matches" in body
    assert "!enabled()" in body


def test_the_right_buttons_mouseup_leaves_the_menu_to_contextmenu():
    # On a Mac contextmenu fires on mousedown, and the mouseup after it would
    # open the menu a second time on whatever is selected by then.
    assert "if (ev.button === 2) return;" in _handler("mouseup")
