"""The call page's conversation (call-shell.js, call-stage.js): the Now card for the current turn, the list of earlier
answers with its search, the board chips and the Following strip, run under node on the real page (call_page.py)."""
import json
import re
from pathlib import Path
from unittest.mock import patch

from call_page import STAGE, CallPage, _settle, needs_node
from helpers import AUTH, CALL, run as run_async, running_app

pytestmark = needs_node

STATIC = Path(__file__).resolve().parents[1] / "static"
TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"
FIRST = f"[[show table | Heat pump or gas boiler]]{TABLE}[[/show]] A heat pump moves heat. It costs more to install. [[key: Install costs more]]"
SECOND = "Yes, though less so at minus ten. The numbers still hold."
THIRD = "Subsidies close much of the gap. Germany covers half."
ASKS = ["How does a heat pump work?", "Is it efficient in the cold?", "What do subsidies change?"]


def asked(tmp_path, answers=(FIRST, SECOND, THIRD), asks=ASKS, seconds=3.0, code=None):
    """A served call where each answer follows a question typed before it (the page's /api/state before any answer, and after each)."""
    import talk

    async def go():
        async with running_app(tmp_path, stage_url=STAGE, **({"code": code} if code else {})) as (client, call, fake):
            fake.seconds = seconds
            states = [await (await client.get("/api/state", headers=AUTH)).json()]
            for q, text in zip(asks, answers):
                call.add("you", q, typed=True)
                await call.answer(text)
                await _settle(call)
                states.append(await (await client.get("/api/state", headers=AUTH)).json())
            return await (await client.get(f"/c/{CALL}")).text(), states
    with patch.object(talk.speech, "voices", lambda wait=True: []):
        return run_async(go())


ROWS = "[...document.querySelectorAll('#tllist .tlrow')]"
CARD = ("{hidden: $('nowcard').hidden, num: $('nownum').textContent, state: $('nowstate').textContent, q: $('nowq').querySelector('.nq-text')?.textContent,"
        " text: $('nowtext').textContent, chips: [...$('nowchips').querySelectorAll('button.chip.board')].map((b) => b.querySelector('.cl').textContent)}")
LIST = f"{ROWS}.map((r) => r.querySelector('.tl-title').textContent)"
STRIP = "[$('nowfollow').hidden, $('nowfollow').dataset.mode, $('nowfollow').querySelector('.fl-state b')?.textContent, $('nowfollow').querySelector('.fl-text')?.textContent, $('nowfollow').querySelector('button')?.textContent]"


def test_the_now_card_holds_the_question_the_whole_text_and_the_state_in_words(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);").check(CARD)
    page.js("$('playpause').click(); await playTo(1.0);").check("$('nowstate').textContent").js("audio.pause();").check("$('nowstate').textContent")
    got = page.run()
    assert got[0] == {"hidden": False, "num": "Answer 3 of 3", "state": "New", "q": "What do subsidies change?", "text": THIRD, "chips": []}
    assert got[1:] == ["Playing", "Paused"]


def test_the_card_names_the_boards_of_its_answer_and_the_key_points_chip_says_how_many_points_it_added(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1);")
    page.check("[...$('nowchips').querySelectorAll('button.chip.board')].map((b) => [b.textContent, b.getAttribute('aria-label'), b.dataset.view, b.getAttribute('aria-pressed')])")
    page.check("$('nowchips').querySelector('.clbl').textContent")
    assert page.run() == [[["Heat pump or gas boiler", "Show on the stage: Heat pump or gas boiler", "heat-pump-or-gas-boiler", "false"],
                           ["Key points+1 point", "Show on the stage: Key points, +1 point", "key-points", "false"]], "On the stage"]


def test_earlier_answers_are_rows_in_columns_with_their_question_gist_boards_time_and_play(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);").check(LIST)
    page.check(f"{ROWS}.map((r) => [r.dataset.id, r.querySelector('.tl-n').textContent, r.querySelector('.tl-gist').textContent, r.querySelector('.tl-b').textContent,"
               " r.querySelector('.tl-t').textContent === clockOf(view.entries.find((e) => e.id == r.dataset.id).at), r.querySelector('button.play').getAttribute('aria-label')])")
    page.check("[$('tlcount').textContent, $('earlier').hidden, $('tlsearch').hidden]")
    got = page.run()
    assert got[0] == [ASKS[0], ASKS[1]]
    assert [r[1:4] for r in got[1]] == [["1", "A heat pump moves heat.", "2"], ["2", "Yes, though less so at minus ten.", ""]]
    assert [r[4:] for r in got[1]] == [[True, "Hear answer 1 again"], [True, "Hear answer 2 again"]]
    assert got[2] == ["Earlier, 2 answers", False, True]


