"""Round 1 of the bulldozer on the call page's conversation (call-shell.js): the Now card's Play and Copy, the Following strip,
the question and note rows, the earlier list's search, Expand all and focus, who each answer answers, and the times on it.
Run under node on the real page (call_page.py), like test_call_shell.py."""
import re
from datetime import date, timedelta
from pathlib import Path

from call_page import CallPage, needs_node
from test_call_shell import ASKS, FIRST, ROWS, SECOND, STATIC, TABLE, THIRD, asked

STRIP_TEXT = "[$('nowfollow').dataset.mode, $('nowfollow').querySelector('.fl-state b')?.textContent, $('nowfollow').querySelector('.fl-text')?.textContent, $('nowfollow').querySelector('.fl-note')?.textContent ?? null, $('nowfollow').querySelector('button').getAttribute('aria-label'), $('nowfollow').querySelector('button').title]"


def css_rules(name):
    """The rules of a stylesheet as (selector, body); a selector given twice (a phone's override) keeps its first body in `css_first`."""
    return re.findall(r"([^{}@]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(), flags=re.S))


def css_first(name):
    out = {}
    for sel, body in css_rules(name):
        out.setdefault(sel.strip(), body)
    return out


# ---- S-tinkerer-6, r1-listener-3: the strip's words, and nothing clamped -----------------------------------------------------

@needs_node
def test_the_strip_names_the_voice_the_board_and_its_answer_in_the_words_the_stage_button_uses(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}, {name: 'key-points', answer: 1}]});")
    page.js("fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'});").check(STRIP_TEXT)
    page.js("document.querySelector('#tllist .tl-main').click(); document.querySelector('#tllist .tlrow .chip.board').click();").check(STRIP_TEXT)
    page.js("$('nowfollow').querySelector('button').click(); fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 2}]});").check(STRIP_TEXT)
    got = page.run()
    assert got == [
        ["following", "Following the voice", "Stage still shows Heat pump or gas boiler from answer 1.", None, "Keep this board", "Keep the stage on this board"],
        ["pinned", "You chose this", "Stage shows Heat pump or gas boiler from answer 1. The voice is on answer 2.", "Play starts answer 1.", "Back to the voice", "Back to the voice"],
        ["following", "Following the voice", "The stage shows what is being read.", None, "Keep this board", "Keep the stage on this board"]]


def test_nothing_in_the_strip_is_cut_by_a_line_clamp_and_the_phone_keeps_its_words_and_44_px_buttons():
    css = (STATIC / "call-shell.css").read_text()
    clamped = [sel.strip() for sel, body in css_rules("call-shell.css") if "line-clamp" in body and re.search(r"fl-text|fl-note|now-follow", sel)]
    assert clamped == []
    phone = css[css.index("@media (max-width:760px)"):]
    assert ".fl-btn{min-width:44px;min-height:44px" in phone
    assert css_first("call-shell.css")['.now-follow[data-mode="following"][data-text="plain"] .fl-text'] == "display:none"   # only the bare sentence goes (its tooltip); a board named is always shown


# ---- S-phone-7: the shell's own buttons on a phone -----------------------------------------------------------------------------

def test_expand_all_and_show_all_and_the_row_buttons_are_44_px_on_a_phone():
    phone = (STATIC / "call-shell.css").read_text()
    phone = phone[phone.index("@media (max-width:760px)"):]
    assert ".tl-expand,.tl-clear{min-width:44px;min-height:44px}" in phone
    assert ".tl-b,.tlrow .play{min-height:44px}" in phone
    assert ".now-transport .ib{width:38px" not in phone and ".speedchip{height:30px" not in phone   # the input batch's 44 px targets are not shrunk here


# ---- S-finder-2: Expand all, the card's window, the fade -------------------------------------------------------------------------

@needs_node
def test_expand_all_brings_the_head_of_the_list_to_the_top_and_collapse_all_does_not(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3); globalThis.jumps = []; $('convo').scrollTo = (o) => { jumps.push(o.top); };")
    page.js("$('tlexpand').click();").check("[$('tlexpand').dataset.label, jumps.length]")
    page.js("$('tlexpand').click();").check("[$('tlexpand').dataset.label, jumps.length]")
    assert page.run() == [["Collapse all", 1], ["Expand all", 1]]


