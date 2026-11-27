"""The thinking row (call-wait.js, #thinking): where a question stands from Send until the answer lands, its clock, its step, the one way
out of each state (Cancel, or Send again when nothing moves), the draft kept, and a replaced answer that is never played by itself.
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
    return f"$('thinking').{expr}"


TEXTS = "[...$('thinking').querySelectorAll('button')].map(b => b.textContent)"


def press(label):
    """JS that clicks the thinking row's button with this label."""
    return f"[...$('thinking').querySelectorAll('button')].find(b => b.textContent === '{label}').click();"


NOTE = "[$('note').hidden, $('note').textContent, $('note').classList.contains('warn')]"


def test_a_question_nobody_has_collected_is_sent_with_a_clock_from_its_own_time_and_a_way_back(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)])
    page.js("await serve(1);")
    page.check("[$('thinking').hidden, waitActive()]")
    page.check(card("className"))
    page.check(card("querySelector('.what').textContent"))
    page.check(card("querySelector('.clock').textContent"))
    page.check(TEXTS)
    assert page.run() == [[False, True], "thinking", "Sent", "1:12", ["Cancel"]]


def test_a_question_nobody_collected_for_too_long_says_not_picked_up_and_offers_send_again_without_a_word_about_a_terminal(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1, stalled=True)]).js("await serve(1);")
    page.check(card("className"))
    page.check(card("querySelector('.what').textContent"))
    page.check(TEXTS)
    page.check("$('thinking').textContent.toLowerCase().includes('terminal')")
    assert page.run() == ["thinking warn", "Not picked up", ["Send again"], False]


def picked(b, n, activity=(), **fields):
    turn = {"entries": [{"id": 0, "state": "picked"}], "earlier": 0, "collected_at": NOW - 66, "alive_at": NOW - 5}
    return waiting(b, n, working=True, activity=list(activity), **{"turn": turn, **fields})


def test_a_question_with_no_running_step_still_counts_its_seconds_from_the_send_time(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1);")
    page.check(card("querySelector('.what').textContent"))
    page.check(card("querySelector('.clock').textContent"))
    page.check(TEXTS)
    assert page.run() == ["Claude is working", "1:12", ["Cancel"]]


def test_a_running_step_is_said_in_place_of_the_title_and_the_finished_ones_are_not_listed(tmp_path):
    acts = [{"label": "Reading the plan", "state": "done", "seconds": 9.2}, {"label": "Searching for analogies", "state": "running", "seconds": 75.4}]
    page = run_states(tmp_path, lambda b: [picked(b, 1, acts)]).js("await serve(1);")
    page.check(card("querySelector('.what').textContent"))
    page.check(card("querySelectorAll('li').length"))
    assert page.run() == ["Searching for analogies", 0]


def test_after_ninety_seconds_the_row_turns_slow_and_keeps_its_way_out(tmp_path):
    turn = {"entries": [{"id": 0, "state": "picked"}], "earlier": 0, "collected_at": NOW - 95, "alive_at": NOW - 40}
    run = [{"label": "Searching for analogies", "state": "running", "seconds": 111.0}]
    page = run_states(tmp_path, lambda b: [picked(b, 1, run, entries=[{**YOU, "at": NOW - 100}], turn=turn)]).js("await serve(1);")
    page.check(card("className"))
    page.check(card("querySelector('.what').textContent"))   # slow is a warning: the title, not the step
    page.check(TEXTS)
    assert page.run() == ["thinking warn", "Taking longer than usual", ["Cancel"]]


def test_a_collected_question_the_server_calls_stalled_says_the_session_went_quiet(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1, stalled=True, entries=[{**YOU, "at": NOW - 230}],
                                                  turn={"entries": [{"id": 0, "state": "picked"}], "earlier": 0, "collected_at": NOW - 225, "alive_at": NOW - 200})])
    page.js("await serve(1);")
    page.check(card("querySelector('.what').textContent"))
    page.check(TEXTS)
    assert page.run() == ["Claude has gone quiet", ["Send again"]]


