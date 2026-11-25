"""The call page's input side (call-input.js, call-live.js): how you talk (the Type / Talk / Live switch and the Your turn
pill), the keys and their sheet, focus in and out of the layers, the voice speed, TV and the theme, run under node (call_page.py)
on the page's own scripts. Layout (touch sizes, tooltips, the phone's heights) is checked by eye with tools/talk_render."""
import json
import re

from call_page import STATIC, CallPage, needs_node, served

pytestmark = needs_node

# a key as the browser gives it: the character, the physical key, the modifiers
KEY = "const press = (key, o = {}, at = document.body) => at.dispatchEvent(new ShimEvent('keydown', {key, code: o.code || '', altKey: !!o.alt, shiftKey: !!o.shift, bubbles: true}));"
ALT = lambda code, key="": f"press({key!r}, {{alt: true, code: {code!r}}});"
SENTENCES = "One two three. Four five six. Seven eight nine."


def page_with(tmp_path, answers=("A short answer.",), **kw):
    html, states = served(tmp_path, list(answers), seconds=kw.get("seconds", 4.0))
    return CallPage(html, states, **kw).js(KEY)


# ---- the Keys sheet: every shortcut listed once, and each one does what it says -------------------------------------

def test_the_keys_sheet_lists_every_shortcut_in_the_order_of_the_key_table(tmp_path):
    page = page_with(tmp_path)
    page.check("[...document.querySelectorAll('#pKeys .krow')].map((r) => r.dataset.key + ' = ' + r.querySelector('.kk').textContent.trim() + ' / ' + r.querySelector('.kw').textContent)")
    page.check("[...document.querySelectorAll('#pKeys h4')].map((h) => h.textContent)")
    page.check("[KEYS.length, document.querySelector('#pKeys .knote').textContent]")
    assert page.run() == [
        ["play = Space / Play or pause the answer", "sentence = ← → / Back or forward one sentence", "speed = Alt S / Next voice speed",
         "message = Alt M / Go to the message field", "player = Alt P / Go to the player", "voice = Alt V / Follow the voice again",
         "keys = ? / Show this list", "close = Esc / Close the open window", "send = Enter / Send the message",
         "newline = Shift Enter / New line in the message", "talk = Alt T / Talk, or Done while recording"],
        ["Listening", "Moving around", "Talking"],
        [3, "Every key has a button. Letters go to the message field, so the shortcuts use Alt."]]


def test_every_listed_key_is_bound_and_does_what_the_sheet_says(tmp_path):
    page = page_with(tmp_path, ("One two three. Four five six. Seven eight nine.",), start=1, seconds=9.0)
    # Space plays, ← and → move by a sentence (the answer is in the player once it plays)
    page.js("document.body.focus(); press(' ');").check("[audio.paused, !!current]")
    page.js("audio._t = 4; press('ArrowLeft'); ").check("audio.currentTime")      # 1 s into sentence 2 (3 s): its start
    page.js("press('ArrowRight');").check("audio.currentTime")                      # the next sentence starts at 6 s
    page.js("press(' ');").check("audio.paused")
    # Alt+S: the next speed; Alt+M: the message field; Alt+P: the player; Alt+V: following again; ?: this sheet
    page.js(ALT("KeyS", "s")).check("[speed, audio.playbackRate, $('speedchip').textContent]")
    page.js("document.body.focus();" + ALT("KeyM", "m")).check("document.activeElement.id")
    page.js(ALT("KeyP", "p")).check("document.activeElement.id")
    page.js("fromStage({ type: 'stage:follow', on: false });").check("follow")
    page.js(ALT("KeyV", "v")).check("follow")
    page.js("document.body.focus(); press('?');").check("[openPop, $('pKeys').hidden]")
    page.js("press('Escape');").check("[openPop, $('pKeys').hidden]")
    # Alt+T presses Talk: no microphone here, so the page says so; the pressing is what is checked
    page.js("showError(''); " + ALT("KeyT", "t")).check("document.getElementById('toasttext').textContent")
    assert page.run() == [[False, True], 3, 6, True, [1.25, 1.25, "1.25×"], "text", "playpause", False, True, ["pKeys", False],
                          [None, True], "This page cannot reach a microphone. Open it over https or on localhost."]


def test_a_question_mark_is_typed_when_the_message_field_holds_words_and_opens_the_sheet_when_it_does_not(tmp_path):
    page = page_with(tmp_path)
    page.js("const t = $('text'); t.focus(); t.value = 'is it'; press('?', {}, t);").check("[openPop, t.value]")
    page.js("t.value = ''; press('?', {}, t);").check("[openPop, $('pKeys').hidden]")
    assert page.run() == [[None, "is it"], ["pKeys", False]]


