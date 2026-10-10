"""Every comment opens in one floating window: the selection's box and the
whole-part card alike. It is moved by its title bar and resized from its
corner, and a rewrite can never take it, or the reader's words, away."""
from pathlib import Path

from skills.annotate.tests.page_source import SCRIPT_JS, STYLE_CSS

STATIC = Path(__file__).resolve().parents[1] / "static"
WIN = (STATIC / "comment-window.js").read_text() if (STATIC / "comment-window.js").exists() else ""
SEL = (STATIC / "selection.js").read_text()


def _fn(src, name):
    i = src.index("function %s(" % name)
    return src[i:src.index("\n}", i) if "\n}" in src[i:] else len(src)]


def test_the_window_moves_by_its_bar_and_resizes_from_its_corner():
    assert "comment-window-bar" in WIN and "pointerdown" in WIN
    assert "comment-window-resize" in WIN
    assert "AnnotateWindowPlace.clamp" in WIN, "a move can push the window off screen"


def test_the_window_lives_on_the_body_not_in_a_part():
    assert "document.body.appendChild(win)" in WIN


def test_a_shrinking_browser_pulls_the_window_back():
    assert 'addEventListener("resize"' in WIN


def test_the_selection_box_and_the_card_both_open_it():
    assert "AnnotateCommentWindow.open(" in SEL
    assert "AnnotateCommentWindow.open(" in _fn(SCRIPT_JS.read_text(), "renderComments")
    assert "insertAdjacentElement" not in _fn(SEL, "openComposer"), "the box is still put inside the text"


def test_no_comment_box_is_mounted_in_the_text_any_more():
    src = SCRIPT_JS.read_text()
    assert '"inline-comments"' not in src
    assert "hostFor(" not in SEL


def test_words_typed_before_a_rewrite_are_kept():
    commit = SEL[SEL.index("const commit = () =>"):]
    commit = commit[:commit.index("};")]
    assert "rangeFor" in commit, "Save no longer checks the words are still there"
    assert "pinComment" in commit and "annotate:orphan-comment" in commit, \
        "words on rewritten text are dropped instead of moved"


def test_the_window_is_styled_and_readable():
    css = STYLE_CSS.read_text()
    assert ".comment-window {" in css and "position: fixed" in css[css.index(".comment-window {"):]
    assert ".comment-window.is-calling" in css