def test_the_clock_moves_each_second_without_rebuilding_the_row(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)]).js("await serve(1); window.t0 = $('thinking').querySelector('.what'); window.b0 = $('thinking').querySelector('button');")
    page.js("Date.now = () => %d; await advance(3000);" % ((NOW + 3) * 1000))
    page.check(card("querySelector('.clock').textContent"))
    page.check("[$('thinking').querySelector('.what') === window.t0, $('thinking').querySelector('button') === window.b0]")
    assert page.run() == ["1:15", [True, True]]


def test_the_clock_stops_when_the_answer_comes_and_the_row_goes(tmp_path):
    html, states = served(tmp_path, ["Here is the answer."])
    answered = states[1]
    asked = {**waiting(states[0], 1)}
    page = CallPage(html, [states[0], asked, {**answered, "v": "done", "entries": [YOU] + [{**e, "id": 1} for e in answered["entries"]]}])
    page.js(FREEZE + "await serve(1);")
    page.check("[$('thinking').hidden, waitActive()]")
    page.js("await serve(2);")
    page.check("[$('thinking').hidden, waitActive(), $('thinking').children.length, waitTick]")
    assert page.run() == [[False, True], [True, False, 0, 0]]


def test_cancel_before_pickup_asks_the_server_and_puts_the_words_back_in_the_box(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)]).js("await serve(1);")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/cancel'
      ? (sentTo.push([p, JSON.parse(o.body)]), respond({cancelled: true, how: 'withdrawn', entries: [0]})) : f0(p, o);
      """ + press("Cancel"))
    page.check("sentTo.filter(s => s[0] === '/api/cancel')")
    page.check("$('text').value")
    page.check(NOTE)
    assert page.run() == [[["/api/cancel", {"entry": 0}]], "How do vaccines work?",
                          [False, "Taken back. Your words are back in the box.", False]]


def test_cancel_after_pickup_says_cancelled_and_keeps_a_draft_already_in_the_box(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1); $('text').value = 'and the shots?'; $('text').dispatchEvent(new ShimEvent('input'));")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/cancel'
      ? (sentTo.push([p, JSON.parse(o.body)]), respond({cancelled: true, how: 'cancelled', entries: [0]})) : f0(p, o);
      """ + press("Cancel"))
    page.check("sentTo.filter(s => s[0] === '/api/cancel')")
    page.check("$('text').value")
    page.check("$('note').textContent")
    assert page.run() == [[["/api/cancel", {"entry": 0}]], "How do vaccines work?\nand the shots?", "Cancelled. Your words are back in the box."]


