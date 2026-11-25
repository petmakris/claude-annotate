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
    page.js("document.querySelector(\"#nowtext .w[data-i='0']\").click();")
    page.check("toStage().find((m) => m.type === 'stage:state')")
    assert page.run() == [{"type": "stage:state", "front": "three-paths-changed", "frames": {}, "keys": 0, "answer": 1}]


def test_a_play_the_reader_starts_keeps_the_board_they_picked(tmp_path):
    # call IriDPEiq: the reader picked a board, went back a sentence and played on, and the stage took the board away
    html, states = served(tmp_path, [FLOW_ANSWER], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.2);")
    page.check("toStage().some((m) => m.type === 'stage:frame' && m.n === 1)")
    starts = {"Play": "$('playpause').click();",
              "word tap": "document.querySelector(\"#nowtext .w[data-i='3']\").click();",
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
    page.js("$('playpause').click();")  # the reader replays an old answer
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
        page.js("toStage().length = 0;").js(f"document.querySelector(\"#nowtext .w[data-i='{word}']\").click();")
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
    page.js("document.querySelector('#tllist .tlrow button.play').click(); audio.pause();")
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


READER = ("[document.querySelector('#reader').className, [...document.querySelectorAll('#rtext .rs')].map((e) => e.className),"
          " document.querySelector('#rtext .now-word')?.textContent ?? null]")


def test_the_stage_reads_the_answer_sentence_by_sentence_and_its_board_takes_over_at_the_cue(tmp_path):
    html, states = served(tmp_path, [f"First things first. [[show table | One]]{TABLE}[[/show]] Then the second thing."], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playTo(0.5);").check(READER)
    page.js("await playTo(3.5);").check(READER)
    page.js("await end(); await advance(1600);").check(READER).check(CAPTIONS)
    # the first sentence is read in large type, the second not shown yet; at the board's cue the board takes the stage
    # and the sentence stays under it on a strip; at rest the board shows alone; the stage never gets a caption
    assert page.run() == [["reader text", ["rs cur", "rs future"], "First"],
                          ["reader strip", ["rs past", "rs cur"], "thing."],
                          ["reader off", ["rs", "rs"], None], []]


def test_an_answer_with_no_board_is_read_on_the_stage_when_no_board_is_in_front(tmp_path):
    html, states = served(tmp_path, ["Just words, nothing to show. And a second sentence."], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(2.0);").check(READER)
    page.js("await end(); await advance(1600);").check(READER).check(CAPTIONS)
    assert page.run() == [["reader text", ["rs past", "rs cur"], "a"], ["reader text", ["rs", "rs"], None], []]


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


LIVE_HEARS = """
globalThis.fetch = (inner => async (path, opts = {}) => {
  if (String(path).startsWith("/api/listen")) {
    sentTo.push([String(path), null]);
    return { ok: true, status: 200, json: async () => ({ text: "it names the old sticker", entry: { id: 9 } }) };
  }
  return inner(path, opts);
})(globalThis.fetch);
"""


def test_a_say_back_spoken_in_live_mode_sends_its_question_and_clears_the_card(tmp_path):
    html, states = served(tmp_path, ["The template names one sticker. [[say back: What does hard-coded mean here]]"], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await end();").js(LIVE_HEARS)
    page.check("[$('stopcard').hidden, $('text').placeholder]")
    page.js("await sendLive({chunks: [new Float32Array(1600)], rate: 16000, gate: false});")
    page.check("[sentTo.filter(s => s[0].startsWith('/api/listen')).map(s => new URLSearchParams(s[0].split('?')[1]).get('answering')),"
               " $('stopcard').hidden, $('text').placeholder]")
    assert page.run() == [[False, "Say it in your own words, then Send"],
                          [["What does hard-coded mean here?"], True, "Type, or press the mic"]]


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


def test_ask_about_a_stage_part_pauses_and_starts_the_question_in_the_text_field(tmp_path):
    html, states = served(tmp_path, [CHECK_ANSWER], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(1.0);")
    page.js("fromStage({ type: 'stage:ask', text: 'About \"the data\": ' });")
    page.check("[audio.paused, $('text').value, document.activeElement === $('text'), $('sendtext').disabled,"
               " sentTo.filter(s => s[0] === '/api/say').length]")
    assert page.run() == [[True, 'About "the data": ', True, False, 0]]  # nothing goes until Send


def test_a_word_that_starts_where_a_sentence_ends_belongs_to_the_next_sentence(tmp_path):
    html, states = served(tmp_path, [], seconds=4.0)
    page = CallPage(html, states, seconds=4.0)
    # "Hi.There now." has no space after the first full stop: "There" starts at 3, the very character the first sentence ends at
    page.js("buildReader({text: 'Hi.There now.', words: [[0, 3, 0], [3, 8, 0.5], [9, 13, 1]]});")
    page.check("[rSents.map((s) => [s.first, s.last]), [...document.querySelectorAll('#rtext .rs')].map((e) => e.textContent),"
               " rWords.map((w) => w.textContent)]")
    assert page.run() == [[[[0, 0], [1, 2]], ["Hi.", "There now."], ["Hi.", "There", "now."]]]


# -- the call page, round 1 of the bulldozer ----------------------------------------
from pathlib import Path as _Path

_CSS = (_Path(__file__).resolve().parents[1] / "static" / "call.css").read_text()


def test_a_phone_gear_panel_is_a_sheet_capped_to_the_space_above_the_panel():
    # callpage-1: the sheet sits one panel height + 10px up (58%, or 52% while a board is up) and was as tall as the page less 68px, so its top left the screen
    assert ".pop,.app[data-side=\"left\"] .pop{top:auto;bottom:calc(var(--ph) + 10px);left:10px;right:10px;width:auto;max-height:calc(100% - var(--ph) - 24px)}" in _CSS
    assert ".app{--ph:58%}" in _CSS and ".app[data-board]{--ph:52%}" in _CSS
    assert ".app[data-rail] .pop,.app[data-rail] .gearpop{top:auto;bottom:70px;max-height:calc(100% - 82px)}" in _CSS


def test_the_strip_is_sized_from_the_font_it_is_set_in_tv_mode_too():
    # callpage-2: the height came from the small font while the TV rule set a big one, so 3 lines needed 1.6x the room
    assert "height:calc(3 * 1.45 * var(--sf) + 24px)" in _CSS
    assert "font-size:var(--sf);line-height:1.45}" in _CSS
    assert ".app[data-tv] .reader.strip{--sf:clamp(26px,1.2vw + 14px,40px)}" in _CSS
    assert ".app[data-tv] .reader:not(.strip) .rtext{font-size:clamp(26px,1.2vw + 14px,40px)}" in _CSS
    assert "margin:auto 0;padding:12px 28px" in _CSS  # centred when it fits, from the top when it overflows


def test_the_strip_scrolls_the_word_being_said_into_sight(tmp_path):
    html, states = served(tmp_path, [f"[[show table | One]]{TABLE}[[/show]] First things first. Then the second thing."], seconds=4.0)
    stub = ("const P = Object.getPrototypeOf(document.createElement('span'));"
            "P.getBoundingClientRect = function () { return this.classList.contains('w') ? { top: 150 - $('reader').scrollTop, bottom: 170 - $('reader').scrollTop }"
            " : this.id === 'reader' ? { top: 0, bottom: 100 } : { top: 0, bottom: 0 }; };")
    page = CallPage(html, states, seconds=4.0).js("await serve(1);" + stub + "await playTo(3.5);")
    page.check("[$('reader').className, $('reader').scrollTop]")
    assert page.run() == [["reader strip", 110]]  # the word's middle (160) is brought to the strip's middle (50)


def test_a_chip_tap_on_the_board_in_front_turns_following_off_and_shows_the_board(tmp_path):
    html, states = served(tmp_path, [f"First things first. [[show table | One]]{TABLE}[[/show]] Then the second thing."], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playTo(0.3);")
    page.js("fromStage({ type: 'stage:shown', view: 'one' });")
    page.check("[$('reader').className, follow]")  # the reader's text covers the stage; the board is in front behind it
    page.js("document.querySelector('#convo button.chip.board').click();")
    page.check("[$('reader').className, follow, toStage().filter((m) => m.type === 'stage:follow').pop().on]")
    assert page.run() == [["reader text", True], ["reader strip", False, False]]


def test_sentences_follow_the_servers_starts_and_fall_back_to_the_pages_own_splitter(tmp_path):
    html, states = served(tmp_path, [], seconds=4.0)
    page = CallPage(html, states, seconds=4.0)
    text = "Use e.g. Redis. Then stop."
    words = "[[0,3,0],[4,8,0.5],[9,15,1],[16,20,1.5],[21,26,2]]"
    page.check(f"sentenceTimes({{text: {text!r}, words: {words}}})")                  # the page's splitter cuts at 'e.g.'
    page.check(f"sentenceTimes({{text: {text!r}, words: {words}, starts: [16]}})")    # the server's starts do not
    page.check(f"sentenceSpans({{text: {text!r}, words: {words}, starts: [16]}})")
    assert page.run() == [[0, 1, 1.5], [0, 1.5], [{"t": 0, "a": 0, "b": 15}, {"t": 1.5, "a": 16, "b": 26}]]


def test_a_second_page_of_the_call_does_not_speak_and_says_so(tmp_path):
    html, states = served(tmp_path, ["Said to two screens."])
    held = {"playing.test-call-id": {"id": "other-page", "at": 0}}
    page = CallPage(html, states, stored=held).js("localStorage.setItem('talk.playing.test-call-id', JSON.stringify({id: 'other-page', at: Date.now()})); await serve(1);")
    page.check("[audio.paused, audio.getAttribute('src'), $('status').textContent]")
    assert page.run() == [[True, "/c/test-call-id/audio/0000.wav", "Playing on another screen."]]


def test_a_page_plays_when_no_other_page_holds_the_voice(tmp_path):
    html, states = served(tmp_path, ["Said to one screen."])
    page = CallPage(html, states).js("await serve(1);")
    page.check("[audio.paused, JSON.parse(localStorage.getItem('talk.playing.test-call-id')).id.length]")
    assert page.run() == [[False, 8]]


def test_an_answer_that_comes_while_another_plays_waits_in_a_row_and_starts_when_that_one_ends(tmp_path):
    html, states = served(tmp_path, ["The first answer is here.", "The second answer is here."], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.0);")
    page.js("await serve(2);")
    page.check("[audio.getAttribute('src'), $('queuerow').hidden, $('queuerow').querySelector('.qr-text').textContent, $('status').hidden]")
    page.js("await end(); await advance(50);")
    page.check("[audio.getAttribute('src'), audio.paused, $('queuerow').hidden, $('status').hidden]")
    assert page.run() == [["/c/test-call-id/audio/0000.wav", False, "Next: answer 2. It plays when this one ends.", True],
                          ["/c/test-call-id/audio/0001.wav", False, True, True]]


def test_the_poll_loop_goes_on_while_the_tab_is_hidden_and_at_once_when_it_is_seen(tmp_path):
    html, states = served(tmp_path, [], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("document.visibilityState = 'hidden'; let n0 = polls.n; await advance(5000);")
    page.check("polls.n - n0 >= 5")
    assert page.run() == [True]


def test_a_tab_out_of_sight_stops_at_a_check_on_the_audios_own_timeupdate(tmp_path):
    html, states = served(tmp_path, [CHECK_ANSWER], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playOn(1.0);")
    # a hidden tab runs no animation frames: only the audio's timeupdate reports the time
    page.js("document.visibilityState = 'hidden'; stopHighlight(); audio._t = 2.8; audio.dispatchEvent(new ShimEvent('timeupdate'));")
    page.check(f"[audio.paused, {STOPS}]")
    assert page.run() == [[True, [[1, 0, "check", None]]]]


def test_a_page_that_holds_the_server_claim_plays_and_one_that_does_not_stays_silent(tmp_path):
    html, states = served(tmp_path, ["Said to two screens."])
    mine = CallPage(html, states).js("globalThis.playerReply = (b) => ({player: b.page}); claimPlayer(false); await serve(1);")
    mine.check("[audio.paused, claims.map((c) => c.take), $('status').textContent]")
    other = CallPage(html, [dict(st, player="the-tv") for st in states]).js("globalThis.playerReply = () => ({player: 'the-tv'}); await claimPlayer(false); await serve(1);")
    other.check("[audio.paused, $('status').textContent]")
    # the storage lock is not consulted once the server answers: a lock another page holds there does not silence this page
    free = CallPage(html, states).js("localStorage.setItem('talk.playing.test-call-id', JSON.stringify({id: 'x', at: Date.now()})); globalThis.playerReply = (b) => ({player: b.page}); await claimPlayer(false); await serve(1);")
    free.check("audio.paused")
    assert mine.run() == [[False, [False, False, False], ""]]
    assert other.run() == [[True, "Playing on another screen."]]
    assert free.run() == [False]


def test_pressing_play_takes_the_claim_and_a_page_that_loses_it_pauses(tmp_path):
    html, states = served(tmp_path, ["Said to two screens."], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("globalThis.playerReply = (b) => ({player: b.page}); await claimPlayer(false); await serve(1); await playTo(0.5);")
    page.js("audio.pause(); claims.length = 0; $('playpause').click();").check("[audio.paused, claims.map((c) => c.take)]")
    # the next answer's state says another page holds the voice (it took it): this page stops
    page.js("tookAt = 0; audio.play(); seeHolder('the-tv');").check("[audio.paused, $('status').textContent]")
    assert page.run() == [[False, [True]], [True, "Playing on another screen."]]


def test_an_audio_file_that_cannot_load_says_so_with_retry_and_a_blocked_play_says_blocked(tmp_path):
    html, states = served(tmp_path, ["Said once."])
    page = CallPage(html, states).js("await serve(1);")
    toast = "[$('toast').hidden, $('toasttext').textContent, $('retry').hidden, $('retry').textContent]"
    page.js("audio.error = {code: 4}; audio.dispatchEvent(new ShimEvent('error'));").check(toast)
    page.js("$('retry').click();").check("[$('toast').hidden, audio.getAttribute('src'), audio.paused]")
    # a refused play is "blocked" only for NotAllowedError; a file the player cannot decode is not that
    page.js("playFailed(Object.assign(new Error('x'), {name: 'NotAllowedError'}));").check("$('toasttext').textContent")
    page.js("playFailed(Object.assign(new Error('x'), {name: 'NotSupportedError'}));").check("$('toasttext').textContent")
    page.js("playFailed(Object.assign(new Error('x'), {name: 'AbortError'}));").check("$('toasttext').textContent")
    assert page.run() == [
        [False, "Cannot load the audio file: it is missing or not supported.", False, "Retry"],
        [True, "/c/test-call-id/audio/0000.wav", False],
        "The browser blocked playback. Press Play.",
        "Cannot play this audio file.",
        "Cannot play this audio file."]
