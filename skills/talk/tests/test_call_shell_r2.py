"""Round 2 of the bulldozer on the call page's conversation (call-shell.js): the Now card's text window sized in whole lines by the free
height, the earlier list's search, the boards icon, a row that opens to the top, one word for replay, the Play target with its reason,
the Following strip's words, the chip badge, the question echo, the heading roles and the Copy word. Run under node on the real page
(call_page.py), like test_call_shell.py; every box measures 0 there, so the sizes a test needs are set on the elements."""
import re

from call_page import CallPage, needs_node
from test_call_shell import ASKS, FIRST, ROWS, SECOND, STATIC, TABLE, THIRD, asked
from test_call_shell_r1 import STRIP_TEXT, css_first

pytestmark = needs_node

TWO = FIRST + " [[show table | Two]]" + TABLE + "[[/show]] More."
# `more(k)` adds k earlier answers (a question and a spoken answer each) to the call's view and paints it
MORE = ("globalThis.more = (k) => { const base = Math.max(...view.entries.map((e) => e.id)); for (let i = 1; i <= k; i++) view.entries.splice(1, 0,"
        " {id: base + 2 * i - 1, who: 'you', text: 'question ' + i, at: 1, typed: true}, {id: base + 2 * i, who: 'claude', n: 100 + i, text: 'Answer ' + i + '. Second.', at: 1, speech: 'ready', words: []}); render(); };")
# sizes the shim cannot measure: the panel, the card and its parts, a line of the text
SIZES = ("const size = (el, o) => { for (const [k, v] of Object.entries(o)) Object.defineProperty(el, k, {value: v, configurable: true, writable: true}); };"
         "globalThis.size = size;")


# ---- r2-returning-3: the window is whole lines, its cue is current, and Show all lifts the cap -------------------------------------

def test_ntlines_snaps_to_whole_lines_between_three_and_sixteen_and_two_on_a_short_laptop(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1);")
    page.check("[ntLines(129, 25, false), ntLines(10, 25, false), ntLines(10, 25, true), ntLines(900, 25, false), ntLines(124.9, 25, false), ntLines(125, 25, false)]")
    assert page.run() == [[5, 3, 2, 16, 4, 5]]


def test_the_window_takes_the_height_the_panel_has_free_after_the_card_and_the_head_of_the_list_and_two_rows(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);" + SIZES)
    page.js("size($('convo'), {clientHeight: 661}); size($('nowcard'), {offsetHeight: 450}); size($('nowtext'), {offsetHeight: 150}); size($('tlhead'), {offsetHeight: 48}); fitNowText();")
    page.check("[$('nowtext').style.getPropertyValue('--nt-lines'), $('convo').classList.contains('has-earlier')]")   # 661 - 336 - (12 + 48 + 136) = 129 px: 5 lines of 25
    page.js("size($('convo'), {clientHeight: 761}); fitNowText();").check("$('nowtext').style.getPropertyValue('--nt-lines')")  # 100 px more: 4 lines more
    page.js("size($('convo'), {clientHeight: 481}); fitNowText();").check("$('nowtext').style.getPropertyValue('--nt-lines')")   # short laptop: two lines, never a half line
    assert page.run() == [["5", True], "9", "2"]


def test_show_all_is_there_only_when_the_text_is_longer_than_the_window_and_lifts_and_restores_the_cap(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);" + SIZES)
    state = "[$('ntmore').hidden, $('ntmore').textContent, $('ntmore').getAttribute('aria-expanded'), $('nowtext').hasAttribute('data-all')]"
    page.js("size($('convo'), {clientHeight: 661}); size($('nowtext'), {scrollHeight: 90}); fitNowText();").check(state)
    page.js("size($('nowtext'), {scrollHeight: 600}); fitNowText();").check(state)
    page.js("$('ntmore').click();").check(state)
    page.js("size($('nowtext'), {scrollHeight: 30}); fitNowText();").check(state)       # the cap is lifted: the control stays so the reader can put it back
    page.js("$('ntmore').click();").check(state)
    assert page.run() == [[True, "Show all", "false", False], [False, "Show all", "false", False], [False, "Show less", "true", True],
                          [False, "Show less", "true", True], [True, "Show all", "false", False]]


