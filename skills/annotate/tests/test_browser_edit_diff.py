# skills/annotate/tests/test_browser_edit_diff.py
"""AnnotateEditDiff in a bare page: pure text, no daemon, no shell."""
from __future__ import annotations

from pathlib import Path

import pytest

from skills.tests.harness import require_playwright  # noqa: E402

require_playwright()

STATIC = Path(__file__).resolve().parents[1] / "static"


@pytest.fixture(scope="module")
def page(browser_session):
    pg = browser_session.new_page()
    pg.set_content("<!doctype html><main></main>")
    pg.add_script_tag(path=str(STATIC / "edit-diff.js"))
    yield pg
    pg.context.close()


def _runs(page, before, after):
    runs = page.evaluate("([b, a]) => AnnotateEditDiff.changedRuns(b, a)", [before, after])
    return [after[r["start"]:r["end"]] for r in runs], runs


def test_a_replaced_word_is_one_run(page):
    assert _runs(page, "a b c", "a X c")[0] == ["X"]


def test_an_appended_word_is_trimmed(page):
    assert _runs(page, "a b c", "a b c d")[0] == ["d"]


def test_a_pure_deletion_has_no_run(page):
    assert _runs(page, "a b c", "a c")[0] == []


def test_a_repeated_word_is_not_blamed(page):
    texts, runs = _runs(page, "same same", "same NEW same")
    assert texts == ["NEW"]
    assert runs[0]["start"] == 5


def test_a_whole_rewrite_is_one_run(page):
    assert _runs(page, "one two three", "alpha beta gamma")[0] == ["alpha beta gamma"]


def test_edits_at_both_ends_get_their_own_runs(page):
    assert _runs(page, "a b c", "X b Y")[0] == ["X", "Y"]


def test_a_changed_word_after_a_newline(page):
    texts, runs = _runs(page, "a\nb", "a\nB")
    assert texts == ["B"] and runs[0]["start"] == 2


def test_word_diff_ops(page):
    d = page.evaluate("() => AnnotateEditDiff.wordDiff('a b c', 'a X c')")
    assert "".join(x["text"] for x in d if x["op"] != "ins") == "a b c"
    assert "".join(x["text"] for x in d if x["op"] != "del") == "a X c"
    assert any(x["op"] == "del" and x["text"] == "b" for x in d)
    assert any(x["op"] == "ins" and x["text"] == "X" for x in d)


def test_over_the_cap_the_whole_after_is_one_run(page):
    before = "head " + " ".join(["w"] * 3000) + " tail"
    after = "head " + " ".join(["v"] * 3000) + " tail"
    texts, _ = _runs(page, before, after)
    assert texts == [after]


def test_a_small_edit_in_a_long_text_stays_small(page):
    before = " ".join(["w"] * 3000)
    after = before + " tail"
    assert _runs(page, before, after)[0] == ["tail"]


def test_two_edits_separated_by_an_unchanged_word_stay_two_runs(page):
    texts, _ = _runs(page, "a b c d e", "a X c Y e")
    assert texts == ["X", "Y"]


def test_crlf_text_gives_offsets_in_the_raw_string(page):
    texts, runs = _runs(page, "one\r\ntwo three", "one\r\nTWO three")
    assert texts == ["TWO"] and runs[0]["start"] == 5


def test_lone_cr_text_gives_offsets_in_the_raw_string(page):
    texts, runs = _runs(page, "one\rtwo\rthree", "one\rtwo\rTHREE")
    assert texts == ["THREE"] and runs[0]["start"] == 8


def test_punctuation_stays_attached_to_its_word(page):
    assert _runs(page, "a b, c", "a X, c")[0] == ["X,"]
    assert _runs(page, "it ends.", "it stops.")[0] == ["stops."]


# ── HTML: a tag is a token of its own, never glued to the word beside it ──

def test_a_word_beside_a_tag_is_its_own_change(page):
    ops = page.evaluate("""() => AnnotateEditDiff.wordDiff('<p x="1">The fox jumps.</p>',
      '<p x="1">A fox leaps.</p>').filter(o => o.op !== 'eq')""")
    assert ops == [{"op": "del", "text": "The"}, {"op": "ins", "text": "A"},
                   {"op": "del", "text": "jumps."}, {"op": "ins", "text": "leaps."}]


def test_a_tag_with_spaces_in_it_is_one_token(page):
    texts, _ = _runs(page, '<p data-x="a b">one two</p>', '<p data-x="a b">one three</p>')
    assert texts == ["three"]


def test_a_lone_angle_bracket_is_still_text(page):
    texts, _ = _runs(page, "a < b", "a < c")
    assert texts == ["c"]
