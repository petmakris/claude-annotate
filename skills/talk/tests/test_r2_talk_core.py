"""Round 2 of the bulldozer on talk: the server's stalled warning, a finished stage, the call page's lead-in
and long words, the Greek question mark, refused boards, bare code paths, the outcome advice and the answer-shape
nudges."""
import asyncio
from unittest.mock import patch

import pytest

import talk
from call_page import CallPage, needs_node, served
from helpers import add_call, make_args, run, running_server
from live_turns import STALLED_AFTER, STALLED_OPEN_AFTER, TurnQueue
from skills.stage import scene as stage_scene


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# -- the server -----------------------------------------------------------------------------------------------

def test_the_state_stamp_moves_when_the_session_is_found_stalled(tmp_path):
    async def go():
        async with running_server() as (client, server, fake):
            call = add_call(server, tmp_path)
            clock = Clock()
            call.turns.clock = clock
            call.turns.offer("t1", [{"who": "you", "text": "hi"}])
            before, view_before = server.stamp(call)[0], call.view()
            clock.now += STALLED_AFTER + 1
            after, view_after = server.stamp(call)[0], call.view()
            return before, after, view_before["stalled"], view_after["stalled"]
    before, after, was, now = run(go())
    assert (was, now) == (False, True)
    assert before.split(".")[0] == after.split(".")[0] and before != after


def test_a_turn_collected_and_never_answered_with_no_doorbell_back_becomes_stalled():
    async def go():
        clock = Clock()
        q = TurnQueue(clock=clock)
        q.offer("t1", [{"who": "you", "text": "hi"}])
        await q.next(timeout=0.1)
        seen = [(q.working, q.stalled, q.listening)]
        clock.now += STALLED_OPEN_AFTER - 1
        seen.append((q.working, q.stalled, q.listening))
        clock.now += 2
        seen.append((q.working, q.stalled, q.listening))
        q.note_activity()  # a tool call: the session is alive
        seen.append((q.working, q.stalled, q.listening))
        # a doorbell back: listening, never stalled
        clock.now += STALLED_OPEN_AFTER + 1
        waiter = asyncio.ensure_future(q.next(timeout=5))
        await asyncio.sleep(0.05)
        seen.append((q.working, q.stalled, q.listening))
        q.ended = {"reason": "over"}
        q._changed.set()
        await waiter
        return seen
    assert run(go()) == [(True, False, False), (True, False, False), (True, True, False), (True, False, False),
                         (True, False, True)]


SID = "261125-100000-0123456789abcdef"


def test_a_stage_the_daemon_finished_is_reopened_and_the_board_shown_again():
    calls = []
    ended = talk.stage_mod.wc.SlugMismatch(f"stage session x in /c was ended (finished): reopen it with 'webcompanion unfinish --sid {SID}'")

    def show(cwd, name, source, **kw):
        calls.append(("show", name))
        if len([c for c in calls if c[0] == "show"]) == 1:
            raise ended
        return {"sid": SID}

    with patch.object(talk.stage_mod, "show", show), \
            patch.object(talk.stage_mod.wc, "request", lambda method, path, *a, **k: calls.append((method, path))):
        assert talk.show_reviving("/c", "v", {"type": "inline"}, slug=SID) == {"sid": SID}
    assert calls == [("show", "v"), ("POST", f"/s/{SID}/api/unfinish?kind=stage"), ("show", "v")]


def test_a_stage_that_cannot_be_reopened_or_another_mismatch_is_raised_as_it_was():
    other = talk.stage_mod.wc.SlugMismatch("stage session x is in /elsewhere (live), not in /c")

    def show(*a, **k):
        raise other

    with patch.object(talk.stage_mod, "show", show), pytest.raises(talk.stage_mod.wc.SlugMismatch) as got:
        talk.show_reviving("/c", "v", {}, slug=SID)
    assert got.value is other


def test_the_call_pages_poll_touches_its_stage_once_in_the_throttle(tmp_path):
    from helpers import AUTH, running_app

    async def go():
        touched = []
        async with running_app(tmp_path) as (client, call, fake):
            call.stage_sid = SID
            with patch.object(talk.stage_mod.wc, "get_items", lambda sid, kind: touched.append((sid, kind)) or {}):
                for _ in range(2):
                    await client.get("/api/state", headers=AUTH)
                call.stage_pool.submit(lambda: None).result(5)
                once = list(touched)
                call.stage_touched -= talk.STAGE_TOUCH_S + 1
                await client.get("/api/state", headers=AUTH)
                call.stage_pool.submit(lambda: None).result(5)
            return once, touched
    once, touched = run(go())
    assert once == [(SID, "stage")] and touched == [(SID, "stage")] * 2