def test_a_new_answer_on_the_card_puts_the_cap_back_and_the_lit_word_keeps_in_view_while_it_is_lifted(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, seconds=3.0).js("await serve(1);" + SIZES + "size($('nowtext'), {scrollHeight: 900}); fitNowText(); $('ntmore').click(); size($('nowtext'), {clientHeight: 900});"
                                                 " globalThis.moved = []; $('convo').scrollTo = (o) => { moved.push(o.top); };")
    page.js("await playTo(1.0); audio.pause(); await settle(); moved.length = 0; size($('convo'), {scrollTop: 40, clientHeight: 300});"
            " size(lastWord, {getBoundingClientRect: () => ({top: 500, bottom: 520})}); size($('convo'), {getBoundingClientRect: () => ({top: 100, bottom: 400, height: 300})}); followVoice(false); globalThis.got = [...moved];")
    page.check("got")                                                                         # 40 + (500 - 100) - 300 * 0.4 = 320
    page.js("await end(); await serve(2);").check("[ntAll, $('nowtext').hasAttribute('data-all')]")
    assert page.run() == [[320], [False, False]]


def test_the_cue_that_text_lies_below_is_painted_again_when_the_panel_changes_not_only_when_the_text_is_built(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);" + SIZES)
    page.check("$('nowtext').hasAttribute('data-below')")
    page.js("size($('nowtext'), {scrollHeight: 400, clientHeight: 100, scrollTop: 0}); render();").check("$('nowtext').hasAttribute('data-below')")
    assert page.run() == [False, True]


def test_the_fade_is_a_line_and_a_half_and_the_scrollbar_shows_while_text_lies_beyond_the_window():
    css = css_first("call-shell.css")
    assert css[".now-text[data-below]"] == "--fade-bottom:calc(1.5 * var(--lh) * 1em);scrollbar-width:auto"
    assert css[".now-text[data-above]"] == "--fade-top:calc(1.5 * var(--lh) * 1em);scrollbar-width:auto"
    assert css[".now-text[data-all]"] == "max-height:none"
    assert "max-height:calc(var(--nt-lines) * var(--lh) * 1em)" in css[".now-text"] and "line-height:var(--lh)" in css[".now-text"]


# ---- r2-returning-2: the list keeps its head in view; the search field is opened, not always there ------------------------------------

def test_the_search_field_shows_after_the_icon_is_pressed_or_when_the_list_is_longer_than_a_screenful(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);" + MORE).check("[$('tlsearch').hidden, $('searchbtn').hidden]")
    page.js("more(8);").check("[$('tlcount').textContent, $('tlsearch').hidden]")                  # ten earlier answers: the rows fit a glance
    page.js("more(2);").check("[$('tlcount').textContent, $('tlsearch').hidden]")                  # twelve is still not more than SEARCH_AFTER
    page.js("more(1);").check("[$('tlcount').textContent, $('tlsearch').hidden]")
    assert page.run() == [[True, False], ["Earlier, 10 answers", True], ["Earlier, 12 answers", True], ["Earlier, 13 answers", False]]
    few = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);").js("$('searchbtn').click();").check("[$('tlsearch').hidden, $('searchbtn').getAttribute('aria-expanded')]")
    assert few.run() == [[False, "true"]]


def test_the_list_is_not_its_own_scroller_and_no_height_rule_of_its_own_was_added():
    css = css_first("call-shell.css")
    assert css[".tl"] == "flex:none;display:flex;flex-direction:column;gap:2px" and "min-height" not in css[".tl"] and "min-height" not in css[".tl-list"]