# ---- focus goes into a layer and comes back ----------------------------------------------------------------------

def test_the_settings_take_the_focus_trap_tab_and_give_it_back_on_escape(tmp_path):
    page = page_with(tmp_path)
    page.js("$('gear').focus(); $('gear').click();")
    page.check("[openPop, $('pGear').contains(document.activeElement), document.activeElement.textContent]")
    # Tab from the last control goes to the first, Shift+Tab from the first to the last
    page.js("const items = [...$('pGear').querySelectorAll('button:not([disabled])')].filter((e) => !e.closest('[hidden]')); items.at(-1).focus(); press('Tab', {}, items.at(-1));")
    page.check("document.activeElement === items[0]")
    page.js("press('Tab', {shift: true}, items[0]);").check("document.activeElement === items.at(-1)")
    page.js("press('Escape');").check("[openPop, document.activeElement.id]")
    assert page.run() == [["pGear", True, "Desk"], True, True, [None, "gear"]]


def test_the_rail_gear_gets_the_focus_back_and_the_keys_row_of_the_settings_hands_back_to_the_gear(tmp_path):
    page = page_with(tmp_path)
    page.js("$('collapse').click(); $('railgear').click(); press('Escape');").check("document.activeElement.id")
    page.js("$('expand').click(); $('gear').click(); $('keysrow').click();")
    page.check("[openPop, $('pKeys').contains(document.activeElement), document.activeElement.getAttribute('aria-label')]")
    page.js("press('Escape');").check("[openPop, document.activeElement.id]")
    assert page.run() == ["railgear", ["pKeys", True, "Close the shortcuts"], [None, "gear"]]


def test_a_layer_closed_by_a_click_elsewhere_does_not_steal_the_focus_back(tmp_path):
    page = page_with(tmp_path)
    page.js("$('gear').click(); $('text').focus(); showPop(null);").check("document.activeElement.id")
    assert page.run() == ["text"]


def test_the_skip_links_go_past_the_stage_and_the_answers(tmp_path):
    html, states = served(tmp_path, ["One answer."])
    page = CallPage(html, states, start=1).js(KEY)
    page.js("$('skipmsg').click();").check("document.activeElement.id")
    page.js("$('skipplay').click();").check("document.activeElement.id")
    page.check("[...document.querySelectorAll('#skip a')].map((a) => a.textContent)")
    assert page.run() == ["text", "playpause", ["Skip to the message", "Skip to the player"]]


# ---- Back is a sentence, the speed is on the player -----------------------------------------------------------------

def test_back_goes_one_sentence_and_never_restarts_a_short_answer_by_a_fixed_ten_seconds(tmp_path):
    page = page_with(tmp_path, (SENTENCES,), start=1, seconds=9.0)
    page.js("$('playpause').click(); await playTo(5.0); audio.pause();").check("audio.currentTime")
    page.js("$('back').click();").check("audio.currentTime")       # 2 s into the second sentence: its start, not 0:00
    page.js("$('back').click();").check("audio.currentTime")       # at its start: the one before
    page.js("audio._t = 8; $('seek').focus(); press('ArrowLeft', {}, $('seek'));").check("audio.currentTime")
    page.js("press('PageDown', {}, $('seek'));").check("audio.currentTime")
    assert page.run() == [5.0, 3, 0, 6, 0]


def test_the_speed_chip_steps_through_the_speeds_and_wraps(tmp_path):
    page = page_with(tmp_path)
    page.check("$('speedchip').textContent")
    for _ in range(5):
        page.js("$('speedchip').click();").check("[speed, audio.playbackRate, $('speedchip').textContent, localStorage.getItem('talk.speed')]")
    assert page.run() == ["1×", [1.25, 1.25, "1.25×", "1.25"], [1.5, 1.5, "1.5×", "1.5"], [0.75, 0.75, "0.75×", "0.75"],
                          [0.85, 0.85, "0.85×", "0.85"], [1, 1, "1×", "1"]]


