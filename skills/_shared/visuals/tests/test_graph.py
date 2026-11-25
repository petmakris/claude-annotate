"""The graph board (graph_svg): a commit graph or a tree, before and after, and what a spec may say."""
import copy
import re

import pytest

from skills._shared.visuals import graph_svg

REBASE = {
    "title": "A rebase copies your commits onto the new tip",
    "lanes": ["main", "feature", "rebased"],
    "nodes": [{"id": "a", "label": "A", "lane": "main"}, {"id": "b", "label": "B", "lane": "main"},
              {"id": "c", "label": "C", "lane": "main", "sub": "new tip"},
              {"id": "d", "label": "D", "lane": "feature", "state": "ghost"}, {"id": "e", "label": "E", "lane": "feature", "state": "ghost"},
              {"id": "d2", "label": "D copy", "lane": "rebased", "state": "new"}, {"id": "e2", "label": "E copy", "lane": "rebased", "state": "new"}],
    "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "b", "to": "d"}, {"from": "d", "to": "e"},
              {"from": "c", "to": "d2"}, {"from": "d2", "to": "e2"}],
}

TREE = {"nodes": [{"id": "r", "label": "root"}, {"id": "x", "label": "left"}, {"id": "y", "label": "right"},
                  {"id": "x1", "label": "leaf 1"}, {"id": "x2", "label": "leaf 2"}],
        "edges": [{"from": "r", "to": "x"}, {"from": "r", "to": "y"}, {"from": "x", "to": "x1"}, {"from": "x", "to": "x2"}]}


def with_(**change):
    spec = copy.deepcopy(REBASE)
    spec.update(change)
    return spec


@pytest.mark.parametrize("spec, why", [
    (with_(nodes=REBASE["nodes"] + [{"id": "a", "label": "again", "lane": "main"}]), "duplicate node id: 'a'"),
    (with_(edges=[{"from": "a", "to": "zzz"}]), "edge 0: unknown to node 'zzz'; the nodes are a, b, c, d, e, d2, e2"),
    (with_(edges=[{"from": "ghost", "to": "a"}]), "edge 0: unknown from node 'ghost'"),
    (with_(edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "a"}]),
     "the edges go round a cycle: a -> b -> c -> a"),
    (with_(edges=[{"from": "a", "to": "a"}]), "node 'a' cannot be its own parent"),
    (with_(edges=[{"from": "a", "to": "b"}, {"from": "a", "to": "b"}]), "edge 'a' -> 'b' is given twice"),
    (with_(nodes=[{"id": "a", "label": "A", "lane": "main"}, {"id": "b", "label": "B"}], edges=[]), "node 'b': no lane"),
    (with_(nodes=[{"id": "a", "label": "A", "lane": "main", "state": "gone"}], edges=[]), "node 'a': unknown state 'gone'"),
    (with_(nodes=[{"id": "a", "label": "A", "lane": "other"}], edges=[]), "node 'a': lane 'other' is not in lanes"),
    (with_(nodes=[]), "graph needs at least 1 node"),
    (with_(nodes=[{"id": "a", "label": "A", "lane": "main", "state": "new"}], edges=[], lanes=None), "every node is new, so there is nothing in the before"),
    (with_(nodes=[{"id": f"n{i}", "label": "x", "lane": "main"} for i in range(41)], edges=[]), "graph has 41 nodes, at most 40"),
    (with_(nodes=[{"id": "a", "label": "", "lane": "main"}], edges=[]), "node 'a': label must be text"),
])
def test_a_spec_that_is_not_a_commit_graph_or_a_tree_is_refused_naming_the_id(spec, why):
    with pytest.raises(graph_svg.ValidationError) as err:
        graph_svg.validate(spec)
    assert why in str(err.value)


def test_a_node_sits_as_many_parents_deep_as_its_column_and_in_its_lane_row():
    geo = graph_svg.layout(REBASE)
    assert geo["layer"] == {"a": 0, "b": 1, "c": 2, "d": 2, "e": 3, "d2": 3, "e2": 4}
    assert geo["lane"] == {"a": 0, "b": 0, "c": 0, "d": 1, "e": 1, "d2": 2, "e2": 2}
    assert geo["names"] == ["main", "feature", "rebased"]