# -- the call page ---------------------------------------------------------------------------------------------

READER = "[document.querySelector('#reader').className]"
TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"
LATE = "STATES[1].entries.at(-1).words = STATES[1].entries.at(-1).words.map((w) => [w[0], w[1], w[2] + 0.25, w[3] + 0.25]);"


@needs_node
def test_an_answer_that_opens_with_its_board_keeps_the_board_in_front_before_the_first_word(tmp_path):
    html, states = served(tmp_path, [f"[[show table | One]]{TABLE}[[/show]] One two three four five six."], seconds=4.0)
    page = CallPage(html, states, seconds=4.0).js(LATE + "await serve(1); await playTo(0.05);").check(READER)
    page.js("await playTo(0.5);").check(READER)
    assert page.run() == [["reader strip"], ["reader strip"]]


@needs_node
def test_a_word_wider_than_the_strip_is_brought_into_view_and_the_text_wraps_anywhere(tmp_path):
    html, states = served(tmp_path, ["Open the long path please."], seconds=2.0)
    page = CallPage(html, states, seconds=2.0)
    page.js("""
      const box = { scrollLeft: 0, scrollTop: 0, getBoundingClientRect: () => ({ left: 0, right: 100, top: 0, bottom: 60 }) };
      const word = { getBoundingClientRect: () => ({ left: 150, right: 450, top: 10, bottom: 30 }) };
      keepWordInStrip(box, word); globalThis.boxed = box;""")
    page.check("[boxed.scrollLeft, boxed.scrollTop]")
    assert page.run() == [[150 + (150 + 450) / 2 - (0 + 100) / 2 - 150, 0]]
    css = (talk.Path(talk.__file__).parent / "static" / "call.css").read_text()
    assert ".reader .rtext{" in css and "overflow-wrap:anywhere" in css.split(".reader .rtext{", 1)[1].split("}", 1)[0]


GREEK = ["Τι κάνεις; Καλά είμαι. Και εσύ;", "Τι κάνεις; Καλά είμαι.", "Wait; this is one clause. Yes.",
         "Ναι; yes it is. Μετά; ναι.", "Τέλος;"]


@needs_node
def test_the_page_and_the_server_split_the_greek_question_mark_alike(tmp_path):
    html, states = served(tmp_path, ["Hello there."])
    page = CallPage(html, states)
    for text in GREEK:
        page.check("(() => { const text = %s, words = [...text.matchAll(/\\S+/g)].map((m) => [m.index, m.index + m[0].length, 0, 0]);"
                   " return sentenceRuns({ text, words }).map(([f]) => words[f][0]).slice(1); })()" % __import__("json").dumps(text))
    page_starts = page.run()
    assert page_starts == [talk.sentence_starts(t) for t in GREEK]
    assert page_starts == [[11, 23], [11], [26], [16, 22], []]


# -- refused boards ------------------------------------------------------------------------------------------------

def answer(tmp_path, text, code=None):
    call = talk.Call(make_args(code=code), "T", tmp_path / "out")
    shown = call.split_reply(text)
    return call, shown


