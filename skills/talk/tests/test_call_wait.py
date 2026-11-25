"""The wait card (call-wait.js): where a question stands from Send until the answer lands, its clock, its step, the way
out of each state, the draft kept, the queued answer's Skip, and a replaced answer that is never played by itself.
Run under node on the page's own files (call_page.py); the server's part is test_wait_server.py. Layout needs
tools/talk_render, not these."""
from __future__ import annotations

from call_page import CallPage, needs_node, served

pytestmark = needs_node

NOW = 1_800_000_000
FREEZE = f"Date.now = () => {NOW * 1000};"  # the page's clock stops, so a clock shown is exact


def waiting(base, n, *, entries=None, **fields):
    """The call's state at a moment of a wait: `entries` are `you` entries (their `at` is the send time)."""
    return {**base, "v": f"w{n}", "now": NOW, "entries": entries or [YOU], "working": False, "stalled": False, "listening": False,
            "activity": [], "turn": {"entries": [{"id": 0, "state": "sent"}], "earlier": 0, "collected_at": None, "alive_at": None}, **fields}


YOU = {"id": 0, "who": "you", "text": "How do vaccines work?", "at": NOW - 72, "typed": True}


def run_states(tmp_path, make, *checks, answers=()):
    html, states = served(tmp_path, list(answers))
    base = states[0]
    page = CallPage(html, states + make(base)).js(FREEZE)
    return page


def card(expr):
    return f"$('waitcard').{expr}"


TEXTS = "[...$('waitcard').querySelectorAll('.wt-btn')].map(b => b.textContent)"


def test_a_question_nobody_has_collected_is_sent_with_a_clock_from_its_own_time_and_a_way_back(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)])
    page.js(f"await serve({1});")
    page.check("[$('nowcard').hidden, $('waitcard').hidden, waitActive(), $('status').hidden]")
    page.check(card("querySelector('.wt-title').textContent"))
    page.check(card("querySelector('.wt-clock').textContent"))
    page.check(card("querySelector('.wt-sub').textContent"))
    page.check(card("querySelector('.wt-q').textContent"))
    page.check(TEXTS)
    page.check("[...$('waitcard').querySelectorAll('.wt-steps li')].map(li => li.className + ':' + li.querySelector('b').textContent + ':' + li.querySelector('.wt-at').textContent)")
    page.check("$('text').placeholder")
    assert page.run() == [
        [False, False, True, True], "Sent", "1:12", "Waiting for Claude to pick it up.", "How do vaccines work?",
        ["Take back", "Copy question"],
        ["now:Sent:0:00", "todo:Picked up:", "todo:Working:", "todo:Answer:"], "Add to your question"]


def test_a_question_nobody_collected_for_too_long_says_not_picked_up_and_offers_send_again_without_a_word_about_a_terminal(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1, stalled=True)]).js("await serve(1);")
    page.check(card("className"))
    page.check(card("querySelector('.wt-title').textContent"))
    page.check(card("querySelector('.wt-sub').textContent"))
    page.check(card("querySelector('.wt-lost').textContent"))
    page.check(TEXTS)
    page.check("$('waitcard').textContent.toLowerCase().includes('terminal')")
    assert page.run() == [
        "wait-card step-notpicked warn", "Not picked up", "Claude has not picked this up yet.",
        "Nothing is lost: your question is saved in the call.", ["Send again", "Copy question", "Take back"], False]


def picked(b, n, activity=(), **fields):
    turn = {"entries": [{"id": 0, "state": "picked"}], "earlier": 0, "collected_at": NOW - 66, "alive_at": NOW - 5}
    return waiting(b, n, working=True, activity=list(activity), **{"turn": turn, **fields})


def test_a_question_with_no_running_step_still_counts_its_seconds_from_the_send_time(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1);")
    page.check(card("querySelector('.wt-title').textContent"))
    page.check(card("querySelector('.wt-clock').textContent"))
    page.check(card("querySelector('.wt-sub').textContent"))
    page.check(TEXTS)
    page.check("[statusText(), $('status').hidden]")
    page.check("[...$('waitcard').querySelectorAll('.wt-steps li')].map(li => li.className + ':' + li.querySelector('.wt-at').textContent)")
    assert page.run() == ["Claude is working", "1:12", "Claude has your question.", ["Cancel"], [None, True],
                          ["done:0:00", "now:0:06", "todo:", "todo:"]]


