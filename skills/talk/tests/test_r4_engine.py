"""Round 4 fixes of the reply parser and its boards (bulldozer bd1125): the nudges, the plain shown text, the
points that clip or name their board, a table with no rows."""
import json

from helpers import make_args, talk
from test_bars_graph import BARS, GRAPH, reply

TABLE = "[[show table | Costs]]| a | b |\\n|---|---|\\n| x | 1 |\\n| y | 2 |\\n[[/show]]".replace("\\n", "\n")


def split(tmp_path, text, code=None):
    call = talk.Call(make_args(code=code), "T", tmp_path / "out")
    shown = call.split_reply(text)
    return shown, call


def lines_file(tmp_path, n=6):
    code = tmp_path / "code"
    code.mkdir(exist_ok=True)
    (code / "a.py").write_text("".join(f"line{i} = {i}\n" for i in range(1, n + 1)))
    return code


# -- r2-engine-4 ---------------------------------------------------------------------------------

def test_a_board_after_a_lead_in_of_sentences_gets_a_nudge_and_one_claim_sentence_does_not(tmp_path):
    _, call = split(tmp_path, f"First thing. Second thing. Third thing. {TABLE} Then the rows.")
    nudge = [p for p in call.board.problems if "first board comes after" in p]
    assert nudge == ["the first board comes after 3 sentences: put it after at most 1 claim sentence, so the stage "
                     "opens on the first sentence and not after a lead-in"]
    assert len(call.board.items) == 1  # a nudge, never a refusal
    _, call = split(tmp_path, f"The costs are low. {TABLE} Then the rows.")
    assert call.board.problems == []
    _, call = split(tmp_path, f"{TABLE} Then the rows.")
    assert call.board.problems == []


# -- r2-engine-5 ---------------------------------------------------------------------------------

def test_markdown_is_taken_out_of_the_shown_text_and_never_out_of_a_board(tmp_path):
    code = lines_file(tmp_path)
    (code / "m.py").write_text("x = a * b * c\n")
    table = "[[show table | T]]| a | b |\n|---|---|\n| **x** | `1` |\n[[/show]]"
    text = ("It is **bold**, *soft* and `code` with a [link](http://x.mac/p) here. "
            f"{table}\n- first bullet\n- second bullet\n"
            "[[show code: m.py:1-1 | M]] And snake_case stays, 2 * 3 stays.")
    shown, call = split(tmp_path, text, code)
    assert shown == ("It is bold, soft and code with a link here.\nfirst bullet\nsecond bullet\n"
                     "And snake_case stays, 2 * 3 stays.")
    assert [p for p in call.board.problems if p.startswith("markdown in the answer")] == [
        "markdown in the answer (emphasis, backticks, bullets or link targets) was shown as plain text; the answer is "
        "spoken and captioned, so write plain sentences"]
    assert call.board.items[0]["body"].splitlines()[2] == "| **x** | `1` |"
    assert call.board.items[1]["lines"] == ["x = a * b * c"]
    plain = split(tmp_path, "Nothing to strip here.")[1]
    assert plain.board.problems == []


# -- r2-codeboards-3 -----------------------------------------------------------------------------

def test_a_point_at_a_page_says_so_and_a_partly_visible_range_is_clipped(tmp_path):
    code = lines_file(tmp_path)
    shown, call = split(tmp_path, "[[show page: https://x.mac/p | P]] The page. [[point: line 1]] Gone.", code)
    assert call.board.problems == ['point not shown: "P", the last board shown, is a page, which has no lines, rows or '
                                   'nodes to light']
    _, call = split(tmp_path, "[[show page: https://x.mac/p | P]] Hi. [[point P: row 1]] There.", code)
    assert call.board.problems == ['point not shown: "P" is a page, which has no lines, rows or nodes to light']
    # lines 3-5 are shown; the point asks for 4-9, so 4-5 are lit and the author is told
    call = talk.Call(make_args(code=code), "T", tmp_path / "out2")
    call.split_reply("[[show code: a.py:3-5 | A]] The lines. [[point: lines 4-9]] Most of them. [[point: lines 7-9]] None.")
    assert call.board.problems == ['point clipped to lines 4-5: lines 4-9 are partly outside lines 3-5 shown of "A"',
                                   'point not shown: lines 7-9 are outside lines 3-5 of "A"']
    frames = call.board.items[0]["scene"]["frames"]
    assert [f["focus"] for f in frames if f.get("focus")] == [["line:4", "line:5"]]


def test_an_unknown_flowchart_role_is_a_board_line(tmp_path):
    spec = {"nodes": [{"id": "a", "label": "Start", "role": "entry"}, {"id": "b", "label": "End", "role": "wizard"}],
            "edges": [{"from": "a", "to": "b"}]}
    _, call = split(tmp_path, f"Look. [[show flowchart | F]] {json.dumps(spec)} [[/show]] Done.")
    assert [i["kind"] for i in call.board.items] == ["flowchart"]
    assert [p for p in call.board.problems if "role" in p] == [
        "flowchart \"F\": unknown role 'wizard' on a node, drawn as plain code; the roles are call, code, decision, "
        "entry, error, success"]


# -- r3-engine-4 ---------------------------------------------------------------------------------

def test_a_point_that_cannot_be_read_at_a_bars_or_graph_board_names_its_forms(tmp_path):
    call, _ = reply(tmp_path, f"[[show bars | Costs]] {json.dumps(BARS)} [[/show]] Hear. [[point Costs: the biggest one]] There.")
    assert call.board.problems == ['point not shown: could not read "the biggest one"; "Costs" is a bars board, '
                                   'use bar ID, row N or rows A-B']
    call, _ = reply(tmp_path, f"[[show graph | Rebase]] {json.dumps(GRAPH)} [[/show]] Hear. [[point Rebase: the old work]] There.")
    assert call.board.problems == ['point not shown: could not read "the old work"; "Rebase" is a graph board, '
                                   'use node ID, before, after or both']
    assert "row N" not in " ".join(call.board.problems) and "column" not in " ".join(call.board.problems)


# -- r3-table-3 ----------------------------------------------------------------------------------

def test_a_table_with_a_header_and_no_rows_is_refused_by_name(tmp_path):
    body, notes = talk.check_table("Empty", "| a | b |\n|---|---|")
    assert body == "" and notes == ['table "Empty" not shown: it has a header but no body rows; add the rows the '
                                    'answer talks about, or say it in a sentence']
    shown, call = split(tmp_path, "Hi. [[show table | Empty]]| a | b |\n|---|---|\n[[/show]] Done.")
    assert call.board.items == []
    assert 'table "Empty" not shown: it has a header but no body rows; add the rows the answer talks about, or say it in a sentence' in call.board.problems
