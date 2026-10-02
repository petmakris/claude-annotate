# ELK Layout Flavours and D2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `kind: "flowchart"` blocks ELK-quality layout with a reader-facing control that switches between several rendered layouts, and replace Mermaid with D2 for `kind: "diagram"`.

**Architecture:** ELK arranges, annotate still draws. A vendored `elk.bundled.js` is driven by a small Node script; Python measures the text, hands ELK node sizes, gets back coordinates and edge bend points, and `flowchart.py` paints exactly as it does now. Every viable layout variant is rendered at push time and stored in the block, and the client swaps between them with no round-trip. Separately, `kind: "diagram"` shells out to the `d2` binary instead of `mmdc`, and Mermaid is deleted.

**Tech Stack:** Python 3.9+ (stdlib only), Node (already required), vendored `elkjs`, the `d2` Go binary, vanilla JS + CSS in `skills/annotate/static/`.

**Spec:** `docs/superpowers/specs/2026-09-07-elk-layouts-and-d2-design.md`

## Global Constraints

- Python is **stdlib only**. No new pip dependencies anywhere in this plan.
- Tests run from the repository root with `python3 -m pytest skills -q` (this is what `.github/workflows/ci.yml` runs).
- `render_block` must **never raise**. Every rendering path failing has to end at the existing compact error-pill SVG, because one malformed block blanking `/raw` blanks the whole page.
- `base["svg"]` keeps holding a working default rendering in every case. `svgs` and `flavours` are additive; an un-updated client reads `svg` and works.
- The ELK path is **always** optional. If `node` is missing, the driver fails, or ELK throws, `layout()` falls back to the existing pure-Python implementation and returns empty routes.
- Do not add per-node comment targets. They were deliberately withdrawn (see `createBlockSection` in `static/script.js`) and this work does not reinstate them.
- Never `git add -A`. Stage the exact paths listed in each commit step.

---

### Task 1: Vendor elkjs and stand up the Node driver

**Files:**
- Create: `skills/annotate/diagrams/vendor/elk.bundled.js` (copied from npm, not hand-written)
- Create: `skills/annotate/diagrams/vendor/README.md`
- Create: `skills/annotate/diagrams/elk_driver.mjs`
- Create: `skills/annotate/diagrams/elk_layout.py`
- Test: `skills/annotate/tests/test_elk_driver.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `elk_layout.run_elk(graph: dict) -> dict` (raises `elk_layout.ElkUnavailable`), and `elk_layout.ElkUnavailable`.

- [ ] **Step 1: Fetch the vendored bundle**

```bash
cd /tmp && npm pack elkjs@0.9.3 && tar -xzf elkjs-0.9.3.tgz
cp /tmp/package/lib/elk.bundled.js \
   ~/projects/claude-annotate/skills/annotate/diagrams/vendor/elk.bundled.js
cp /tmp/package/LICENSE \
   ~/projects/claude-annotate/skills/annotate/diagrams/vendor/ELK_LICENSE.txt
```

Expected: `elk.bundled.js` is roughly 1.4 MB. This mirrors how the fonts are already vendored under `skills/annotate/static/fonts/`, licence file included.

- [ ] **Step 2: Write the vendor README**

Create `skills/annotate/diagrams/vendor/README.md`:

```markdown
# Vendored

`elk.bundled.js` — the Eclipse Layout Kernel, JavaScript build, from npm
`elkjs@0.9.3`. Vendored rather than depended on so the plugin installs with no
package step; `elk_driver.mjs` is the only thing that loads it.

Upgrade: `npm pack elkjs@<version>`, copy `package/lib/elk.bundled.js` here,
run `python3 -m pytest skills/annotate/tests/test_elk_driver.py -q`.

Licence: EPL-2.0, see `ELK_LICENSE.txt`.
```

- [ ] **Step 3: Write the failing test**

Create `skills/annotate/tests/test_elk_driver.py`:

```python
"""The Node side of ELK: a graph in, a laid-out graph out."""
import pytest

from skills.annotate.diagrams.elk_layout import ElkUnavailable, run_elk


def _graph():
    return {
        "id": "root",
        "layoutOptions": {"elk.algorithm": "layered", "elk.direction": "DOWN",
                          "elk.edgeRouting": "ORTHOGONAL"},
        "children": [
            {"id": "a", "width": 120.0, "height": 40.0},
            {"id": "b", "width": 120.0, "height": 40.0},
        ],
        "edges": [{"id": "e0", "sources": ["a"], "targets": ["b"]}],
    }


def test_run_elk_positions_nodes_and_routes_the_edge():
    out = run_elk(_graph())

    kids = {c["id"]: c for c in out["children"]}
    assert set(kids) == {"a", "b"}
    for c in kids.values():
        assert isinstance(c["x"], (int, float))
        assert isinstance(c["y"], (int, float))
    # DOWN means b sits below a
    assert kids["b"]["y"] > kids["a"]["y"]
    assert out["width"] > 0 and out["height"] > 0

    sections = out["edges"][0]["sections"]
    assert sections
    assert "startPoint" in sections[0] and "endPoint" in sections[0]


def test_run_elk_raises_elk_unavailable_on_a_malformed_graph():
    with pytest.raises(ElkUnavailable):
        run_elk({"id": "root", "children": [{"id": "a"}],
                 "edges": [{"id": "e0", "sources": ["ghost"], "targets": ["a"]}]})
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_elk_driver.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.diagrams.elk_layout'`

- [ ] **Step 5: Write the driver**

Create `skills/annotate/diagrams/elk_driver.mjs`:

```javascript
// Reads one ELK graph as JSON on stdin, writes the laid-out graph as JSON on
// stdout. A driver, not a renderer: no styling, no fonts, no knowledge of what
// the boxes contain. Python measures the text and sends sizes; this returns
// coordinates and edge bend points and nothing else.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
// elk.bundled.js is a UMD build; under createRequire it may hand back either
// the class or a module namespace with it on `default`.
const mod = require("./vendor/elk.bundled.js");
const ELK = mod.default || mod;

let graph;
try {
  graph = JSON.parse(readFileSync(0, "utf8"));
} catch (e) {
  process.stderr.write("bad graph json: " + (e && e.message));
  process.exit(1);
}

new ELK()
  .layout(graph)
  .then((out) => {
    process.stdout.write(JSON.stringify(out));
  })
  .catch((e) => {
    process.stderr.write(String((e && e.message) || e));
    process.exit(1);
  });
```

- [ ] **Step 6: Write the Python side**

Create `skills/annotate/diagrams/elk_layout.py`:

