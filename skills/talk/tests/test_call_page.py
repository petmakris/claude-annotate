"""The call page plays the answers and drives the stage with them: run on call.js itself under node (call_page.py),
against a served call's real state, with no browser."""
from call_page import CallPage, needs_node, served

pytestmark = needs_node


def six(name):
    return " ".join(f"{name}{i}" for i in range(6))


TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"
FLOW_ANSWER = (f"[[show diagram | Flow]]graph TD; P[Page]-->Q[Queue]-->R[Reply][[/show]] "
               f"{six('lead')} [[+ P]] {six('page')} [[+ P->Q]] {six('queue')}.")
SENT = "toStage().filter((m) => m.type === 'stage:follow' || m.type === 'stage:state').map((m) => m.type === 'stage:follow' ? 'follow:' + m.on : 'state')"
RESTS = "toStage().filter((m) => m.type === 'stage:rest')"


def test_play_on_a_page_opened_after_the_answer_plays_the_last_answer(tmp_path):
    html, states = served(tmp_path, ["Said before you came back."])
    page = CallPage(html, states, start=1)  # an answer that was there when the page loaded is never played by itself
    page.check("[audio.paused, $('playpause').hidden]")
    page.js("$('playpause').click();").check("[audio.paused, audio.getAttribute('src')]")
    assert page.run() == [[True, False], [False, "/c/test-call-id/audio/0000.wav"]]


def test_the_voice_fronts_each_board_once_as_it_reaches_it(tmp_path):
    html, states = served(tmp_path, [f"[[show table | One]]{TABLE}[[/show]] {six('first')} "
                                     f"[[show table | Two]]| c | d |\n|---|---|\n| 3 | 4 |[[/show]] {six('second')}."])
    page = CallPage(html, states).js("await serve(1);").check("audio.paused").js("await end();")
    page.check("toStage().filter((m) => m.type === 'stage:state' || m.type === 'stage:front')")
    assert page.run() == [False, [{"type": "stage:state", "front": "one", "frames": {}, "keys": 0, "answer": 1},
                                  {"type": "stage:front", "view": "two", "manual": False, "answer": 1}]]


def test_a_replay_from_the_first_word_fronts_the_board_the_answer_came_in_with(tmp_path):
    # call ggkm: the answer opens with words before its first board, which it put up in front as it arrived
    html, states = served(tmp_path, [f"{six('intro')}. [[show table | Three paths changed]]{TABLE}[[/show]] "
                                     f"{six('paths')}. [[show table | Nightly batch guard]]{TABLE}[[/show]] {six('guard')}."])
    page = CallPage(html, states, autoplay=False).js("await serve(1); toStage().length = 0;")
    page.js("document.querySelector(\"#cap .w[data-i='0']\").click();")
    page.check("toStage().find((m) => m.type === 'stage:state')")
    assert page.run() == [{"type": "stage:state", "front": "three-paths-changed", "frames": {}, "keys": 0, "answer": 1}]


def test_a_play_the_reader_starts_takes_the_board_back_to_the_voice(tmp_path):
    html, states = served(tmp_path, [FLOW_ANSWER], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.2);")
    page.check("toStage().some((m) => m.type === 'stage:frame' && m.n === 1)")
    starts = {"Play": "$('playpause').click();",
              "conversation Play": "$('hist').click(); document.querySelector('#convo .turn.claude button.play').click(); key('Escape');",
              "word tap": "document.querySelector(\"#cap .w[data-i='3']\").click();",
              "Space": "document.body.focus(); key(' ');"}
    for how, start in starts.items():
        page.js("if (!audio.paused) $('playpause').click();")
        # the reader stepped the board by hand: the stage turned following off and said so
        page.js("fromStage({ type: 'stage:follow', on: false });").check("follow")
        page.js("toStage().length = 0;").js(start)
        page.check(f"[{how!r}, !audio.paused, follow, {SENT}]")
    assert page.run() == [True] + [x for how in starts for x in (False, [how, True, True, ["follow:true", "state"]])]


def test_an_answer_played_to_its_end_holds_its_last_frame_then_shows_its_boards_whole(tmp_path):
    html, states = served(tmp_path, [FLOW_ANSWER], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await end();")
    page.js("await advance(1000);").check(RESTS)  # the hold: the last frame stays
    page.js("$('playpause').click(); await playTo(0.5); await advance(600);").check(RESTS)  # played again within the hold
    page.js("await end(); await advance(1600);").check(RESTS)
    assert page.run() == [[], [], [{"type": "stage:rest", "views": ["flow"], "answer": 1}]]
