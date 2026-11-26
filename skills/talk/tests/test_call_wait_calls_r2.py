"""Round 2, batch wait-calls: the Autoplay switch's name and announcement, the strip and the wait card saying one thing, the
earlier-question line, Take back's count and box, the mic note leaving, the strip's link to the Calls menu, the live region
clearing and the strip's tip staying inside the page. Run under node on the page's own files (call_page.py); layout is the run's
shots, so the CSS is pinned by its text where the node DOM cannot measure it."""
from __future__ import annotations

import re
from pathlib import Path

from call_page import CallPage, needs_node, served
from test_call_return import CLOCK, page_of
from test_call_wait import CANCEL_EACH, NOW, YOU, again_entries, card, picked, waiting

pytestmark = needs_node

STATIC = Path(__file__).resolve().parents[1] / "static"
FREEZE = f"Date.now = () => {NOW * 1000};"


def wait_page(tmp_path, make, *, language=None):
    """A page that has the call's first state, then `make(base)`'s states (the page's clock stopped at NOW, as in test_call_wait)."""
    html, states = served(tmp_path, [])
    stored = {"language": language} if language else {}
    return CallPage(html, states + make(states[0]), stored=stored).js(FREEZE)


def greek_page(tmp_path, **kw):
    html, states = served(tmp_path, ["First answer.", "Second answer."])
    return CallPage(html, states, start=2, stored={"language": "el"}, **kw).js(CLOCK)


# ---- S-screenreader-5: the switch is named by its visible word, and a toggle is said once --------------------------------

def test_the_autoplay_switch_is_named_by_its_visible_word_in_both_languages(tmp_path):
    # a browser leaves the markup's own English alone while the language is English (applyLang), so the strip's repaint must name it
    stale = "$('ssauto').setAttribute('aria-label', 'stale'); stripSig = ''; paintStateStrip();"
    shown = "[$('ssauto').getAttribute('aria-label'), $('ssautolbl').textContent, $('ssauto').getAttribute('aria-pressed')]"
    en = page_of(tmp_path).js(stale).check(shown)
    el = greek_page(tmp_path).js(stale).check(shown)
    assert en.run() == [["Autoplay: new answers play by themselves", "Autoplay on", "true"]]
    assert el.run() == [["Αυτόματη: οι νέες απαντήσεις παίζουν μόνες τους", "Αυτόματη: ναι", "true"]]
    for name, word in (("Autoplay: new answers play by themselves", "Autoplay on"), ("Αυτόματη: οι νέες απαντήσεις παίζουν μόνες τους", "Αυτόματη: ναι")):
        assert name.startswith(re.split(r"[ :]", word)[0])   # the name starts with the visible word, and holds no state


def test_a_toggle_of_autoplay_is_said_once_from_the_strip_and_from_the_settings_row(tmp_path):
    page = page_of(tmp_path)
    page.js("window.said = []; announce = t => window.said.push(t); $('ssauto').click(); await tick(10);").check("[...window.said]")
    page.js("$('autoplay').click(); await tick(10);").check("[...window.said]")
    assert page.run() == [["Autoplay is off: new answers wait for Play"],
                          ["Autoplay is off: new answers wait for Play", "Autoplay is on: new answers play by themselves"]]


# ---- r2-first-2: the note wraps, the Greek words are short ------------------------------------------------------------------

def test_the_greek_strip_keeps_the_answer_number_and_a_short_chip_word(tmp_path):
    page = greek_page(tmp_path).js("$('playpause').click(); await settle();")
    page.check("[$('sstext').textContent, $('ssautolbl').textContent]")
    page.js("$('ssauto').click(); await tick(10);").check("[$('ssautolbl').textContent, $('ssnote').hidden, $('ssnote').textContent]")
    assert page.run() == [["Παίζει η απάντηση 2", "Αυτόματη: ναι"],
                          ["Αυτόματη: όχι", False, "Οι νέες απαντήσεις δεν θα παίζουν μόνες τους"]]