```python
"""ELK-backed geometry for the flowchart renderer.

`flowchart_layout` stays as the fallback and as the source of node sizing;
this module hands ELK the sizes that module measured and turns what comes back
into the same `positions` shape the renderer already reads, plus edge routes it
did not have before.

The subprocess and JSON I/O are isolated here, the way `mermaid.py` isolated
its own. Everything above this module stays pure.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

DRIVER = Path(__file__).with_name("elk_driver.mjs")

# ELK on a diagram-sized graph is ~130 ms. The ceiling is for a wedged node
# process, not for a slow layout.
LAYOUT_TIMEOUT_S = 20


class ElkUnavailable(RuntimeError):
    """Raised when node is missing, the driver fails, or ELK rejects the graph."""


def run_elk(graph: dict[str, Any]) -> dict[str, Any]:
    """Lay out one ELK graph. Raises ElkUnavailable on any failure."""
    node = shutil.which("node")
    if not node:
        raise ElkUnavailable("node not found on PATH")
    try:
        proc = subprocess.run(
            [node, str(DRIVER)],
            input=json.dumps(graph).encode("utf-8"),
            capture_output=True,
            timeout=LAYOUT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ElkUnavailable(f"elk driver did not run: {e}") from e
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()[:300]
        raise ElkUnavailable(detail or "elk driver failed")
    try:
        return json.loads(proc.stdout.decode("utf-8"))
    except ValueError as e:
        raise ElkUnavailable(f"elk driver returned non-JSON: {e}") from e
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_elk_driver.py -q`
Expected: 2 passed

- [ ] **Step 8: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/diagrams/vendor/ skills/annotate/diagrams/elk_driver.mjs \
        skills/annotate/diagrams/elk_layout.py \
        skills/annotate/tests/test_elk_driver.py
git commit -m "feat(annotate): vendor elkjs and add the node layout driver"
```

---

### Task 2: The house set and the viability gate

**Files:**
- Create: `skills/annotate/diagrams/flavours.py`
- Test: `skills/annotate/tests/test_flavours.py`

**Interfaces:**
- Consumes: nothing (this module is a leaf — it must not import `flowchart` or `elk_layout`, or the import graph cycles).
- Produces:
  - `flavours.HOUSE_SET: tuple[tuple[str, dict[str, str]], ...]`
  - `flavours.options(variant: str) -> dict[str, str]`
  - `flavours.pins_entries(variant: str) -> bool`
  - `flavours.viable(positions: dict, routes: dict, edge_count: int) -> bool`
  - `flavours.select(results: list[tuple[str, dict, float, float, dict]], edge_count: int) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_flavours.py`:

```python
"""House-set presets and the viability gate."""
from skills.annotate.diagrams import flavours


def _positions(boxes):
    """boxes: {id: (cx, cy, w, h)} -> the subset of the positions shape used here."""
    return {k: {"cx": cx, "cy": cy, "w": w, "h": h}
            for k, (cx, cy, w, h) in boxes.items()}


def test_house_set_order_is_layered_compact_wide_tree():
    assert [name for name, _ in flavours.HOUSE_SET] == \
        ["layered", "compact", "wide", "tree"]


def test_options_merge_base_with_the_variant():
    assert flavours.options("layered")["elk.algorithm"] == "layered"
    assert flavours.options("compact")["elk.spacing.nodeNode"] == "22"
    assert flavours.options("wide")["elk.direction"] == "RIGHT"
    assert flavours.options("tree")["elk.algorithm"] == "mrtree"


def test_pins_entries_only_for_the_layered_algorithm():
    assert flavours.pins_entries("layered") is True
    assert flavours.pins_entries("compact") is True
    assert flavours.pins_entries("wide") is True
    assert flavours.pins_entries("tree") is False


def test_viable_rejects_a_missing_route():
    pos = _positions({"a": (50, 20, 80, 30), "b": (50, 120, 80, 30)})
    assert flavours.viable(pos, {0: [(0, 0), (0, 10)]}, edge_count=1) is True
    assert flavours.viable(pos, {}, edge_count=1) is False


def test_viable_rejects_a_one_point_route():
    pos = _positions({"a": (50, 20, 80, 30)})
    assert flavours.viable(pos, {0: [(0, 0)]}, edge_count=1) is False


def test_viable_rejects_overlapping_nodes():
    pos = _positions({"a": (50, 20, 80, 30), "b": (55, 25, 80, 30)})
    assert flavours.viable(pos, {0: [(0, 0), (0, 10)]}, edge_count=1) is False


def test_select_keeps_layered_even_when_it_fails_the_gate():
    results = [("layered", _positions({"a": (5, 5, 80, 30), "b": (6, 6, 80, 30)}),
                100.0, 100.0, {})]
    assert flavours.select(results, edge_count=1) == ["layered"]


def test_select_drops_a_near_duplicate_canvas():
    pos = _positions({"a": (50, 20, 80, 30), "b": (50, 120, 80, 30)})
    routes = {0: [(0, 0), (0, 10)]}
    results = [
        ("layered", pos, 1000.0, 900.0, routes),
        ("compact", pos, 1020.0, 890.0, routes),   # within 5% on both axes
        ("wide", pos, 2100.0, 480.0, routes),
    ]
    assert flavours.select(results, edge_count=1) == ["layered", "wide"]