def test_a_running_step_and_the_finished_ones_are_rows_with_their_seconds_and_the_foot_says_nothing_about_working(tmp_path):
    acts = [{"label": "Reading the plan", "state": "done", "seconds": 9.2}, {"label": "Searching for analogies", "state": "running", "seconds": 75.4}]
    page = run_states(tmp_path, lambda b: [picked(b, 1, acts)]).js("await serve(1);")
    page.check(card("querySelector('.wt-sub').textContent"))
    page.check("[...$('waitcard').querySelectorAll('.wt-acts li')].map(li => [li.className, li.querySelector('.wt-act').textContent, li.querySelector('.wt-sec').textContent])")
    page.check("[...$('waitcard').querySelectorAll('.wt-steps li')].map(li => li.className).join(' ')")
    page.check("[statusText(), $('status').hidden]")
    assert page.run() == ["",
                          [["done", "Reading the plan", "9s"], ["run", "Searching for analogies", "1:15"]],
                          "done done now todo", [None, True]]


def test_after_ninety_seconds_the_card_turns_slow_and_says_when_the_session_last_showed_life(tmp_path):
    slow = lambda b: [picked(b, 1, entries=[{**YOU, "at": NOW - 100}], turn={"entries": [{"id": 0, "state": "picked"}], "earlier": 0,
                                                                              "collected_at": NOW - 95, "alive_at": NOW - 40})]
    page = run_states(tmp_path, slow).js("await serve(1);")
    page.check(card("className"))
    page.check(card("querySelector('.wt-title').textContent"))
    page.check(card("querySelector('.wt-sub').textContent"))
    page.check(TEXTS)
    assert page.run() == ["wait-card step-slow warn", "Taking longer than usual", "Last sign of life 40s ago.",
                          ["Cancel", "Copy question"]]


def test_a_collected_question_the_server_calls_stalled_says_the_session_went_quiet(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1, stalled=True, entries=[{**YOU, "at": NOW - 230}],
                                                  turn={"entries": [{"id": 0, "state": "picked"}], "earlier": 0, "collected_at": NOW - 225, "alive_at": NOW - 200})])
    page.js("await serve(1);")
    page.check(card("querySelector('.wt-title').textContent"))
    page.check(card("querySelector('.wt-sub').textContent"))
    page.check(TEXTS)
    assert page.run() == ["Claude has gone quiet", "No sign of life for 3:20.", ["Send again", "Copy question", "Cancel"]]


def test_the_clock_moves_each_second_without_rebuilding_the_card(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)]).js("await serve(1); window.t0 = $('waitcard').querySelector('.wt-title'); window.b0 = $('waitcard').querySelector('.wt-btn');")
    page.js("Date.now = () => %d; await advance(3000);" % ((NOW + 3) * 1000))
    page.check(card("querySelector('.wt-clock').textContent"))
    page.check("[$('waitcard').querySelector('.wt-title') === window.t0, $('waitcard').querySelector('.wt-btn') === window.b0]")
    assert page.run() == ["1:15", [True, True]]


def test_the_clock_stops_when_the_answer_comes_and_the_card_goes(tmp_path):
    html, states = served(tmp_path, ["Here is the answer."])
    answered = states[1]
    asked = {**waiting(states[0], 1)}
    page = CallPage(html, [states[0], asked, {**answered, "v": "done", "entries": [YOU] + [{**e, "id": 1} for e in answered["entries"]]}])
    page.js(FREEZE + "await serve(1);")
    page.check("[$('waitcard').hidden, waitActive()]")
    page.js("await serve(2);")
    page.check("[$('waitcard').hidden, waitActive(), $('waitcard').children.length, $('text').placeholder]")
    assert page.run() == [[False, True], [True, False, 0, "Type, or press the mic"]]