# ---- r2-returning-1: the boards icon of an answer with several boards opens the row and shows its first board ---------------------

def test_the_boards_icon_of_several_boards_opens_the_row_and_puts_the_first_board_on_the_stage_and_never_closes_the_row(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND, THIRD), asks=ASKS)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    icon = f"{ROWS}[0].querySelector('.tl-b')"
    fronts = "toStage().filter((m) => m.type === 'stage:front').map((m) => m.view)"
    page.check(f"[{icon}.getAttribute('aria-label'), {icon}.title]")
    page.js(f"{icon}.click();").check(f"[{ROWS}[0].classList.contains('open'), {fronts}, follow]")
    page.js(f"{icon}.click();").check(f"[{ROWS}[0].classList.contains('open'), {fronts}]")          # an open row stays open
    page.js(f"toStage().length = 0; {ROWS}[0].querySelector('.tl-main').click(); {ROWS}[0].querySelector('.tl-main').click();").check(f"[{ROWS}[0].classList.contains('open'), {fronts}]")
    page.js(f"toStage().length = 0; {ROWS}[0].querySelector('.tl-main').click(); $('tlexpand').click();").check(f"[{ROWS}.map((r) => r.classList.contains('open')), {fronts}]")
    got = page.run()
    assert got[0] == ["2 boards, open the answer and show Heat pump or gas boiler on the stage",
                      "Opens the answer and shows Heat pump or gas boiler on the stage. Boards: Heat pump or gas boiler, Key points"]
    assert got[1:] == [[True, ["heat-pump-or-gas-boiler"], False], [True, ["heat-pump-or-gas-boiler", "heat-pump-or-gas-boiler"]],
                       [True, []], [[True, True], []]]


def test_without_a_stage_the_icon_only_opens_the_row_and_says_so(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND, THIRD), asks=ASKS)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("CFG.stageUrl = ''; await serve(3);")
    icon = f"{ROWS}[0].querySelector('.tl-b')"
    page.check(f"[{icon}.getAttribute('aria-label'), {icon}.title]").js(f"{icon}.click();").check(f"[{ROWS}[0].classList.contains('open'), toStage().filter((m) => m.type === 'stage:front').length]")
    assert page.run() == [["2 boards, open the answer", "Heat pump or gas boiler, Key points"], [True, 0]]


# ---- r2-finder-3: a row that opens comes to the top of the panel ---------------------------------------------------------------------

def test_a_row_that_opens_scrolls_to_the_top_of_the_panel_and_a_row_that_closes_does_not(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3); globalThis.moved = []; $('convo').scrollTo = (o) => { moved.push(o.top); };" + SIZES)
    page.js("size($('convo'), {scrollTop: 50}); let P = Object.getPrototypeOf($('convo')); while (!Object.prototype.hasOwnProperty.call(P, 'getBoundingClientRect')) P = Object.getPrototypeOf(P); const rect = P.getBoundingClientRect;"   # rows are rebuilt when they open: measure by class
            "P.getBoundingClientRect = function () { return this.classList.contains('tlrow') ? {top: 640, bottom: 707, height: 67} : this.id === 'convo' ? {top: 88, bottom: 749, height: 661} : rect.call(this); };"
            f"{ROWS}[1].querySelector('.tl-main').click();").check("moved")
    page.js(f"{ROWS}[1].querySelector('.tl-main').click();").check("moved")   # closing it moves nothing
    assert page.run() == [[598], [598]]


# ---- r2-first-6: one word for replay, and the preview is not shown twice ------------------------------------------------------------