def test_the_off_note_wraps_to_a_second_line_and_is_never_cut_by_an_ellipsis():
    css = (STATIC / "call-calls.css").read_text()
    rule = re.search(r"\.statestrip \.ssnote\{([^}]*)\}", css).group(1)
    assert "nowrap" not in rule and "ellipsis" not in rule


# ---- r2-tinkerer-1: the tip stays inside the strip and the page never scrolls sideways ---------------------------------------

def test_the_strips_tip_opens_inside_the_strip_below_the_chip_and_the_page_is_clipped():
    css = (STATIC / "call-calls.css").read_text()
    tip = re.search(r"\.statestrip \.ib\[data-tip\]::after\{([^}]*)\}", css).group(1)
    for part in ("left:auto", "right:0", "transform:none", "top:calc(100% + 8px)", "bottom:auto", "white-space:normal", "max-width:calc(100cqw - 16px)", "width:max-content"):
        assert part in tip, part
    assert re.search(r"\n\.app\{overflow:clip\}", css)
    assert re.search(r"\nhtml,body\{overflow:hidden;max-width:100%\}", css)
    html = (STATIC / "call.html").read_text()
    assert html.index('href="/static/call.css"') < html.index('href="/static/call-calls.css"')   # so the rule above wins over call.css's generic tip


# ---- r2-interrupter-3: the strip says what the card says, with the card's clock ---------------------------------------------

def test_the_strip_counts_from_the_first_send_like_the_card_even_after_send_again(tmp_path):
    first = lambda b: waiting(b, 1, entries=again_entries(), turn={"entries": [{"id": 2, "state": "sent"}], "earlier": 0, "collected_at": None, "alive_at": None})
    page = wait_page(tmp_path, lambda b: [first(b), {**first(b), "v": "w2", "stalled": True}]).js("await serve(1);")
    both = "[$('sstext').textContent, $('waitcard').querySelector('.wt-clock').textContent, $('statestrip').dataset.key]"
    page.check(both)
    page.js("await serve(2);").check(both)
    assert page.run() == [["Sent, waiting for Claude to pick it up · 1:12", "1:12", "answering"],
                          ["Claude has not picked this up yet · 1:12", "1:12", "stalled"]]


def silent(b):
    return picked(b, 1, stalled=True, entries=[{**YOU, "at": NOW - 230}],
                  turn={"entries": [{"id": 0, "state": "picked"}], "earlier": 0, "collected_at": NOW - 225, "alive_at": NOW - 200})


def test_a_session_gone_quiet_is_said_as_gone_quiet_in_the_strip_in_both_languages(tmp_path):
    row = "[$('sstext').textContent, $('waitcard').querySelector('.wt-title').textContent]"
    en = wait_page(tmp_path, lambda b: [silent(b)]).js("await serve(1);").check(row)
    el = wait_page(tmp_path, lambda b: [silent(b)], language="el").js("await serve(1);").check(row)
    assert en.run() == [["Claude has gone quiet · 3:50", "Claude has gone quiet"]]
    assert el.run() == [["Ο Claude έχει σιωπήσει · 3:50", "Ο Claude έχει σιωπήσει"]]


# ---- r2-interrupter-2: the earlier question is a condition ---------------------------------------------------------------------

def correction(b, **fields):
    new = {**YOU, "id": 1, "text": "no, ten days", "replaces": 0, "at": NOW - 4}
    return waiting(b, 1, entries=[{**YOU, "superseded": True}, new], turn={"entries": [{"id": 1, "state": "sent"}], "earlier": 1, "collected_at": None, "alive_at": None}, **fields)