def test_slower_and_faster_said_aloud_move_the_speed_one_step_and_stop_at_the_ends(tmp_path):
    page = page_with(tmp_path)
    page.js("runCommand('slower', {});").check("[speed, audio.playbackRate]")
    page.js("runCommand('slower', {}); runCommand('slower', {});").check("[speed, liveFlash.text]")
    page.js("runCommand('faster', {}); runCommand('faster', {}); runCommand('faster', {}); runCommand('faster', {}); runCommand('faster', {});").check("[speed, liveFlash.text]")
    assert page.run() == [[0.85, 0.85], [0.75, "Already as slow as it goes."], [1.5, "Already as fast as it goes."]]


def test_the_commands_the_server_hears_for_the_speed():
    import talk
    heard = {"Slower": "slower", "please go slower.": "slower", "Slow down": "slower", "faster!": "faster", "speed up": "faster",
             "Say that again slower": "repeat_slower", "πιο αργά": "slower", "go on": "resume", "slower please, I am lost": None}
    assert {text: talk.command_of(text) for text in heard} == heard


# ---- how you talk: Type, Talk, Live; the Your turn pill -----------------------------------------------------------------

def test_the_switch_maps_type_talk_and_live_to_the_talk_mode_and_is_remembered(tmp_path):
    page = page_with(tmp_path)
    state = ("[inputMode, talkMode, localStorage.getItem('talk.inputMode'), [...document.querySelectorAll('#modesw button')].map((b) => b.dataset.mode + ':' + b.getAttribute('aria-pressed')).join(' '),"
             " $('talk').hidden, $('railtalk').hidden, $('text').placeholder, document.activeElement.id]")
    page.check(state)
    page.js("document.querySelector('#modesw [data-mode=type]').click();").check(state)
    page.js("document.querySelector('#modesw [data-mode=live]').click();").check(state)
    page.js("document.querySelector('#modesw [data-mode=talk]').click();").check(state)
    assert page.run() == [
        ["talk", "manual", None, "type:false talk:true live:false", False, False, "Type, or press the mic", ""],
        ["type", "manual", '"type"', "type:true talk:false live:false", True, True, "Type a message", "text"],
        ["live", "live", '"live"', "type:false talk:false live:true", False, False, "Just speak, or type here", "text"],
        ["talk", "manual", '"talk"', "type:false talk:true live:false", False, False, "Type, or press the mic", "text"]]


def test_a_switch_kept_by_an_earlier_page_is_read_from_its_talk_mode(tmp_path):
    for stored, mode in (({"talkMode": "live"}, "live"), ({"talkMode": "manual"}, "talk"), ({"inputMode": "type", "talkMode": "manual"}, "type"), ({"inputMode": "bogus"}, "talk")):
        html, states = served(tmp_path, [])
        assert CallPage(html, states, stored=stored).check("[inputMode, talkMode]").run() == [[mode, "live" if mode == "live" else "manual"]], stored


def test_the_switch_is_locked_while_recording_and_says_why(tmp_path):
    page = page_with(tmp_path)
    page.js("recorder = {}; paintAll();").check("[...document.querySelectorAll('#modesw button')].map((b) => b.disabled + '/' + b.title)")
    page.js("document.querySelector('#modesw [data-mode=type]').click();").check("inputMode")
    page.js("recorder = null; paintAll();").check("[...document.querySelectorAll('#modesw button')].map((b) => b.disabled)")
    assert page.run() == [["true/Finish the recording first"] * 3, "talk", [False] * 3]


def test_the_your_turn_pill_says_whose_turn_it_is_in_words(tmp_path):
    page = page_with(tmp_path)
    pill = "[$('yourturn').textContent, $('yourturn').dataset.state, $('yourturn').hidden]"
    page.check(pill)                                                                  # nothing going on
    page.js("$('text').value = 'a draft'; $('text').dispatchEvent(new ShimEvent('input'));").check(pill)
    page.js("$('text').value = ''; $('text').dispatchEvent(new ShimEvent('input')); recorder = {}; paintAll();").check(pill)
    page.js("recorder = null; busy = true; paintAll();").check(pill)
    page.js("busy = false; view.working = true; paintAll();").check(pill)
    page.js("view.working = false; view.ended = 'over'; paintAll();").check("$('yourturn').hidden")
    assert page.run() == [["Your turn", "turn", False], ["Typing", "typing", False], ["Recording", "rec", False],
                          ["Writing it out", "work", False], ["Claude is working", "work", False], True]


LIVE = ("live = {stream: {getAudioTracks: () => [{enabled: true}]}, ctx: null, rate: 16000, recent: [], pre: [], loud: 0, quiet: 0, voiced: 0, ms: 0, speech: false,"
        " chunks: [], floorTaken: false, parked: null, lastVoice: performance.now(), suspended: false, muted: false, noSignal: false, flatMs: 0}; talkMode = 'live'; wokeAt = -5000; paintAll();")


