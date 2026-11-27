"""Round 1 of the bulldozer on the call page's conversation (call-shell.js): who each answer answers, and what a board entry carries
for the server. Run under node on the real page (call_page.py), like test_call_shell.py."""
from call_page import CallPage, needs_node
from test_call_shell import ASKS, FIRST, SECOND, asked


# ---- who each answer answers -----------------------------------------------------------------------------------------------

TURNS = ("const E = (id, who, extra = {}) => ({id, who, text: who + id, at: 1, ...extra});"
         "const rows = (list) => turnsOf(list).turns.map((t) => [t.a.id, t.q && t.q.id, t.also.map((x) => x.id)]);")


@needs_node
def test_a_replaced_answer_belongs_to_the_question_it_was_written_for_and_the_next_answer_to_the_correction(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST,), asks=ASKS[:1])
    page = CallPage(html, states, autoplay=False, seconds=3.0).js(TURNS)
    page.check("rows([E(0, 'you', {superseded: true}), E(1, 'you', {replaces: 0}), E(2, 'claude', {superseded: true, superseded_kind: 'correction'}), E(3, 'claude')])")
    page.check("rows([E(0, 'you'), E(1, 'you', {while_working: true}), E(2, 'claude', {superseded: true, superseded_kind: 'addition'}), E(3, 'claude')])")
    page.check("rows([E(0, 'you'), E(1, 'you'), E(2, 'claude')])")
    page.check("rows([E(0, 'you', {superseded: true}), E(1, 'you', {withdrawn: true, superseded: true}), E(2, 'you', {replaces: 1}), E(3, 'claude', {superseded: true, superseded_kind: 'correction'}), E(4, 'claude')])")
    page.check("rows([E(0, 'you'), E(1, 'claude'), E(2, 'claude')])")
    assert page.run() == [[[2, 0, []], [3, 1, []]], [[2, 0, []], [3, 1, []]], [[2, 1, [0]]], [[3, 0, []], [4, 2, []]], [[1, 0, []], [2, None, []]]]


# ---- r1-finder-5: what a board shows is searchable --------------------------------------------------------------------------------------------------

PASSES = ("[[show bars | Pass prices]]{\"title\": \"Pass prices\", \"unit\": \"EUR\", \"bars\": [{\"id\": \"d21\", \"label\": \"21-day pass\", \"value\": 45, \"note\": \"best value\"},"
          " {\"id\": \"d3\", \"label\": \"3-day pass\", \"value\": 18}]}[[/show]] The longer passes cost less a day.")


def test_a_board_entry_carries_the_words_its_board_shows(tmp_path):
    html, states = asked(tmp_path, answers=(FIRST, PASSES), asks=ASKS[:2])
    boards = {e["text"]: e["search"] for e in states[-1]["entries"] if e["who"] == "board"}
    assert boards == {"Heat pump or gas boiler": "a b 1 2", "Key points: +1": "Install costs more", "Pass prices": "Pass prices EUR 21-day pass 45 best value 3-day pass 18"}


def test_board_text_reads_each_kind_of_board_and_is_cut_at_a_word():
    import talk
    assert talk.board_text({"kind": "table", "body": "| Pass | Price |\n|---|---|\n| **21-day** | [€45](http://x) |"}) == "Pass Price 21-day €45"
    assert talk.board_text({"kind": "diagram", "body": "graph LR\n  A[Client] --> B[Server]"}) == "graph LR A[Client] --> B[Server]"
    assert talk.board_text({"kind": "scene", "body": "<div class='slide'><h1>Cost &amp; time</h1><script>x()</script></div>"}) == "Cost & time"
    assert talk.board_text({"kind": "code", "path": "a.py", "lines": ["x = 1", "y = 2"]}) == "a.py x = 1 y = 2"
    assert talk.board_text({"kind": "sequence", "visual": {"spec": {"actors": [{"id": "u", "label": "User"}], "steps": [{"id": "s1", "from": "u", "to": "u", "label": "Logs in", "tone": "blue"}]}}}) == "User Logs in"
    long = talk.board_text({"kind": "diagram", "body": "word " * 1000})
    assert len(long) <= talk.BOARD_TEXT_MAX and long.endswith("word")