def test_a_tree_with_no_lanes_gets_a_row_per_leaf():
    geo = graph_svg.layout(TREE)
    assert geo["lane"] == {"r": 0, "x": 0, "y": 2, "x1": 0, "x2": 1}
    assert geo["layer"] == {"r": 0, "x": 1, "y": 1, "x1": 2, "x2": 2}
    assert not graph_svg.has_frames(TREE)
    assert 'data-frames="1"' in graph_svg.render(TREE, "t1") and "BEFORE" not in graph_svg.render(TREE, "t1")


def test_before_holds_what_was_there_and_after_what_is_there_now():
    assert graph_svg.frame_nodes(REBASE, "before") == ["a", "b", "c", "d", "e"]
    assert graph_svg.frame_nodes(REBASE, "after") == ["a", "b", "c", "d", "e", "d2", "e2"]
    svg = graph_svg.render(REBASE, "g1", keyed=True)
    before, after = (re.search(rf'<g data-frame="{f}">.*?</g>', svg, re.S)[0] for f in ("before", "after"))
    assert "D copy" not in before and "NEW" not in before and "D copy" in after and after.count("NEW") == 2


def test_a_ghost_is_faint_and_dashed_after_and_ordinary_before_a_struck_node_is_struck_after_only():
    spec = with_(nodes=[{"id": "a", "label": "A", "lane": "main"}, {"id": "b", "label": "B", "lane": "main", "state": "struck"}],
                 edges=[{"from": "a", "to": "b"}], lanes=None)
    svg = graph_svg.render(spec, "g2", keyed=True)
    before, after = (re.search(rf'<g data-frame="{f}">.*?</g>', svg, re.S)[0] for f in ("before", "after"))
    assert 'class="stk"' not in before and after.count('class="stk"') == 1
    assert 'class="ed faint"' not in before and 'class="ed faint"' in after
    ghost = graph_svg.render(REBASE, "g3", keyed=True)
    before, after = (re.search(rf'<g data-frame="{f}">.*?</g>', ghost, re.S)[0] for f in ("before", "after"))
    assert " gh" not in before and after.count("bx nd gh") == 2


def test_a_node_and_an_edge_carry_the_same_key_in_both_frames():
    svg = graph_svg.render(REBASE, "g4", keyed=True)
    assert svg.count('data-key="node:b"') == 2 * 2  # a rect and its label, in two frames
    assert svg.count('data-key="node:d2"') == 3     # new: the after frame only (its rect, its label and its NEW tag)
    assert svg.count('data-key="edge:a-&gt;b#0"') == 2
    assert graph_svg.node_keys(REBASE)[:3] == ["node:a", "node:b", "node:c"]
    assert graph_svg.edge_keys(REBASE)[:2] == ["edge:a->b#0", "edge:b->c#0"]
    assert "data-key" not in graph_svg.render(REBASE, "g4")


def test_the_svg_gives_each_frame_its_own_viewbox_for_a_phone_to_show_one_at_a_time():
    svg = graph_svg.render(REBASE, "g5")
    vb = {k: tuple(map(int, v.split())) for k, v in re.findall(r'data-vb-(\w+)="([^"]*)"', svg)}
    assert vb == {"before": (0, 64, 759, 200), "after": (0, 276, 759, 284), "both": (0, 0, 759, 560)}
    assert 'viewBox="0 0 759 560"' in svg and 'data-frames="2"' in svg


def test_labels_reach_the_page_only_as_text():
    spec = with_(title="<img src=x onerror=1>", nodes=[{"id": "a", "label": "<script>x</script>", "lane": "main"}], edges=[], lanes=None)
    svg = graph_svg.render(spec, "g6")
    assert "<script" not in svg and "<img" not in svg and "&lt;script&gt;" in svg
