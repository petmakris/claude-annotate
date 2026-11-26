"""Return and place on the call page (call-return.js): the welcome-back card, the since-you-left divider, the state strip, the
polite live region and the way to the newest answer. Run under node (call_page.py). The page's `Date.now` is moved by tick(ms), so
the rate limits and the time away are exact."""
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


def test_the_panel_starts_with_a_way_to_the_newest_answer(tmp_path):
    # study screenreader-4: nothing to jump to with the keyboard; the newest answer was found by scanning
    html = (STATIC / "call.html").read_text()
    assert re.search(r'<div class="open">\s*<a class="skip" id="skiplatest" href="#nowcard" data-t="skip.latest">Jump to the latest answer</a>', html)
    page = page_of(tmp_path)
    page.js("$('skiplatest').click();").check("[document.activeElement.id, $('nowtext').textContent.trim()]")
    assert page.run() == [["nowcard", "Second answer."]]


def test_a_quick_switch_for_playing_new_answers_by_themselves_sits_in_the_strip(tmp_path):
    # study screenreader-5: the only off switch was inside the Settings popover
    page = page_of(tmp_path)
    page.check("[$('ssauto').getAttribute('aria-pressed'), $('ssauto').getAttribute('aria-label'), autoplay]")
    page.js("$('ssauto').click();").check("[$('ssauto').getAttribute('aria-pressed'), autoplay, $('autoplay').getAttribute('aria-pressed'), localStorage.getItem('talk.autoplay')]")
    page.js("$('ssauto').click();").check("[$('ssauto').getAttribute('aria-pressed'), autoplay]")
    assert page.run() == [["true", "Play new answers by themselves", True], ["false", False, "false", "false"], ["true", True]]


def test_the_strip_says_in_words_what_the_call_is_doing(tmp_path):
    page = page_of(tmp_path, start=0, autoplay=False)
    row = "[$('statestrip').dataset.key, $('sstext').textContent, $('statestrip').classList.contains('warn')]"
    page.check(row)
    page.js("await serve(2);").check(row)
    page.js("$('playpause').click(); await settle();").check(row)
    page.js("audio._t = 1; audio.pause(); await settle();").check(row)
    # a question 42 s old, still working: the clock counts from it in the server's time
    page.js("audio.pause(); const NOW = Date.now() / 1000; STATES[2].entries.push({id: 70, who: 'you', text: 'And then?', at: NOW - 42});"
            " STATES[2] = {...STATES[2], v: 'w', now: NOW, working: true}; await serve(2);").check(row)
    page.js("STATES[2] = {...STATES[2], v: 's', now: STATES[2].now, stalled: true}; await serve(2);").check(row)
    page.js("STATES[2] = {...STATES[2], v: 'e', stalled: false, working: false, ended: 'over'}; await serve(2);").check(row)
    assert page.run() == [
        ["waiting", "Waiting for your first question", False],
        ["waiting", "Waiting for you", False],
        ["playing", "Playing answer 2", False],
        ["paused", "Paused at answer 2", False],
        ["answering", "Claude is answering · 0:42", False],
        ["stalled", "Claude has not picked this up yet · 0:42", True],
        ["ended", "The call has ended", False]]


def test_the_strip_says_that_a_board_follows_the_voice_or_stays_pinned(tmp_path):
    page = page_of(tmp_path, ["An answer."])
    page.js("STATES[1].entries.push({id: 80, who: 'board', text: 'Boiler', view: 'boiler', kind: 'table', answer: 1}); STATES[1].v = 'b'; await serve(1);")
    page.js("frontBoard = 'boiler'; $('playpause').click(); await settle();").check("$('sstext').textContent")
    page.js("fromStage({type: 'stage:follow', on: false}); audio.dispatchEvent(new ShimEvent('timeupdate'));").check("$('sstext').textContent")
    assert page.run() == ["Playing answer 1 · following the board", "Playing answer 1 · board pinned"]


def test_after_an_absence_the_strip_counts_the_answers_not_heard(tmp_path):
    page = page_of(tmp_path, away=(3600 * 1000, -1))
    page.check("[$('statestrip').dataset.key, $('sstext').textContent]")
    assert page.run() == [["new", "2 answers not heard"]]