def test_the_pill_names_what_an_open_microphone_is_doing(tmp_path):
    page = page_with(tmp_path)
    pill = "[$('yourturn').textContent, $('yourturn').dataset.state, $('talk').getAttribute('aria-label')]"
    page.js(LIVE).check(pill)
    page.js("live.speech = true; paintAll();").check(pill)
    page.js("live.speech = false; live.suspended = true; paintAll();").check(pill)
    page.js("live.suspended = false; live.parked = 'screen'; paintAll();").check(pill)
    page.js("live.parked = null; live.noSignal = true; paintAll();").check(pill)
    page.js("live.noSignal = false; live = null; paintAll();").check(pill)
    assert page.run() == [["Listening", "live", "Mute"], ["Hearing you", "live", "Mute"], ["Click to start listening", "warn", "Start listening"],
                          ["Live on another screen", "off", "Listen here"], ["No sound heard", "warn", "Mute"], ["Live is off", "off", "Listen"]]


def test_mute_keeps_the_microphone_open_and_sends_nothing_until_unmuted(tmp_path):
    page = page_with(tmp_path)
    page.js(LIVE + " const track = live.stream.getAudioTracks()[0]; live.stream.getAudioTracks = () => [track];")
    page.js("$('talk').click();")
    page.check("[live.muted, track.enabled, listening(), $('yourturn').textContent, $('talk').getAttribute('aria-label'), $('app').hasAttribute('data-live')]")
    page.js("liveChunk(new Float32Array(2048).fill(0.5)); liveChunk(new Float32Array(2048).fill(0.5));").check("[live.loud, live.flatMs, live.speech]")
    page.js("$('talk').click();")
    page.check("[live.muted, track.enabled, listening(), $('yourturn').textContent, $('talk').getAttribute('aria-label')]")
    assert page.run() == [[True, False, False, "Muted", "Unmute", False], [0, 0, False], [False, True, True, "Listening", "Mute"]]


def test_a_stream_flat_at_zero_for_ten_seconds_is_no_sound_and_a_sound_clears_it(tmp_path):
    page = page_with(tmp_path)
    page.js(LIVE)
    page.js("for (let i = 0; i < 78; i++) liveChunk(new Float32Array(2048));").check("[live.flatMs, live.noSignal, $('yourturn').textContent]")
    page.js("liveChunk(new Float32Array(2048));").check("[live.flatMs, live.noSignal, $('yourturn').textContent, $('yourturn').dataset.state]")
    page.js("liveChunk(new Float32Array(2048).fill(0.2));").check("[live.flatMs, live.noSignal, $('yourturn').textContent]")
    # a quiet room is not a dead one: noise above the floor never counts
    page.js("for (let i = 0; i < 200; i++) liveChunk(new Float32Array(2048).fill(0.002));").check("[live.noSignal, live.flatMs]")
    assert page.run() == [[9984, False, "Listening"], [10112, True, "No sound heard", "warn"], [0, False, "Listening"], [False, 0]]


def test_the_two_live_options_are_pills_of_the_switch_that_step_to_the_next_value(tmp_path):
    page = page_with(tmp_path)
    page.check("[$('livepills').hidden, document.getElementById('tmode'), document.getElementById('barge'), document.getElementById('liveopts')]")
    page.js("setInputMode('live');").check("[$('livepills').hidden, $('bargepill').textContent, $('pausepill').textContent]")
    page.js("$('bargepill').click(); $('pausepill').click();").check("[barge, endPause, $('bargepill').textContent, $('pausepill').textContent, localStorage.getItem('talk.barge'), localStorage.getItem('talk.endPause')]")
    page.js("$('pausepill').click(); $('pausepill').click(); $('bargepill').click();").check("[barge, endPause]")
    assert page.run() == [[True, None, None, None], [False, "Interrupt: talking", "Send after 1.2 s"],
                          ["keyword", 2000, "Interrupt: “wait”", "Send after 2 s", '"keyword"', "2000"], ["talk", 1200]]


# ---- TV, the theme, the engine's words -----------------------------------------------------------------------------------

def test_the_address_names_the_screen_and_the_gear_still_wins(tmp_path):
    html, states = served(tmp_path, [])
    state = "[screenMode, $('app').hasAttribute('data-tv'), localStorage.getItem('talk.screen')]"
    assert CallPage(html, states, query="?screen=tv").check(state).js("document.querySelector('#screen [data-choice=desk]').click();").check(state).run() == [
        ["tv", True, '"tv"'], ["desk", False, '"desk"']]
    assert CallPage(html, states, query="?screen=bogus").check(state).run() == [["desk", False, None]]


