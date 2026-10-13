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
    page.check("[audio.paused, $('player').hidden]")
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
    page.js("document.querySelector(\"#convo .turn.claude .w[data-i='0']\").click();")
    page.check("toStage().find((m) => m.type === 'stage:state')")
    assert page.run() == [{"type": "stage:state", "front": "three-paths-changed", "frames": {}, "keys": 0, "answer": 1}]


def test_a_play_the_reader_starts_keeps_the_board_they_picked(tmp_path):
    # call IriDPEiq: the reader picked a board, went back a sentence and played on, and the stage took the board away
    html, states = served(tmp_path, [FLOW_ANSWER], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.2);")
    page.check("toStage().some((m) => m.type === 'stage:frame' && m.n === 1)")
    starts = {"Play": "$('playpause').click();",
              "conversation Play": "document.querySelector('#convo .turn.claude button.play').click();",
              "word tap": "document.querySelector(\"#convo .turn.claude .w[data-i='3']\").click();",
              "Space": "document.body.focus(); key(' ');",
              "← then Space": "document.body.focus(); key('ArrowLeft'); key(' ');",
              "← on the stage then Space": "fromStage({ type: 'stage:key', key: 'ArrowLeft' }); fromStage({ type: 'stage:key', key: ' ' });"}
    for how, start in starts.items():
        page.js("if (!audio.paused) $('playpause').click();")
        # the reader picked a board by hand: the stage turned following off and said so
        page.js("fromStage({ type: 'stage:follow', on: false });").check("follow")
        page.js("toStage().length = 0;").js(start)
        page.check(f"[{how!r}, !audio.paused, follow, {SENT}]")
    # Follow the voice on the stage puts it back where the voice is
    page.js("toStage().length = 0; fromStage({ type: 'stage:follow', on: true });").check(f"[follow, {SENT}]")
    sent = {how: ["state", "state"] if how.startswith("←") else ["state"] for how in starts}  # ← sends its own picture
    assert page.run() == [True] + [x for how in starts for x in (False, [how, True, False, sent[how]])] + [[True, ["state"]]]


def test_only_an_answer_that_starts_by_itself_turns_following_back_on(tmp_path):
    html, states = served(tmp_path, ["The first answer.", "The second answer."])
    page = CallPage(html, states, start=1)
    page.js("fromStage({ type: 'stage:follow', on: false }); toStage().length = 0;")
    page.js("document.querySelector('#convo .turn.claude button.play').click();")  # the reader replays an old answer
    page.js("await end(); await serve(2);")  # a new one comes and plays by itself
    page.check("toStage().filter((m) => m.type === 'stage:answer')")
    assert page.run() == [[{"type": "stage:answer", "n": 1, "follow": False}, {"type": "stage:answer", "n": 2, "follow": True}]]


def test_play_on_a_board_the_voice_is_not_on_plays_its_explanation_and_follows_again(tmp_path):
    html, states = served(tmp_path, [f"[[show table | One]]{TABLE}[[/show]] {six('first')}. "
                                     f"[[show table | Two]]| c | d |\n|---|---|\n| 3 | 4 |[[/show]] {six('second')}."], seconds=6.0)
    page = CallPage(html, states, seconds=6.0).js("await serve(1); await playTo(5.0); audio.pause();")
    page.js("fromStage({ type: 'stage:views', list: [{name: 'one', answer: 1}, {name: 'two', answer: 1}] });")
    page.js("fromStage({ type: 'stage:shown', view: 'one' }); fromStage({ type: 'stage:follow', on: false }); toStage().length = 0;")
    page.js("$('playpause').click();").check(f"[!audio.paused, audio.currentTime, follow, {SENT}]")
    assert page.run() == [[True, 0, True, ["follow:true", "state"]]]