def test_a_queued_answer_and_another_screen_are_said_in_the_strip(tmp_path):
    page = page_of(tmp_path, ["First.", "Second."], start=1)
    page.js("$('playpause').click(); await settle(); await serve(2);").check("$('sstext').textContent")
    page.js("queued = null; elsewhere = true; audio.pause(); await settle(); paintAll();").check("$('sstext').textContent")
    assert page.run() == ["Answer 2 is next", "Playing on another screen"]


def test_other_calls_that_need_you_are_counted_at_the_end_of_the_strip(tmp_path):
    page = page_of(tmp_path)
    page.js("STATES[2] = {...STATES[2], v: 'c', calls: [{id: 'a', topic: 'A', unheard: 1, started: 1, last_at: 1}, {id: 'b', topic: 'B', stalled: true, started: 2, last_at: 1}]}; await serve(2);")
    page.check("[$('ssmore').textContent, $('ssmore').title, $('ssmore').hidden]")
    page.js("STATES[2] = {...STATES[2], v: 'd', calls: [{id: 'a', topic: 'A', unheard: 1, started: 1, last_at: 1}]}; await serve(2);")
    page.check("[$('ssmore').textContent, $('ssmore').hidden, $('callsword').textContent, $('callsbtn').dataset.tip, $('callsbtn').getAttribute('aria-label')]")
    assert page.run() == [["2 other calls need you", "Calls that need you: “B”, “A”", False],
                          ["1 other call needs you", False, "1 other call needs you", "1 other call needs you", "Calls: 1 other call needs you. New answer in “A”"]]


# ---- the welcome-back card ------------------------------------------------------------------------

CARD = "[$('welcome').hidden, $('wbaway').textContent, [...$('wbfacts').children].map((s) => s.textContent), $('wbplaytext').textContent, $('wbwork').hidden]"


def test_after_two_hours_away_the_card_says_what_came_and_offers_to_play_it(tmp_path):
    page = page_of(tmp_path, away=(2 * 3600 * 1000 + 600000, -1))
    page.check(CARD)
    page.check(f"localStorage.getItem('talk.{KEY}')")
    assert page.run() == [[False, "away 2 h 10 min", ["2 answers not heard", "8 s of audio"], "Play the 2 new", True], "null"]


def test_a_short_absence_gets_no_card_and_a_page_with_nothing_missed_none(tmp_path):
    for away in ((60 * 1000, -1), (10 * 1000, -1), (3 * 3600 * 1000, 1)):  # a minute, ten seconds, hours but nothing came since
        page = page_of(tmp_path, away=away)
        page.check("$('welcome').hidden")
        assert page.run() == [True], away


def test_the_card_goes_when_the_answers_are_heard_or_the_reader_dismisses_it(tmp_path):
    page = page_of(tmp_path, away=(3600 * 1000, -1))
    page.check("$('welcome').hidden")
    page.js("$('wbx').click();").check("[$('welcome').hidden, welcomeOpen]")
    page2 = page_of(tmp_path, away=(3600 * 1000, -1))
    page2.js("STATES[2] = {...STATES[2], v: 'h', heard_upto: 1}; await serve(2);").check("[$('welcome').hidden, absence]")
    assert page.run() == [False, [True, False]] and page2.run() == [[True, None]]


def test_leaving_the_tab_for_a_while_and_coming_back_shows_the_card_for_what_came_meanwhile(tmp_path):
    page = page_of(tmp_path, ["First.", "Second.", "Third."], start=1, autoplay=False)
    page.js("document.visibilityState = 'hidden'; document.dispatchEvent(new ShimEvent('visibilitychange'));")
    page.check(f"JSON.parse(localStorage.getItem('talk.{KEY}')).upto")
    page.js("await serve(3); await tick(20 * 60 * 1000); document.visibilityState = 'visible'; document.dispatchEvent(new ShimEvent('visibilitychange')); await settle();")
    page.check(CARD)
    assert page.run() == [0, [False, "away 20 min", ["2 answers not heard", "8 s of audio"], "Play the 2 new", True]]