def test_a_point_after_a_refused_board_lights_nothing_and_says_so_once(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("".join(f"line {i}\n" for i in range(1, 11)))
    text = ("[[show code: a.py:1-5 | Good]] First. [[show code: nope.py:1-5 | Bad]] [[point: line 2]] Second. "
            "[[point Bad: line 3]] [[point: line 4]] Third.")
    call, _ = answer(tmp_path, text, code)
    assert call.board.problems == [
        "code not shown, no such file in the code folder: nope.py",
        'point not shown: the board "Bad" was not shown (see the board: line above), so there is nothing on the '
        "stage to point at; fix that board and show it again"]
    assert [c for c in call.board.cues if c["kind"] == "frame"] == []
    # shown again, the title points again
    call, _ = answer(tmp_path, "[[show code: nope.py:1-5 | Bad]] [[show code: a.py:1-5 | Bad]] [[point: line 2]] Said.", code)
    assert len([c for c in call.board.cues if c["kind"] == "frame"]) == 1


def test_a_verb_after_a_refused_board_is_dropped_the_same_way_and_the_next_reply_starts_clean(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "a.py").write_text("a\nb\nc\n")
    call, _ = answer(tmp_path, "[[show code: a.py:1-3 | Good]] One. [[show code: nope.py:1-3 | Bad]] Two. [[next]] Three.", code)
    assert [p for p in call.board.problems if "was not shown" in p] == [
        'next not shown: the board "Bad" was not shown (see the board: line above), so there is nothing on the stage '
        "to point at; fix that board and show it again"]
    before = len(call.board.problems)
    call.split_reply("[[point Good: line 2]] Next. [[point: line 3]] More.")
    assert call.board.problems[before:] == []


# -- bare code paths -----------------------------------------------------------------------------------------------

def test_a_bare_code_path_shows_the_file_from_line_one_and_notes_only_a_cut(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "short.py").write_text("".join(f"s{i}\n" for i in range(1, 8)))
    (code / "long.py").write_text("".join(f"l{i}\n" for i in range(1, 100)))
    call, _ = answer(tmp_path, "[[show code: short.py | Short]] Said.", code)
    item = call.board.items[0]
    assert (item["start"], len(item["lines"]), item["title"], call.board.problems) == (1, 7, "Short", [])
    call, _ = answer(tmp_path, "[[show code: long.py:3 | Long]] Said.", code)
    item = call.board.items[0]
    assert (item["start"], len(item["lines"]), item["title"]) == (1, 60, "Long (first 60 lines)")
    assert call.board.problems == ["code cut to lines 1-60 of long.py: at most 60 lines"]
    call, _ = answer(tmp_path, "[[show code: short.py:2-4 | Range]] Said.", code)
    assert (call.board.items[0]["start"], len(call.board.items[0]["lines"])) == (2, 3)


# -- the outcome advice ----------------------------------------------------------------------------------------------

def test_the_advice_for_an_unnamed_part_is_a_tag_that_resolves_to_that_part():
    model = stage_scene.sequence_model({
        "actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "steps": [{"id": "s1", "from": "a", "to": "b", "label": "Ask"}],
        "outcome": {"title": "Done well", "text": "It worked"}})
    assert talk.point_for("outcome:end") == "[[point: outcome]]"
    assert stage_scene.resolve(model, "outcome", "S")[0] == ["outcome:end"]
    text = talk.by_order_problem("S", model, ["outcome:end"], {}, ["One."], "Done well")
    assert text == ('1 of 2 parts of "S" are named by no sentence, so they came in by order, not where they are said. '
                    "Say each one's words in the sentence about it, or put its tag there, "
                    'end with a sentence that says "Done well" and carries [[point: outcome]]')
    for key in ("step:s1", "outcome:end"):
        tag = talk.point_for(key)[len("[[point: "):-2]
        assert stage_scene.resolve(model, tag, "S")[0] == [key]


# -- the shape of an answer --------------------------------------------------------------------------------------------

def test_an_answer_with_over_three_key_points_gets_one_board_line_and_keeps_every_key(tmp_path):
    keys = " ".join(f"Point {i} is made. [[key: Key {i}]]" for i in range(1, 5))
    call, _ = answer(tmp_path, keys)
    assert (talk.MAX_KEY_POINTS, len(call.keys)) == (3, 4)
    assert call.board.problems == ["4 key points in one answer: keep at most 3, the ones worth keeping, and say the rest"]
    call, _ = answer(tmp_path, " ".join(f"Point {i} is made. [[key: Key {i}]]" for i in range(1, 4)))
    assert call.board.problems == []


def test_a_board_title_over_five_words_gets_one_board_line_and_the_board_stays(tmp_path):
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    call, _ = answer(tmp_path, f"[[show table | A title of six whole words]]{table}[[/show]] Said it. "
                               f"[[show table | Five word title is fine]]{table}[[/show]] Again.")
    assert talk.MAX_TITLE_WORDS == 5
    assert call.board.problems == ['board title "A title of six whole words" is 6 words: keep a board title to 5 words, '
                                   "it names the picture and the voice says the rest"]
    assert [i["title"] for i in call.board.items] == ["A title of six whole words", "Five word title is fine"]