def test_take_back_asks_the_server_and_puts_the_words_back_in_the_box(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)]).js("await serve(1);")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/cancel'
      ? (sentTo.push([p, JSON.parse(o.body)]), respond({cancelled: true, how: 'withdrawn', entries: [0]})) : f0(p, o);
      [...$('waitcard').querySelectorAll('.wt-btn')].find(b => b.textContent === 'Take back').click();""")
    page.check("sentTo.filter(s => s[0] === '/api/cancel')")
    page.check("$('text').value")
    page.check("[$('sendnote').hidden, $('sendnote').querySelector('.sn-text').textContent]")
    assert page.run() == [[["/api/cancel", {"entry": 0}]], "How do vaccines work?",
                          [False, "Taken back. Your words are back in the box."]]


def test_cancel_after_pickup_says_cancelled_and_keeps_a_draft_already_in_the_box(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1); $('text').value = 'and the shots?'; $('text').dispatchEvent(new ShimEvent('input'));")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/cancel'
      ? (sentTo.push([p, JSON.parse(o.body)]), respond({cancelled: true, how: 'cancelled', entries: [0]})) : f0(p, o);
      [...$('waitcard').querySelectorAll('.wt-btn')].find(b => b.textContent === 'Cancel').click();""")
    page.check("sentTo.filter(s => s[0] === '/api/cancel')")
    page.check("$('text').value")
    page.check("$('sendnote').querySelector('.sn-text').textContent")
    assert page.run() == [[["/api/cancel", {"entry": 0}]], "How do vaccines work?\nand the shots?", "Cancelled. Your words are back in the box."]


def test_a_take_back_that_comes_too_late_says_so_and_changes_no_box(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)]).js("await serve(1);")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/cancel' ? respond({cancelled: false}) : f0(p, o);
      [...$('waitcard').querySelectorAll('.wt-btn')].find(b => b.textContent === 'Take back').click();""")
    page.check("[$('text').value, $('sendnote').querySelector('.sn-text').textContent, $('sendnote').className]")
    assert page.run() == [["", "Too late: Claude already answered it.", "sendnote warn"]]


def test_send_again_replaces_the_first_question_and_leaves_the_draft_alone(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1, stalled=True)]).js("await serve(1); $('text').value = 'half a thought'; $('text').dispatchEvent(new ShimEvent('input'));")
    page.js("[...$('waitcard').querySelectorAll('.wt-btn')].find(b => b.textContent === 'Send again').click();")
    page.check("sentTo.filter(s => s[0] === '/api/say')")
    page.check("[$('text').value, $('sendnote').querySelector('.sn-text').textContent]")
    assert page.run() == [[["/api/say", {"text": "How do vaccines work?", "replaces": 0}]], ["half a thought", "Sent again."]]


def test_copy_question_puts_the_question_on_the_clipboard(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1, stalled=True)]).js("await serve(1); window.copied = []; Object.defineProperty(globalThis, 'navigator', {value: {clipboard: {writeText: async t => { window.copied.push(t); }}}, configurable: true});")
    page.js("[...$('waitcard').querySelectorAll('.wt-btn')].find(b => b.textContent === 'Copy question').click();")
    page.check("[window.copied, $('sendnote').querySelector('.sn-text').textContent]")
    assert page.run() == [[["How do vaccines work?"], "Copied."]]


def test_a_draft_typed_while_a_question_is_in_flight_is_kept_with_a_note_and_a_replace_button(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1), picked(b, 2, activity=[{"label": "Reading", "state": "running", "seconds": 1}])])
    page.js("await serve(1); $('text').value = 'no wait, six year olds'; $('text').dispatchEvent(new ShimEvent('input'));")
    page.check("[$('sendnote').hidden, $('sendnote').querySelector('.sn-text').textContent, [...$('sendnote').querySelectorAll('.wt-btn')].map(b => b.textContent)]")
    page.js("await serve(2);")  # a poll while Claude works leaves the draft
    page.check("[$('text').value, $('sendnote').hidden]")
    assert page.run() == [[False, "Draft kept. Send adds it to your question.", ["Replace question"]], ["no wait, six year olds", False]]


def test_replace_sends_the_draft_as_a_correction_of_the_question_in_flight(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1); $('text').value = 'no wait, six year olds'; $('text').dispatchEvent(new ShimEvent('input'));")
    page.js("[...$('sendnote').querySelectorAll('.wt-btn')].find(b => b.textContent === 'Replace question').click();")
    page.check("sentTo.filter(s => s[0] === '/api/say')")
    page.check("[$('text').value, $('sendnote').querySelector('.sn-text').textContent]")
    assert page.run() == [[["/api/say", {"text": "no wait, six year olds", "replaces": 0}]], ["", "Replaced. Claude will answer this one."]]


def test_plain_send_while_a_question_is_in_flight_adds_to_it_without_a_replaces(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1); $('text').value = 'and also the shots'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click();")
    page.check("sentTo.filter(s => s[0] === '/api/say')")
    assert page.run() == [[["/api/say", {"text": "and also the shots"}]]]


def test_a_failed_send_keeps_the_draft_and_says_so(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1);")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/say' ? {ok: false, status: 500, json: async () => ({})} : f0(p, o);
      $('text').value = 'will not go'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click();""")
    page.check("[$('text').value, $('sendnote').querySelector('.sn-text').textContent, $('sendnote').className]")
    assert page.run() == [["will not go", "Not sent. Your draft is kept.", "sendnote warn"]]