def test_a_row_opens_in_place_with_its_full_text_and_boards_and_expand_all_opens_every_row(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    page.js(f"{ROWS}[0].querySelector('.tl-main').click();")
    page.check(f"{ROWS}.map((r) => [r.classList.contains('open'), r.querySelector('.tl-main').getAttribute('aria-expanded'), r.querySelector('.tl-text')?.textContent ?? null,"
               " [...r.querySelectorAll('.chip.board')].map((b) => b.querySelector('.cl').textContent)])")
    page.js("$('tlexpand').click();").check(f"[$('tlexpand').dataset.label, {ROWS}.map((r) => r.classList.contains('open'))]")
    page.js("$('tlexpand').click();").check(f"[$('tlexpand').dataset.label, {ROWS}.map((r) => r.classList.contains('open'))]")
    assert page.run() == [[[True, "true", "A heat pump moves heat. It costs more to install.", ["Heat pump or gas boiler", "Key points"]], [False, "false", None, []]],
                          ["Collapse all", [True, True]], ["Expand all", [False, False]]]


def test_a_search_finds_an_answer_by_its_question_its_words_or_its_boards_without_accents_or_case(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, "Το μάρμαρο ήρθε από το όρος Πεντέλη. Ένα δεύτερο.", THIRD))
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    page.js("globalThis.find = (q) => { $('tlsearch').value = q; $('tlsearch').dispatchEvent(new ShimEvent('input'));"
            f" return [{LIST}, $('tlcount').textContent, [...document.querySelectorAll('#tllist mark')].map((m) => m.textContent)]; }};")
    for q in ("EFFICIENT", "gas boiler", "μαρμαρο", "πεντελη", "subsid", "zzz"):
        page.check(f"find({q!r})")
    page.check("document.querySelector('#tllist .tl-none').textContent")
    page.js("$('tlsearch').value = ''; $('tlsearch').dispatchEvent(new ShimEvent('input'));").check(f"[{LIST}, $('tlcount').textContent]")
    assert page.run() == [
        [[ASKS[1]], "Filtered: 1 of 3 answers", ["efficient"]],
        [[ASKS[0]], "Filtered: 1 of 3 answers", []],
        [[ASKS[1]], "Filtered: 1 of 3 answers", ["μάρμαρο"]],
        [[ASKS[1]], "Filtered: 1 of 3 answers", ["Πεντέλη"]],
        [[ASKS[2]], "Filtered: 1 of 3 answers", ["subsid", "Subsid"]],
        [[], "Filtered: 0 of 3 answers", []],
        "No answer mentions “zzz”.",
        [[ASKS[0], ASKS[1]], "Earlier, 2 answers"]]


def test_progress_notes_the_session_posted_are_not_rows_of_the_conversation(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("view.entries.splice(1, 0, {id: 70, who: 'status', text: 'thinking it through', at: 1}, {id: 71, who: 'status', text: 'checking numbers', at: 2}); render();")
    page.check("[document.querySelectorAll('#convo .status, #convo .line').length, $('convo').textContent.includes('thinking it through'), "
               "$('convo').textContent.includes('checking numbers')]")
    assert page.run() == [[0, False, False]]


def test_the_foots_status_rule_never_reaches_a_status_line_of_the_conversation():
    css = (STATIC / "call.css").read_text()
    bare = [m for m in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if re.search(r"(^|,)\s*\.status\s*$", m[0].strip()) and "flex:1" in m[1].replace(" ", "")]
    scoped = [m[0].strip() for m in re.findall(r"([^{}]+)\{([^{}]*)\}", css) if "flex:1" in m[1].replace(" ", "") and ".status" in m[0]]
    assert bare == [] and scoped == [".foot .status"]


def test_a_new_answer_or_a_question_just_sent_brings_the_card_back_into_view(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1); $('convo').scrollTop = 300; convoFollow = false;")
    page.js("await serve(2);").check("$('convo').scrollTop")
    page.js("$('convo').scrollTop = 250; served = {...STATES[2], v: 'q', entries: [...STATES[2].entries, {id: 99, who: 'you', text: 'and more?', at: 5}]}; await advance(900);")
    page.check("$('convo').scrollTop")
    assert page.run() == [0, 0]


def test_a_text_only_answer_leaves_the_board_in_front_where_it_is_and_the_reader_names_its_answer(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST + " [[show table | Two]]" + TABLE + "[[/show]] More.", SECOND), asks=ASKS[:2])
    reader = "[$('reader').className, document.querySelector('#reader.text #rtext .rhead')?.textContent ?? null]"
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await end(); await advance(1600); fromStage({type: 'stage:shown', view: 'two'});")
    page.js("await serve(2); await playTo(1.0);").check(reader).js("await end(); await advance(1600);").check(reader)
    # with no board in front (the stage empty) the same answer is read in large type, under the label of its answer
    nobody = CallPage(html, states, seconds=3.0).js("await serve(2); await playTo(1.0);").check(reader)
    assert page.run() == [["reader strip", None], ["reader off", None]]
    assert nobody.run() == [["reader text", "Answer 2"]]


