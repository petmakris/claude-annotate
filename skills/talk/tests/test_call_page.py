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