FULL = ("document.documentElement.requestFullscreen = async () => { document.fullscreenElement = document.documentElement; document.dispatchEvent(new ShimEvent('fullscreenchange')); };"
        " document.exitFullscreen = async () => { document.fullscreenElement = null; document.dispatchEvent(new ShimEvent('fullscreenchange')); };")


def test_full_screen_on_a_big_display_that_has_not_chosen_is_the_tvs_size_for_as_long_as_it_lasts(tmp_path):
    html, states = served(tmp_path, [])
    state = "[screenMode, localStorage.getItem('talk.screen'), toStage().filter((m) => m.type === 'stage:zoom').map((m) => m.zoom)]"
    page = CallPage(html, states).js(FULL + " innerWidth = 1920;").check(state)
    page.js("$('fullscreen').click();").check(state)
    page.js("await document.exitFullscreen(); await settle();").check(state)
    # a small window, or a size already chosen, is left alone
    assert page.run() == [["desk", None, [1]], ["tv", None, [1, 1.35]], ["desk", None, [1, 1.35, 1]]]
    page = CallPage(html, states).js(FULL + " innerWidth = 1280;").js("$('fullscreen').click();").check("screenMode")
    assert page.run() == ["desk"]
    page = CallPage(html, states, stored={"screen": "desk"}).js(FULL + " innerWidth = 1920;").js("$('fullscreen').click();").check("screenMode")
    assert page.run() == ["desk"]


def test_a_tv_size_chosen_in_full_screen_is_kept_when_the_gear_picks_it(tmp_path):
    html, states = served(tmp_path, [])
    page = CallPage(html, states).js(FULL + " innerWidth = 1920; $('fullscreen').click(); document.querySelector('#screen [data-choice=tv]').click();")
    page.js("await document.exitFullscreen(); await settle();").check("[screenMode, localStorage.getItem('talk.screen')]")
    assert page.run() == [["tv", '"tv"']]


def test_the_page_follows_the_system_theme_until_one_is_picked_and_the_choices_are_named_apart(tmp_path):
    html, states = served(tmp_path, [])
    assert re.search(r"""localStorage.getItem\("talk.theme"\) \|\| '"system"'""", html)
    page = CallPage(html, states).check("[theme, [...document.querySelectorAll('#theme button')].map((b) => b.textContent + ':' + b.getAttribute('aria-pressed')),"
                                         " [...document.querySelectorAll('#lang button')].map((b) => b.textContent), document.querySelector('#lang').previousElementSibling.textContent]")
    assert page.run() == [["system", ["Light:false", "Dark:false", "System:true"], ["Detect", "English", "Ελληνικά"], "Speech language"]]
    assert CallPage(html, states, stored={"theme": "dark"}).check("theme").run() == ["dark"]


def test_the_voice_is_described_in_plain_words_with_no_machine_or_profile(tmp_path):
    html, states = served(tmp_path, [])
    page = CallPage(html, states)
    for engine, voice, voices in (("VoiceStudio", "Talk", []), ("Azure", "en-US-AvaMultilingualNeural", []), ("Azure", "en-US-AvaMultilingualNeural", [{"id": "a", "name": "Ava", "note": ""}])):
        page.js(f"CFG.engine = {engine!r}; CFG.voice = {voice!r}; CFG.voices = {json.dumps(voices)};").check("engineText()")
    assert page.run() == ["A voice made on this computer: free, a little slower to start",
                          "Ava, a cloud voice: quick to start, billed per character",
                          "a cloud voice: quick to start, billed per character"]


# ---- the markup ------------------------------------------------------------------------------------------------------------

def test_the_gear_no_longer_holds_what_the_switch_does_and_the_header_has_no_mode_chip():
    html = (STATIC / "call.html").read_text()
    for gone in ("modechip", 'id="tmode"', 'id="barge"', 'id="endpause"', 'id="liveopts"'):
        assert gone not in html, gone
    for there in ("keysbtn", "keysrow", "speedchip", "skipmsg", "skipplay", 'id="pKeys"', 'id="modesw"', 'id="yourturn"'):
        assert there in html, there
    assert "paintModeChip" not in (STATIC / "call.js").read_text() + (STATIC / "call-input.js").read_text()
