"""Round 2, batch wait-calls: a quiet session said in both languages, Cancel's count and box,
the mic note leaving, the live region clearing. Run under node on the page's own files (call_page.py)."""
from __future__ import annotations

from call_page import CallPage, needs_node, served
from test_call_return import page_of
from test_call_wait import CANCEL_EACH, NOW, YOU, again_entries, picked, press, waiting

pytestmark = needs_node

FREEZE = f"Date.now = () => {NOW * 1000};"


def wait_page(tmp_path, make, *, language=None):
    """A page that has the call's first state, then `make(base)`'s states (the page's clock stopped at NOW, as in test_call_wait)."""
    html, states = served(tmp_path, [])
    stored = {"language": language} if language else {}
    return CallPage(html, states + make(states[0]), stored=stored).js(FREEZE)


def silent(b):
    return picked(b, 1, stalled=True, entries=[{**YOU, "at": NOW - 230}],
                  turn={"entries": [{"id": 0, "state": "picked"}], "earlier": 0, "collected_at": NOW - 225, "alive_at": NOW - 200})


def test_a_session_gone_quiet_is_said_as_gone_quiet_in_the_thinking_row_in_both_languages(tmp_path):
    row = "[$('thinking').querySelector('.what').textContent, $('thinking').className, [...$('thinking').querySelectorAll('button')].map(b => b.textContent)]"
    en = wait_page(tmp_path, lambda b: [silent(b)]).js("await serve(1);").check(row)
    el = wait_page(tmp_path, lambda b: [silent(b)], language="el").js("await serve(1);").check(row)
    assert en.run() == [["Claude has gone quiet", "thinking warn", ["Send again"]]]
    assert el.run()[0][:2] == ["Ο Claude έχει σιωπήσει", "thinking warn"]


def test_cancel_counts_the_questions_put_back_and_scrolls_the_box_to_its_top(tmp_path):
    turn = {"entries": [{"id": 2, "state": "sent"}], "earlier": 0, "collected_at": None, "alive_at": None}
    page = wait_page(tmp_path, lambda b: [waiting(b, 1, entries=again_entries(), turn=turn)]).js("await serve(1);")
    page.js("globalThis.OUTCOME = {2: {cancelled: true, how: 'withdrawn', entries: [2]}};" + CANCEL_EACH
            + "$('text').scrollTop = 48; " + press("Cancel") + " await advance(10);")
    page.check("$('text').value")
    page.check("$('note').textContent")
    page.check("$('text').scrollTop")
    assert page.run() == ["How do vaccines work?\nand the shots?", "Took back 2 questions. Your words are back in the box, in order.", 0]


def test_the_nothing_was_heard_note_goes_when_the_reader_types_or_a_typed_message_is_sent(tmp_path):
    page = page_of(tmp_path)
    page.js("showMicNote('Nothing was heard in 3.9 s.');").check("[$('note').hidden, $('note').textContent]")
    page.js("$('text').value = 'h'; $('text').dispatchEvent(new ShimEvent('input'));").check("[$('note').hidden, micNote]")
    page.js("showMicNote('Nothing was heard in 3.9 s.'); $('text').value = 'A typed question'; $('sendtext').click(); await tick(100);").check("[micNote, $('text').value]")
    assert page.run() == [[False, "Nothing was heard in 3.9 s."], [True, ""], ["", ""]]


# ---- r2-screenreader-2: the live region does not keep an old sentence -------------------------------------------------------------

def test_the_live_region_clears_a_while_after_a_sentence_and_a_new_one_restarts_the_wait(tmp_path):
    page = page_of(tmp_path)
    region = "$('announcer').textContent"
    page.js("announce('One.'); await tick(100);").check(region)
    page.js("await tick(12000);").check(region)          # a long sentence is not cut: still there 12 s after
    page.js("await tick(2000);").check(region)           # 14 s after it was set: gone
    page.js("announce('Two.'); await tick(100);").check(region)
    page.js("await tick(9000); announce('Three.'); await tick(100);").check(region)
    page.js("await tick(6000);").check(region)           # 6 s after Three: Two's timer was cancelled, so it did not clear Three
    page.js("await tick(8000);").check(region)
    assert page.run() == ["One.", "One.", "", "Two.", "Three.", "Three.", ""]
