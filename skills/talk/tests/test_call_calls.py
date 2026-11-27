"""The calls part of the call page (call-calls.js): the words a call's state is said in, the Calls button and popover, Next waiting,
the tab's title and icon, and the pause another call causes. Run under node (call_page.py), with the server's summary part on a real server."""
import time
from urllib.parse import unquote

from call_page import CallPage, needs_node, served
from helpers import add_call, run, running_server

pytestmark = needs_node

OTHERS = ("[{id: 'a', topic: 'Weekend reading', ended: false, working: false, stalled: false, unheard: 2, floor: false, started: 1, last_at: NOW - 360},"
          " {id: 'b', topic: 'Hunting a flaky test', ended: false, working: true, stalled: false, unheard: 0, floor: false, started: 2, last_at: NOW - 40},"
          " {id: 'c', topic: 'Yearly fees', ended: true, working: false, stalled: false, unheard: 0, floor: false, started: 3, last_at: NOW - 7300},"
          " {id: 'd', topic: 'Parthenon', ended: false, working: false, stalled: false, unheard: 0, floor: false, started: 4, last_at: NOW - 900},"
          " {id: 'e', topic: 'Sourdough', ended: false, working: false, stalled: true, unheard: 0, floor: false, started: 5, last_at: NOW - 120}]")


def with_calls(page, calls=OTHERS, at=1):
    """The server moves on to state `at` with these other calls in it."""
    return page.js(f"const NOW = Date.now() / 1000; STATES[{at}] = {{...STATES[{at}], v: 'calls', now: NOW, calls: {calls}}}; await serve({at});")