def test_a_chip_tap_pins_the_stage_and_the_strip_says_so_with_one_button_back(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}, {name: 'key-points', answer: 1}]});"
            "fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'});").check(STRIP)
    page.js("toStage().length = 0; document.querySelector('#tllist .tl-main').click(); document.querySelector('#tllist .tlrow .chip.board').click();")
    page.check(STRIP).check("[follow, toStage().filter((m) => m.type === 'stage:follow').map((m) => m.on)]")
    page.js("$('nowfollow').querySelector('button').click();").check(STRIP).check("[follow, toStage().filter((m) => m.type === 'stage:follow').map((m) => m.on)]")
    page.js("$('nowfollow').querySelector('button').click();").check("[follow, $('nowfollow').dataset.mode]")
    assert page.run() == [
        [False, "following", "Following the voice", "Stage still on: Heat pump or gas boiler", "Keep this board"],
        [False, "pinned", "You chose this", "Stage shows Heat pump or gas boiler from answer 1. The voice is on answer 2.", "Back to the voice"],
        [False, [False]],
        [False, "following", "Following the voice", "Stage still on: Heat pump or gas boiler", "Keep this board"],
        [True, [False, True]],
        [False, "pinned"]]


def test_the_chip_of_the_board_in_front_is_pressed_and_a_change_of_board_is_said_to_a_screen_reader(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1); globalThis.said = []; announce = (t) => said.push(t);")
    chips = "[...$('nowchips').querySelectorAll('button.chip.board')].map((b) => b.getAttribute('aria-pressed'))"
    page.js("fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'});").check(chips)
    page.js("fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'}); $('nowchips').querySelectorAll('button.chip.board')[1].click();").check("[...said]")
    page.js("fromStage({type: 'stage:shown', view: 'key-points'});").check(chips)
    assert page.run() == [["true", "false"], ["The stage shows Heat pump or gas boiler.", "Pinned the stage to Key points."], ["false", "true"]]


def test_play_on_another_answers_row_follows_the_voice_again_and_the_cards_own_play_keeps_the_pin(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST + " [[show table | Two]]" + TABLE + "[[/show]] More.", SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2); fromStage({type: 'stage:follow', on: false});").check("follow")
    page.js("$('playpause').click();").check("follow")
    page.js("audio.pause(); fromStage({type: 'stage:follow', on: false});").check("follow")
    page.js("document.querySelector('#tllist .tlrow button.play').click();").check("[follow, current.n, $('nownum').textContent]")
    assert page.run() == [False, False, False, [True, 1, "Answer 1 of 2"]]