def test_the_card_says_when_claude_is_still_working_and_on_what(tmp_path):
    page = page_of(tmp_path, away=(3600 * 1000, -1))
    page.js("const NOW = Date.now() / 1000; STATES[2].entries.push({id: 70, who: 'you', text: 'And the heat pump?', at: NOW - 95});"
            " STATES[2] = {...STATES[2], v: 'w', now: NOW, working: true}; await serve(2);")
    page.check("[$('wbwork').hidden, $('wbwork').textContent]")
    assert page.run() == [[False, "Claude is still working on “And the heat pump?” · 1:35"]]


def test_play_the_new_plays_them_in_order_the_first_by_the_reader_and_the_rest_by_themselves(tmp_path):
    page = page_of(tmp_path, ["One.", "Two.", "Three."], start=3, away=(3600 * 1000, -1), autoplay=False)
    page.check("$('wbplaytext').textContent")
    page.js("$('wbplay').click(); await settle();").check("[current.id, !audio.paused, $('welcome').hidden, readerAnswer]")
    page.js("await end();").check("[current.id, !audio.paused, readerAnswer]")
    page.js("await end();").check("[current.id, !audio.paused, readerAnswer, catchPlaying]")
    page.js("await end();").check("[current.id, audio.paused, catchPlaying]")
    assert page.run() == ["Play the 3 new", [0, True, True, 0], [1, True, 0], [2, True, 0, 2], [2, True, None]]


def test_an_answer_that_comes_during_play_the_new_waits_until_the_list_is_played(tmp_path):
    html, states = served(tmp_path, ["One.", "Two.", "Three."])
    page = CallPage(html, states, start=2, stored={KEY: {"at": int(time.time() * 1000) - 3600 * 1000, "upto": -1}}, autoplay=True).js(CLOCK)
    page.js("$('wbplay').click(); await settle(); await serve(3);").check("[current.id, queued && queued.id]")
    page.js("await end();").check("[current.id, !audio.paused, queued, catchStash && catchStash.id]")
    page.js("await end();").check("[current.id, !audio.paused, queued, catchStash]")
    assert page.run() == [[0, 2], [1, True, None, 2], [2, True, None, None]]


def test_pressing_another_answer_ends_the_walk_through_the_new_ones(tmp_path):
    page = page_of(tmp_path, ["One.", "Two.", "Three."], start=3, away=(3600 * 1000, -1), autoplay=False)
    page.js("$('wbplay').click(); await settle(); document.querySelectorAll('#tllist .tlrow button.play')[1].click(); await settle();")
    page.js("await end();").check("[current.id, catchPlaying, catchUp]")
    assert page.run() == [[2, None, []]]


def test_read_them_scrolls_to_the_new_ones_and_plays_nothing(tmp_path):
    page = page_of(tmp_path, away=(3600 * 1000, -1), autoplay=False)
    page.js("let scrolled = 0; $('sinceleft').scrollIntoView = () => { scrolled++; }; $('wbread').click(); await settle();")
    page.check("[audio.paused, !!current, $('welcome').hidden, document.activeElement.id, scrolled]")
    assert page.run() == [[True, False, True, "sinceleft", 1]]


# ---- the since-you-left divider -------------------------------------------------------------------

def rows(ids):
    """A stand-in for the list of earlier answers: one .tlrow per answer id."""
    return (f"$('tllist').replaceChildren(...{list(ids)}.map((id) => Object.assign(document.createElement('div'), {{className: 'tlrow'}})));"
            f" [...$('tllist').children].forEach((r, i) => {{ r.dataset.id = {list(ids)}[i]; }});")


def test_the_divider_sits_before_the_first_answer_that_came_while_you_were_away(tmp_path):
    page = page_of(tmp_path, ["A.", "B.", "C.", "D."], away=(3600 * 1000, 0))
    page.js(rows([0, 1, 2, 3]) + " returnMarkEarlier($('tllist'));")
    page.check("[...$('tllist').children].map((r) => r.id || r.dataset.id)")
    page.check("[$('sinceleft').querySelector('.slabel').textContent, $('sinceleft').querySelector('.scount').textContent, $('sinceleft').getAttribute('role')]")
    page.js("returnMarkEarlier($('tllist'));").check("$('tllist').children.length")
    page.js("STATES[4] = {...STATES[4], v: 'h', heard_upto: 3}; await serve(4); returnMarkEarlier($('tllist'));").check("$('tllist').querySelector('#sinceleft') === null")
    assert page.run() == [["0", "sinceleft", "1", "2", "3"], ["Since you left", "3 not heard", "listitem"], 5, True]