def test_select_drops_an_unroutable_variant():
    pos = _positions({"a": (50, 20, 80, 30), "b": (50, 120, 80, 30)})
    results = [
        ("layered", pos, 1000.0, 900.0, {0: [(0, 0), (0, 10)]}),
        ("tree", pos, 400.0, 300.0, {}),
    ]
    assert flavours.select(results, edge_count=1) == ["layered"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_flavours.py -q`
Expected: FAIL — `ImportError: cannot import name 'flavours'`

- [ ] **Step 3: Write the module**

Create `skills/annotate/diagrams/flavours.py`:

```python
"""The house set of layout variants, and the gate that decides which ship.

A reader learns one control, so every flowchart offers the same four names in
the same order — minus any that comes out unusable for that particular graph.
`layered` is never dropped: it is the default rendering and the thing
`base["svg"]` holds.

This module is a leaf. It knows ELK option strings and geometry, and nothing
about rendering, so `elk_layout` and `flowchart` can both import it.
"""
from __future__ import annotations

from typing import Any

# Shared by every layered variant. Values are strings because that is what ELK
# reads them as.
BASE: dict[str, str] = {
    "elk.algorithm": "layered",
    "elk.direction": "DOWN",
    "elk.edgeRouting": "ORTHOGONAL",
    "elk.layered.spacing.nodeNodeBetweenLayers": "62",
    "elk.spacing.nodeNode": "34",
    "elk.spacing.edgeNode": "22",
    "elk.spacing.edgeEdge": "14",
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
}

HOUSE_SET: tuple[tuple[str, dict[str, str]], ...] = (
    ("layered", {}),
    ("compact", {"elk.layered.spacing.nodeNodeBetweenLayers": "38",
                 "elk.spacing.nodeNode": "22"}),
    ("wide", {"elk.direction": "RIGHT"}),
    ("tree", {"elk.algorithm": "mrtree"}),
)

_BY_NAME = dict(HOUSE_SET)

# Two canvases this close on both axes are the same picture to a reader.
DUPLICATE_TOLERANCE = 0.05

DEFAULT = "layered"


def options(variant: str) -> dict[str, str]:
    """Full ELK option map for one house-set variant."""
    return {**BASE, **_BY_NAME.get(variant, {})}


def pins_entries(variant: str) -> bool:
    """Whether entry nodes should be pinned to the first layer.

    `elk.layered.layering.layerConstraint` belongs to the layered algorithm and
    is meaningless — and on some versions an error — anywhere else.
    """
    return options(variant).get("elk.algorithm") == "layered"


def _boxes(positions: dict[str, Any]) -> list[tuple[float, float, float, float]]:
    return [(p["cx"] - p["w"] / 2, p["cy"] - p["h"] / 2,
             p["cx"] + p["w"] / 2, p["cy"] + p["h"] / 2)
            for p in positions.values()]


def _overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def viable(positions: dict[str, Any], routes: dict[int, list], edge_count: int) -> bool:
    """True when this variant is fit to put in front of a reader.

    Two failures are worth naming because they are what the exotic algorithms
    actually do: `rectpacking` places boxes and routes no edges at all, and
    `stress` reaches its very small canvas by letting boxes overlap.
    """
    if len(routes) != edge_count:
        return False
    if any(len(pts) < 2 for pts in routes.values()):
        return False
    boxes = _boxes(positions)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if _overlap(a, b):
                return False
    return True


def _near(w: float, h: float, kw: float, kh: float) -> bool:
    return (abs(w - kw) <= kw * DUPLICATE_TOLERANCE
            and abs(h - kh) <= kh * DUPLICATE_TOLERANCE)


def select(results: list[tuple[str, dict, float, float, dict]],
           edge_count: int) -> list[str]:
    """Names to ship, in house-set order.

    `results` carries one entry per variant that laid out at all, as
    ``(name, positions, canvas_w, canvas_h, routes)``.
    """
    kept: list[tuple[str, float, float]] = []
    for name, positions, w, h, routes in results:
        if name == DEFAULT:
            kept.append((name, w, h))
            continue
        if not viable(positions, routes, edge_count):
            continue
        if any(_near(w, h, kw, kh) for _, kw, kh in kept):
            continue
        kept.append((name, w, h))
    return [name for name, _, _ in kept]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_flavours.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/diagrams/flavours.py skills/annotate/tests/test_flavours.py
git commit -m "feat(annotate): add the layout house set and its viability gate"
```

---

### Task 3: ELK-backed `layout()` with a mandatory fallback

**Files:**
- Modify: `skills/annotate/diagrams/elk_layout.py` (append; `run_elk` from Task 1 is unchanged)
- Test: `skills/annotate/tests/test_elk_layout.py`

**Interfaces:**
- Consumes: `elk_layout.run_elk`, `elk_layout.ElkUnavailable` (Task 1); `flavours.options`, `flavours.pins_entries` (Task 2); `flowchart_layout.layout`, `flowchart_layout.node_size`, `flowchart_layout.node_lines` (existing).
- Produces: `elk_layout.layout(nodes, edges, variant="layered") -> tuple[dict, float, float, dict[int, list[tuple[float, float]]]]`.

The `positions` value keeps exactly the keys `flowchart.py` already reads: `cx`, `cy`, `w`, `h`, `role`, `node`, `lines`, `layer`. `routes` maps the **index of the edge in `edges`** to a list of absolute `(x, y)` points.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_elk_layout.py`:

```python
"""ELK geometry, and the fallback that makes it optional."""
from unittest import mock

from skills.annotate.diagrams import elk_layout


def _graph():
    nodes = [
        {"id": "a", "role": "entry", "label": "start"},
        {"id": "b", "role": "code", "ref": "F:1", "method": "m()"},
        {"id": "c", "role": "success", "label": "done"},
    ]
    edges = [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "ok"}]
    return nodes, edges


def test_layout_returns_positions_canvas_and_routes():
    nodes, edges = _graph()
    positions, w, h, routes = elk_layout.layout(nodes, edges)

    assert set(positions) == {"a", "b", "c"}
    for p in positions.values():
        assert {"cx", "cy", "w", "h", "role", "node", "lines", "layer"} <= set(p)
        assert p["w"] > 0 and p["h"] > 0
    assert w > 0 and h > 0
    assert set(routes) == {0, 1}
    for pts in routes.values():
        assert len(pts) >= 2
        assert all(len(pt) == 2 for pt in pts)


def test_layout_puts_every_node_inside_the_canvas():
    nodes, edges = _graph()
    positions, w, h, _ = elk_layout.layout(nodes, edges)
    for p in positions.values():
        assert p["cx"] - p["w"] / 2 >= 0
        assert p["cy"] - p["h"] / 2 >= 0
        assert p["cx"] + p["w"] / 2 <= w
        assert p["cy"] + p["h"] / 2 <= h


def test_wide_variant_is_wider_than_it_is_tall_relative_to_layered():
    nodes, edges = _graph()
    _, dw, dh, _ = elk_layout.layout(nodes, edges, variant="layered")
    _, ww, wh, _ = elk_layout.layout(nodes, edges, variant="wide")
    assert ww / wh > dw / dh


def test_layout_falls_back_to_python_when_elk_is_unavailable():
    nodes, edges = _graph()
    with mock.patch.object(elk_layout, "run_elk",
                           side_effect=elk_layout.ElkUnavailable("no node")):
        positions, w, h, routes = elk_layout.layout(nodes, edges)
    assert set(positions) == {"a", "b", "c"}
    assert w > 0 and h > 0
    assert routes == {}


def test_layout_falls_back_when_elk_returns_nonsense():
    nodes, edges = _graph()
    with mock.patch.object(elk_layout, "run_elk", return_value={"children": []}):
        positions, w, h, routes = elk_layout.layout(nodes, edges)
    assert set(positions) == {"a", "b", "c"}
    assert routes == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_elk_layout.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'layout'`

- [ ] **Step 3: Append the layout function**

Append to `skills/annotate/diagrams/elk_layout.py`:

```python
from . import flavours
from .flowchart_layout import layout as _python_layout
from .flowchart_layout import node_lines, node_size

# Room around the drawing. ELK lays out from (0, 0); annotate's canvas has
# always carried a margin, and edge labels are placed after layout and clamped
# to the canvas, so they need somewhere to sit.
MARGIN = 24.0


def _build_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
                 variant: str) -> dict[str, Any]:
    pin = flavours.pins_entries(variant)
    children = []
    for n in nodes:
        w, h = node_size(n)
        child: dict[str, Any] = {"id": n["id"], "width": w, "height": h}
        if pin and n.get("role") == "entry":
            # The single most valuable option in the set: without it a layered
            # algorithm puts each entry point wherever crossings are cheapest,
            # and five starts read as noise.
            child["layoutOptions"] = {
                "elk.layered.layering.layerConstraint": "FIRST"}
        children.append(child)
    return {
        "id": "root",
        "layoutOptions": flavours.options(variant),
        "children": children,
        # Labels are NOT sent. flowchart.py places them itself, better than ELK
        # would, and only the layered algorithm places them at all.
        "edges": [{"id": f"e{i}", "sources": [e["from"]], "targets": [e["to"]]}
                  for i, e in enumerate(edges)],
    }


def _positions_from(out: dict[str, Any],
                    nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_id = {n["id"]: n for n in nodes}
    placed = {}
    for c in out.get("children") or []:
        node = by_id.get(c["id"])
        if node is None:
            continue
        w, h = float(c["width"]), float(c["height"])
        placed[c["id"]] = {
            "cx": float(c["x"]) + w / 2 + MARGIN,
            "cy": float(c["y"]) + h / 2 + MARGIN,
            "w": w, "h": h,
            "role": node.get("role"),
            "node": node,
            "lines": node_lines(node),
            # ELK does not expose its layering, and the renderer only reads
            # `layer` on the fallback path where routes are absent.
            "layer": 0,
        }
    return placed


def _routes_from(out: dict[str, Any]) -> dict[int, list[tuple[float, float]]]:
    routes: dict[int, list[tuple[float, float]]] = {}
    for e in out.get("edges") or []:
        try:
            idx = int(str(e["id"])[1:])
        except (KeyError, ValueError):
            continue
        pts: list[tuple[float, float]] = []
        for sec in e.get("sections") or []:
            pts.append((float(sec["startPoint"]["x"]) + MARGIN,
                        float(sec["startPoint"]["y"]) + MARGIN))
            for b in sec.get("bendPoints") or []:
                pts.append((float(b["x"]) + MARGIN, float(b["y"]) + MARGIN))
            pts.append((float(sec["endPoint"]["x"]) + MARGIN,
                        float(sec["endPoint"]["y"]) + MARGIN))
        if len(pts) >= 2:
            routes[idx] = pts
    return routes


def layout(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
           variant: str = flavours.DEFAULT):
    """Position every node, and route every edge when ELK could.

    Returns ``(positions, canvas_w, canvas_h, routes)``. On any failure — node
    missing, driver error, malformed reply — this falls back to the pure-Python
    layout and returns empty routes, so the renderer keeps working exactly as
    it did before ELK existed.
    """
    try:
        out = run_elk(_build_graph(nodes, edges, variant))
        positions = _positions_from(out, nodes)
        if len(positions) != len(nodes):
            raise ElkUnavailable("elk did not place every node")
        canvas_w = float(out["width"]) + 2 * MARGIN
        canvas_h = float(out["height"]) + 2 * MARGIN
        return positions, canvas_w, canvas_h, _routes_from(out)
    except (ElkUnavailable, KeyError, TypeError, ValueError):
        positions, canvas_w, canvas_h = _python_layout(nodes, edges)
        return positions, canvas_w, canvas_h, {}
```

Move the `from typing import Any` import already at the top of the file if the linter complains about ordering; do not duplicate it.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_elk_layout.py -q`
Expected: 5 passed

- [ ] **Step 5: Run the whole suite to prove nothing else moved**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills -q`
Expected: all pass. Nothing imports `elk_layout` yet, so this is a regression check only.

- [ ] **Step 6: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/diagrams/elk_layout.py skills/annotate/tests/test_elk_layout.py
git commit -m "feat(annotate): ELK-backed flowchart layout with a python fallback"
```

---

### Task 4: Render from ELK routes, and render every variant

**Files:**
- Modify: `skills/annotate/diagrams/flowchart.py:18` (import), `:278-306` (`render`)
- Test: `skills/annotate/tests/test_diagrams_flowchart.py` (append)

**Interfaces:**
- Consumes: `elk_layout.layout` (Task 3); `flavours.HOUSE_SET`, `flavours.select`, `flavours.DEFAULT` (Task 2).
- Produces:
  - `flowchart.render(spec, block_id, variant="layered") -> str` (the existing two-argument call still works)
  - `flowchart.render_variants(spec, block_id) -> tuple[dict[str, str], list[str]]` returning `(svgs, names)` where `names` is in house-set order and `names[0]` is always `"layered"`.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_diagrams_flowchart.py`:

```python
def test_render_accepts_a_variant_and_still_produces_svg():
    svg = render(_spec(), "section-1", variant="wide")
    assert svg.startswith("<svg")
    assert 'class="annotate-flow"' in svg


def test_render_variants_returns_layered_first():
    svgs, names = render_variants(_spec(), "section-1")
    assert names[0] == "layered"
    assert set(names) <= {"layered", "compact", "wide", "tree"}
    assert set(svgs) == set(names)
    for svg in svgs.values():
        assert svg.startswith("<svg")


def test_render_variants_are_actually_different_pictures():
    svgs, names = render_variants(_spec(), "section-1")
    if len(names) > 1:
        assert len(set(svgs.values())) == len(names)


def test_edge_labels_survive_the_elk_path():
    svg = render(_spec(), "section-1", variant="layered")
    assert "OFF" in svg
    assert "ON + doc missing" in svg
    assert svg.count('class="edge-label"') == 2
```

Update the import at the top of that file:

```python
from skills.annotate.diagrams.flowchart import (
    ValidationError, render, render_variants, validate,
)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_diagrams_flowchart.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_variants'`

- [ ] **Step 3: Change the import in `flowchart.py`**

Replace line 18:

```python
from .flowchart_layout import SIDE_GUTTER, layout
```

with:

```python
from . import flavours
from .elk_layout import layout
from .flowchart_layout import SIDE_GUTTER
```

- [ ] **Step 4: Add the end-trim helper**

Insert after `_sample_polyline` (after line 203):

```python
def _trim_end(points: list[tuple[float, float]],
              gap: float) -> list[tuple[float, float]]:
    """Pull the last point back along its segment so the arrowhead sits clear.

    ELK routes edge to node border; the marker is drawn at the path end, so
    without this the head overlaps the box the same way an untrimmed bezier
    would.
    """
    if len(points) < 2:
        return points
    (x0, y0), (x1, y1) = points[-2], points[-1]
    dx, dy = x1 - x0, y1 - y0
    dist = (dx * dx + dy * dy) ** 0.5
    if dist <= gap:
        return points
    t = (dist - gap) / dist
    return points[:-1] + [(x0 + dx * t, y0 + dy * t)]
```

- [ ] **Step 5: Rewrite `render` and add `render_variants`**

Replace the body of `render` (lines 278-306) with:

```python
def _draw(spec: dict[str, Any], block_id: str, positions: dict[str, Any],
          canvas_w: float, canvas_h: float,
          routes: dict[int, list[tuple[float, float]]]) -> str:
    """Turn one laid-out graph into SVG.

    Split out of `render` so `render_variants` can lay out each variant once
    and draw from the result, instead of laying out twice per variant.
    """
    nodes = spec["nodes"]
    edges = spec.get("edges") or []
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}" class="annotate-flow">',
        _defs(),
    ]
    # edges first (under nodes); labels last (over everything)
    obstacles = [_bbox(p) for p in positions.values()]
    labels: list[str] = []
    for i, e in enumerate(edges):
        pts = routes.get(i)
        if pts:
            pts = _trim_end(pts, ARROW_GAP)
            d = _rounded_polyline(pts, CORNER_R)
            samples = _sample_polyline(pts)
        else:
            src, dst = positions[e["from"]], positions[e["to"]]
            d, samples = _route(src, dst, canvas_w)
        parts.append(f'<path class="flow-edge" d="{d}" marker-end="url(#fc-arrow)"/>')
        label = e.get("label", "")
        if label:
            rect = _place_label(label, samples, obstacles, canvas_w)
            obstacles.append(rect)  # later labels avoid the ones already placed
            labels.append(_label_svg(label, rect))
    for n in nodes:
        parts.append(_node_svg(positions[n["id"]], block_id))
    parts.extend(labels)
    parts.append("</svg>")
    return "".join(parts)


def render(spec: dict[str, Any], block_id: str,
           variant: str = flavours.DEFAULT) -> str:
    """Render a validated flowchart spec to an SVG string with hit-target IDs."""
    validate(spec)
    nodes = spec["nodes"]
    edges = spec.get("edges") or []
    positions, canvas_w, canvas_h, routes = layout(nodes, edges, variant)
    return _draw(spec, block_id, positions, canvas_w, canvas_h, routes)


def render_variants(spec: dict[str, Any],
                    block_id: str) -> tuple[dict[str, str], list[str]]:
    """Render every house-set variant that is fit to ship.

    Returns ``(svgs, names)`` with names in house-set order; ``names[0]`` is
    always the default, so the caller can use it for ``base["svg"]``.
    """
    validate(spec)
    nodes = spec["nodes"]
    edges = spec.get("edges") or []

    laid: dict[str, tuple] = {}
    results: list[tuple[str, dict, float, float, dict]] = []
    for name, _ in flavours.HOUSE_SET:
        try:
            positions, w, h, routes = layout(nodes, edges, name)
        except Exception:
            continue
        laid[name] = (positions, w, h, routes)
        results.append((name, positions, w, h, routes))

    names = flavours.select(results, len(edges))
    svgs = {name: _draw(spec, block_id, *laid[name]) for name in names}
    return svgs, names
```

- [ ] **Step 6: Run the flowchart tests**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_diagrams_flowchart.py skills/annotate/tests/test_flowchart_geometry.py skills/annotate/tests/test_flowchart_layout.py -q`
Expected: all pass. If `test_flowchart_geometry.py` asserts an exact canvas size or an exact path string, it was written against the pure-Python layout — update the expected values to what ELK now produces and note in the commit message that the geometry goldens moved.

- [ ] **Step 7: Run the whole suite**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/diagrams/flowchart.py skills/annotate/tests/test_diagrams_flowchart.py
git commit -m "feat(annotate): draw flowchart edges from ELK routes and render every variant"
```

---

### Task 5: Ship the variants in the block body

**Files:**
- Modify: `skills/annotate/render.py:18` (import), `:71-112` (the `flowchart` branch)
- Test: `skills/annotate/tests/test_server_flowchart.py` (append)

**Interfaces:**
- Consumes: `flowchart.render_variants` (Task 4).
- Produces: block bodies carrying `svg` (unchanged), `svgs: dict[str, str]`, and `flavours: list[str]`.

- [ ] **Step 1: Write the failing test**

Append to `skills/annotate/tests/test_server_flowchart.py`:

```python
def test_flowchart_block_ships_variants_and_a_default():
    out = render_block(_blk())
    assert out["flavours"][0] == "layered"
    assert set(out["svgs"]) == set(out["flavours"])
    # the default rendering is exactly what an un-updated client reads
    assert out["svg"] == out["svgs"]["layered"]


def test_flowchart_error_pill_carries_no_variants():
    blk = _blk()
    blk["spec"]["edges"] = [{"from": "a", "to": "ghost"}]
    out = render_block(blk)
    assert "render failed" in out["svg"]
    assert "svgs" not in out
    assert "flavours" not in out
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_server_flowchart.py -q`
Expected: FAIL — `KeyError: 'flavours'`

- [ ] **Step 3: Change the import**

Replace line 18 of `skills/annotate/render.py`:

```python
from skills.annotate.diagrams.flowchart import render as render_flowchart
```

with:

```python
from skills.annotate.diagrams.flowchart import render_variants as render_flowchart_variants
```

- [ ] **Step 4: Rewrite the flowchart branch**

Inside the `elif kind == "flowchart":` branch, replace

```python
        try:
            if source_error:
                raise ValueError(source_error)
            svg = render_flowchart(spec, block_id=blk["id"])
        except Exception as e:
```

with

```python
        svgs: dict[str, str] = {}
        names: list[str] = []
        try:
            if source_error:
                raise ValueError(source_error)
            svgs, names = render_flowchart_variants(spec, block_id=blk["id"])
            svg = svgs[names[0]]
        except Exception as e:
            svgs, names = {}, []
```

Leave the rest of that `except` body — the compact error-pill SVG — exactly as
it is. The two added lines only make sure a failed render ships no control.

After the existing `base["spec"] = spec` / `base["svg"] = svg` pair in that branch, add:

```python
        # Additive: an un-updated client reads `svg` and is none the wiser.
        # A block whose variants all failed ships the error pill and no control.
        if len(names) > 1:
            base["svgs"] = svgs
            base["flavours"] = names
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_server_flowchart.py -q`
Expected: all pass.

Note: `test_flowchart_block_ships_variants_and_a_default` asserts `flavours[0]`, which requires more than one variant to survive on the two-node fixture. If only `layered` survives for that graph, the block ships no `flavours` key by design — in that case widen `_blk()` in the test file to the five-node fixture used in `test_diagrams_flowchart.py::_spec` so the wide variant differs enough to be kept.

- [ ] **Step 6: Run the whole suite**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/render.py skills/annotate/tests/test_server_flowchart.py
git commit -m "feat(annotate): ship flowchart layout variants in the block body"
```

---

### Task 6: The reader's control

**Files:**
- Modify: `skills/annotate/static/script.js` (`paintFlowchart`, around line 1201)
- Modify: `skills/annotate/static/diagram.css` (append)
- Modify: `skills/annotate/references/block-kinds/flowchart.md`
- Test: `skills/annotate/tests/test_smoke_flavour_control.py`

**Interfaces:**
- Consumes: block bodies carrying `svgs` and `flavours` (Task 5).
- Produces: no Python interface. A `.flow-flavours` control element inside `.block-content`.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_smoke_flavour_control.py`:

```python
"""Structural guards for the layout-flavour control.

Static assertion only, in the same spirit as test_smoke_maximize.py: what a
source read can see. The rules below are the ones whose violation is silent —
a control that paints before the SVG, a localStorage read outside try/catch, or
a control rendered for a block with a single layout.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = (REPO / "skills" / "annotate" / "static" / "script.js").read_text()
CSS = (REPO / "skills" / "annotate" / "static" / "diagram.css").read_text()


def test_paint_flowchart_builds_the_control():
    body = SCRIPT[SCRIPT.index("function paintFlowchart"):]
    body = body[:body.index("\n  }")]
    assert "flavours" in body
    assert "flow-flavours" in body


def test_control_is_skipped_for_a_single_layout():
    assert re.search(r"flavours\s*\|\|\s*\[\]", SCRIPT)
    assert "length > 1" in SCRIPT


def test_local_storage_access_is_guarded():
    idx = SCRIPT.index("annotate.flavour.")
    window = SCRIPT[max(0, idx - 900):idx + 900]
    assert "try {" in window and "catch" in window


def test_control_has_styles():
    assert ".flow-flavours" in CSS
    assert ".flow-flavours button" in CSS
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_smoke_flavour_control.py -q`
Expected: FAIL — `ValueError: substring not found`

- [ ] **Step 3: Rewrite `paintFlowchart`**

Replace the whole function (currently lines 1201-1207):

```javascript
  // A block that laid out cleanly in more than one way ships every rendering
  // and lets the reader pick. The choice is theirs alone: it lives in
  // localStorage, is never sent to the daemon, and never reaches another
  // viewer. Storage can throw outright in a private window or with site data
  // blocked, so every access is guarded and an unreadable store simply means
  // the block opens on its default.
  const FLAVOUR_KEY = "annotate.flavour.";

  function readFlavour(blockId) {
    try {
      return window.localStorage.getItem(FLAVOUR_KEY + blockId);
    } catch (e) {
      return null;
    }
  }

  function writeFlavour(blockId, name) {
    try {
      window.localStorage.setItem(FLAVOUR_KEY + blockId, name);
    } catch (e) {
      /* per-viewer convenience only — losing it costs nothing */
    }
  }

  function flavourLabel(name) {
    return name.charAt(0).toUpperCase() + name.slice(1);
  }

  // Paint a flowchart block: the server SVG, plus the source pane when the
  // block was authored as pflow, plus the layout control when it shipped more
  // than one rendering. Shared by create and update so an in-place refresh
  // cannot leave one without the others.
  function paintFlowchart(content, blk) {
    const names = blk.flavours || [];
    const svgs = blk.svgs || {};

    const paint = (name) => {
      // Trusted server output — deliberately bypasses sanitizeFreeHtml so the
      // class/data-* hit targets survive.
      content.innerHTML = (name && svgs[name]) || blk.svg || "";
      if (names.length > 1) content.prepend(buildFlavourControl(blk, paint, name));
      const source = renderPflowSource(blk);
      if (source) content.appendChild(source);
    };

    let chosen = names.length > 1 ? readFlavour(blk.id) : null;
    if (names.indexOf(chosen) === -1) chosen = names[0] || null;
    paint(chosen);
  }

  function buildFlavourControl(blk, paint, current) {
    const wrap = document.createElement("div");
    wrap.className = "flow-flavours";
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "Diagram layout");
    (blk.flavours || []).forEach((name) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = flavourLabel(name);
      b.dataset.flavour = name;
      if (name === current) b.setAttribute("aria-pressed", "true");
      else b.setAttribute("aria-pressed", "false");
      b.addEventListener("click", () => {
        writeFlavour(blk.id, name);
        paint(name);
      });
      wrap.appendChild(b);
    });
    return wrap;
  }
```

Leave `linkPflowHover` exactly as it is: it binds to `content`, not to the SVG, so it survives every repaint.

- [ ] **Step 4: Add the styles**

Append to `skills/annotate/static/diagram.css`:

```css
/* Layout-flavour control — one row of buttons above a flowchart that shipped
   more than one rendering. Sits inside .block-content so a repaint replaces it
   with the SVG it belongs to and the two can never disagree. */
.flow-flavours {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 10px;
}
.flow-flavours button {
  font: inherit;
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text-dim);
  background: none;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 11px;
  cursor: pointer;
}
.flow-flavours button:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.flow-flavours button:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.flow-flavours button[aria-pressed="true"] {
  color: var(--accent);
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_smoke_flavour_control.py -q`
Expected: 4 passed

- [ ] **Step 6: Document the flavours**

In `skills/annotate/references/block-kinds/flowchart.md`, add this section immediately after "### Size guidance":

```markdown
### Layout flavours

Every flowchart block is laid out four ways at push time and ships whichever
came out fit to read. The reader gets a row of buttons above the diagram and
picks; their choice is remembered in their own browser and reaches nobody else.

| name | what it is | when a reader wants it |
|---|---|---|
| `layered` | top-down, orthogonal edges, entry nodes pinned to the top rank | the default, and the one `base.svg` holds |
| `compact` | the same, tightened | a long diagram on a short screen |
| `wide` | left-to-right | a strip that sits above prose |
| `tree` | a tree layout | a graph that really is a tree |

You author nothing for this — there is no `flavours` key in the spec. A variant
is dropped automatically when it leaves an edge unrouted, overlaps two nodes,
or lands within 5% of a variant already kept, so a simple graph may offer two
buttons and a dense one four. `layered` is never dropped.

**The one thing you do author** is `role: "entry"`. Beyond its colour, it now
pins the node to the first layer, which is what stops several entry points
scattering across three ranks and reading as noise. Give every genuine starting
point that role.
```

Also, in the same file, delete the three "use Mermaid instead" pointers — the `kind: "diagram"` block is D2 from Task 7, so replace each mention of Mermaid with D2 and drop the sentence about Mermaid's `type:"flowchart"` being deprecated.

- [ ] **Step 7: Run the whole suite**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/static/script.js skills/annotate/static/diagram.css \
        skills/annotate/references/block-kinds/flowchart.md \
        skills/annotate/tests/test_smoke_flavour_control.py
git commit -m "feat(annotate): let the reader pick a flowchart's layout"
```

---

### Task 7: D2 replaces Mermaid

**Files:**
- Create: `skills/annotate/diagrams/d2.py`
- Create: `skills/annotate/tests/test_diagrams_d2.py`
- Delete: `skills/annotate/diagrams/mermaid.py`, `skills/annotate/tests/test_diagrams_mermaid.py`
- Modify: `skills/annotate/render.py:17` (import), `:113-134` (the `diagram` branch)
- Modify: `skills/annotate/references/block-kinds/diagram.md`, `skills/annotate/SKILL.md`, `README.md`, `skills/annotate/README.md`, `skills/annotate/references/handling-events.md`, `skills/annotate/static/script.js` (two comments), `skills/annotate/diagrams/text_metrics.py` (one comment), `skills/annotate/diagrams/flowchart.py` (one comment)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `d2.render(spec, block_id) -> str`, `d2.ValidationError`, `d2.RenderError`.

- [ ] **Step 1: Write the failing test**

Create `skills/annotate/tests/test_diagrams_d2.py`:

```python
"""D2-backed diagram renderer."""
import shutil

import pytest

from skills.annotate.diagrams.d2 import RenderError, ValidationError, render, validate

needs_d2 = pytest.mark.skipif(shutil.which("d2") is None,
                              reason="the d2 binary is not on PATH")


def test_validate_rejects_an_empty_source():
    with pytest.raises(ValidationError):
        validate({"source": "   "})
    with pytest.raises(ValidationError):
        validate({})


def test_validate_ignores_a_leftover_type_key():
    # `type` existed only to pick a Mermaid diagram family. An old blocks.json
    # still carrying it must render, not raise.
    validate({"type": "class", "source": "a -> b"})


@needs_d2
def test_render_produces_a_tagged_transparent_svg():
    svg = render({"source": "a -> b"}, "section-1")
    assert svg.startswith("<svg")
    assert "annotate-diagram" in svg
    assert 'fill="transparent"' in svg
    assert "<?xml" not in svg
    assert "<script" not in svg


@needs_d2
def test_render_carries_both_palettes():
    svg = render({"source": "a -> b"}, "section-1")
    assert "prefers-color-scheme" in svg


def test_render_raises_when_the_binary_is_missing(monkeypatch):
    monkeypatch.setattr("skills.annotate.diagrams.d2.shutil.which", lambda _: None)
    with pytest.raises(RenderError) as e:
        render({"source": "a -> b"}, "section-1")
    assert "brew install d2" in str(e.value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_diagrams_d2.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'skills.annotate.diagrams.d2'`

- [ ] **Step 3: Write the renderer**

Create `skills/annotate/diagrams/d2.py`:

```python
"""D2-backed diagram validator + server-side SVG renderer.

Renders a `kind: "diagram"` block's D2 source to SVG via the `d2` CLI, with
ELK as the layout engine. Replaces the Mermaid renderer, which produced
crossing edges on anything past a dozen nodes and put its node labels inside
`foreignObject`, so its SVG rendered blank text in anything that was not a
browser.

Like the module it replaces, this does subprocess and temp-file I/O because
layout is delegated to an external engine; that I/O is isolated entirely here.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any

# The d2 binary is a single Go process, no browser. A diagram-sized graph is
# under half a second; the ceiling is for a wedged process.
RENDER_TIMEOUT_S = 30

# Light and dark theme ids. `--dark-theme` makes d2 emit ONE svg carrying both
# palettes behind a prefers-color-scheme query, which is the closest an
# external renderer gets to the page's own theme handling.
THEME_LIGHT = 0     # Neutral Default
THEME_DARK = 200    # Dark Mauve

_XML_PROLOG = re.compile(r"^\s*<\?xml[^>]*\?>\s*")
_SCRIPT_TAG = re.compile(r"<script\b.*?</script\s*>", re.I | re.S)


class ValidationError(ValueError):
    """Raised when a diagram spec is structurally invalid."""


class RenderError(RuntimeError):
    """Raised when d2 is missing or fails to produce an SVG."""


def validate(spec: dict[str, Any]) -> None:
    """Raise ValidationError if the spec is malformed; otherwise return None.

    `type` is not read. It existed to pick a Mermaid diagram family and D2 has
    none — a spec still carrying it is rendered, not rejected, so an old
    blocks.json on disk does not become a hard error.
    """
    source = spec.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValidationError("diagram source must be a non-empty string")


def render(spec: dict[str, Any], block_id: str) -> str:
    """Render a validated spec to an SVG string.

    Raises ValidationError if the spec is malformed, RenderError if d2 is
    missing or fails. There is no fallback renderer by design: a silent
    downgrade to a worse engine is how the unreadable diagram got shipped in
    the first place.
    """
    validate(spec)

    d2 = shutil.which("d2")
    if not d2:
        raise RenderError("d2 not found on PATH — install it with: brew install d2")

    # Without this d2 paints the theme's own background rect across the whole
    # canvas, which lands as a coloured slab over the annotate card. Setting
    # the root fill makes it emit fill="transparent" instead.
    source = "style.fill: transparent\n\n" + spec["source"]

    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.d2")
        out_path = os.path.join(td, "out.svg")
        with open(in_path, "w", encoding="utf-8") as f:
            f.write(source)
        try:
            proc = subprocess.run(
                [d2, "--layout=elk", f"--theme={THEME_LIGHT}",
                 f"--dark-theme={THEME_DARK}", "--pad=20", in_path, out_path],
                capture_output=True,
                timeout=RENDER_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise RenderError(f"d2 did not run: {e}") from e
        if proc.returncode != 0 or not os.path.exists(out_path):
            detail = proc.stderr.decode("utf-8", "replace").strip()[:400]
            raise RenderError(detail or "d2 failed to produce an SVG")
        with open(out_path, "r", encoding="utf-8") as f:
            return _postprocess(f.read())


def _postprocess(svg: str) -> str:
    """Strip the XML prolog and tag the root <svg> with our CSS hook class.

    No per-render id is injected, unlike the Mermaid renderer: d2 already
    scopes its whole stylesheet under a per-render hash class and gives every
    marker a unique id, so two diagrams on one page cannot cross-apply.
    """
    svg = _XML_PROLOG.sub("", svg).strip()
    # Defence in depth: this SVG is injected as innerHTML.
    svg = _SCRIPT_TAG.sub("", svg)
    if re.search(r"""<svg\b[^>]*class=["'][^"']*\bannotate-diagram\b""", svg):
        return svg
    if re.search(r"""<svg\b[^>]*class=["']""", svg):
        return re.sub(r"""(<svg\b[^>]*class=["'])""",
                      r"\1annotate-diagram ", svg, count=1)
    return re.sub(r"<svg\b", '<svg class="annotate-diagram"', svg, count=1)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills/annotate/tests/test_diagrams_d2.py -q`
Expected: 5 passed (2 skipped if `d2` is not installed — install it with `brew install d2` and re-run so the render tests actually execute).

- [ ] **Step 5: Point `render.py` at D2 and delete Mermaid**

In `skills/annotate/render.py`, replace line 17:

```python
from skills.annotate.diagrams.mermaid import render as render_mermaid
```

with:

```python
from skills.annotate.diagrams.d2 import render as render_d2
```

In the `elif kind == "diagram":` branch replace `render_mermaid(spec, block_id=blk["id"])` with `render_d2(spec, block_id=blk["id"])`, and change the error-pill's `aria-label` from `"mermaid diagram failed to render"` to `"diagram failed to render"`.

Then:

```bash
cd ~/projects/claude-annotate
git rm skills/annotate/diagrams/mermaid.py skills/annotate/tests/test_diagrams_mermaid.py
```

- [ ] **Step 6: Sweep the remaining mentions**

Run this to find every one:

```bash
cd ~/projects/claude-annotate
grep -rni "mmdc\|mermaid" --include='*.py' --include='*.js' --include='*.md' . \
  | grep -v node_modules | grep -v docs/superpowers
```

Edit each hit:

- `skills/annotate/references/block-kinds/diagram.md` — rewrite. Replace everything from the "## When a Mermaid diagram is the right block" heading down to (but not including) "## Rewriting a diagram block after a comment" with:

  ````markdown
  ## When a D2 diagram is the right block

  Emit a `kind: "diagram"` block when content is clearer seen than read AND it
  is one of these shapes (the cases a sequence diagram does NOT cover):

  - **architecture** — system/service architecture, how components connect.
  - **state** — state machines, lifecycle transitions.
  - **er** — entity-relationship / data-model shapes.
  - **class** — class hierarchies, static structure.

  The block carries D2 source; the server renders it to SVG with the `d2`
  binary, laid out by ELK, in one file carrying both a light and a dark palette
  so the picture follows the reader's browser theme.

  **Do NOT use a `kind: "diagram"` block for:**

  - Temporal actor↔actor flows — that's a `kind: "sequence"` block.
  - Branching/decision logic, process flows — that's a `kind: "flowchart"`
    block, which is also the only kind whose nodes carry jump-to-source links
    and whose reader can switch the layout.
  - Anything that fits in 1–2 sentences, or a short list that reads fine as
    prose.

  **One diagram per concept.** Frame it with a short prose block; the diagram
  must add clarity, not decorate.

  ## Authoring rules — keep the graph legible

  ELK will not rescue bad topology. Check each before emitting:

  - **No self-loops.** `a -> a` renders as a dangling teardrop. Put "this
    repeats" as a label on the meaningful transition instead.
  - **One dominant direction.** Declare it once at the top: `direction: down`
    for pipelines, `direction: right` for wide fan-outs.
  - **Group with containers, not name prefixes.** `strategy: { transmit; check }`
    draws a real boundary; `strategy_transmit` draws two unrelated boxes.
  - **Bound the size.** Aim for ≤ ~10 top-level nodes. Bigger, and it is two
    diagrams.
  - **Quote a label with punctuation.** `a: "prepare(): the write path"`.
    Break lines with `\n` inside the quotes.
  - **Fan out, don't loop back.** One producer feeding three consumers is three
    forward edges, never a reverse arrow.

  ## Block shape

  A `kind: "diagram"` block looks like this in `blocks.json`:

      {"id": "section-N", "kind": "diagram", "spec": {
        "title": "<short title>",
        "source": "<d2 source>"
      }}

  There is no `type` field. It existed to pick a Mermaid diagram family and D2
  has none — the shape lives in the source. A spec still carrying one is
  ignored rather than rejected.

  Commenting is whole-diagram only — there are no per-node hit targets, so
  comments arrive with `step_id: null` and are made from the card header.
  ````
- `skills/annotate/SKILL.md` — in the block-kind menu, change the `diagram` row's description from "Mermaid source → server renders SVG" to "D2 source, ELK layout → server renders SVG".
- `README.md` and `skills/annotate/README.md` — change "`mermaid.py` is the one renderer that shells out, to `mmdc`" to "`d2.py` is the one renderer that shells out, to the `d2` binary; `elk_layout.py` shells out to `node` for geometry".
- `skills/annotate/references/handling-events.md` — the one mention, in the diagram rewrite contract: drop the word Mermaid, the contract itself is unchanged.
- `skills/annotate/static/script.js` — two comments naming "Mermaid's inline `<style>`"; change to "D2's inline `<style>`". The behaviour is identical: both bypass `sanitizeFreeHtml` for the same reason.
- `skills/annotate/diagrams/text_metrics.py` and `skills/annotate/diagrams/flowchart.py` — one comment each saying "No Mermaid, no external process". `flowchart.py` now does use an external process for geometry, so make that comment read "Geometry comes from `elk_layout`, which shells out to node; the drawing here is pure."

- [ ] **Step 7: Run the whole suite**

Run: `cd ~/projects/claude-annotate && python3 -m pytest skills -q`
Expected: all pass. `test_skill_structure.py` may assert the set of files under `diagrams/` or the block-kind menu rows — update its expectations to include `d2.py`, `elk_layout.py`, `flavours.py`, `elk_driver.mjs` and `vendor/`, and to drop `mermaid.py`.

- [ ] **Step 8: Verify by hand, end to end**

```bash
cd ~/projects/claude-annotate
cat > /tmp/blocks.json <<'JSON'
{"response_id": "resp-1", "title": "D2 and flavours smoke",
 "blocks": [
   {"id": "section-1", "kind": "diagram", "title": "A D2 diagram",
    "spec": {"source": "a: OrdersSyncService\nb: OrdersSendStrategy\nc: OrdersSyncClient\na -> b: send\nb -> c"}},
   {"id": "section-2", "kind": "flowchart", "title": "A flowchart with layouts",
    "spec": {"nodes": [{"id": "a", "role": "entry", "label": "Proposal agreed"},
                        {"id": "b", "role": "entry", "label": "SEND_ORDERS"},
                        {"id": "c", "role": "code", "label": "OrdersSyncService", "ref": "OrdersSyncService:35"},
                        {"id": "d", "role": "decision", "label": "anything to send?"},
                        {"id": "e", "role": "success", "label": "sent"}],
              "edges": [{"from": "a", "to": "c"}, {"from": "b", "to": "c"},
                        {"from": "c", "to": "d"}, {"from": "d", "to": "e", "label": "yes"}]}}
 ]}
JSON
PYTHONPATH=. python3 -m skills.annotate.push --blocks /tmp/blocks.json --cwd "$PWD" \
  --title "D2 and flavours smoke" --eval
```

Open the printed URL. Expected: the D2 block renders with no coloured background slab behind it and follows your browser's dark mode; the flowchart block shows a row of layout buttons, clicking one swaps the picture instantly, and reloading the page keeps the one you picked.

- [ ] **Step 9: Commit**

```bash
cd ~/projects/claude-annotate
git add skills/annotate/diagrams/d2.py skills/annotate/tests/test_diagrams_d2.py \
        skills/annotate/render.py skills/annotate/SKILL.md \
        skills/annotate/references/block-kinds/diagram.md \
        skills/annotate/references/handling-events.md \
        skills/annotate/static/script.js skills/annotate/diagrams/text_metrics.py \
        skills/annotate/diagrams/flowchart.py \
        README.md skills/annotate/README.md
git commit -m "feat(annotate)!: render diagram blocks with D2, remove Mermaid

kind:\"diagram\" now shells out to the d2 binary with ELK layout and a
light/dark theme pair instead of mmdc. spec.type is no longer read; a spec
still carrying it renders rather than raising. Pages already published are
unaffected — their SVG was stored at push time."
```

---

## Notes for the executor

**Published pages are not at risk.** `render.py` renders at push time and the daemon stores the SVG opaquely, so every page already published keeps rendering. Removing Mermaid only affects a block that is pushed again, where the source gets rewritten as D2 anyway. There is no migration.

**If `test_flowchart_geometry.py` fails in Task 4**, read it before changing it. Assertions about *relationships* (b below a, nothing overlapping, labels inside the canvas) are the real contract and must still hold; assertions about exact pixel values were goldens against the pure-Python layout and are expected to move.

**Do not reinstate per-node comments.** If a node click opens a composer, something has gone wrong — see the long comment in `createBlockSection` for why that was withdrawn.