def test_a_cancel_that_comes_too_late_says_so_and_changes_no_box(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)]).js("await serve(1);")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/cancel' ? respond({cancelled: false}) : f0(p, o);
      """ + press("Cancel"))
    page.check("[$('text').value, $('note').textContent, $('note').classList.contains('warn')]")
    assert page.run() == [["", "Too late: Claude already answered it.", True]]


def test_send_again_replaces_the_first_question_and_leaves_the_draft_alone(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1, stalled=True)]).js("await serve(1); $('text').value = 'half a thought'; $('text').dispatchEvent(new ShimEvent('input'));")
    page.js(press("Send again"))
    page.check("sentTo.filter(s => s[0] === '/api/say')")
    page.check("[$('text').value, $('note').textContent]")
    assert page.run() == [[["/api/say", {"text": "How do vaccines work?", "replaces": 0}]], ["half a thought", "Sent again."]]


def test_a_draft_typed_while_a_question_is_in_flight_is_kept_across_polls(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1), picked(b, 2, activity=[{"label": "Reading", "state": "running", "seconds": 1}])])
    page.js("await serve(1); $('text').value = 'no wait, six year olds'; $('text').dispatchEvent(new ShimEvent('input'));")
    page.js("await serve(2);")  # a poll while Claude works leaves the draft
    page.check("[$('text').value, $('thinking').hidden, $('thinking').querySelector('.what').textContent]")
    assert page.run() == [["no wait, six year olds", False, "Reading"]]


def test_plain_send_while_a_question_is_in_flight_adds_to_it_without_a_replaces(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1); $('text').value = 'and also the shots'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click();")
    page.check("sentTo.filter(s => s[0] === '/api/say')")
    assert page.run() == [[["/api/say", {"text": "and also the shots"}]]]


def test_a_failed_send_keeps_the_draft_and_says_so(tmp_path):
    page = run_states(tmp_path, lambda b: [picked(b, 1)]).js("await serve(1);")
    page.js("""const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/say' ? {ok: false, status: 500, json: async () => ({})} : f0(p, o);
      $('text').value = 'will not go'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click();""")
    page.check("[$('text').value, $('note').textContent, $('note').classList.contains('warn')]")
    assert page.run() == [["will not go", "Not sent. Your draft is kept.", True]]


TWO = lambda b, **extra: waiting(b, 1, working=True, turn={"entries": [{"id": 0, "state": "picked"}, {"id": 1, "state": "sent"}], "earlier": 0, "collected_at": NOW - 60, "alive_at": NOW - 3},
                                 **{"entries": [YOU, {**YOU, "id": 1, "text": "and the shots?", "at": NOW - 10}], **extra})


def test_two_questions_in_flight_count_from_the_oldest_in_one_row(tmp_path):
    page = run_states(tmp_path, lambda b: [TWO(b)])
    page.js("await serve(1);")
    page.check(card("querySelector('.clock').textContent"))
    page.check("[$('thinking').querySelectorAll('.clock').length, waitModel().text]")
    assert page.run() == ["1:12", [1, "How do vaccines work?\nand the shots?"]]


def unpicked_two(b):
    return waiting(b, 1, entries=[YOU, {**YOU, "id": 1, "text": "and the shots?", "at": NOW - 10}],
                   turn={"entries": [{"id": 0, "state": "sent"}, {"id": 1, "state": "sent"}], "earlier": 0, "collected_at": None, "alive_at": None})


CANCEL_EACH = """const f0 = fetch; globalThis.fetch = async (p, o) => String(p) === '/api/cancel'
  ? (sentTo.push([p, JSON.parse(o.body)]), respond(OUTCOME[JSON.parse(o.body).entry])) : f0(p, o);"""


def test_cancel_withdraws_every_unpicked_question_and_puts_them_in_the_box_in_order(tmp_path):
    page = run_states(tmp_path, lambda b: [unpicked_two(b)]).js("await serve(1);")
    page.check(TEXTS)
    page.js("globalThis.OUTCOME = {0: {cancelled: true, how: 'withdrawn', entries: [0]}, 1: {cancelled: true, how: 'withdrawn', entries: [1]}};" + CANCEL_EACH
            + press("Cancel") + " await advance(10);")
    page.check("sentTo.filter(s => s[0] === '/api/cancel')")
    page.check("$('text').value")
    page.check("$('note').textContent")
    assert page.run() == [["Cancel"], [["/api/cancel", {"entry": 0}], ["/api/cancel", {"entry": 1}]],
                          "How do vaccines work?\nand the shots?", "Took back 2 questions. Your words are back in the box, in order."]


def test_cancel_says_how_many_came_back_when_claude_picked_one_up_meanwhile(tmp_path):
    page = run_states(tmp_path, lambda b: [unpicked_two(b)]).js("await serve(1);")
    page.js("globalThis.OUTCOME = {0: {cancelled: false}, 1: {cancelled: true, how: 'withdrawn', entries: [1]}};" + CANCEL_EACH
            + press("Cancel") + " await advance(10);")
    page.check("$('text').value")
    page.check("[$('note').textContent, $('note').classList.contains('warn')]")
    assert page.run() == ["and the shots?", ["Took back 1 of 2 questions. Claude has picked up the rest. Your words are back in the box.", True]]


def again_entries(**fields):
    """Two questions sent before pickup, then Send again: the server set both aside and holds the joined words as entry 2."""
    first, second = {**YOU, "superseded": True, "withdrawn": True}, {**YOU, "id": 1, "text": "and the shots?", "at": NOW - 40, "superseded": True, "withdrawn": True}
    return [first, second, {**YOU, "id": 2, "text": "How do vaccines work?\nand the shots?", "at": NOW - 9, "replaces": 0, **fields}]


def test_a_question_sent_again_counts_its_wait_from_the_first_send_and_a_typed_correction_from_its_own_time(tmp_path):
    turn = lambda i: {"entries": [{"id": i, "state": "sent"}], "earlier": 0, "collected_at": None, "alive_at": None}
    correction = [{**YOU, "superseded": True}, {**YOU, "id": 1, "text": "no, six year olds", "replaces": 0, "at": NOW - 4}]
    page = run_states(tmp_path, lambda b: [waiting(b, 1, entries=again_entries(), stalled=True, turn=turn(2)), waiting(b, 2, entries=correction, turn=turn(1))])
    page.js("await serve(1);")
    page.check(card("querySelector('.clock').textContent"))
    page.check(TEXTS)
    page.js("await serve(2);")
    page.check(card("querySelector('.clock').textContent"))
    assert page.run() == ["1:12", ["Send again"], "0:04"]


def test_without_a_turn_in_the_view_an_older_server_still_gets_a_row_for_the_newest_unanswered_question(tmp_path):
    def old(b):
        s = waiting(b, 1, working=True)
        del s["turn"]
        return [s]
    page = run_states(tmp_path, old).js("await serve(1);")
    page.check("[$('thinking').hidden, $('thinking').querySelector('.what').textContent]")
    assert page.run() == [[False, "Claude is working"]]


# ---- replaced answers -------------------------------------------------------------------

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


def test_an_answer_to_a_question_added_to_after_pickup_sits_below_the_addition_and_still_never_plays_or_queues(tmp_path):
    """The late answer 1 is entered after the correction that was collected as its own turn: below it in the list, so the
    older rule (a newer you-entry after the answer) cannot see it. The server tags it, and the tag alone keeps it silent."""
    html, states = served(tmp_path, ["The old answer."])
    you0, you1 = {**YOU, "text": "Plan me 14 days in Japan"}, {**YOU, "id": 1, "text": "no wait, only 10 days"}
    late = {**states[1]["entries"][0], "id": 2, "superseded": True, "superseded_kind": "addition"}
    page = CallPage(html, [states[0], {**states[1], "v": "late", "entries": [you0, you1, late]}])
    page.js("await serve(1);")
    page.check("[audio.paused, audio.getAttribute('src'), queued === null, current]")
    assert page.run() == [[True, None, True, None]]


def test_a_queued_answer_that_was_replaced_meanwhile_is_dropped_when_the_voice_ends(tmp_path):
    html, states = served(tmp_path, ["The first answer is here.", "The second answer is here."], seconds=3.0)
    again = {**states[2], "v": "rep", "entries": [states[2]["entries"][0], {**states[2]["entries"][1], "superseded": True}]}
    page = CallPage(html, states + [again], seconds=3.0).js("await serve(1); await playTo(1.0); await serve(2); await serve(3); await end(); await advance(50);")
    page.check("[audio.getAttribute('src'), queued]")
    assert page.run() == [["/c/test-call-id/audio/0000.wav", None]]


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
    assert page.run() == [["Claude is working", "Claude has gone quiet"]]


def test_a_question_sent_is_announced_once(tmp_path):
    page = run_states(tmp_path, lambda b: [waiting(b, 1)])
    page.js("window.said = []; announce = t => window.said.push(t); $('text').value = 'hello'; $('text').dispatchEvent(new ShimEvent('input')); $('sendtext').click(); await settle(); await serve(1);")
    page.check("window.said")
    assert page.run() == [["Your question was sent."]]