def test_a_replay_of_the_sentence_about_a_page_fronts_the_page(tmp_path):
    # call IriDPEiq: the answer opened on its page, then went on to a table
    code = tmp_path / "code"
    code.mkdir()
    (code / "walk.html").write_text("<h1>Walkthrough</h1>")
    html, states = served(tmp_path, [f"[[show page: walk.html | Report data walkthrough]] {six('page')}. "
                                     f"[[show table | One asset's groups]]{TABLE}[[/show]] {six('fund')}."], seconds=4.0, code=code)
    page = CallPage(html, states, seconds=4.0, autoplay=False).js("await serve(1);")
    page.check("[...document.querySelectorAll('#convo button.chip.board')].map((b) => b.dataset.view)")
    for word in (0, 7):
        page.js("toStage().length = 0;").js(f"document.querySelector(\"#convo .turn.claude .w[data-i='{word}']\").click();")
        page.check("toStage().find((m) => m.type === 'stage:state').front")
    assert page.run() == [["report-data-walkthrough", "one-asset-s-groups"], "report-data-walkthrough", "one-asset-s-groups"]


def test_an_answer_played_to_its_end_holds_its_last_frame_then_shows_its_boards_whole(tmp_path):
    html, states = served(tmp_path, [FLOW_ANSWER], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await end();")
    page.js("await advance(1000);").check(RESTS)  # the hold: the last frame stays
    page.js("$('playpause').click(); await playTo(0.5); await advance(600);").check(RESTS)  # played again within the hold
    page.js("await end(); await advance(1600);").check(RESTS)
    assert page.run() == [[], [], [{"type": "stage:rest", "views": ["flow"], "answer": 1}]]


def test_an_answer_that_comes_while_the_tab_is_hidden_waits_and_plays_when_the_tab_is_seen(tmp_path):
    html, states = served(tmp_path, ["Said while you were in another tab."])
    page = CallPage(html, states)
    page.js("document.visibilityState = 'hidden'; await serve(1);").check("[audio.paused, audio.getAttribute('src')]")
    page.js("document.visibilityState = 'visible'; document.dispatchEvent(new ShimEvent('visibilitychange'));")
    page.check("audio.paused")
    assert page.run() == [[True, "/c/test-call-id/audio/0000.wav"], False]


def test_an_answer_held_for_a_hidden_tab_stays_put_once_the_reader_played_something_else(tmp_path):
    html, states = served(tmp_path, ["The first answer.", "The second answer."])
    page = CallPage(html, states, start=1)
    page.js("document.visibilityState = 'hidden'; await serve(2);")
    # back in the tab, the reader plays the first answer from its Play, then pauses it
    page.js("document.querySelector('#convo .turn.claude button.play').click(); audio.pause();")
    page.js("document.visibilityState = 'visible'; document.dispatchEvent(new ShimEvent('visibilitychange'));")
    page.check("[audio.paused, audio.getAttribute('src')]")
    assert page.run() == [[True, "/c/test-call-id/audio/0000.wav"]]


def test_the_panel_collapses_to_a_rail_and_moves_sides_and_both_are_remembered(tmp_path):
    html, states = served(tmp_path, [])
    page = CallPage(html, states)
    state = "[$('app').hasAttribute('data-rail'), $('app').dataset.side, localStorage.getItem('talk.panel'), localStorage.getItem('talk.side')]"
    page.check(state)
    page.js("$('collapse').click();").check(state)
    page.js("document.querySelector('#side [data-choice=left]').click();").check(state)
    page.js("$('expand').click();").check(state)
    assert page.run() == [[False, "right", None, None], [True, "right", '"rail"', None],
                          [True, "left", '"rail"', '"left"'], [False, "left", '"open"', '"left"']]


VOICES = [{"id": "en-US-AvaMultilingualNeural", "name": "Ava", "note": "American, reads Greek too"},
          {"id": "el-GR-AthinaNeural", "name": "Athina", "note": "Greek only"}]
PICKED = "[...document.querySelectorAll('#voices .vpick')].map((b) => b.dataset.voice + ':' + b.getAttribute('aria-checked'))"


def test_the_voice_kept_on_this_origin_is_sent_to_the_call_when_the_page_opens(tmp_path):
    html, states = served(tmp_path, [], voices=VOICES)
    page = CallPage(html, states, stored={"voice": "el-GR-AthinaNeural"})
    page.check("sentTo.filter(([path]) => path === '/api/voice')").check(PICKED)
    assert page.run() == [[["/api/voice", {"voice": "el-GR-AthinaNeural"}]],
                          ["en-US-AvaMultilingualNeural:false", "el-GR-AthinaNeural:true"]]


def test_a_voice_picked_in_the_settings_is_sent_and_kept(tmp_path):
    html, states = served(tmp_path, [], voices=VOICES)
    page = CallPage(html, states)
    page.check("sentTo.filter(([path]) => path === '/api/voice').length")
    page.js("document.querySelector('#voices .vpick[data-voice=el-GR-AthinaNeural]').click();")
    page.check("[sentTo.filter(([path]) => path === '/api/voice'), localStorage.getItem('talk.voice')]").check(PICKED)
    assert page.run() == [0, [[["/api/voice", {"voice": "el-GR-AthinaNeural"}]], '"el-GR-AthinaNeural"'],
                          ["en-US-AvaMultilingualNeural:false", "el-GR-AthinaNeural:true"]]


SEQ_ANSWER = ('[[show sequence | Turn]] {"actors": [{"id": "p", "label": "Page"}, {"id": "s", "label": "Server"}], "steps": ['
              '{"id": "s1", "from": "p", "to": "s", "arrow": "request", "label": "send"},'
              '{"id": "s2", "from": "s", "to": "p", "arrow": "event", "label": "answer", "reply_to": "s1"}]} [[/show]] '
              f"{six('first')}. [[+ s1]] {six('second')}. [[+ s2]] {six('third')}.")
CUE_TIME = ("(() => { const e = served.entries.find((x) => x.who === 'claude'), c = e.cues.find((c) => c.kind === 'frame' && c.n === 2);"
            " return e.words.find((w) => w[0] >= c.at)[2]; })()")


def test_play_from_here_on_a_stage_step_plays_the_answer_from_the_sentence_that_says_it(tmp_path):
    html, states = served(tmp_path, [SEQ_ANSWER], seconds=6.0)
    page = CallPage(html, states, seconds=6.0, autoplay=False).js("await serve(1);")
    page.js("fromStage({ type: 'stage:follow', on: false });")
    page.js("fromStage({ type: 'stage:play', view: 'turn', answer: 1, n: 2 });")
    page.check(f"[!audio.paused, follow, audio.currentTime > 0 && audio.currentTime === {CUE_TIME}]")
    # a frame no answer has does nothing
    page.js("audio.pause(); fromStage({ type: 'stage:play', view: 'turn', answer: 1, n: 9 });").check("audio.paused")
    assert page.run() == [[True, True, True], True]


LISTEN_HEARS = """
globalThis.fetch = (inner => async (path, opts = {}) => {
  if (String(path).startsWith("/api/listen")) {
    sentTo.push([String(path), null]);
    return { ok: true, status: 200, json: async () => ({ text: "show me the queue" }) };
  }
  return inner(path, opts);
})(globalThis.fetch);
"""


def test_a_recording_is_written_into_the_text_field_to_edit_and_sent_only_with_send(tmp_path):
    html, states = served(tmp_path, [])
    page = CallPage(html, states).js(LISTEN_HEARS)
    page.js("await sendWav(new Blob(['x']));")
    page.check("[$('text').value, sentTo.map(s => s[0].split('?')[0])]")
    page.js("$('text').value = 'show me the reply queue'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click();")
    page.check("sentTo.filter(s => s[0] === '/api/say').map(s => s[1])")
    assert page.run() == [["show me the queue", ["/api/listen"]],
                          [{"text": "show me the reply queue", "spoken": True}]]


def test_a_recording_adds_to_what_is_already_typed(tmp_path):
    html, states = served(tmp_path, [])
    page = CallPage(html, states).js(LISTEN_HEARS)
    page.js("$('text').value = 'about the tests:'; await sendWav(new Blob(['x']));")
    page.check("$('text').value")
    assert page.run() == ["about the tests: show me the queue"]


CAPTIONS = "toStage().filter((m) => m.type === 'stage:caption').map((m) => m.text)"


def test_the_sentence_being_said_goes_to_the_stage_and_clears_when_the_answer_rests(tmp_path):
    html, states = served(tmp_path, [f"[[show table | One]]{TABLE}[[/show]] First things first. Then the second thing."], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playTo(0.5);").check(CAPTIONS)
    page.js("await playTo(3.5);").check(CAPTIONS)
    page.js("await end(); await advance(1600);").check(CAPTIONS)
    assert page.run() == [["First things first."], ["First things first.", "Then the second thing."],
                          ["First things first.", "Then the second thing.", ""]]


def test_an_answer_with_no_board_sends_no_caption_and_keeps_its_text_open(tmp_path):
    html, states = served(tmp_path, ["Just words, nothing to show."], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.0);").check(CAPTIONS)
    page.check("document.querySelector('#convo .turn.claude').classList.contains('folded')")
    assert page.run() == [[], False]


def test_an_answer_with_boards_folds_its_text_and_show_text_opens_it(tmp_path):
    html, states = served(tmp_path, [f"[[show table | One]]{TABLE}[[/show]] First things first. Then the second thing."])
    page = CallPage(html, states, autoplay=False).js("await serve(1);")
    turn = "document.querySelector('#convo .turn.claude')"
    page.check(f"[{turn}.classList.contains('folded'), {turn}.querySelector('button.fold').textContent]")
    page.js(f"{turn}.querySelector('button.fold').click();")
    page.check(f"[{turn}.classList.contains('folded'), {turn}.querySelector('button.fold').textContent]")
    page.js("await serve(1); await advance(1000);")  # the page polls again: the reader's choice stays
    page.check(f"{turn}.classList.contains('folded')")
    assert page.run() == [[True, "Show text"], [False, "Hide text"], False]


# -- stops: the answer asks, and waits ------------------------------------------------
STOPS = "toStage().filter((m) => m.type === 'stage:stop').map((m) => m.stop && [m.answer, m.i, m.stop.type, m.stop.picked])"
CHECK_ANSWER = f"[[show table | One]]{TABLE}[[/show]] First things first here. [[check]] Then the second thing."


def test_a_check_pauses_the_voice_after_its_question_and_go_on_plays_on(tmp_path):
    html, states = served(tmp_path, [CHECK_ANSWER], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(3.9);")
    page.check(f"[audio.paused, Math.round(audio.currentTime * 10) / 10, {STOPS}]")
    # the card asks on the stage, in place of the caption; Play there is Go on
    page.js("fromStage({ type: 'stage:pick', answer: 1, i: 0, choice: 0 });").check(f"[audio.paused, {STOPS}]")
    # played on past it, the stop is not stopped at again; played from before it, it is
    page.js("await playOn(3.9);").check("audio.paused")
    page.js("audio.pause(); audio.currentTime = 0; audio.play(); await playOn(3.9);").check(f"[audio.paused, {STOPS}.length]")
    page.js("$('playpause').click();").check(f"[audio.paused, {STOPS}.length]")
    # the stop stands after "Clear so far?": "far?" is the 7th of 11 words, which ends at 7/11 of the 4 seconds (2.55 s)
    assert page.run() == [[True, 2.5, [[1, 0, "check", None]]], [False, [[1, 0, "check", None], None]], False,
                          [True, 3], [False, 4]]


def test_again_slower_plays_the_stretch_again_at_a_slower_speed_and_stops_there_again(tmp_path):
    html, states = served(tmp_path, [CHECK_ANSWER], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(3.9);")
    page.js("fromStage({ type: 'stage:pick', answer: 1, i: 0, choice: 1 });")
    page.check("[audio.paused, audio.currentTime, audio.playbackRate]")
    page.js("await playOn(3.9);").check("[audio.paused, audio.playbackRate]")
    assert page.run() == [[False, 0, 0.8], [True, 1]]


def test_another_example_sends_a_turn_and_the_card_goes(tmp_path):
    html, states = served(tmp_path, [CHECK_ANSWER], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(3.9);")
    page.js("fromStage({ type: 'stage:pick', answer: 1, i: 0, choice: 2 });")
    page.check(f"[sentTo.filter(s => s[0] === '/api/say').map(s => s[1]), audio.paused, {STOPS}.pop()]")
    assert page.run() == [[[{"text": "Another example, please."}], True, None]]


def test_a_guess_marks_the_pick_sends_it_and_plays_on(tmp_path):
    html, states = served(tmp_path, [f"[[show table | One]]{TABLE}[[/show]] Ben buys a fund. "
                                     "[[guess: What prints | Fixed Income | *Old name]] It prints the old name."], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(3.9);")
    page.js("fromStage({ type: 'stage:pick', answer: 1, i: 0, choice: 0 });")
    page.check(f"[audio.paused, {STOPS}.pop(), sentTo.filter(s => s[0] === '/api/pick').map(s => s[1])]")
    page.js("fromStage({ type: 'stage:pick', answer: 1, i: 0, choice: 1 });")  # one pick per guess
    page.js("await advance(1700);").check(f"[audio.paused, {STOPS}.pop(), sentTo.filter(s => s[0] === '/api/pick').length]")
    assert page.run() == [[True, [1, 0, "guess", 0], [{"answer": 1, "i": 0, "choice": 0}]], [False, None, 1]]


def test_a_stop_of_an_answer_with_no_board_asks_in_the_panel(tmp_path):
    html, states = served(tmp_path, ["Just words here. [[deeper]] The longer version now."], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(3.9);")
    card = "$('stopcard')"
    page.check(f"[audio.paused, {card}.hidden, [...{card}.querySelectorAll('button')].map(b => b.textContent), {STOPS}]")
    page.js(f"{card}.querySelector('button').click();").check(f"[audio.paused, {card}.hidden]")
    assert page.run() == [[True, False, ["Go deeper", "That's enough"], [None]], [False, True]]


def test_a_say_back_waits_for_the_answer_in_the_text_field_and_sends_its_question(tmp_path):
    html, states = served(tmp_path, ["The template names one sticker. [[say back: What does hard-coded mean here]]"], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await end();")
    page.check("[$('stopcard').hidden, $('text').placeholder, document.activeElement === $('text')]")
    page.js("$('text').value = 'it names the old sticker'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click();")
    page.check("[sentTo.filter(s => s[0] === '/api/say').map(s => s[1]), $('stopcard').hidden, $('text').placeholder]")
    assert page.run() == [[False, "Say it in your own words, then Send", True],
                          [[{"text": "it names the old sticker", "answering": "What does hard-coded mean here?"}], True,
                           "Type, or press the mic"]]


def test_the_stage_never_runs_past_a_guess_the_reader_has_not_answered(tmp_path):
    scene = ('[[show scene | Ben]] <section data-part="data" data-name="the data">x</section>'
             '<section data-part="pdf" data-name="the PDF">Old name</section> [[/show]] ')
    html, states = served(tmp_path, [scene + "First the data comes. [[guess: What does the PDF print | Fixed Income | *Old name]] "
                                             "The PDF prints the old name."], seconds=4.0)
    frames = "toStage().filter((m) => m.type === 'stage:frame' || m.type === 'stage:state').map((m) => m.n ?? m.frames.ben)"
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(3.9);").check(f"[audio.paused, {frames}]")
    page.js("await advance(500);").check(frames)  # waiting at the guess, the stage stays where it is
    page.js("fromStage({ type: 'stage:pick', answer: 1, i: 0, choice: 1 }); await advance(1700); await playOn(3.9);").check(frames)
    assert page.run() == [[True, [1]], [1], [1, 2]]