def test_with_no_absence_there_is_no_divider(tmp_path):
    page = page_of(tmp_path, ["A.", "B."])
    page.js(rows([0, 1]) + " returnMarkEarlier($('tllist'));").check("$('tllist').children.length")
    assert page.run() == [2]


def test_the_dividers_play_starts_the_walk_through_the_new_ones(tmp_path):
    page = page_of(tmp_path, ["A.", "B.", "C."], away=(3600 * 1000, 0), autoplay=False)
    page.js(rows([0, 1, 2]) + " returnMarkEarlier($('tllist')); $('sinceleft').querySelector('.splay').click(); await settle();")
    page.check("[current.id, catchUp, readerAnswer]")
    assert page.run() == [[1, [2], 1]]


# ---- the autoplay switch of the strip (r1-listener-1) ------------------------------------------------------------------

def test_the_autoplay_switch_has_a_loop_glyph_a_word_and_a_line_in_the_strip_while_it_is_off(tmp_path):
    html = (STATIC / "call.html").read_text()
    glyph = re.search(r'<button class="ib ssauto".*?</button>', html, re.S).group(0)
    assert 'class="mute"' not in glyph and 'class="wv"' not in glyph and 'class="off"' in glyph   # no speaker, no sound waves
    page = page_of(tmp_path)
    show = "[$('ssauto').getAttribute('aria-pressed'), $('ssautolbl').textContent, $('ssnote').hidden, $('ssnote').textContent, $('ssauto').dataset.tip]"
    page.check(show)
    page.js("$('ssauto').click();").check(show)
    page.js("$('ssauto').click();").check(show)
    assert page.run() == [
        ["true", "Autoplay on", True, "New answers will not play by themselves", "Autoplay is on: new answers play by themselves"],
        ["false", "Autoplay off", False, "New answers will not play by themselves", "Autoplay is off: new answers wait for Play"],
        ["true", "Autoplay on", True, "New answers will not play by themselves", "Autoplay is on: new answers play by themselves"]]


# ---- a first open of an old call (r1-returning-2) ---------------------------------------------------------------------------

def aged_page(tmp_path, seconds, answers=("One.", "Two."), heard=None, away=None):
    """A page whose first view already holds answers `seconds` old (a call left alone for a while), opened on a browser with no note."""
    html, states = served(tmp_path, list(answers))
    for st in states:
        st["now"] = time.time()
        for e in st["entries"]:
            e["at"] = st["now"] - seconds
        if heard is not None:
            st["heard_upto"] = heard
    stored = {KEY: {"at": int(time.time() * 1000) - away, "upto": -1}} if away else {}
    return CallPage(html, states, start=len(answers), stored=stored, autoplay=False).js(CLOCK)


def test_a_browser_with_no_note_that_opens_a_call_whose_newest_unheard_answer_is_old_gets_the_welcome_card(tmp_path):
    page = aged_page(tmp_path, 7500, ("First answer.", "Second answer.", "Third answer."))
    page.check("[absence && absence.upto, absence && Math.round(absence.ms / 60000), hadAwayNote]")
    page.check("[$('welcome').hidden, $('wbaway').textContent, [...$('wbfacts').children].map((s) => s.textContent)]")
    assert page.run() == [[1, 125, False], [False, "away 2 h 5 min", ["1 answer not heard", "4 s of audio"]]]


def test_the_page_alone_offers_nothing_for_a_fresh_answer_a_heard_one_a_short_wait_or_a_note(tmp_path):
    state = "[$('welcome').hidden, absence]"
    assert aged_page(tmp_path, 5).check(state).run() == [[True, None]]                       # seconds old: nothing to welcome back to
    assert aged_page(tmp_path, 7200, heard=1).check(state).run() == [[True, None]]           # old, but heard up to the newest
    assert aged_page(tmp_path, 240).check(state).run() == [[True, None]]                     # four minutes: under AWAY_MS
    # a note the last page left is the only source: a short note is no absence, however old the answers
    assert aged_page(tmp_path, 7200, away=5000).check("[$('welcome').hidden, absence, hadAwayNote]").run() == [[True, None, True]]
