"""Where a flowchart's arrows run (skills/stage/static/route.js), run under node on hand-placed parts: no browser, no layout.
The router is pure, so the coordinates are exact."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROUTE = Path(__file__).resolve().parents[1] / "static" / "route.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

SCRIPT = """
import { routeEdges, routeProblems, rounded } from %(route)s;
const input = %(input)s;
const nodes = new Map(Object.entries(input.nodes));
const rank = new Map(Object.entries(input.rank));
const edges = input.edges.map(([from, to, kind], i) => ({ i, from, to, back: kind === "back", self: kind === "self" }));
const routes = routeEdges({ mode: input.mode, nodes, rank, edges, bounds: { width: 1100, tall: 700, side: 12 } });
const out = { pts: {}, problems: routeProblems(routes, nodes, edges), rounded: rounded([[0, 0], [40, 0], [40, 40]], 12) };
for (const [i, r] of routes) out.pts[i] = r.pts.map((p) => p.map(Math.round));
console.log(JSON.stringify(out));
"""


def run(**inp):
    if not shutil.which("node"):
        pytest.skip("node not installed")
    src = SCRIPT % {"route": json.dumps(ROUTE.as_uri()), "input": json.dumps(inp)}
    got = subprocess.run(["node", "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


def node(x, y, hw=65, hh=28):
    return {"x": x, "y": y, "hw": hw, "hh": hh}


# the change lifecycle of the owner's trial D: a row of five parts, then two outcomes, with ways back and a loop
LIFECYCLE = dict(
    mode="across",
    nodes={"a": node(100, 360), "b": node(270, 360), "c": node(440, 360), "d": node(610, 360), "e": node(780, 360),
           "f": node(950, 300), "g": node(950, 420)},
    rank={"a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5, "g": 5},
    edges=[["a", "b"], ["b", "c"], ["c", "d"], ["c", "a", "back"], ["d", "e"], ["e", "g"], ["e", "f"], ["f", "a", "back"],
           ["g", "b", "back"], ["f", "f", "self"], ["g", "e", "back"]],
)


@needs_node
def test_every_arrow_of_the_lifecycle_runs_round_the_parts_it_does_not_join_with_exact_corners():
    got = run(**LIFECYCLE)
    assert got["problems"] == []
    assert got["pts"]["0"] == [[165, 360], [200, 360]]
    assert got["pts"]["5"] == [[845, 368], [865, 368], [865, 420], [880, 420]]    # e to g: out, down its own lane, in
    assert got["pts"]["6"] == [[845, 352], [865, 352], [865, 300], [880, 300]]    # e to f: its lane is another height
    assert got["pts"]["3"] == [[419, 388], [419, 470], [79, 470], [79, 393]]      # a way back runs under the row
    assert got["pts"]["7"] == [[943, 272], [943, 250], [93, 250], [93, 327]]      # one with a part under its start runs over


@needs_node
def test_an_arrow_that_skips_a_column_runs_in_the_free_corridor_of_the_column_it_skips():
    # a to c across b, which stands on the straight line: the arrow goes over b, not through it
    got = run(mode="across", nodes={"a": node(100, 200), "b": node(300, 200), "c": node(500, 200), "x": node(300, 320)},
              rank={"a": 0, "b": 1, "c": 2, "x": 1}, edges=[["a", "c"], ["a", "b"], ["b", "c"]])
    assert got["problems"] == []
    assert got["pts"]["0"] == [[165, 192], [200, 192], [200, 165], [400, 165], [400, 192], [430, 192]]   # b's top edge is y 172
    assert got["pts"]["1"] == [[165, 208], [200, 208], [200, 200], [230, 200]]   # its neighbours keep their own ports


@needs_node
def test_two_arrows_into_one_part_and_two_through_one_corridor_never_lie_one_over_the_other():
    got = run(mode="across",
              nodes={"a": node(100, 300), "b": node(300, 100), "c": node(300, 500), "d": node(500, 300), "e": node(500, 100)},
              rank={"a": 0, "b": 1, "c": 1, "d": 2, "e": 2},
              edges=[["a", "d"], ["a", "e"], ["b", "d"], ["c", "d"], ["a", "b"], ["a", "c"]])
    assert got["problems"] == []
    # a to e and b to d both change height in the gap before the last column, and b to d runs out at y 100 where a to e
    # runs in at y 100: b to d takes the lane on the left (x 400), a to e the one on its right (x 412)
    assert got["pts"]["1"] == [[165, 276], [412, 276], [412, 100], [430, 100]]
    assert got["pts"]["2"] == [[365, 100], [400, 100], [400, 284], [430, 284]]


@needs_node
def test_a_flow_read_top_to_bottom_is_routed_with_the_same_rules():
    got = run(mode="down", nodes={"a": node(200, 80), "b": node(200, 220), "c": node(200, 360), "d": node(330, 220)},
              rank={"a": 0, "b": 1, "d": 1, "c": 2}, edges=[["a", "c"], ["a", "b"], ["b", "c"], ["c", "a", "back"], ["a", "d"], ["d", "c"]])
    assert got["problems"] == []
    assert got["pts"]["0"][0][1] > 80 and got["pts"]["0"][-1][1] < 360   # leaves a's foot, enters c's top


@needs_node
def test_a_corner_is_rounded_by_at_most_the_radius():
    assert run(**LIFECYCLE)["rounded"] == "M 0 0 L 28 0 Q 40 0 40 12 L 40 40"
