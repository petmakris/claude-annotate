"""The call page's conversation (call-shell.js, call-stage.js): one chat list of questions and answers whose words light as
they are said, run under node on the real page (call_page.py)."""
import re
from pathlib import Path
from unittest.mock import patch

from call_page import STAGE, CallPage, _settle, needs_node
from helpers import AUTH, CALL, run as run_async, running_app

pytestmark = needs_node

STATIC = Path(__file__).resolve().parents[1] / "static"
TABLE = "| a | b |\n|---|---|\n| 1 | 2 |"
FIRST = f"[[show table | Heat pump or gas boiler]]{TABLE}[[/show]] A heat pump moves heat. It costs more to install. [[key: Install costs more]]"
SECOND = "Yes, though less so at minus ten. The numbers still hold."
THIRD = "Subsidies close much of the gap. Germany covers half."
ASKS = ["How does a heat pump work?", "Is it efficient in the cold?", "What do subsidies change?"]


def asked(tmp_path, answers=(FIRST, SECOND, THIRD), asks=ASKS, seconds=3.0, code=None):
    """A served call where each answer follows a question typed before it (the page's /api/state before any answer, and after each)."""
    import talk

    async def go():
        async with running_app(tmp_path, stage_url=STAGE, **({"code": code} if code else {})) as (client, call, fake):
            fake.seconds = seconds
            states = [await (await client.get("/api/state", headers=AUTH)).json()]
            for q, text in zip(asks, answers):
                call.add("you", q, typed=True)
                await call.answer(text)
                await _settle(call)
                states.append(await (await client.get("/api/state", headers=AUTH)).json())
            return await (await client.get(f"/c/{CALL}")).text(), states
    with patch.object(talk.speech, "voices", lambda wait=True: []):
        return run_async(go())