def test_replay_is_worded_hear_again_on_the_row_and_the_open_row_and_an_open_row_does_not_repeat_its_preview(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    row = f"{ROWS}[0]"
    page.check(f"[{row}.querySelector('button.play').textContent, {row}.querySelector('button.play').getAttribute('aria-label'), !!{row}.querySelector('.tl-gist')]")
    page.js(f"{row}.querySelector('.tl-main').click();")
    page.check(f"[[...{row}.querySelectorAll('.tl-acts .btn')].map((b) => b.textContent), {row}.querySelector('button.play').textContent, !!{row}.querySelector('.tl-gist')]")
    page.js("$('tlsearch').value = 'heat'; $('tlsearch').dispatchEvent(new ShimEvent('input'));").check(f"!!{row}.querySelector('.tl-gist')")   # a search keeps the words round its match
    assert page.run() == [["Hear again", "Hear answer 1 again", True], [["Hear again", "Copy"], "Hear again", False], True]


def test_the_greek_words_for_replay_are_the_same_on_the_row_and_the_open_row(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0, stored={"language": "el"}).js("await serve(3); " + ROWS + "[0].querySelector('.tl-main').click();")
    page.check(f"[{ROWS}[0].querySelector('button.play').textContent, {ROWS}[0].querySelector('.tl-acts .btn').textContent, {ROWS}[0].querySelector('button.play').getAttribute('aria-label')]")
    assert page.run() == [["Ακούστε ξανά", "Ακούστε ξανά", "Ακούστε ξανά την απάντηση 1"]]


# ---- S-first-1: Play names its target with the reason, and the card's own answer stays playable from the card ----------------------

def test_with_a_board_pinned_and_the_voice_paused_play_names_its_answer_with_the_reason_in_text_tooltip_and_label_and_the_strip_says_the_same(tmp_path):
    html, states = asked(tmp_path, answers=(TWO, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}]}); fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'}); fromStage({type: 'stage:follow', on: false});")
    pp = "[$('playpause').getAttribute('aria-label'), $('playpause').dataset.tip, $('playpause').querySelector('.pp-word').textContent]"
    note = "[$('nowfollow').querySelector('.fl-note')?.textContent, [...$('nowfollow').querySelectorAll('button')].map((b) => b.textContent)]"
    page.check(pp).check(note)
    assert page.run() == [["Play answer 1 (the board you chose)", "Play answer 1 (the board you chose) · Space", "Play answer 1 (the board you chose)"],
                          ["Play answer 1 (the board you chose)", ["Back to the voice", "Play this answer (2)"]]]


def test_the_card_has_its_own_play_while_the_board_is_pinned_and_it_plays_the_cards_answer_and_keeps_the_pin(tmp_path):
    html, states = asked(tmp_path, answers=(TWO, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}]}); fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'}); fromStage({type: 'stage:follow', on: false});")
    page.js("document.querySelector('#nowfollow .fl-own').click();").check("[current.n, follow, $('nownum').textContent, !!document.querySelector('#nowfollow .fl-own')]")
    page.js("audio.pause(); fromStage({type: 'stage:follow', on: true});").check("[!!document.querySelector('#nowfollow .fl-own'), $('playpause').getAttribute('aria-label')]")
    assert page.run() == [[2, False, "Answer 2 of 2", False], [False, "Play"]]


# ---- r2-listener-2: the strip says why the stage keeps a board, at a readable size, and what Keep this board does -------------------

def test_the_strip_says_why_the_stage_keeps_an_older_board_and_what_keeping_it_does_in_visible_words(tmp_path):
    html, states = asked(tmp_path, answers=(TWO, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}]}); fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'});")
    page.check("[$('nowfollow').querySelector('.fl-text').textContent, $('nowfollow').querySelector('.fl-hint')?.textContent ?? null, $('nowfollow').dataset.text]")
    page.js("await serve(2); fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 2}]});").check("[!!$('nowfollow').querySelector('.fl-hint'), $('nowfollow').dataset.text]")
    assert page.run() == [["This answer has no board, so the stage keeps Heat pump or gas boiler (answer 1).",
                           "Keep this board stops the stage from moving to the next answer's board.", "board"], [False, "plain"]]
    css = css_first("call-shell.css")
    assert "font-size:13.5px" in css[".fl-text"] and "font-size:13px" in css[".fl-hint"] and "line-clamp" not in css[".fl-text"] + css[".fl-hint"]


