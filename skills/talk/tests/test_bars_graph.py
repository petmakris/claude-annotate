"""The bars and graph boards through the reply parser: a tag draws one, a point lights a bar, a row range, a node or a frame,
a near miss is read as the nearest id with a `board:` line, and a miss names what the board has."""
import json
import re

import pytest
from helpers import make_args, stage_rule_breaks, talk

BARS = {"title": "A miss costs a hundred hits", "unit": "ns", "scale": "log",
        "bars": [{"id": "l1", "label": "L1 cache", "value": 1}, {"id": "l2", "label": "L2 cache", "value": 4},
                 {"id": "l3", "label": "L3 cache", "value": 15}, {"id": "ram", "label": "Main memory", "value": 100}]}
GRAPH = {"title": "A rebase copies commits",
         "nodes": [{"id": "a", "label": "base", "lane": "main"}, {"id": "b", "label": "tip", "lane": "main"},
                   {"id": "d", "label": "old work", "lane": "feature", "state": "ghost"},
                   {"id": "d2", "label": "copied work", "lane": "after", "state": "new"}],
         "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "d"}, {"from": "b", "to": "d2"}]}
FLAT = {"nodes": [{"id": "a", "label": "base", "lane": "main"}, {"id": "b", "label": "tip", "lane": "main"}], "edges": [{"from": "a", "to": "b"}]}


def reply(tmp_path, text):
    """A reply through a call with no stage. Its board problems leave out the count of parts no sentence names,
    which these fixtures never try to name."""
    call = talk.Call(make_args(), "T", tmp_path / "out")
    shown = call.split_reply(text)
    call.board.problems[:] = [p for p in call.board.problems if "named by no sentence" not in p]
    return call, shown


def frames(call):
    item = next(i for i in call.board.items if i["kind"] in ("bars", "graph"))
    return item, item["scene"]["frames"]


def test_a_bars_tag_draws_a_keyed_svg_and_its_aliases_read_the_same(tmp_path):
    for tag in ("bars", "chart", "show: bars", "show chart"):
        call, _ = reply(tmp_path, f"Look. [[{'show ' if 'show' not in tag else ''}{tag} | Costs]] {json.dumps(BARS)} [[/show]] Done.")
        item = call.board.items[0]
        assert (item["kind"], call.board.problems) == ("bars", []), tag
        assert item["visual"]["tool"] == "bars" and 'data-key="bar:l1"' in item["visual"]["svg"] and "log scale" in item["visual"]["svg"]


def test_a_graph_tag_draws_both_frames_and_a_mermaid_graph_is_still_a_flowchart(tmp_path):
    call, _ = reply(tmp_path, f"Look. [[show graph | Rebase]] {json.dumps(GRAPH)} [[/show]] Done.")
    item = call.board.items[0]
    assert (item["kind"], call.board.problems) == ("graph", []) and item["visual"]["svg"].split('<g data-orient="tall">')[0].count("<g data-frame=") == 2
    call, _ = reply(tmp_path, "Look. [[show graph | Old]]\ngraph TD\n A-->B\n[[/show]] Done.")
    assert (call.board.items[0]["kind"], call.board.problems) == ("flowchart", [])  # `graph` was Mermaid's name before it was a board


@pytest.mark.parametrize("tag, kind, why", [
    ("bars", {**BARS, "scale": "log", "bars": [{"id": "z", "label": "Zero", "value": 0}]}, "bar 'z': value 0 is not above zero"),
    ("bars", {**BARS, "bars": [{"id": "s", "label": "Text", "value": "5 ms"}]}, "bar 's': value must be a number, got '5 ms'"),
    ("bars", {**BARS, "bars": [{"id": "m", "label": "Mixed", "value": 5, "unit": "ms"}]}, "bar 'm': unit 'ms' is not the board's unit 'ns'"),
    ("graph", {**GRAPH, "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}, "the edges go round a cycle: a -> b -> a"),
    ("graph", {**GRAPH, "edges": [{"from": "a", "to": "nope"}]}, "edge 0: unknown to node 'nope'"),
    ("graph", {**GRAPH, "nodes": GRAPH["nodes"] + [GRAPH["nodes"][0]]}, "duplicate node id: 'a'"),
])
def test_a_spec_that_breaks_a_rule_is_not_shown_and_a_board_line_names_the_id(tmp_path, tag, kind, why):
    call, _ = reply(tmp_path, f"Look. [[show {tag} | T]] {json.dumps(kind)} [[/show]] Done.")
    assert call.board.items == [] and len(call.board.problems) == 1
    assert why in call.board.problems[0] and call.board.problems[0].startswith(f'{tag} "T" not shown')


def test_a_point_lights_a_bar_by_its_id_its_label_or_a_range_of_rows(tmp_path):
    call, _ = reply(tmp_path, f"[[show bars | Costs]] {json.dumps(BARS)} [[/show]] Hear. [[point: bar l2]] One. [[point: rows 3-4]] Two. "
                              "[[point: row \"Main memory\"]] Three. [[point: bar ram]] Four.")
    _, fr = frames(call)
    # the bar no sentence or point reaches is never lit by order: it comes in with the rest frame
    assert call.board.problems == ['1 of 4 elements of "Costs" are never revealed; they come in with the rest frame']
    assert [f["focus"] for f in fr[1:-1]] == [["bar:l2"], ["bar:l3", "bar:ram"], ["bar:ram"], ["bar:ram"]]
    assert fr[-1]["show"] == ["bar:l1", "bar:l2", "bar:l3", "bar:ram"] and fr[-1]["focus"] == []  # the rest view shows every row


def test_a_bar_that_is_nearly_an_id_is_read_as_it_and_one_that_is_not_names_the_bars(tmp_path):
    call, _ = reply(tmp_path, f"[[show bars | Costs]] {json.dumps(BARS)} [[/show]] Hear. [[point: bar l22]] One. [[point: bar swap]] Two. [[point: rows 5-6]] Three.")
    assert call.board.problems == ['"bar l22" in "Costs" read as bar:l2',
                                   '"bar swap" in "Costs" matches nothing; the bars are l1, l2, l3, ram',
                                   '"Costs" has 4 bars, not rows 5-6; dropped',
                                   '3 of 4 elements of "Costs" are never revealed; they come in with the rest frame']
    _, fr = frames(call)
    assert [f["focus"] for f in fr[1:-1]] == [["bar:l2"]]  # a dropped point lights nothing, and no part is lit by order in its place


def test_a_point_on_a_graph_lights_a_node_or_a_frame_and_a_flat_graph_has_no_frames(tmp_path):
    call, _ = reply(tmp_path, f"[[show graph | Rebase]] {json.dumps(GRAPH)} [[/show]] Before it. [[point: before]] After it. [[point: after]] "
                              "Old one. [[point: node d]] All. [[point: both]] Typo. [[point: node d22]]")
    _, fr = frames(call)
    assert [f["focus"] for f in fr[1:-1]] == [["mode:before"], ["mode:after"], ["node:d"], ["mode:both"], ["node:d2"]]
    assert call.board.problems[0] == '"node d22" in "Rebase" read as node:d2'
    call, _ = reply(tmp_path, f"[[show graph | Flat]] {json.dumps(FLAT)} [[/show]] Hear. [[point: before]] Gone.")
    assert call.board.problems == ['point not shown: "Flat" has no before and after to point at; mark a node new, ghost or struck']


def test_a_point_of_the_wrong_kind_at_a_bars_or_graph_board_says_what_works(tmp_path):
    call, _ = reply(tmp_path, f"[[show bars | Costs]] {json.dumps(BARS)} [[/show]] Hear. [[point: node a]] One. [[point: before]] Two. [[point: box a]] Three.")
    assert call.board.problems == ['point not shown: "Costs" is a bars board; use bar ID, row N or rows A-B'] * 3
    call, _ = reply(tmp_path, f"[[show graph | Rebase]] {json.dumps(GRAPH)} [[/show]] Hear. [[point: bar a]] One. [[point: rows 1-2]] Two.")
    assert call.board.problems == ['point not shown: "Rebase" is a graph board; use node ID, before, after or both'] * 2


def test_verbs_reveal_bars_and_graphs_and_a_board_with_the_rules_the_stage_keeps(tmp_path):
    text = (f"[[show bars | Costs]] {json.dumps(BARS)} [[/show]] Four levels. [[next]] The first is the L1 cache. [[+ bar l2]] Then the L2 cache. [[next 2]] "
            f"And the rest. [[show graph | Rebase]] {json.dumps(GRAPH)} [[/show]] [[+ a, b]] Base and tip. [[+ d]] The old work. [[all]] Everything.")
    call, shown = reply(tmp_path, text)
    assert call.board.problems == [] and stage_rule_breaks(call, shown) == []
    bars = next(i for i in call.board.items if i["kind"] == "bars")["scene"]
    assert bars["start"] == "empty" and [f["show"] for f in bars["frames"][1:4]] == [["bar:l1"], ["bar:l1", "bar:l2"], ["bar:l1", "bar:l2", "bar:l3", "bar:ram"]]


def test_a_spec_is_told_apart_by_its_keys_so_a_wrong_tag_names_the_right_one():
    assert talk.spec_tool(json.dumps(BARS)) == "bars"
    assert talk.spec_tool(json.dumps(GRAPH)) == "graph"
    assert talk.spec_tool(json.dumps({"nodes": [{"id": "a", "role": "entry", "label": "A"}], "edges": []})) == "flowchart"


def test_l1_and_l2_are_told_apart_when_a_sentence_names_a_bar():
    from skills.stage import scene
    model = scene.bars_model(BARS)
    said = scene.said_parts(model, ["The L2 cache answers in four.", "Main memory takes a hundred."])
    assert said == {0: ["bar:l2"], 1: ["bar:ram"]}
    assert re.fullmatch(r"(?:\w+)", "x")
