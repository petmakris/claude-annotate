"""The call page's side of round 2 (batch stage): the page tells the stage its language, following comes back to the board the
voice showed last, and the reader's strip says when the board over it is another answer's."""
from pathlib import Path

from call_page import CallPage, needs_node, served

pytestmark = needs_node

STATIC = Path(__file__).resolve().parents[1] / "static"
TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"
FIRST = f"Lead words for the first answer. [[show table | One]]{TABLE}[[/show]] First words go on and on for a while."
SECOND = f"Lead words for the second answer. [[show table | Two]]{TABLE}[[/show]] Second words go on and on for a while."
TEXT_ONLY = "A plain answer that shows nothing new and keeps talking for a good while longer."
VIEWS = ("fromStage({type: 'stage:views', list: [{name: 'one', title: 'One', kind: 'table', answer: 1}, "
         "{name: 'two', title: 'Two', kind: 'table', answer: 2}]});")
LANG = "toStage().filter((m) => m.type === 'stage:lang')"
FOLLOWS = "toStage().filter((m) => m.type === 'stage:follow')"


# -- r2-greek-2: the page says its language to the stage --------------------------------------------------------------

def test_the_page_sends_the_stage_its_language_on_ready_and_on_a_change(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = CallPage(html, states).check(LANG)
    page.js("uiLang = 'el'; sendStageLang(); sendStageLang();").check(LANG)
    page.js("fromStage({type: 'stage:ready'});").check(LANG)             # a stage loaded again starts from the page's language
    greek = CallPage(html, states, stored={"language": "el"}).check(LANG)
    assert page.run() == [[{"type": "stage:lang", "lang": "en"}],
                          [{"type": "stage:lang", "lang": "en"}, {"type": "stage:lang", "lang": "el"}],
                          [{"type": "stage:lang", "lang": "en"}, {"type": "stage:lang", "lang": "el"}, {"type": "stage:lang", "lang": "el"}]]
    assert greek.run() == [[{"type": "stage:lang", "lang": "el"}]]
    js = (STATIC / "call-stage.js").read_text()
    assert 'new MutationObserver(sendStageLang).observe(document.documentElement, {attributes: true, attributeFilter: ["lang"]})' in js   # applyLang sets <html lang>: the one event of a change


# -- r2-first-3: following comes back to the board the voice showed last --------------------------------------------------

def test_back_to_the_voice_asks_the_stage_for_the_board_the_voice_showed_but_a_play_of_the_board_in_front_does_not(tmp_path):
    html, states = served(tmp_path, [FIRST, SECOND], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(2);" + VIEWS + "await playTo(2.0);")
    page.js("fromStage({type: 'stage:follow', on: false}); followAgain();").check(FOLLOWS + ".slice(-1)")
    page.js("fromStage({type: 'stage:follow', on: false}); followAgain(false);").check(FOLLOWS + ".slice(-1)")
    page.js("fromStage({type: 'stage:follow', on: false}); $('follow').click();").check(FOLLOWS + ".slice(-1)")      # the gear's switch turns it on
    page.js("$('follow').click();").check(FOLLOWS + ".slice(-1)")                                                      # and off: no front
    got = page.run()
    assert got == [[{"type": "stage:follow", "on": True, "front": True}], [{"type": "stage:follow", "on": True, "front": False}],
                   [{"type": "stage:follow", "on": True, "front": True}], [{"type": "stage:follow", "on": False, "front": False}]]
    assert "followAgain(false)" in (STATIC / "call-player.js").read_text()      # playFrom of the board in front keeps it: no front asked


def test_the_page_names_the_latest_real_board_a_front_cue_fronted_for_the_card_to_offer(tmp_path):
    html, states = served(tmp_path, [FIRST, SECOND, TEXT_ONLY], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(2);" + VIEWS).check("voiceBoard()")                  # the answer opens with its board: its cue fronted it at once
    page.js("await playTo(2.0); fromStage({type: 'stage:shown', view: 'two'});").check("voiceBoard()")
    page.js("await end(); await serve(3); await playTo(1.0);").check("voiceBoard()")                                  # a text-only answer: the board is where the voice left it
    page.js("fromStage({type: 'stage:shown', view: 'one'});").check("voiceBoard()")
    page.js("fromStage({type: 'stage:follow', on: false}); showVoiceBoard();").check("[toStage().filter((m) => m.type === 'stage:front').slice(-1)[0], toStage().filter((m) => m.type === 'stage:follow').slice(-1)[0]]")
    got = page.run()
    two = {"view": "two", "answer": 2, "title": "Two"}
    assert got[0] == {**two, "shown": False}    # the stage has not said it is on it yet
    assert got[1] == {**two, "shown": True} and got[2] == {**two, "shown": True}
    assert got[3] == {**two, "shown": False}
    assert got[4] == [{"type": "stage:front", "view": "two", "manual": False, "answer": 2}, {"type": "stage:follow", "on": True, "front": True}]


# -- r2-finder-4: the strip names its answer and dims when the board over it is another answer's ----------------------------

STRIP = ("(() => { const r = $('reader'), h = r.querySelector('.rhead'); return {cls: r.className, foreign: r.hasAttribute('data-foreign'), opacity: r.style.opacity,"
         " label: h && h.textContent, shown: h && h.style.display}; })()")


def test_with_following_off_the_strip_over_another_answers_board_says_which_answer_it_is_and_dims(tmp_path):
    html, states = served(tmp_path, [FIRST, SECOND], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(2);" + VIEWS + "fromStage({type: 'stage:follow', on: false}); fromStage({type: 'stage:shown', view: 'one'}); await playTo(2.5);")
    page.check(STRIP)
    page.js("fromStage({type: 'stage:shown', view: 'two'}); await playTo(2.6);").check(STRIP)                  # the board of this very answer: nothing to say
    page.js("fromStage({type: 'stage:shown', view: 'one'}); fromStage({type: 'stage:follow', on: true}); await playTo(2.7);").check(STRIP)   # following: the voice owns the stage
    got = page.run()
    assert got[0] == {"cls": "reader strip", "foreign": True, "opacity": "0.62", "label": "Answer 2:", "shown": "inline"}
    assert got[1] == {"cls": "reader strip", "foreign": False, "opacity": "", "label": "Answer 2", "shown": ""}
    assert got[2]["foreign"] is False and got[2]["label"] == "Answer 2"


def test_following_an_answer_with_no_board_the_strip_over_the_earlier_board_names_its_answer_and_dims(tmp_path):
    html, states = served(tmp_path, [FIRST, TEXT_ONLY], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(2);fromStage({type: 'stage:views', list: [{name: 'one', answer: 1}]}); fromStage({type: 'stage:shown', view: 'one'}); await playTo(2.5);")
    page.check(STRIP)
    page.check("$('nowfollow').querySelector('.fl-text').textContent")
    got = page.run()
    assert got[0] == {"cls": "reader strip", "foreign": True, "opacity": "0.62", "label": "Answer 2:", "shown": "inline"}
    assert got[1] == "Stage still on: One"
