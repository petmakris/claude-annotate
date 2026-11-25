"""Where a flowchart's arrow labels sit (skills/stage/static/map_labels.js), run under node on hand-placed parts and the
router's own routes: no browser, no layout. A state machine of six states and eight arrows, every label's rectangle
measured against every part, every other label and every other arrow."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

SCRIPT = """
import { routeEdges } from %(route)s;
import { placeEdgeLabels } from %(labels)s;
const input = %(input)s;
const nodes = new Map(Object.entries(input.nodes));
const rank = new Map(Object.entries(input.rank));
const edges = input.edges.map(([from, to, kind], i) => ({ i, from, to, back: kind === "back", self: kind === "self" }));
const routes = routeEdges({ mode: "across", nodes, rank, edges, bounds: { width: 1300, tall: 600, side: 12 } });
const labels = input.labels.map(([i, w]) => ({ i, pts: routes.get(i).pts, spots: null, w, h: 21,
  end: routes.get(i).pts.at(-1), start: routes.get(i).pts[0] }));
const cards = [...nodes.values()].map((n) => [n.x - n.hw - 3, n.y - n.hh - 3, n.x + n.hw + 3, n.y + n.hh + 3]);
const got = placeEdgeLabels({ labels, cards, routes, width: 1300, side: 12, across: true });
const out = { rects: {}, pts: {} };
for (const [i, b] of got) out.rects[i] = b.rect.map(Math.round);
for (const [i, r] of routes) out.pts[i] = r.pts.map((p) => p.map(Math.round));
console.log(JSON.stringify(out));
"""


def run(**inp):
    src = SCRIPT % {"route": json.dumps((STATIC / "route.js").as_uri()), "labels": json.dumps((STATIC / "map_labels.js").as_uri()),
                    "input": json.dumps(inp)}
    got = subprocess.run(["node", "--input-type=module", "-e", src], capture_output=True, text=True, timeout=30)
    assert got.returncode == 0, got.stderr
    return json.loads(got.stdout)


def node(x, y, hw=65, hh=28):
    return {"x": x, "y": y, "hw": hw, "hh": hh}


# a call's states: idle, dialling, ringing, connected, on hold, ended; eight arrows, one of them a way back
STATES = dict(
    nodes={"idle": node(90, 300), "dial": node(300, 300), "ring": node(510, 300), "conn": node(720, 300), "hold": node(930, 300), "end": node(1140, 300)},
    rank={"idle": 0, "dial": 1, "ring": 2, "conn": 3, "hold": 4, "end": 5},
    edges=[["idle", "dial"], ["dial", "ring"], ["ring", "conn"], ["conn", "hold"], ["hold", "conn", "back"], ["conn", "end"], ["hold", "end"], ["ring", "end"]],
    labels=[[0, 34], [1, 36], [2, 62], [3, 36], [4, 52], [5, 62], [6, 62], [7, 62]],
)


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def cut(r, a, b):
    return min(a[0], b[0]) < r[2] and max(a[0], b[0]) > r[0] and min(a[1], b[1]) < r[3] and max(a[1], b[1]) > r[1]


@needs_node
def test_eight_labels_of_a_six_state_machine_each_sit_clear_of_every_part_label_and_other_arrow():
    got = run(**STATES)
    rects = {int(i): r for i, r in got["rects"].items()}
    assert sorted(rects) == list(range(8))
    assert got["rects"] == {"0": [176, 290, 210, 311], "1": [385, 290, 421, 311], "2": [564, 240, 626, 261], "3": [809, 267, 845, 288],
                            "4": [757, 340, 809, 361], "5": [940, 347, 1002, 368], "6": [1002, 249, 1064, 270], "7": [859, 356, 921, 377]}
    for i, r in rects.items():
        for name, n in STATES["nodes"].items():
            assert not overlap(r, [n["x"] - n["hw"], n["y"] - n["hh"], n["x"] + n["hw"], n["y"] + n["hh"]]), (i, "on part", name)
        for j, q in rects.items():
            assert i == j or not overlap(r, q), (i, "on label", j)
        for j, pts in got["pts"].items():
            if int(j) != i:
                for a, b in zip(pts, pts[1:]):
                    assert not cut(r, a, b), (i, "on arrow", j)
