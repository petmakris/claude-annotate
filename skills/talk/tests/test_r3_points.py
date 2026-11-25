"""Round 3 of the bulldozer on talk: a point at a sequence's outcome, at a node named by its label, after a table
written without a tag, and the separator row a table needs."""
import talk
from helpers import make_args

SEQ = ('[[show sequence | Flow]]{"actors": [{"id": "p", "label": "Page"}, {"id": "s", "label": "Server"}], "steps": ['
       '{"id": "a", "from": "p", "to": "s", "arrow": "request", "label": "go"}, '
       '{"id": "b", "from": "s", "to": "p", "arrow": "event", "label": "done"}], '
       '"outcome": {"title": "Done well", "text": "It worked"}}[[/show]]')
FLOW = ('[[show flowchart | G]]{"nodes": [{"id": "api", "label": "Gateway"}, {"id": "db", "label": "Database"}], '
        '"edges": [{"from": "api", "to": "db"}]}[[/show]]')
TABLE = "| Name | Cost |\n|---|---|\n| A | 1 |\n| B | 2 |\n"


def answer(tmp_path, text):
    call = talk.Call(make_args(code=None), "T", tmp_path / "out")
    shown = call.split_reply(text)
    return call, shown


def focus(call):
    return {i["view"]: [f["focus"] for f in i["scene"]["frames"]] for i in call.board.items if i.get("scene")}


def test_a_point_at_the_outcome_of_a_plain_sequence_lights_the_verdict(tmp_path):
    call, shown = answer(tmp_path, SEQ + " First. [[point: step a]] Then. [[point: outcome]] Finally.")
    assert call.board.problems == []
    assert focus(call) == {"flow": [[], ["step:a"], ["outcome:end"], []]}
    assert shown == "First. Then. Finally."


def test_a_point_at_a_node_named_by_its_label_lights_that_node(tmp_path):
    call, _ = answer(tmp_path, FLOW + " Start. [[point: node Gateway]] Then. [[point: node nothing]] End.")
    assert call.board.problems == ['point not shown: no node nothing in "G"']
    assert focus(call) == {"g": [[], ["node:api"], []]}


def test_points_after_a_table_written_without_a_tag_all_light_their_rows(tmp_path):
    call, shown = answer(tmp_path, "Look.\n\n" + TABLE + '\nFirst. [[point: row "B"]] Second. [[point: row "A"]] Third.')
    assert call.board.problems == ["table shown without a tag; wrap it in [[show table | title]] next time"]
    assert focus(call) == {"name-cost": [[], ["row#2"], ["row#1"], []]}
    assert shown == "Look.\n\nFirst. Second. Third."
    assert [(c["at"], c["kind"], c.get("n")) for c in call.reply_cues] == [(7, "front", None), (14, "frame", 1), (22, "frame", 2)]


def test_a_separator_row_with_the_wrong_cell_count_is_no_table_and_is_mended_with_a_board_line(tmp_path):
    bad = "| a | b | c |\n|---|---|\n| 1 | 2 | 3 |"
    assert talk.table_count(bad) == 0
    assert talk.table_count("| a | b |\n|---|---|\n| 1 | 2 |\n\n| c | d |\n|--|\n| 1 | 2 |") == 1
    body, notes = talk.check_table("T", bad)
    assert body == "| a | b | c |\n|---|---|---|\n| 1 | 2 | 3 |"
    assert notes == ['table "T" has a separator row of 2 cells under a header of 3, so it was not a table; the separator '
                     "was rewritten to 3 (write one --- per header cell)"]
    assert talk.table_count(body) == 1