def test_play_plays_the_answer_the_card_shows_and_only_a_board_the_reader_picked_sends_it_to_the_boards_answer(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST + " [[show table | Two]]" + TABLE + "[[/show]] More.", SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("fromStage({type: 'stage:views', list: [{name: 'heat-pump-or-gas-boiler', answer: 1}]});"
            "fromStage({type: 'stage:shown', view: 'heat-pump-or-gas-boiler'});")
    word = "[$('playpause').getAttribute('aria-label'), $('playpause').dataset.tip, $('playpause').querySelector('.pp-word').textContent, $('playpause').classList.contains('has-word')]"
    page.check(word)                       # following the voice, the newest answer is text only: Play is Play
    page.js("$('playpause').click();").check("[current.n, follow]")
    page.js("audio.pause(); audio.currentTime = 0; fromStage({type: 'stage:follow', on: false});").check(word)   # the reader pinned the board: Play says which answer
    page.js("$('playpause').click();").check("[current.n, follow]")
    assert page.run() == [["Play", "Play · Space", "", False], [2, True],
                          ["Play answer 1 (the board you chose)", "Play answer 1 (the board you chose) · Space", "Play answer 1 (the board you chose)", True], [1, True]]


def test_an_answer_replaced_by_a_correction_is_tagged_on_the_card_and_its_row(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("view.entries.find((e) => e.who === 'claude' && e.n === 2).superseded = true; view.entries.find((e) => e.who === 'claude' && e.n === 1).superseded = true; render();")
    page.check("[$('nowhead').querySelector('.now-tag')?.textContent, document.querySelector('#tllist .tl-tag')?.textContent]")
    assert page.run() == [["Replaced by your correction", "Replaced"]]


def test_the_empty_conversation_gives_a_question_to_start_with(tmp_path):
    html, states = asked(tmp_path, answers=(), asks=())
    page = CallPage(html, states, autoplay=False).check("[$('empty').hidden, $('empty').textContent, $('nowcard').hidden, $('earlier').hidden]")
    assert page.run() == [[False, "Nothing has been said yet.Type below or press the mic. For example: “Give me the short version.”", True, True]]


def test_the_transport_steps_by_sentence_and_the_speed_chip_cycles_the_speeds(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playTo(0.2);")
    page.js("$('next').click();").check("audio.currentTime > 0.2")
    page.js("$('back').click();").check("audio.currentTime < 0.3")
    page.check("[$('speedchip').textContent, $('seek').getAttribute('aria-label'), $('seek').getAttribute('aria-valuetext')]")
    page.js("$('speedchip').click();").check("[$('speedchip').textContent, audio.playbackRate]")
    assert page.run() == [True, True, ["1×", "Position in answer 1", "0:00 of 0:04"], ["1.25×", 1.25]]


def test_the_stages_board_list_runs_in_the_order_its_counter_counts_and_says_no_newest_first():
    css = (Path(__file__).resolve().parents[2] / "stage" / "static" / "stage.css").read_text()
    js = (Path(__file__).resolve().parents[2] / "stage" / "static" / "stage.js").read_text()
    tabs = re.search(r"\.tabs\{([^}]*)\}", css).group(1)
    assert "flex-direction:column;" in tabs and "column-reverse" not in tabs
    assert '<h4>${wd("boards")}</h4>' in js and "newest first" not in js


def test_a_search_that_matches_the_words_of_an_answer_shows_the_match_near_the_start_of_the_snippet_on_two_lines(tmp_path):
    long_first = "This opening runs on for a good while before it reaches anything of interest to the reader. Frankfurt is the healthiest of the three."
    html, states = asked(tmp_path, answers=(long_first, SECOND, THIRD))
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);")
    page.js("$('tlsearch').value = 'frankfurt'; $('tlsearch').dispatchEvent(new ShimEvent('input'));")
    page.check("[$('tllist').classList.contains('searching'), document.querySelector('#tllist .tl-gist').textContent]")
    page.js("$('tlsearch').value = ''; $('tlsearch').dispatchEvent(new ShimEvent('input'));").check("$('tllist').classList.contains('searching')")
    assert page.run() == [[True, "…the reader. Frankfurt is the healthiest of the three."], False]
    css = (STATIC / "call-shell.css").read_text()
    assert "#tllist.searching .tl-gist{display:-webkit-box;white-space:normal;-webkit-line-clamp:2" in css


def test_every_board_kind_has_its_own_chip_icon_and_none_falls_back_to_the_page_icon():
    import re as _re
    js = (STATIC / "call-shell.js").read_text()
    kinds = _re.search(r'BOARD_KINDS = \(([^)]*)\)', (Path(__file__).resolve().parents[1] / "talk.py").read_text()).group(1)
    have = set(_re.findall(r"^  (\w+): '<", js.split("const KIND_ICONS = {")[1].split("};")[0], _re.M))
    have |= set(_re.findall(r"KIND_ICONS\.(\w+) =", js))
    want = set(_re.findall(r'"(\w+)"', kinds))
    assert sorted(want - have) == []


def test_typing_in_the_search_brings_the_field_to_the_top_so_a_phone_shows_the_results():
    html, states = asked(Path(__import__("tempfile").mkdtemp()), answers=(FIRST, SECOND, THIRD))
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3); globalThis.jumps = 0; $('convo').scrollTo = () => { jumps++; };")
    page.js("$('tlsearch').value = 'subsid'; $('tlsearch').dispatchEvent(new ShimEvent('input'));").check("jumps")
    page.js("$('tlsearch').value = ''; $('tlsearch').dispatchEvent(new ShimEvent('input'));").check("jumps")
    assert page.run() == [1, 1]