@needs_node
def test_the_card_window_is_shorter_while_earlier_answers_exist_and_the_conversation_fades_when_more_lies_below(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1);").check("[$('convo').classList.contains('has-earlier'), $('earlier').hidden]")
    page.js("await serve(3);").check("[$('convo').classList.contains('has-earlier'), $('convo').hasAttribute('data-more'), $('convo').lastElementChild.id]")
    page.js("Object.defineProperty($('convo'), 'scrollHeight', {value: 900, configurable: true}); $('convo').clientHeight = 400; $('convo').dispatchEvent(new ShimEvent('scroll'));")
    page.check("$('convo').hasAttribute('data-more')")
    page.js("$('convo').scrollTop = 500; $('convo').dispatchEvent(new ShimEvent('scroll'));").check("$('convo').hasAttribute('data-more')")
    assert page.run() == [[False, True], [True, False, "convofade"], True, False]
    css = css_first("call-shell.css")
    assert css[".convo.has-earlier .now-text"] == "max-height:clamp(150px,28vh,300px)"
    assert ".convo[data-more] .convo-fade::after" in css and css[".convo[data-more] .convo-fade::after"] == "opacity:1"


# ---- r1-greek-2: an answer played to its end shows its first line again ---------------------------------------------------------------

@needs_node
def test_an_answer_played_to_its_end_shows_its_first_line_again_and_a_pause_keeps_the_place(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playTo(1.0);")
    above = "[$('nowtext').scrollTop, $('nowtext').hasAttribute('data-above')]"
    page.js("$('nowtext').scrollTop = 40; $('nowtext').dispatchEvent(new ShimEvent('scroll'));").check(above)
    page.js("audio.pause();").check(above)
    page.js("$('playpause').click(); await playTo(3.0); $('nowtext').scrollTop = 40; $('nowtext').dispatchEvent(new ShimEvent('scroll'));").check(above)
    page.js("await end();").check(above).check("$('nowstate').textContent")
    assert page.run() == [[40, True], [40, True], [40, True], [0, False], "Played"]
    css = css_first("call-shell.css")
    assert css[".now-text[data-above]"] == "--fade-top:26px" and css[".now-text[data-below]"] == "--fade-bottom:26px"
    assert "mask-image:linear-gradient(to bottom,transparent 0,#000 var(--fade-top)" in css[".now-text"]


# ---- r1-finder-1: the search ends when a question is sent or an answer comes --------------------------------------------------------------

SEARCH = "[tlQuery, $('tlsearch').value, searchOpen, $('tlcount').textContent, $('tlclear').hidden]"
ANSWER = "served = {...STATES[2], v: 'a' + Math.random(), entries: [...STATES[2].entries, STATES[3].entries.at(-1)]}; await advance(900);"
TYPE = "$('tlsearch').value = 'efficient'; $('tlsearch').dispatchEvent(new ShimEvent('input'));"


@needs_node
def test_a_question_sent_or_an_answer_that_comes_ends_the_search_but_opening_a_row_keeps_it(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);").check(SEARCH)
    page.js(TYPE).check(SEARCH)
    page.js("document.querySelector('#tllist .tl-main').click();").check(SEARCH)           # a row opened from the result: still filtered
    page.js("served = {...STATES[2], v: 'q', entries: [...STATES[2].entries, {id: 99, who: 'you', text: 'and more?', at: 5}]}; await advance(900);").check(SEARCH)
    page.js("await serve(2); " + TYPE + " " + ANSWER).check(SEARCH)                          # a new answer comes
    page.js("await serve(2); " + TYPE + " $('tlsearch').focus(); " + ANSWER).check(SEARCH)   # ... but not while the reader types in the search
    page.js("$('tlclear').click();").check(SEARCH)
    assert page.run() == [
        ["", "", False, "Earlier, 1 answer", True],
        ["efficient", "efficient", False, "Filtered: 1 of 2 answers", False],
        ["efficient", "efficient", False, "Filtered: 1 of 2 answers", False],
        ["", "", False, "Earlier, 1 answer", True],
        ["", "", False, "Earlier, 2 answers", True],
        ["efficient", "efficient", False, "Filtered: 1 of 3 answers", False],
        ["", "", False, "Earlier, 2 answers", True]]


# ---- r1-typist-1: a long typed question keeps its breaks, at the weight of the text, held to three lines ------------------------------

LONG_Q = "Please compare these:\n1. the running cost\n2. the noise\n3. the install time\nand tell me which one wins."


@needs_node
def test_a_long_question_keeps_its_breaks_is_held_to_three_lines_and_opens_with_show_all(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=(LONG_Q, ASKS[1]))
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1);")
    q = "[...document.querySelectorAll('#nowq .nq')].map((b) => [b.querySelector('.nq-text').textContent, b.querySelector('.nq-text').className, b.querySelector('.nq-more').hidden, b.querySelector('.nq-more').textContent])"
    page.check(q)
    page.js("document.querySelector('#nowq .nq-more').click();").check(q)
    page.js("document.querySelector('#nowq .nq-more').click();").check(q)
    page.js("await serve(2);").check(q)
    assert page.run() == [
        [[LONG_Q, "nq-text clamped", False, "Show all"]],
        [[LONG_Q, "nq-text", False, "Show less"]],
        [[LONG_Q, "nq-text clamped", False, "Show all"]],
        [[ASKS[1], "nq-text clamped", True, "Show all"]]]


