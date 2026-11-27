"""The polite live region of the call page (call-announce.js). Run under node (call_page.py). The page's `Date.now` is moved by tick(ms),
so the rate limits are exact."""
import re
import time
from pathlib import Path

from call_page import CallPage, needs_node, served

pytestmark = needs_node

STATIC = Path(__file__).resolve().parents[1] / "static"
KEY = "away.test-call-id"
CLOCK = ("globalThis.skew = 0; const T0 = Date.now(); Date.now = () => T0 + skew;"
         " async function tick(ms) { skew += ms; await advance(ms); }")


def page_of(tmp_path, answers=("First answer.", "Second answer."), start=None, away=None, **kw):
    """A page opened on the call after all `answers`; `away`: the note the last page left, [ms ago, newest answer then]."""
    html, states = served(tmp_path, list(answers))
    stored = {}
    if away:
        stored[KEY] = {"at": int(time.time() * 1000) - away[0], "upto": away[1]}
    page = CallPage(html, states, start=len(answers) if start is None else start, stored=stored, **kw)
    return page.js(CLOCK)


def test_the_live_region_says_each_sentence_once_a_burst_as_one_and_not_while_typing(tmp_path):
    page = page_of(tmp_path)
    page.js("announce('One.'); await tick(100);").check("$('announcer').textContent")
    page.js("announce('One.'); announce('Two.'); announce('Three.'); await tick(100);").check("$('announcer').textContent")
    page.js("await tick(1500);").check("$('announcer').textContent")
    # the same words again within ten seconds are not said; after them they are
    page.js("announce('Three.'); await tick(100);").check("annQueue.length")
    page.js("await tick(10000); announce('Two.'); await tick(100);").check("$('announcer').textContent")
    # while a message is being typed nothing is said; it waits and is said once the field is empty
    page.js("const t = $('text'); t.value = 'half a sent'; t.focus(); await tick(3000); announce('Typing.'); await tick(3000);").check("[$('announcer').textContent, annQueue.length]")
    page.js("t.value = ''; await tick(600);").check("[$('announcer').textContent, annQueue.length]")
    assert page.run() == ["One.", "One.", "Two. Three.", 0, "Two.", ["Two.", 1], ["Typing.", 0]]


def test_a_sentence_nobody_could_say_in_time_is_dropped(tmp_path):
    page = page_of(tmp_path)
    page.js("const t = $('text'); t.value = 'typing on'; t.focus(); announce('Late.'); await tick(25000);").check("[$('announcer').textContent, annQueue.length]")
    assert page.run() == [["", 0]]


ARRIVES = ("STATES[1].entries.unshift({id: 90, who: 'you', text: 'How do the fees compare?', at: 1});"
           " await serve(1); await tick(1600);")


def test_a_screen_reader_hears_that_an_answer_arrived_when_the_voice_does_not_read_it(tmp_path):
    # study screenreader-1: the arrival of an answer was silent (the wait card says its own steps, test_call_wait.py)
    page = page_of(tmp_path, ["Answer."], start=0, autoplay=False)
    page.check("$('announcer').textContent")
    page.js(ARRIVES).check("$('announcer').textContent")
    assert page.run() == ["", "Answer 1 arrived: How do the fees compare?."]


def test_the_arrival_is_not_said_over_an_answer_that_autoplays_and_is_said_when_no_voice_comes(tmp_path):
    # r1-screenreader-5: autoplay is on by default, so the voice starts at once and a screen reader on top of it talks over it
    page = page_of(tmp_path, ["Answer."], start=0)
    page.js(ARRIVES).check("[$('announcer').textContent, !audio.paused, arrivalHeld.length, annQueue.length]")
    page.js("await end(); await tick(2000);").check("[$('announcer').textContent, arrivalHeld.length]")
    # the voice failed: nothing is coming, so the line is said at once
    page2 = page_of(tmp_path, ["Answer."], start=0)
    page2.js("STATES[1].entries[0].speech = 'failed';" + ARRIVES).check("[$('announcer').textContent, arrivalHeld.length]")
    # a voice that never comes (nothing plays in 15 s) lets the line go
    page3 = page_of(tmp_path, ["Answer."], start=0)
    page3.js("STATES[1].entries[0].speech = 'pending';" + ARRIVES).check("[$('announcer').textContent, arrivalHeld.length]")
    page3.js("await tick(15500);").check("[$('announcer').textContent, arrivalHeld.length]")
    assert page.run() == [["", True, 0, 0], ["", 0]]
    assert page2.run() == [["Answer 1 arrived: How do the fees compare?.", 0]]
    assert page3.run() == [["", 1], ["Answer 1 arrived: How do the fees compare?.", 0]]


def test_what_is_there_when_the_page_opens_is_not_announced_and_an_end_is(tmp_path):
    page = page_of(tmp_path)
    page.check("[$('announcer').textContent, annQueue.length]")
    page.js("STATES[2] = {...STATES[2], v: 'e', stalled: false, ended: 'over'}; await serve(2); await tick(1600);").check("$('announcer').textContent")
    assert page.run() == [["", 0], "The call has ended."]


def test_a_board_that_changes_at_rest_is_said_but_not_while_the_answer_plays(tmp_path):
    page = page_of(tmp_path, ["An answer."])
    page.js("STATES[1].entries.push({id: 80, who: 'board', text: 'Heat pump or gas boiler', view: 'heat', kind: 'table', answer: 1}); STATES[1].v = 'b'; await serve(1); await tick(100);")
    page.js("frontBoard = 'heat'; paintAll(); await tick(100);").check("$('announcer').textContent")
    page.js("$('playpause').click(); await tick(2000); frontBoard = ''; paintAll(); frontBoard = 'heat'; paintAll(); await tick(2000);").check("$('announcer').textContent")
    assert page.run() == ["Board: Heat pump or gas boiler.", "Board: Heat pump or gas boiler."]
    # the second reading is the first still standing: nothing new was said while the voice played


def test_the_reader_over_the_stage_is_not_read_twice(tmp_path):
    # study screenreader-7: the reader repeats the answer the panel holds; it is a picture of it
    html = (STATIC / "call.html").read_text()
    tag = re.search(r'<div class="reader" id="reader"[^>]*>', html).group(0)
    assert 'aria-hidden="true"' in tag and "aria-label" not in tag


CARD = "[$('welcome').hidden, $('wbaway').textContent, [...$('wbfacts').children].map((s) => s.textContent), $('wbplaytext').textContent, $('wbwork').hidden]"