def test_a_correction_in_flight_says_claude_is_finishing_the_earlier_question(tmp_path):
    new = {**YOU, "id": 1, "text": "no, ten days", "replaces": 0, "at": NOW - 4}
    old = {**YOU, "superseded": True}
    page = run_states(tmp_path, lambda b: [waiting(b, 1, entries=[old, new], turn={"entries": [{"id": 1, "state": "sent"}], "earlier": 1, "collected_at": None, "alive_at": None})])
    page.js("await serve(1);")
    page.check(card("querySelector('.wt-sub').textContent"))
    page.check(card("querySelector('.wt-q').textContent"))
    page.check(card("querySelector('.wt-clock').textContent"))
    assert page.run() == ["Claude is finishing the earlier question. This one comes next.", "no, ten days", "0:04"]


def test_two_questions_in_flight_count_from_the_oldest_and_show_both(tmp_path):
    second = {**YOU, "id": 1, "text": "and the shots?", "at": NOW - 10}
    page = run_states(tmp_path, lambda b: [waiting(b, 1, entries=[YOU, second], working=True,
                                                    turn={"entries": [{"id": 0, "state": "picked"}, {"id": 1, "state": "sent"}], "earlier": 0, "collected_at": NOW - 60, "alive_at": NOW - 3})])
    page.js("await serve(1);")
    page.check(card("querySelector('.wt-clock').textContent"))
    page.check(card("querySelector('.wt-q').textContent"))
    assert page.run() == ["1:12", "How do vaccines work?\nand the shots?"]


def test_without_a_turn_in_the_view_an_older_server_still_gets_a_card_for_the_newest_unanswered_question(tmp_path):
    def old(b):
        s = waiting(b, 1, working=True)
        del s["turn"]
        return [s]
    page = run_states(tmp_path, old).js("await serve(1);")
    page.check("[$('waitcard').hidden, $('waitcard').querySelector('.wt-title').textContent]")
    assert page.run() == [[False, "Claude is working"]]


# ---- the queue and replaced answers -------------------------------------------------------------------

def test_skip_drops_the_queued_answer_from_the_queue_and_it_stays_in_the_list_unplayed(tmp_path):
    html, states = served(tmp_path, ["The first answer is here.", "The second answer is here."], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.0); await serve(2);")
    page.check("[$('queuerow').hidden, [...$('queuerow').querySelectorAll('.wt-btn')].map(b => b.getAttribute('aria-label'))]")
    page.js("$('queuerow').querySelector('.qr-skip').click(); await end(); await advance(50);")
    page.check("[$('queuerow').hidden, queued, audio.getAttribute('src'), view.entries.filter(e => e.who === 'claude').length]")
    assert page.run() == [[False, ["Skip"]], [True, None, "/c/test-call-id/audio/0000.wav", 2]]