def test_the_question_is_set_as_typed_at_normal_weight_in_the_card_the_tv_and_the_phone():
    css = css_first("call-shell.css")
    text = css[".nq-text"].replace(" ", "")
    assert "white-space:pre-wrap" in text and text.startswith("font:400") and "overflow-wrap:anywhere" in text
    assert css[".nq-text.clamped"] == "display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden"
    assert css[".app[data-tv] .nq-text"] == "font-size:20px"
    phone = (STATIC / "call-shell.css").read_text()
    assert ".nq-text{font-size:14.5px}" in phone[phone.index("@media (max-width:760px)"):]
    assert "now-q strong" not in (STATIC / "call-shell.css").read_text()


# ---- r1-typist-3: Copy answer on the card -------------------------------------------------------------------------------------------------

@needs_node
def test_the_card_has_a_copy_answer_button_that_says_copied_on_itself_and_to_a_screen_reader(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js(
        "await serve(3); globalThis.copied = []; globalThis.said = []; announce = (t) => said.push(t);"
        "Object.defineProperty(navigator, 'clipboard', {value: {writeText: async (t) => { copied.push(t); }}, configurable: true});")
    btn = "[$('nowcopy').hidden, $('nowcopy').getAttribute('aria-label'), $('nowcopy').textContent, $('nowcopy').classList.contains('done'), $('nowcopy').parentNode.id]"
    page.check(btn)
    page.js("$('nowcopy').click();").check(btn).check("[copied, said]")
    page.js("await advance(1700);").check(btn)
    assert page.run() == [
        [False, "Copy answer", "", False, "nowhead"],
        [False, "Copied", "Copied", True, "nowhead"],
        [[THIRD], ["Copied"]],
        [False, "Copy answer", "", False, "nowhead"]]


# ---- r1-keyboard-1: Enter on a row's Play keeps the keyboard in the panel ------------------------------------------------------------------

@needs_node
def test_playing_from_a_row_leaves_focus_on_the_players_button_or_on_the_row_that_stayed(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    where = "[document.activeElement.id, document.activeElement.className, $('tllist').contains(document.activeElement)]"
    page.js("document.querySelector('#tllist button.play').focus(); document.querySelector('#tllist button.play').click();").check(where)
    page.js("audio.pause(); document.querySelector('#tllist .tl-main').click();"
            "const again = [...document.querySelectorAll('#tllist .tl-acts .btn')].find((b) => b.textContent === 'Play from the start'); again.focus(); again.click();").check(where)
    page.js("audio.pause(); rail = true; document.querySelector('#tllist button.play').focus(); document.querySelector('#tllist button.play').click(); rail = false;").check("document.activeElement.id")
    got = page.run()
    assert [got[0][0], got[0][2], got[1][0], got[1][2], got[2]] == ["playpause", False, "playpause", False, "railpp"]
    stayed = CallPage(html, states, autoplay=False, seconds=3.0).js(
        "await serve(3); $('tlsearch').value = 'efficient'; $('tlsearch').dispatchEvent(new ShimEvent('input'));"
        "const p = document.querySelector('#tllist button.play'); p.focus(); p.click();").check(where)
    assert stayed.run() == [["", "play", True]]


# ---- r1-interrupter-1: who each answer answers -----------------------------------------------------------------------------------------------

TURNS = ("const E = (id, who, extra = {}) => ({id, who, text: who + id, at: 1, ...extra});"
         "const rows = (list) => turnsOf(list).map((t) => [t.a.id, t.q && t.q.id, t.also.map((x) => x.id)]);")


@needs_node
def test_a_replaced_answer_belongs_to_the_question_it_was_written_for_and_the_next_answer_to_the_correction(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js(TURNS)
    page.check("rows([E(0, 'you', {superseded: true}), E(1, 'you', {replaces: 0}), E(2, 'claude', {superseded: true, superseded_kind: 'correction'}), E(3, 'claude')])")
    page.check("rows([E(0, 'you'), E(1, 'you', {while_working: true}), E(2, 'claude', {superseded: true, superseded_kind: 'addition'}), E(3, 'claude')])")
    page.check("rows([E(0, 'you'), E(1, 'you'), E(2, 'claude')])")
    page.check("rows([E(0, 'you', {superseded: true}), E(1, 'you', {withdrawn: true, superseded: true}), E(2, 'you', {replaces: 1}), E(3, 'claude', {superseded: true, superseded_kind: 'correction'}), E(4, 'claude')])")
    page.check("rows([E(0, 'you'), E(1, 'claude'), E(2, 'claude')])")
    assert page.run() == [[[2, 0, []], [3, 1, []]], [[2, 0, []], [3, 1, []]], [[2, 1, [0]]], [[3, 0, []], [4, 2, []]], [[1, 0, []], [2, None, []]]]


@needs_node
def test_the_list_titles_a_replaced_answer_by_its_own_question_and_the_card_shows_the_correction(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("const [y1, y2] = [...STATES[2].entries.filter((e) => e.who === 'you')], [a1, a2] = STATES[2].entries.filter((e) => e.who === 'claude');"
            "served = {...STATES[2], v: 'r', entries: [{...y1, superseded: true}, {...y2, replaces: y1.id}, {...a1, superseded: true, superseded_kind: 'correction'}, a2]}; await advance(900);")
    page.check("[document.querySelector('#tllist .tl-title').textContent, document.querySelector('#tllist .tl-tag')?.textContent, $('nowq').querySelector('.nq-text').textContent, $('nownum').textContent]")
    assert page.run() == [[ASKS[0], "Replaced", ASKS[1], "Answer 2 of 2"]]


# ---- r1-returning-1: a day on every time -----------------------------------------------------------------------------------------------------------

def _stamp(days):
    d = date.today() - timedelta(days=days)
    return d


@needs_node
def test_a_time_from_another_day_says_yesterday_or_the_date_at_every_place_it_is_shown(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js(
        "await serve(2); globalThis.ago = (days) => { const d = new Date(serverNow() * 1000); d.setDate(d.getDate() - days); d.setHours(9, 5, 0, 0); return d.getTime() / 1000; };")
    page.check("[clockOf(ago(0)), clockOf(ago(1)), clockOf(ago(3)), clockOf(ago(400)), clockOf(0)]")
    page.js("const [y1, y2] = STATES[2].entries.filter((e) => e.who === 'you'), [a1, a2] = STATES[2].entries.filter((e) => e.who === 'claude');"
            "served = {...STATES[2], v: 'd', entries: [{...y1, at: ago(1)}, {...a1, at: ago(1)}, {...y2, at: ago(3)}, {...a2, at: ago(3)}]}; await advance(900);")
    page.check("[document.querySelector('#tllist .tl-t').textContent, document.querySelector('#tllist .tl-t').title, $('nowclock').textContent, $('nowclock').title, $('nowq').querySelector('small').textContent]")
    got = page.run()
    three, old = _stamp(3), _stamp(400)
    mon = lambda d: f"{d.day} {d.strftime('%b')}"
    assert got[0] == ["09:05", "Yesterday 09:05", f"{mon(three)} 09:05", f"{mon(old)} {old.year} 09:05", ""]
    assert got[1] == ["Yesterday 09:05", "Answered at Yesterday 09:05", f"{mon(three)} 09:05", f"Answered at {mon(three)} 09:05", f"You asked, {mon(three)} 09:05"]


# ---- r1-phone-2: a saved note ---------------------------------------------------------------------------------------------------------------------------

NOTE = "Book Pena Palace tickets in advance, about 14 days before you go, to skip the queue at the gate."


@needs_node
def test_a_saved_note_is_a_row_with_a_check_and_the_word_saved_that_wraps_and_links_to_nothing(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js(f"view.entries.splice(view.entries.length - 1, 0, {{id: 80, who: 'note', text: {NOTE!r}, at: 1}}); render();")
    page.check("[...$('nowchips').querySelectorAll('.note-row')].map((r) => [r.tagName, r.querySelector('b').textContent, r.querySelector('.note-text').textContent, r.title, !!r.querySelector('svg'), r.querySelector('button, a') === null])")
    page.check("[$('nowchips').querySelectorAll('.chip.note').length, $('nowchips').hidden]")
    assert page.run() == [[["DIV", "Saved", NOTE, "Saved in this call's transcript", True, True]], [0, False]]
    css = css_first("call-shell.css")
    rule = css[".note-row"] + css[".note-text"]
    assert "overflow:hidden" not in rule and "line-clamp" not in rule and "flex:1 1 100%" in css[".note-row"] and "overflow-wrap:anywhere" in css[".note-text"]


# ---- r1-finder-5: what a board shows is searchable --------------------------------------------------------------------------------------------------

PASSES = ("[[show bars | Pass prices]]{\"title\": \"Pass prices\", \"unit\": \"EUR\", \"bars\": [{\"id\": \"d21\", \"label\": \"21-day pass\", \"value\": 45, \"note\": \"best value\"},"
          " {\"id\": \"d3\", \"label\": \"3-day pass\", \"value\": 18}]}[[/show]] The longer passes cost less a day.")


def test_a_board_entry_carries_the_words_its_board_shows(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, PASSES), asks=ASKS[:2])
    boards = {e["text"]: e["search"] for e in states[-1]["entries"] if e["who"] == "board"}
    assert boards == {"Heat pump or gas boiler": "a b 1 2", "Key points: +1": "Install costs more", "Pass prices": "Pass prices EUR 21-day pass 45 best value 3-day pass 18"}


def test_board_text_reads_each_kind_of_board_and_is_cut_at_a_word():
    import talk
    assert talk.board_text({"kind": "table", "body": "| Pass | Price |\n|---|---|\n| **21-day** | [€45](http://x) |"}) == "Pass Price 21-day €45"
    assert talk.board_text({"kind": "diagram", "body": "graph LR\n  A[Client] --> B[Server]"}) == "graph LR A[Client] --> B[Server]"
    assert talk.board_text({"kind": "scene", "body": "<div class='slide'><h1>Cost &amp; time</h1><script>x()</script></div>"}) == "Cost & time"
    assert talk.board_text({"kind": "code", "path": "a.py", "lines": ["x = 1", "y = 2"]}) == "a.py x = 1 y = 2"
    assert talk.board_text({"kind": "sequence", "visual": {"spec": {"actors": [{"id": "u", "label": "User"}], "steps": [{"id": "s1", "from": "u", "to": "u", "label": "Logs in", "tone": "blue"}]}}}) == "User Logs in"
    long = talk.board_text({"kind": "diagram", "body": "word " * 1000})
    assert len(long) <= talk.BOARD_TEXT_MAX and long.endswith("word")


@needs_node
def test_a_search_finds_a_figure_that_lives_in_a_board_and_shows_it_with_the_boards_icon(tmp_path):
    html, states = asked(tmp_path, answers=(PASSES, SECOND, THIRD))
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    page.js("globalThis.find = (q) => { $('tlsearch').value = q; $('tlsearch').dispatchEvent(new ShimEvent('input'));"
            f" return [{ROWS}.map((r) => r.querySelector('.tl-title').textContent), {ROWS}.map((r) => r.querySelector('.tl-gist')?.textContent), [...document.querySelectorAll('#tllist mark')].map((m) => m.textContent), !!document.querySelector('#tllist .in-board svg')]; }};")
    page.check("find('21-day')").check("find('EUR')").check("find('nothing here')")
    assert page.run() == [
        [[ASKS[0]], ["in Pass prices: …EUR 21-day pass 45 best value 3-day pass 18"], ["21-day"], True],
        [[ASKS[0]], ["in Pass prices: …EUR 21-day pass 45 best value 3-day pass 18"], ["EUR"], True],
        [[], [], [], False]]