def test_progress_notes_the_session_posted_are_not_rows_of_the_conversation(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("view.entries.splice(1, 0, {id: 70, who: 'status', text: 'thinking it through', at: 1}, {id: 71, who: 'status', text: 'checking numbers', at: 2}); render();")
    page.check("[document.querySelectorAll('#convo .status, #convo .line').length, $('convo').textContent.includes('thinking it through'), "
               "$('convo').textContent.includes('checking numbers')]")
    assert page.run() == [[0, False, False]]


def test_a_new_answer_or_a_question_just_sent_brings_the_end_of_the_list_into_view(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(1); $('convo').scrollTop = 300; convoFollow = false;")
    page.js("await serve(2);").check("$('convo').scrollTop")
    page.js("$('convo').scrollTop = 250; served = {...STATES[2], v: 'q', entries: [...STATES[2].entries, {id: 99, who: 'you', text: 'and more?', at: 5}]}; await advance(900);")
    page.check("$('convo').scrollTop")
    assert page.run() == [0, 0]


def test_a_text_only_answer_leaves_the_board_in_front_where_it_is_and_the_reader_names_its_answer(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST + " [[show table | Two]]" + TABLE + "[[/show]] More.", SECOND), asks=ASKS[:2])
    reader = "[$('reader').className, document.querySelector('#reader.text #rtext .rhead')?.textContent ?? null]"
    page = CallPage(html, states, seconds=3.0).js("await serve(1); await end(); await advance(1600); fromStage({type: 'stage:shown', view: 'two'});")
    page.js("await serve(2); await playTo(1.0);").check(reader).js("await end(); await advance(1600);").check(reader)
    # with no board in front (the stage empty) the same answer is read in large type, under the label of its answer
    nobody = CallPage(html, states, seconds=3.0).js("await serve(2); await playTo(1.0);").check(reader)
    assert page.run() == [["reader strip", None], ["reader off", None]]
    assert nobody.run() == [["reader text", "Answer 2"]]


def test_the_stages_board_list_runs_in_the_order_its_counter_counts_and_says_no_newest_first():
    css = (Path(__file__).resolve().parents[2] / "stage" / "static" / "stage.css").read_text()
    js = (Path(__file__).resolve().parents[2] / "stage" / "static" / "stage.js").read_text()
    tabs = re.search(r"\.tabs\{([^}]*)\}", css).group(1)
    assert "flex-direction:column;" in tabs and "column-reverse" not in tabs
    assert '<h4>${wd("boards")}</h4>' in js and "newest first" not in js




TURNS = "[...document.querySelectorAll('#turns > .turn')].filter((t) => t.dataset.id).map((t) => [[...t.querySelectorAll('.q .qt')].map((q) => q.textContent), t.querySelector('.a .at').textContent])"


def test_the_conversation_is_one_list_of_turns_each_with_its_question_bubble_and_its_answer(tmp_path):
    html, states = asked(tmp_path)
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(3);").check(TURNS)
    page.check("[$('empty').hidden, document.querySelectorAll('#turns .a .w').length > 0, [...document.querySelectorAll('#turns .a')].map((a) => a.getAttribute('aria-label'))]")
    got = page.run()
    assert [t[0] for t in got[0]] == [[ASKS[0]], [ASKS[1]], [ASKS[2]]]
    assert got[0][2][1] == THIRD and got[0][1][1] == SECOND
    assert got[1] == [True, True, ["Answer 1", "Answer 2", "Answer 3"]]


def test_a_tap_on_a_word_plays_its_answer_from_there_and_the_word_being_said_is_lit(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    lit = "[...document.querySelectorAll('#turns .w.now-word')].map((w) => w.textContent)"
    said = "document.querySelectorAll('#turns .w.said').length"
    page.js("globalThis.getSelection = () => ''; document.querySelectorAll('#turns .turn')[0].querySelectorAll('.w')[3].click(); await playTo(1.5);").check("[current.n, audio.currentTime > 0]")
    page.check(lit).check(said)
    got = page.run()
    assert got[0] == [1, True]
    assert len(got[1]) == 1 and got[2] >= 1


def test_an_answer_replaced_by_a_correction_is_tagged_with_a_play_button_that_plays_it_anyway(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("view.entries.find((e) => e.who === 'claude' && e.n === 1).superseded = true; render();")
    tag = "[...document.querySelectorAll('#turns .a .tag')].map((t) => [t.firstChild.textContent.trim(), t.querySelector('button')?.textContent ?? null])"
    page.check(tag)
    page.js("globalThis.asked = []; playAnyway = (e) => asked.push(e.n); document.querySelector('#turns .a .tag button').click();").check("asked")
    assert page.run() == [[["Replaced by your correction", "Play"]], [1]]


def test_an_answer_whose_speech_failed_says_so_in_a_tag_and_a_normal_one_has_none(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=ASKS[:2])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    page.js("Object.assign(view.entries.find((e) => e.who === 'claude' && e.n === 2), {speech: 'failed', speech_error: 'no voice'}); render();")
    page.check("[...document.querySelectorAll('#turns .a')].map((a) => a.querySelector('.tag')?.textContent ?? null)")
    assert page.run() == [[None, "Not read aloud: no voice"]]


def test_the_empty_conversation_gives_a_question_to_start_with(tmp_path):
    html, states = asked(tmp_path, answers=(), asks=())
    page = CallPage(html, states, autoplay=False).check("[$('empty').hidden, $('empty').textContent, $('turns').querySelectorAll('.a').length]")
    assert page.run() == [[False, "Nothing has been said yet.", 0]]


def test_the_player_is_one_button_a_position_and_a_time(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, seconds=4.0).js("await serve(1); await playTo(1.0);")
    page.js("audio.dispatchEvent(new ShimEvent('timeupdate'));").check("[$('playpause').getAttribute('aria-label'), $('seek').getAttribute('aria-valuetext'), $('time').textContent, $('player').hidden, audio.currentTime]")
    page.js("$('playpause').click();").check("[$('playpause').getAttribute('aria-label'), audio.paused]")
    assert page.run() == [["Pause", "0:01 / 0:04", "−0:03", False, 1], ["Play", True]]


def test_a_long_question_is_held_to_six_lines_and_opens_with_a_more_button(tmp_path):
    long_q = "Please compare these:\n1. the running cost\n2. the noise\n3. the install time\n4. the subsidy\n5. the warranty\n6. the space needed\nand tell me which one wins."
    html, states = asked(tmp_path, answers=(FIRST, SECOND), asks=(long_q, ASKS[1]))
    page = CallPage(html, states, autoplay=False, seconds=3.0).js("await serve(2);")
    q = "[...document.querySelectorAll('#turns .q')].map((b) => [b.querySelector('.qt').className, b.querySelector('.more')?.textContent ?? null])"
    page.check(q)
    page.js("document.querySelector('#turns .q .more').click();").check(q)
    got = page.run()
    assert got[0] == [["qt clamped", "Show all"], ["qt", None]]
    assert got[1][0][0] == "qt" and got[1][0][1] is not None
