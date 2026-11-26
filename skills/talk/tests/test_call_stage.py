"""The call page's side of the stage (call-stage.js, call.html), round 1 of the bulldozer on the side panel (batch stage):
the reader's place when an answer ends, the stage frame's name for a screen reader, and a pause left for long."""
import json

from call_page import CallPage, needs_node, served

pytestmark = needs_node

TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"
RESTS = "toStage().filter((m) => m.type === 'stage:rest')"
FLOW = ("[[show diagram | Flow]]graph TD; P[Page]-->Q[Queue]-->R[Reply][[/show]] "
        "lead lead lead lead lead lead [[+ P]] page page page page page page [[+ P->Q]] queue queue queue queue queue queue.")


# -- r1-mic-1: a finished answer reads from its first sentence --------------------------------------------------------

def test_the_reader_goes_back_to_its_first_sentence_when_an_answer_ends_but_keeps_its_place_on_a_pause(tmp_path):
    html, states = served(tmp_path, ["Just words, nothing to show. And a second sentence."], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(2.0);").check("[$('reader').className, audio.paused]")
    page.js("$('reader').scrollTop = 120; $('playpause').click();").check("[audio.paused, $('reader').scrollTop]")   # paused: it stays
    page.js("$('playpause').click(); $('reader').scrollTop = 120; await end();").check("[$('reader').className, audio.ended, $('reader').scrollTop]")
    assert page.run() == [["reader text", False], [True, 120], ["reader text", True, 0]]


# -- r1-screenreader-3: the stage frame names the board in front -----------------------------------------------------

def test_the_stage_frame_is_titled_with_the_board_in_front_its_kind_and_place_and_the_stage_is_a_region(tmp_path):
    html, states = served(tmp_path, ["Nothing yet."])
    assert '<div class="stagewrap" id="stagewrap" role="region" aria-label="Stage">' in html
    page = CallPage(html, states).check("$('stage').title")
    views = {"type": "stage:views", "list": [{"name": "a", "title": "Hours after feeding", "kind": "table", "answer": 1},
                                            {"name": "b", "title": "Is it ready", "kind": "diagram", "answer": 2}]}
    page.js("fromStage(%s); fromStage({ type: 'stage:shown', view: 'b' });" % json.dumps(views)).check("$('stage').title")
    page.js("fromStage({ type: 'stage:shown', view: 'a' });").check("$('stage').title")
    page.js("fromStage({ type: 'stage:views', list: [] });").check("$('stage').title")
    assert page.run() == ["Stage", "Stage: Is it ready, diagram, board 2 of 2", "Stage: Hours after feeding, table, board 1 of 2", "Stage"]


# -- S-listener-6: a pause left for long shows the boards whole ------------------------------------------------------

def test_a_pause_left_for_thirty_seconds_shows_the_boards_whole_and_playing_again_cancels_it(tmp_path):
    html, states = served(tmp_path, [FLOW], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.2); $('playpause').click();")
    page.js("await advance(29000);").check(RESTS)
    page.js("$('playpause').click(); await playTo(1.6); $('playpause').click(); await advance(29000);").check(RESTS)   # played again: the wait starts over
    page.js("await advance(2000);").check(RESTS)
    assert page.run() == [[], [], [{"type": "stage:rest", "views": ["flow"], "answer": 1}]]