def test_the_greek_strip_says_why_and_what_keep_does(tmp_path):
    html, states = asked(tmp_path, answers=(TWO, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0, stored={"language": "el"}).js("await serve(2);")
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}]}); fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'});")
    page.check("[$('nowfollow').querySelector('.fl-text').textContent, !!$('nowfollow').querySelector('.fl-hint')]")
    assert page.run() == [["Αυτή η απάντηση δεν έχει πίνακα, γι' αυτό η σκηνή κρατά το Heat pump or gas boiler (απάντηση 1).", True]]


# ---- r2-tinkerer-4: the badge on the Key points chip is a fact ---------------------------------------------------------------------

def test_the_key_points_badge_says_how_many_points_the_answer_added_in_both_languages(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST + " [[key: Two]]",), asks=ASKS[:1])
    badge = "[...$('nowchips').querySelectorAll('button.chip.board small')].map((s) => s.textContent)"
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1);").check(badge)
    el = CallPage(html, states, autoplay=False, seconds=3.0, stored={"language": "el"}).js("await serve(1);").check(badge)
    assert page.run() == [["+2 points"]] and el.run() == [["+2 σημεία"]]
    one = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    assert CallPage(*one, autoplay=False, seconds=3.0).js("await serve(1);").check(badge).run() == [["+1 point"]]
    assert CallPage(*one, autoplay=False, seconds=3.0, stored={"language": "el"}).js("await serve(1);").check(badge).run() == [["+1 σημείο"]]


# ---- r2-typist-4: blank lines do not use up the clamp -------------------------------------------------------------------------------

def test_the_clamped_question_squeezes_blank_lines_and_show_all_gives_the_text_whole(tmp_path):
    q = "Great. Here is my draft:\n\nHi Anna,\n\n\nI want a heat pump.\n\nThanks"
    html, states = asked(tmp_path, answers=(FIRST,), asks=(q,))
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1);")
    text = "[$('nowq').querySelector('.nq-text').textContent, $('nowq').querySelector('.nq-more').hidden]"
    page.check(text).js("$('nowq').querySelector('.nq-more').click();").check(text)
    assert page.run() == [["Great. Here is my draft:\nHi Anna,\nI want a heat pump.\nThanks", False], [q, False]]


# ---- r2-screenreader-4: the answers are headings -------------------------------------------------------------------------------------

def test_the_card_and_every_earlier_row_are_headings_of_level_three_and_the_row_button_stays_a_button(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    page.check("[$('nownum').getAttribute('role'), $('nownum').getAttribute('aria-level')]")
    page.check(f"{ROWS}.map((r) => [r.querySelector('.tl-h').getAttribute('role'), r.querySelector('.tl-h').getAttribute('aria-level'), r.querySelector('.tl-h > button.tl-main') !== null])")
    assert page.run() == [["heading", "3"], [["heading", "3", True], ["heading", "3", True]]]


# ---- r2-typist-1: the word Copy beside the icon when the card is wide ----------------------------------------------------------------

def test_the_copy_button_shows_the_word_copy_beside_its_icon_on_a_wide_card_and_the_icon_alone_on_a_narrow_one(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    page.check("[$('nowcopy').querySelector('.cp-word').textContent, $('nowcopy').getAttribute('aria-label'), $('nowcopy').dataset.tip]")
    assert page.run() == [["Copy", "Copy answer", "Copy answer"]]
    css = (STATIC / "call-shell.css").read_text()
    assert css_first("call-shell.css")[".nowcopy .cp-word"].startswith("display:none")
    assert re.search(r"@media \(min-width:761px\)\{\.nowcopy:not\(\.done\)\{width:auto;padding:0 8px\}\.nowcopy:not\(\.done\) \.cp-word\{display:inline\}\}", css)
