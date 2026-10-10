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


def _inner(src, name):
    """An indented `function name(` inside an IIFE, up to its closing brace."""
    i = src.index("function %s(" % name)
    return src[i:src.index("\n  }\n", i)]


def test_esc_keeps_the_readers_words():
    esc = WIN[WIN.index('e.key !== "Escape"'):]
    esc = esc[:esc.index("});")]
    assert "if (hasWords()) call(); else close();" in esc, \
        "Esc closes a window holding words, and the card's onClose deletes the draft"
    assert '"Escape"' not in _inner(SEL, "openComposer"), \
        "the selection's box handles Esc itself again, around the window's rule"


def test_one_has_words_rule_for_both_openers():
    assert ".paste-thumb" in _inner(WIN, "hasWords"), \
        "a window holding only a pasted picture counts as empty"
    assert "W().hasWords()" in _inner(SEL, "openComposer")
    assert "AnnotateCommentWindow.hasWords()" in _fn(SCRIPT_JS.read_text(), "openAnnotation")


def test_a_saved_draft_does_not_replace_a_window_with_words():
    assert "!W.hasWords()" in _fn(SCRIPT_JS.read_text(), "renderComments"), \
        "a response switch opens a saved draft over the selection's box and drops its words"


def test_the_window_shows_over_a_maximized_part_and_in_full_screen():
    css = (STATIC / "style-comment-window.css").read_text()
    assert "body.has-max-overlay .comment-window { z-index: 1250; }" in css
    assert 'addEventListener("fullscreenchange", mount)' in WIN
    i = WIN.index("function mount(")
    assert "document.fullscreenElement" in WIN[i:WIN.index("\n  }", i)]


def test_a_response_switch_sends_the_windows_words_to_the_general_box():
    body = _fn(SCRIPT_JS.read_text(), "startNewResponse")
    assert body.index("annotate:orphan-comment") < body.index("STORAGE_KEY = ")