def test_skip_leaves_following_and_the_players_claim_alone(tmp_path):
    html, states = served(tmp_path, ["The first answer is here.", "The second answer is here."], seconds=3.0)
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await playTo(1.0); await serve(2); const f0 = follow, c0 = claims.length, h0 = holder;")
    page.js("$('queuerow').querySelector('.qr-skip').click(); await advance(50);")
    page.check("[follow === f0, claims.length === c0, holder === h0]")
    assert page.run() == [[True, True, True]]


def replaced(states, **fields):
    """The state after the first answer, that answer kept unspoken as the server keeps an answer to a replaced question."""
    answers = [e for e in states[1]["entries"] if e["who"] == "claude"]
    return {**states[1], "v": "rep", "entries": [{**e, **fields} for e in answers]}


def test_an_answer_to_a_replaced_question_never_plays_by_itself_and_is_never_queued(tmp_path):
    html, states = served(tmp_path, ["The old answer."])
    page = CallPage(html, [states[0], replaced(states, superseded=True, superseded_kind="correction")])
    page.js("await serve(1);")
    page.check("[audio.paused, audio.getAttribute('src'), queued === null, current]")
    assert page.run() == [[True, None, True, None]]


def test_a_queued_answer_that_was_replaced_meanwhile_is_dropped_when_the_voice_ends(tmp_path):
    html, states = served(tmp_path, ["The first answer is here.", "The second answer is here."], seconds=3.0)
    again = {**states[2], "v": "rep", "entries": [states[2]["entries"][0], {**states[2]["entries"][1], "superseded": True}]}
    page = CallPage(html, states + [again], seconds=3.0).js("await serve(1); await playTo(1.0); await serve(2); await serve(3); await end(); await advance(50);")
    page.check("[audio.getAttribute('src'), queued, $('queuerow').hidden]")
    assert page.run() == [["/c/test-call-id/audio/0000.wav", None, True]]


def test_play_anyway_makes_the_voice_of_a_skipped_answer_and_plays_it_when_it_is_ready(tmp_path):
    html, states = served(tmp_path, ["The old answer."])
    skipped = replaced(states, superseded=True, superseded_kind="correction", speech="skipped", audio=None, words=[])
    ready = replaced(states, superseded=True, superseded_kind="correction")
    page = CallPage(html, [states[0], skipped, {**ready, "v": "rdy"}])
    page.js("await serve(1); playAnyway(view.entries[0]); await advance(10);")
    page.check("sentTo.filter(s => s[0] === '/api/speak')")
    page.check("[audio.paused, audio.getAttribute('src'), playAnywayId]")
    page.js("await serve(2);")
    page.check("[audio.paused, audio.getAttribute('src'), playAnywayId]")
    assert page.run() == [[["/api/speak", {"entry": 0}]], [True, None, 0], [False, "/c/test-call-id/audio/0000.wav", None]]


def test_a_screen_reader_hears_each_change_of_step_once_and_never_the_clock(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1), picked(b, 2), picked(b, 3, activity=[{"label": "Reading", "state": "running", "seconds": 1}]),
                                           waiting(b, 4, stalled=True, turn=picked(b, 4)["turn"], working=True)])
    page.js("window.said = []; announce = t => window.said.push(t); await serve(1); await advance(3000); await serve(2); await advance(2000); await serve(3); await serve(4);")
    page.check("window.said")
    assert page.run() == [["Claude is working. Claude has your question.", "Claude has gone quiet. No sign of life for 0:05."]]


def test_a_question_sent_is_announced_once(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)])
    page.js("window.said = []; announce = t => window.said.push(t); $('text').value = 'hello'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click(); await settle(); await serve(1);")
    page.check("window.said")
    assert page.run() == [["Your question was sent."]]
