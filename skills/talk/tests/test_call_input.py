"""The call page's input side (call-input.js, call-live.js): how you talk (the mic, the Live switch in the settings),
the keys and their sheet, focus in and out of the layers, the voice speed, TV and the theme, run under node (call_page.py)
on the page's own scripts. Layout (touch sizes, tooltips, the phone's heights) is checked by eye with tools/talk_render."""
import json
import re

from call_page import STATIC, CallPage, needs_node, served
from helpers import CALL

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
    page.check("[...document.querySelectorAll('#pKeys .row')].map((r) => r.dataset.key + ' = ' + r.querySelector('.kk').textContent.trim() + ' / ' + r.querySelector('.kw').textContent)")
    page.check("[...document.querySelectorAll('#pKeys .sheetbody h3')].map((h) => h.textContent)")
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
    page.js(ALT("KeyS", "s")).check("[speed, audio.playbackRate]")
    page.js("document.body.focus();" + ALT("KeyM", "m")).check("document.activeElement.id")
    page.js(ALT("KeyP", "p")).check("document.activeElement.id")
    page.js("fromStage({ type: 'stage:follow', on: false });").check("follow")
    page.js(ALT("KeyV", "v")).check("follow")
    page.js("document.body.focus(); press('?');").check("[openPop, $('pKeys').hidden]")
    page.js("press('Escape');").check("[openPop, $('pKeys').hidden]")
    # Alt+T presses Talk: no microphone here, so the page says so; the pressing is what is checked
    page.js("showError(''); " + ALT("KeyT", "t")).check("document.getElementById('toasttext').textContent")
    assert page.run() == [[False, True], 3, 6, True, [1.25, 1.25], "text", "playpause", False, True, ["pKeys", False],
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
    assert page.run() == [["pGear", True, "Done"], True, True, [None, "gear"]]


def test_the_keys_row_of_the_settings_hands_the_focus_to_the_keys_and_back_to_the_gear(tmp_path):
    page = page_with(tmp_path)
    page.js("$('gear').click(); $('keysrow').click();")
    page.check("[openPop, $('pKeys').contains(document.activeElement), document.activeElement.textContent]")
    page.js("press('Escape');").check("[openPop, document.activeElement.id]")
    assert page.run() == [["pKeys", True, "Done"], [None, "gear"]]


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
    assert page.run() == ["text", "playpause", ["Skip to the message", "Skip to the player", "Read the board as text"]]


# ---- Back is a sentence, the speed is on the player -----------------------------------------------------------------

def test_back_goes_one_sentence_and_never_restarts_a_short_answer_by_a_fixed_ten_seconds(tmp_path):
    page = page_with(tmp_path, (SENTENCES,), start=1, seconds=9.0)
    page.js("$('playpause').click(); await playTo(5.0); audio.pause();").check("audio.currentTime")
    page.js("document.body.focus(); press('ArrowLeft');").check("audio.currentTime")       # 2 s into the second sentence: its start, not 0:00
    page.js("press('ArrowLeft');").check("audio.currentTime")       # at its start: the one before
    page.js("audio._t = 8; $('seek').focus(); press('ArrowLeft', {}, $('seek'));").check("audio.currentTime")
    page.js("press('PageDown', {}, $('seek'));").check("audio.currentTime")
    assert page.run() == [5.0, 3, 0, 6, 0]


def test_the_speed_buttons_of_the_settings_set_the_speed_and_it_is_remembered(tmp_path):
    page = page_with(tmp_path)
    page.check("[...document.querySelectorAll('#speeds button')].map((b) => b.dataset.speed + ':' + b.getAttribute('aria-pressed')).join(' ')")
    for n in (1.25, 0.75):
        page.js(f"document.querySelector('#speeds [data-speed=\"{n}\"]').click();").check("[speed, audio.playbackRate, localStorage.getItem('talk.speed')]")
    assert page.run() == ["0.75:false 0.85:false 1:true 1.25:false 1.5:false", [1.25, 1.25, "1.25"], [0.75, 0.75, "0.75"]]


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


# ---- how you talk: the mic, and the Live switch in the settings ------------------------------------------------------

def test_the_live_switch_sets_the_talk_mode_is_remembered_and_shows_its_two_options_only_in_live(tmp_path):
    page = page_with(tmp_path)
    state = ("[talkMode, localStorage.getItem('talk.talkMode'), $('livemode').getAttribute('aria-pressed'), $('bargerow').hidden, $('pauserow').hidden,"
             " $('text').placeholder, $('app').hasAttribute('data-live')]")
    page.check(state)
    page.js("$('livemode').click();").check(state)
    page.js("$('livemode').click();").check(state)
    assert page.run() == [
        ["manual", None, "false", True, True, "Message", False],
        ["live", '"live"', "true", False, False, "Speak, or type", False],     # no microphone under node: the mic is not open
        ["manual", '"manual"', "false", True, True, "Message", False]]


def test_a_talk_mode_kept_by_an_earlier_page_is_read_and_anything_else_is_manual(tmp_path):
    for stored, mode in (({"talkMode": "live"}, "live"), ({"talkMode": "manual"}, "manual"), ({"talkMode": "bogus"}, "manual"), ({}, "manual")):
        html, states = served(tmp_path, [])
        assert CallPage(html, states, stored=stored).check("talkMode").run() == [mode], stored


def test_the_live_switch_is_locked_while_recording(tmp_path):
    page = page_with(tmp_path)
    page.js("recorder = {}; paintAll();").check("$('livemode').disabled")
    page.js("recorder = null; paintAll();").check("$('livemode').disabled")
    assert page.run() == [True, False]


LIVE = ("live = {stream: {getAudioTracks: () => [{enabled: true}]}, ctx: null, rate: 16000, recent: [], pre: [], loud: 0, quiet: 0, voiced: 0, ms: 0, speech: false,"
        " chunks: [], floorTaken: false, parked: null, lastVoice: performance.now(), suspended: false, muted: false, noSignal: false, flatMs: 0}; talkMode = 'live'; wokeAt = -5000; paintAll();")


def test_the_line_above_the_field_names_what_an_open_microphone_is_doing(tmp_path):
    page = page_with(tmp_path)
    line = "[$('note').hidden ? '' : $('note').textContent, $('talk').getAttribute('aria-label')]"
    page.js(LIVE).check(line)
    page.js("live.speech = true; paintAll();").check(line)
    page.js("live.speech = false; live.suspended = true; paintAll();").check(line)
    page.js("live.suspended = false; live.parked = 'screen'; paintAll();").check(line)
    page.js("live.parked = null; live.noSignal = true; paintAll();").check("$('talk').getAttribute('aria-label')")
    page.js("live.noSignal = false; live = null; paintAll();").check(line)
    assert page.run() == [["", "Mute"], ["Hearing you…", "Mute"], ["Click anywhere to start listening.", "Start listening"],
                          ["Listening on another screen. Press the mic to listen here.", "Listen here"], "Mute", ["", "Listen"]]


def test_mute_keeps_the_microphone_open_and_sends_nothing_until_unmuted(tmp_path):
    page = page_with(tmp_path)
    page.js(LIVE + " const track = live.stream.getAudioTracks()[0]; live.stream.getAudioTracks = () => [track];")
    page.js("$('talk').click();")
    page.check("[live.muted, track.enabled, listening(), $('talk').getAttribute('aria-label'), $('app').hasAttribute('data-live')]")
    page.js("liveChunk(new Float32Array(2048).fill(0.5)); liveChunk(new Float32Array(2048).fill(0.5));").check("[live.loud, live.flatMs, live.speech]")
    page.js("$('talk').click();")
    page.check("[live.muted, track.enabled, listening(), $('talk').getAttribute('aria-label')]")
    assert page.run() == [[True, False, False, "Unmute", False], [0, 0, False], [False, True, True, "Mute"]]


def test_a_stream_flat_at_zero_for_ten_seconds_is_no_sound_and_a_sound_clears_it(tmp_path):
    page = page_with(tmp_path)
    page.js(LIVE)
    page.js("for (let i = 0; i < 78; i++) liveChunk(new Float32Array(2048));").check("[live.flatMs, live.noSignal]")
    page.js("liveChunk(new Float32Array(2048));").check("[live.flatMs, live.noSignal]")
    page.js("liveChunk(new Float32Array(2048).fill(0.2));").check("[live.flatMs, live.noSignal]")
    # a quiet room is not a dead one: noise above the floor never counts
    page.js("for (let i = 0; i < 200; i++) liveChunk(new Float32Array(2048).fill(0.002));").check("[live.noSignal, live.flatMs]")
    assert page.run() == [[9984, False], [10112, True], [0, False], [False, 0]]


def test_the_two_live_options_are_segmented_controls_of_the_settings_shown_only_in_live(tmp_path):
    page = page_with(tmp_path)
    state = ("[barge, endPause, localStorage.getItem('talk.barge'), localStorage.getItem('talk.endPause'),"
             " [...document.querySelectorAll('#barge button, #endpause button')].filter((b) => b.getAttribute('aria-pressed') === 'true').map((b) => b.dataset.choice)]")
    page.check("[$('bargerow').hidden, $('pauserow').hidden]")
    page.js("$('livemode').click();").check("[$('bargerow').hidden, $('pauserow').hidden]")
    page.check(state)
    page.js("document.querySelector('#barge [data-choice=keyword]').click(); document.querySelector('#endpause [data-choice=\"2000\"]').click();").check(state)
    page.js("document.querySelector('#barge [data-choice=talk]').click(); document.querySelector('#endpause [data-choice=\"800\"]').click();").check("[barge, endPause]")
    assert page.run() == [[True, True], [False, False], ["talk", 1200, None, None, ["talk", "1200"]],
                          ["keyword", 2000, '"keyword"', "2000", ["keyword", "2000"]], ["talk", 800]]


# ---- a typed turn that is only a command to the player (S-tv-7) -------------------------------------------------------------

SAYS = "sentTo.filter((x) => x[0] === '/api/say').map((x) => x[1].text)"


def test_a_typed_turn_that_is_only_a_speed_command_moves_the_voice_and_is_not_sent(tmp_path):
    page = page_with(tmp_path)
    page.js("const t = $('text'); t.value = 'slower'; fitText(); $('sendtext').click(); await settle();")
    page.check(f"[speed, audio.playbackRate, t.value, {SAYS}, liveFlash.text, $('announcer').textContent]")
    page.js("t.value = 'Faster, please!'; fitText(); t.dispatchEvent(new ShimEvent('keydown', {key: 'Enter', bubbles: true})); await settle();")
    page.check(f"[speed, t.value, {SAYS}]")
    # words after the command make it a question for Claude: it is sent, and the speed stays
    page.js("t.value = 'slower please, and explain tides'; fitText(); $('sendtext').click(); await settle();").check(f"[speed, {SAYS}]")
    assert page.run() == [[0.85, 0.85, "", [], "Slower: 0.85×", ""], [1, "", []], [1, ["slower please, and explain tides"]]]


def test_the_commands_the_page_applies_to_a_typed_turn_are_the_ones_the_server_hears_for_the_player():
    import talk
    wanted = {p: c for p, c in talk.COMMANDS.items() if c in ("slower", "faster", "repeat_slower", "repeat")}
    assert len(wanted) == 22
    other = {p: c for p, c in talk.COMMANDS.items() if c not in wanted.values()}
    page_cmds = json.loads(re.search(r"const LOCAL_COMMANDS = (\{.*?\});", (STATIC / "call-input.js").read_text(), re.S).group(1))
    assert page_cmds == wanted
    assert not set(page_cmds) & set(other)


def test_the_page_reads_a_command_with_courtesy_words_round_it_and_nothing_else(tmp_path):
    page = page_with(tmp_path)
    page.check("['Slower', 'please go slower.', 'Claude, speed up!', 'ξαναπές το πιο αργά', 'Repeat that', ''].map(localCommand)")
    page.check("['slower please, I am lost', 'make it slower', 'go on', 'stop', 'explain tides'].map(localCommand)")
    assert page.run() == [["slower", "slower", "faster", "repeat_slower", "repeat", None], [None] * 5]


# ---- why a recording gave no words (r1-mic-2) -------------------------------------------------------------------------------

def test_an_empty_recording_is_said_above_the_field_with_its_length_and_whether_the_microphone_gave_a_signal(tmp_path):
    page = page_with(tmp_path)
    page.check("[micNoteText({seconds: 2.46, peak: 0.0004}), micNoteText({seconds: 14.2, peak: 0.31}), micNoteText({seconds: 0.2, peak: 0}), micNoteText(undefined)]")
    # a recording that comes back empty: the note, not the toast, and it stays until the next press
    page.js("const f0 = globalThis.fetch; globalThis.fetch = async (p, o) => String(p).startsWith('/api/listen') ? {ok: true, status: 200, json: async () => ({text: ''})} : f0(p, o);")
    page.js("const wav = new Blob([new Uint8Array(100)], {type: 'audio/wav'}); wav.heard = {seconds: 3, peak: 0.002}; await sendWav(wav); await advance(13000);")
    page.check("[$('note').hidden, $('note').textContent, $('toast').hidden, $('toasttext').textContent]")
    page.js("showMicNote(''); await sendWav(Object.assign(new Blob([new Uint8Array(100)]), {heard: {seconds: 1, peak: 0.4}}));").check("$('note').textContent")
    page.js("await startRecording();").check("$('note').hidden")
    assert page.run() == [
        ["Nothing was heard in 2.5 s of recording: the microphone gave almost no signal. Check that it is switched on and not muted, then try again.",
         "Nothing was heard in 14 s of recording, though the microphone picked up some sound. Try again a little closer to it.",
         "Nothing was heard: the microphone gave almost no signal. Check that it is switched on and not muted, then try again.",
         "Nothing was heard, though the microphone picked up some sound. Try again a little closer to it."],
        [False, "Nothing was heard in 3.0 s of recording: the microphone gave almost no signal. Check that it is switched on and not muted, then try again.",
         True, ""],
        "Nothing was heard in 1.0 s of recording, though the microphone picked up some sound. Try again a little closer to it.",
        True]


# ---- TV, the theme, the engine's words -----------------------------------------------------------------------------------

def test_the_address_names_the_screen_and_the_gear_still_wins(tmp_path):
    html, states = served(tmp_path, [])
    state = "[screenMode, $('app').hasAttribute('data-tv'), localStorage.getItem('talk.screen')]"
    assert CallPage(html, states, query="?screen=tv").check(state).js("document.querySelector('#screen [data-choice=desk]').click();").check(state).run() == [
        ["tv", True, '"tv"'], ["desk", False, '"desk"']]
    assert CallPage(html, states, query="?screen=bogus").check(state).run() == [["desk", False, None]]


def test_the_page_follows_the_system_theme_until_one_is_picked_and_the_choices_are_named_apart(tmp_path):
    html, states = served(tmp_path, [])
    assert re.search(r"""localStorage.getItem\("talk.theme"\) \|\| '"system"'""", html)
    page = CallPage(html, states).check("[theme, [...document.querySelectorAll('#theme button')].map((b) => b.textContent + ':' + b.getAttribute('aria-pressed')),"
                                         " [...document.querySelectorAll('#lang button')].map((b) => b.textContent), document.querySelector('#lang').previousElementSibling.textContent]")
    assert page.run() == [["system", ["Light:false", "Dark:false", "Auto:true"], ["Detect", "English", "Ελληνικά"], "Language"]]
    assert CallPage(html, states, stored={"theme": "dark"}).check("theme").run() == ["dark"]


def test_the_voice_is_described_in_plain_words_with_no_machine_or_profile(tmp_path):
    html, states = served(tmp_path, [])
    page = CallPage(html, states)
    for engine, voice, voices in (("VoiceStudio", "Talk", []), ("Azure", "en-US-AvaMultilingualNeural", []), ("Azure", "en-US-AvaMultilingualNeural", [{"id": "a", "name": "Ava", "note": ""}])):
        page.js(f"CFG.engine = {engine!r}; CFG.voice = {voice!r}; CFG.voices = {json.dumps(voices)};").check("engineText()")
    assert page.run() == ["A voice made on this computer: free, a little slower to start",
                          "Ava, a cloud voice: quick to start, billed per character",
                          "a cloud voice: quick to start, billed per character"]


# ---- layout the page keeps, pinned by the stylesheets (no box measures under node; tools/talk_render shows them) ---------------

CSS = {name: (STATIC / name).read_text() for name in ("call.css", "call-panel.css")}
HTML = (STATIC / "call.html").read_text()


def block(css, header):
    """The text inside the braces of the first `header { ... }` (an @media or @container), braces matched."""
    start = css.index(header + "{") + len(header) + 1 if (header + "{") in css else css.index(header + " {") + len(header) + 2
    depth, i = 1, start
    while depth:
        depth += {"{": 1, "}": -1}.get(css[i], 0); i += 1
    return css[start:i - 1]


def decls(css, selector):
    """The declarations of the rule whose selector is exactly `selector`, as a dict (the first such rule)."""
    m = re.search(r"(?:^|[}\n])\s*" + re.escape(selector) + r"\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return {k.strip(): v.strip() for k, v in (d.split(":", 1) for d in m.group(1).split(";") if ":" in d)}


def test_end_call_is_the_last_row_of_the_settings_sheet_which_scrolls_in_its_body():
    pop = HTML[HTML.index('id="pGear"'):HTML.index('id="pKeys"')]
    assert pop.index('class="sheethead"') < pop.index('class="sheetbody"') < pop.index('id="follow"') < pop.index('id="keysrow"') < pop.index('id="demo"') < pop.index('id="end"')
    assert pop.count("</div>") == pop.count("<div")
    panel = CSS["call-panel.css"]
    assert decls(panel, ".sheet")["inset"] == "0" and decls(panel, ".sheet")["flex-direction"] == "column"
    body = decls(panel, ".sheetbody")
    assert body["overflow"] == "auto" and body["flex"] == "1" and body["min-height"] == "0"      # the head stays, the body scrolls
    assert "color" in decls(panel, ".endrow")


def test_on_a_phone_the_targets_are_44_px_and_the_header_is_44_px_high():
    phone = block(CSS["call-panel.css"], "@media (max-width:760px)")
    assert decls(phone, ".ib,.compose .ib") == {"width": "44px", "height": "44px"}
    assert decls(phone, ".phead")["min-height"] == "44px"
    assert decls(CSS["call-panel.css"], ".phead")["min-height"] == "calc(54px * var(--tv))"
    assert decls(CSS["call-panel.css"], ".topic")["text-overflow"] == "ellipsis"


# ---- the markup ------------------------------------------------------------------------------------------------------------

def test_the_page_has_the_settings_the_keys_row_and_no_mode_switch_or_rail():
    html = (STATIC / "call.html").read_text()
    for gone in ("modechip", 'id="tmode"', 'id="liveopts"', 'id="modesw"', 'id="yourturn"', 'id="keyhint"', 'id="keysbtn"', 'id="speedchip"',
                 'id="collapse"', 'id="expand"', 'id="fullscreen"', 'id="tvoffer"', 'id="statestrip"', 'id="nowcard"', 'id="queuerow"', 'id="welcome"'):
        assert gone not in html, gone
    for there in ("keysrow", "skipmsg", "skipplay", 'id="pKeys"', 'id="livemode"', 'id="barge"', 'id="endpause"', 'id="geardone"'):
        assert there in html, there
    assert "paintModeChip" not in (STATIC / "call.js").read_text() + (STATIC / "call-input.js").read_text()


# ---- typed input: a first send, a draft over a reload, a keyboard start (bd1125b-vote-6, -7, -8) --------------------------

def test_a_typed_command_with_nothing_to_act_on_still_says_it_was_taken_and_not_sent(tmp_path):
    page = page_with(tmp_path)
    page.js("const t = $('text'); t.value = 'repeat that'; fitText(); $('sendtext').click(); await settle();")
    page.check(f"[t.value, {SAYS}, liveFlash.text]")
    page.js("t.value = 'slower'; fitText(); $('sendtext').click(); await settle();").check("liveFlash.text")
    assert page.run() == [["", [], "Nothing to repeat yet. Not sent to Claude."], "Slower: 0.85×"]


def test_pressing_send_twice_before_the_server_answers_sends_the_words_once(tmp_path):
    page = page_with(tmp_path)
    page.js("const t = $('text'); t.value = 'explain tides'; fitText(); sendText(); sendText(); t.dispatchEvent(new ShimEvent('keydown', {key: 'Enter', bubbles: true})); await settle();")
    page.check(f"[{SAYS}, $('text').value]")
    # a composing Enter (an input method confirming its word) is not a send
    page.js("t.value = 'ni'; fitText(); t.dispatchEvent(new ShimEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true})); await settle();")
    page.check(f"[{SAYS}.length, t.value]")
    assert page.run() == [[["explain tides"], ""], [1, "ni"]]


def test_the_draft_is_kept_per_call_over_a_reload_and_cleared_by_a_send_and_by_the_end(tmp_path):
    page = page_with(tmp_path)
    page.js("const t = $('text'); t.value = 'half a thought'; t.dispatchEvent(new ShimEvent('input')); await settle();")
    page.check("Object.fromEntries(Object.entries(sessionStorage.dump()).filter(([k]) => k.startsWith('talk.draft.')))")
    page.js("$('sendtext').click(); await settle();").check("[Object.fromEntries(Object.entries(sessionStorage.dump()).filter(([k]) => k.startsWith('talk.draft.'))), t.value]")
    assert page.run() == [{f"talk.draft.{CALL}": "half a thought"}, [{}, ""]]
    # a reload: the tab's session storage still holds it, and the page puts it back with Send showing
    again = page_with(tmp_path, session={f"talk.draft.{CALL}": "half a thought"})
    again.check("[$('text').value, $('sendtext').disabled, document.activeElement === $('text')]")
    # another call's draft is not this call's
    other = page_with(tmp_path, session={"talk.draft.someone-else": "not mine"})
    other.check("[$('text').value, $('sendtext').hidden]")
    assert again.run() == [["half a thought", False, True]]
    assert other.run() == [["", True]]


def test_a_kept_draft_is_not_put_over_a_say_back_question_and_goes_when_the_call_ends(tmp_path):
    page = page_with(tmp_path, session={f"talk.draft.{CALL}": "old words"})
    page.js("$('text').value = ''; answering = 'q1'; restoreDraft();").check("[$('text').value, Object.fromEntries(Object.entries(sessionStorage.dump()).filter(([k]) => k.startsWith('talk.draft.')))]")
    page.js("answering = null; view.ended = true; paintAll();").check("Object.fromEntries(Object.entries(sessionStorage.dump()).filter(([k]) => k.startsWith('talk.draft.')))")
    assert page.run() == [["", {f"talk.draft.{CALL}": "old words"}], {}]


def test_the_message_field_takes_the_focus_on_load_on_a_wide_screen_and_not_on_a_phone(tmp_path):
    wide = page_with(tmp_path).check("document.activeElement === $('text')")
    assert wide.run() == [True]
    phone = page_with(tmp_path)
    phone.js("""globalThis.matchMedia = () => ({matches: false, addEventListener() {}, removeEventListener() {}});
      document.body.focus(); vm.runInThisContext(readFileSync(%r, 'utf8'));""" % str(STATIC / "call-boot.js"))
    phone.check("document.activeElement === $('text')")
    assert phone.run() == [False]