def test_a_call_is_said_in_one_set_of_words_and_ranked_by_how_much_it_needs_you(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = with_calls(CallPage(html, states, start=1))
    page.check("(view.calls).map((c) => { const i = callInfo(c); return [c.topic, i.key, i.word, i.rank]; })")
    page.check("[{unheard: 1}, {ended: true, unheard: 0}, {floor: true}, {}].map((c) => callState(c))")
    assert page.run() == [
        [["Weekend reading", "new", "2 new answers", 1], ["Hunting a flaky test", "answering", "Answering", 2],
         ["Yearly fees", "ended", "Ended", 6], ["Parthenon", "waiting", "Waiting for you", 5], ["Sourdough", "stalled", "Stalled", 0]],
        ["New answer", "Ended", "Talking now", "Waiting for you"]]


def test_the_popover_lists_this_call_first_and_the_others_by_need_with_their_age(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = with_calls(CallPage(html, states, start=1))
    page.check("[...$('calls').children].map((r) => [r.className, r.dataset.state, r.querySelector('.ct').textContent, r.querySelector('.cs').textContent, r.querySelector('.ca').textContent])")
    assert page.run()[0] == [
        ["callrow here", "waiting", "Test topic", "Here · Waiting for you", ""],
        ["callrow needs", "stalled", "Sourdough", "Stalled", "2m"],
        ["callrow needs", "new", "Weekend reading", "2 new answers", "6m"],
        ["callrow", "answering", "Hunting a flaky test", "Answering", "now"],
        ["callrow", "waiting", "Parthenon", "Waiting for you", "15m"],
        ["callrow", "ended", "Yearly fees", "Ended", "2h"]]


def test_the_row_of_this_call_says_what_it_is_doing(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = with_calls(CallPage(html, states, start=1))
    page.js("$('playpause').click();")
    page.check("$('calls').children[0].querySelector('.cs').textContent")
    assert page.run() == ["Here · Playing"]


def test_next_waiting_opens_the_call_that_needs_you_most_and_hides_while_none_does(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = with_calls(CallPage(html, states, start=1))
    page.check("[nextWaiting().id, [...$('nextwait').children].map((x) => x.textContent)]")
    page.js("const home = location.href; $('nextbtn').click();")
    page.check("location.href").js("location.href = home;")
    page.js("STATES[1] = {...STATES[1], v: 'calm', calls: [{id: 'd', topic: 'Parthenon', ended: false, working: false, stalled: false, unheard: 0, floor: false, started: 4, last_at: 1}]}; await serve(1);")
    page.check("[nextWaiting(), [...$('nextwait').children].map((x) => x.textContent)]")
    assert page.run() == [["e", ["Next waiting", "All calls"]], "/c/e", [None, ["All calls"]]]


def test_among_calls_that_need_you_equally_the_one_that_has_waited_longest_comes_first(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    calls = ("[{id: 'x', topic: 'X', ended: false, working: false, stalled: false, unheard: 1, floor: false, started: 1, last_at: NOW - 60},"
             " {id: 'y', topic: 'Y', ended: false, working: false, stalled: false, unheard: 1, floor: false, started: 2, last_at: NOW - 900}]")
    page = with_calls(CallPage(html, states, start=1), calls)
    page.check("callsNeedingYou().map((x) => x.c.id)")
    assert page.run() == [["y", "x"]]


def test_the_calls_button_counts_the_calls_that_need_you_and_names_them(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = CallPage(html, states, start=1)
    page.check("[$('callsbtn').hidden, $('callsdot').hidden]")
    with_calls(page)
    page.check("[$('callsbtn').hidden, $('callsdot').hidden, $('callsdot').textContent, $('callsbtn').dataset.need, $('callsbtn').dataset.tip, $('callsbtn').getAttribute('aria-label')]")
    assert page.run() == [
        [True, True],
        [False, False, "2", "stalled", "2 other calls need you",
         "Calls: 2 other calls need you. Stalled in “Sourdough”; 2 new answers in “Weekend reading”"]]


def test_the_tab_title_and_icon_say_what_the_call_is_doing(tmp_path):
    html, states = served(tmp_path, ["First.", "Second."])
    page = CallPage(html, states, start=2).js("document.body.append(Object.assign(document.createElement('link'), {id: 'favicon'}));")
    page.check("[document.title, tabState()]")
    page.js("$('playpause').click();").check("[document.title, tabState().key]")
    page.js("audio.pause();")
    page.js("STATES[2] = {...STATES[2], v: 'w', working: true}; await serve(2);").check("[document.title, tabState().key]")
    page.js("STATES[2] = {...STATES[2], v: 's', stalled: true}; await serve(2);").check("[document.title, tabState().key]")
    page.js("STATES[2] = {...STATES[2], v: 'e', ended: 'over'}; await serve(2);").check("[document.title, tabState().key]")
    assert page.run() == [
        ["Talk · Test topic", {"key": "idle", "word": "", "count": 0}],
        ["Playing · Test topic", "playing"], ["Answering · Test topic", "answering"],
        ["Stalled · Test topic", "stalled"], ["Ended · Test topic", "ended"]]


def test_answers_that_came_while_the_tab_was_out_of_sight_are_counted_in_the_title(tmp_path):
    html, states = served(tmp_path, ["First.", "Second.", "Third."])
    page = CallPage(html, states, start=1, autoplay=False).js("document.body.append(Object.assign(document.createElement('link'), {id: 'favicon'}));")
    page.check("document.title")
    page.js("document.visibilityState = 'hidden'; await serve(3);")
    page.check("[document.title, tabState(), unheardHere().map((e) => e.id)]")
    page.js("document.visibilityState = 'visible'; document.dispatchEvent(new ShimEvent('visibilitychange')); await settle();")
    page.check("[document.title, unheardHere().length]")
    assert page.run() == ["Talk · Test topic",
                          ["(2) New · Test topic", {"key": "new", "word": "New", "count": 2}, [1, 2]],
                          ["Talk · Test topic", 0]]


def test_the_icon_is_a_disc_in_the_state_colour_with_the_count_in_it(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = CallPage(html, states, start=1).js("document.body.append(Object.assign(document.createElement('link'), {id: 'favicon'})); tabSig = ''; paintTab();")
    page.check("decodeURIComponent($('favicon').href)")
    page.check("decodeURIComponent(tabIcon({key: 'new', count: 12}))")
    page.check("decodeURIComponent(tabIcon({key: 'stalled', count: 0}))")
    idle, many, stalled = page.run()
    head = "data:image/svg+xml,<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 32 32\">"
    assert idle == head + '<circle cx="16" cy="16" r="15" fill="#1967D2"/><circle cx="16" cy="16" r="5.2" fill="#fff"/></svg>'
    assert many == head + ('<circle cx="16" cy="16" r="15" fill="#1967D2"/><text x="16" y="22.5" font-family="Arial,sans-serif" '
                           'font-size="19" font-weight="700" text-anchor="middle" fill="#fff">9+</text></svg>')
    assert stalled.startswith(head + '<circle cx="16" cy="16" r="15" fill="#F9AB00"/>')


def test_when_another_call_takes_the_voice_the_page_says_so_in_the_note_and_no_toast_covers_the_board(tmp_path):
    # study power-6: the pause was a 12 s toast over the board's header, worded as if the user talked
    html, states = served(tmp_path, ["An answer."])
    page = with_calls(CallPage(html, states, start=1))
    page.js("$('playpause').click(); await settle(); floorN = 0;")  # the harness answers /api/floor with no floor_n
    page.js("STATES[1] = {...STATES[1], v: 'f', floor_call: 'a', floor_n: 5}; await serve(1);")
    page.check("[audio.paused, $('toast').hidden, $('note').hidden, $('note').textContent]")
    page.js("resumeHere();")
    page.check("[!audio.paused, floorNote, $('note').hidden]")
    assert page.run() == [[True, True, False, "Paused: \u201cWeekend reading\u201d took the voice."],
                          [True, None, True]]


def test_resume_here_is_a_play_the_reader_starts_so_it_goes_through_readerplays(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = with_calls(CallPage(html, states, start=1))
    page.js("$('playpause').click(); await settle(); floorN = 0; STATES[1] = {...STATES[1], v: 'f', floor_call: 'a', floor_n: 5}; await serve(1); toStage().length = 0;")
    page.js("resumeHere();")
    page.check("readerAnswer")
    assert page.run() == [0]


def test_a_new_answer_in_another_call_is_announced(tmp_path):
    html, states = served(tmp_path, ["An answer."])
    page = with_calls(CallPage(html, states, start=1))
    page.js("STATES[1] = {...STATES[1], v: 'more', calls: STATES[1].calls.map((c) => c.id === 'd' ? {...c, unheard: 1} : c)}; await serve(1); await advance(200);")
    page.check("$('announcer').textContent")
    assert page.run() == ["New answer in “Parthenon”."]


def test_the_servers_summary_of_a_call_says_when_it_stalled_and_when_it_last_moved(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path, call_id="a", token="ta", topic="Alpha")
            quiet = server.summary(call)
            entry = call.add("you", "Hello")
            call.turns.offer("t1", [])
            call.turns.clock = lambda: time.time() + 100
            return quiet, server.summary(call), entry["at"], call.started
    quiet, stalled, at, started = run(go())
    assert (quiet["stalled"], quiet["last_at"]) == (False, started)
    assert (stalled["stalled"], stalled["last_at"]) == (True, at)


def test_the_all_calls_page_says_the_words_of_the_popover():
    from pathlib import Path
    home = (Path(__file__).resolve().parents[1] / "static" / "home.html").read_text()
    js = (Path(__file__).resolve().parents[1] / "static" / "call-i18n.js").read_text()   # the words are in the page's table
    for word in ("New answer", "Ended", "Stalled", "Answering", "Talking now", "Waiting for you"):
        assert f'"{word}"' in home and f'"{word}"' in js, word
    assert '" new answers"' in home and '"{n} new answers"' in js
    assert '"Open"' not in home.split("function stateOf")[1].split("let sig")[0]
