"""The bars and graph boards on the stage page (stage.js under node, as test_stage_page.py runs it): which parts a frame shows
and lights, what a pointed frame does to the graph, and what a tap on a bar or a node asks about. Page logic only: nothing is
laid out here, so a phone's one-frame view is the harness's check (its shots at 390 px), not this file's."""
from __future__ import annotations

from skills.stage import scene
from skills.stage.tests.stage_page import StagePage, needs_node, visual
from skills.stage.tests.test_stage_page import SPOP, _scene

pytestmark = needs_node

BARS = {"title": "A miss costs a hundred hits", "unit": "ns", "scale": "log",
        "bars": [{"id": "l1", "label": "L1 cache", "value": 1}, {"id": "l2", "label": "L2 cache", "value": 4},
                 {"id": "ram", "label": "Main memory", "value": 100, "tone": "red"}]}
GRAPH = {"title": "A rebase copies commits",
         "nodes": [{"id": "a", "label": "base", "lane": "main"}, {"id": "b", "label": "tip", "lane": "main"},
                   {"id": "d", "label": "old work", "lane": "feature", "state": "ghost"},
                   {"id": "d2", "label": "copied work", "lane": "after", "state": "new"}],
         "edges": [{"from": "a", "to": "b"}, {"from": "a", "to": "d"}, {"from": "b", "to": "d2"}]}
SEEN = ("(n => { const b = pane(n).querySelector('.visual.vzmap'), svg = b.querySelector('svg.vz'), set = (s) => [...new Set(keys(b.querySelectorAll(s)))];"
        " return {cls: b.className, hidden: set('.k-hidden'), focus: set('.k-focus'), dim: b.classList.contains('k-dim'),"
        " mode: ['mode-before', 'mode-after'].filter((c) => svg.classList.contains(c))}; })")


def test_a_bars_board_comes_in_bar_by_bar_and_lights_the_one_pointed_at(tmp_path):
    built = _scene(scene.bars_model(BARS), [["next"], ["next"], ["focus bar ram"]], "Costs")
    page = StagePage(tmp_path).show("costs", visual("bars", BARS), title="Costs", extra={"scene": built}).open()
    for n in (1, 2, 3, 4):
        page.send({"type": "stage:frame", "view": "costs", "n": n, "animate": False}).check(SEEN + "('costs')")
    out = page.run()
    assert [o["hidden"] for o in out] == [["bar:l2", "bar:ram"], ["bar:ram"], [], []]
    assert [o["focus"] for o in out] == [[], [], ["bar:ram"], []]
    assert out[0]["cls"] == "visual vzmap vzbars" and out[2]["dim"] is True and out[3]["dim"] is False  # the rest view lights nothing


def test_a_graph_frame_pointed_at_dims_the_other_frame_and_lights_no_part(tmp_path):
    built = _scene(scene.graph_model(GRAPH), [["focus before"], ["focus after"], ["focus node d"], ["focus both"]], "Rebase")
    page = StagePage(tmp_path).show("rebase", visual("graph", GRAPH), title="Rebase", extra={"scene": built}).open()
    for n in (1, 2, 3, 4, 5):
        page.send({"type": "stage:frame", "view": "rebase", "n": n, "animate": False}).check(SEEN + "('rebase')")
    out = page.run()
    assert [o["mode"] for o in out] == [["mode-before"], ["mode-after"], [], [], []]
    # a frame is not a part: nothing else dims while one is pointed at, and a node lit does dim the rest
    assert [(o["focus"], o["dim"]) for o in out[:4]] == [([], False), ([], False), (["node:d"], True), ([], False)]
    assert out[0]["cls"] == "visual vzmap vzgraph"


def test_a_tap_on_a_bar_or_a_node_asks_about_it_by_its_label(tmp_path):
    built = _scene(scene.bars_model(BARS), [["next"]] * 3, "Costs")
    page = StagePage(tmp_path, embedded=True).show("costs", visual("bars", BARS), title="Costs", extra={
        "scene": built, "scenes": {"1": built}, "answer": 1}).open()
    page.send({"type": "stage:state", "front": "costs", "frames": {"costs": 3}, "keys": 0})
    page.js("pane('costs').querySelector('text[data-key=\"bar:ram\"]').click();").check(SPOP)
    assert page.run() == [[False, "Main memory", "", ["Ask about this", "Play from here"]]]
    built = _scene(scene.graph_model(GRAPH), [["next"]] * 4, "Rebase")
    page = StagePage(tmp_path, embedded=True).show("rebase", visual("graph", GRAPH), title="Rebase", extra={
        "scene": built, "scenes": {"1": built}, "answer": 1}).open()
    page.send({"type": "stage:state", "front": "rebase", "frames": {"rebase": 4}, "keys": 0})
    page.js("pane('rebase').querySelector('text[data-key=\"node:d2\"]').click();").check(SPOP)
    assert page.run() == [[False, "Copied work", "", ["Ask about this", "Play from here"]]]


# -- vote-10: a board is readable to a screen reader ---------------------------------------------------------------

OUTLINE_TABLE = {"type": "inline", "format": "table", "body": "| Hours | Mood |\n|---|---|\n| 1 | Calm |\n| 3 | Hungry |"}


def test_a_table_board_is_a_named_figure_with_a_caption_and_answers_the_call_page_with_its_rows(tmp_path):
    page = StagePage(tmp_path).show("hours", OUTLINE_TABLE, title="Hours after feeding").open()
    page.check("(() => { const b = pane('hours').querySelector('.md'); return [b.getAttribute('role'), b.getAttribute('aria-label'),"
               " b.querySelector('table caption').textContent, b.querySelector('table caption').className, b.querySelectorAll('th').length, b.querySelectorAll('td').length]; })()")
    page.send({"type": "stage:outline", "view": "hours"})
    out = page.run()
    assert out == [["figure", "Hours after feeding", "Hours after feeding", "sr-cap", 2, 4]]
    outline = [m for m in page.posted if m["type"] == "stage:outline"]
    assert outline == [{"type": "stage:outline", "view": "hours", "title": "Hours after feeding", "kind": "table",
                        "head": ["Hours", "Mood"], "lines": ["Hours: 1; Mood: Calm", "Hours: 3; Mood: Hungry"]}]


def test_the_part_being_said_carries_aria_current_and_the_outline_of_a_bars_board_lists_its_parts(tmp_path):
    built = _scene(scene.bars_model(BARS), [["next"], ["next"], ["focus bar ram"]], "Costs")
    page = StagePage(tmp_path).show("costs", visual("bars", BARS), title="Costs", extra={"scene": built}).open()
    cur = "(n => [...pane(n).querySelectorAll('[aria-current]')].map((e) => e.dataset.key).filter((k, i, a) => a.indexOf(k) === i))('costs')"
    for n in (1, 2, 3, 4):
        page.send({"type": "stage:frame", "view": "costs", "n": n, "animate": False}).check(cur)
    page.send({"type": "stage:outline", "view": "costs"})
    out = page.run()
    assert out == [["bar:l1"], ["bar:l2"], ["bar:ram"], []]
    outline = [m for m in page.posted if m["type"] == "stage:outline"][0]
    assert outline["kind"] == "board" and outline["title"] == "Costs" and outline["lines"] == ["L1 cache: 1 ns", "L2 cache: 4 ns", "Main memory: 100 ns"]