def test_the_earlier_question_line_needs_a_sign_that_the_session_is_working_and_says_may(tmp_path):
    sub = card("querySelector('.wt-sub').textContent")
    dead = wait_page(tmp_path, lambda b: [correction(b)]).js("await serve(1);").check(sub)
    live = wait_page(tmp_path, lambda b: [correction(b, working=True, activity=[{"label": "Reading", "state": "running", "seconds": 3}])]).js("await serve(1);").check(sub)
    greek = wait_page(tmp_path, lambda b: [correction(b, working=True, activity=[{"label": "Reading", "state": "running", "seconds": 3}])], language="el").js("await serve(1);").check(sub)
    assert dead.run() == ["Waiting for Claude to pick it up."]
    assert live.run() == ["Claude may still be finishing the earlier question. This one comes next."]
    assert greek.run() == ["Ο Claude ίσως ολοκληρώνει ακόμη την προηγούμενη ερώτηση. Αυτή έρχεται μετά."]


# ---- r2-interrupter-4: Take back counts the questions and shows the box from its first line --------------------------------------

def test_take_back_counts_the_questions_put_back_and_scrolls_the_box_to_its_top(tmp_path):
    turn = {"entries": [{"id": 2, "state": "sent"}], "earlier": 0, "collected_at": None, "alive_at": None}
    page = wait_page(tmp_path, lambda b: [waiting(b, 1, entries=again_entries(), turn=turn)]).js("await serve(1);")
    page.js("globalThis.OUTCOME = {2: {cancelled: true, how: 'withdrawn', entries: [2]}};" + CANCEL_EACH
            + "$('text').scrollTop = 48; [...$('waitcard').querySelectorAll('.wt-btn')].find(b => b.textContent === 'Take back').click(); await advance(10);")
    page.check("$('text').value")
    page.check("$('sendnote').querySelector('.sn-text').textContent")
    page.check("$('text').scrollTop")
    assert page.run() == ["How do vaccines work?\nand the shots?", "Took back 2 questions. Your words are back in the box, in order.", 0]


# ---- r2-mic-2: the mic note goes with a typed message ----------------------------------------------------------------------------

def test_the_nothing_was_heard_note_goes_when_the_reader_types_or_a_typed_message_is_sent(tmp_path):
    page = page_of(tmp_path)
    page.js("showMicNote('Nothing was heard in 3.9 s.');").check("[$('micnote').hidden, $('micnote').textContent]")
    page.js("$('text').value = 'h'; $('text').dispatchEvent(new ShimEvent('input'));").check("$('micnote').hidden")
    page.js("showMicNote('Nothing was heard in 3.9 s.'); $('text').value = 'A typed question'; $('sendtext').click(); await tick(100);").check("[$('micnote').hidden, $('text').value]")
    assert page.run() == [[False, "Nothing was heard in 3.9 s."], True, [True, ""]]


# ---- r2-power-2: "1 other call needs you" opens the Calls menu ---------------------------------------------------------------------

OTHERS = ("STATES[2] = {...STATES[2], v: 'c', calls: [{id: 'a', topic: 'A', unheard: 1, started: 1, last_at: 1}]}; await serve(2);")


def test_the_other_calls_line_is_a_button_that_opens_the_calls_menu_by_click_enter_and_space(tmp_path):
    page = page_of(tmp_path).js(OTHERS)
    page.check("[$('ssmore').getAttribute('role'), $('ssmore').tabIndex, $('ssmore').title, $('pCalls').hidden]")
    page.js("$('ssmore').click(); await settle();").check("[$('pCalls').hidden, $('callsbtn').getAttribute('aria-expanded')]")
    page.js("showPop(null); $('ssmore').dispatchEvent(new ShimEvent('keydown', {key: 'Enter', bubbles: true})); await settle();").check("$('pCalls').hidden")
    page.js("showPop(null); $('ssmore').dispatchEvent(new ShimEvent('keydown', {key: ' ', bubbles: true})); await settle();").check("$('pCalls').hidden")
    page.js("showPop(null); $('ssmore').dispatchEvent(new ShimEvent('keydown', {key: 'a', bubbles: true})); await settle();").check("$('pCalls').hidden")
    assert page.run() == [["button", 0, "Calls that need you: “A”", True], [False, "true"], False, False, True]


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
