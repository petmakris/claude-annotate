"""ELK-backed geometry for the flowchart renderer.

`flowchart_layout` stays as the fallback and as the source of node sizing;
this module hands ELK the sizes that module measured and turns what comes back
into the same `positions` shape the renderer already reads, plus edge routes it
did not have before.

The subprocess and JSON I/O are isolated here; everything above this module
stays pure.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import flavours, views
from .flowchart_layout import layout as _python_layout
from .flowchart_layout import node_lines, node_size

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
        payload = json.dumps(graph).encode("utf-8")
    except TypeError as e:
        raise ElkUnavailable(f"elk graph is not JSON-serializable: {e}") from e
    try:
        proc = subprocess.run(
            [node, str(DRIVER)],
            input=payload,
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


# Room around the drawing. ELK lays out from (0, 0); annotate's canvas has
# always carried a margin, and edge labels are placed after layout and clamped
# to the canvas, so they need somewhere to sit.
MARGIN = 24.0


def _build_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]],
                 variant: str) -> dict[str, Any]:
    pin = flavours.pins_entries(variant)
    # Bands are the authored role axis. ELK's own layering is derived from the
    # edges, so it carries whatever distortion the edge set has; a band does
    # not, which is what lets two views of one graph be compared side by side.
    band = views.bands({"nodes": nodes})
    children = []
    for n in nodes:
        w, h = node_size(n)
        child: dict[str, Any] = {"id": n["id"], "width": w, "height": h}
        if n["id"] in band:
            child["layoutOptions"] = {
                "elk.partitioning.partition": str(band[n["id"]])}
        elif pin and n.get("role") == "entry":
            # The single most valuable option in the set: without it a layered
            # algorithm puts each entry point wherever crossings are cheapest,
            # and five starts read as noise.
            child["layoutOptions"] = {
                "elk.layered.layering.layerConstraint": "FIRST"}
        children.append(child)
    root = dict(flavours.options(variant))
    if band:
        root["elk.partitioning.activate"] = "true"
    return {
        "id": "root",
        "layoutOptions": root,
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
        # Each edge is handled independently: a malformed section or point in
        # one edge's reply must not discard the node positions ELK already
        # computed for the whole graph, so the error is caught per-edge here
        # rather than bubbling up to layout()'s outer handler.
        try:
            idx = int(str(e["id"])[1:])
            pts: list[tuple[float, float]] = []
            for sec in e.get("sections") or []:
                pts.append((float(sec["startPoint"]["x"]) + MARGIN,
                            float(sec["startPoint"]["y"]) + MARGIN))
                for b in sec.get("bendPoints") or []:
                    pts.append((float(b["x"]) + MARGIN, float(b["y"]) + MARGIN))
                pts.append((float(sec["endPoint"]["x"]) + MARGIN,
                            float(sec["endPoint"]["y"]) + MARGIN))
        except (KeyError, ValueError, TypeError):
            continue
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
        if not isinstance(out, dict):
            raise ElkUnavailable("elk returned a non-object reply")
        positions = _positions_from(out, nodes)
        if len(positions) != len(nodes):
            raise ElkUnavailable("elk did not place every node")
        canvas_w = float(out["width"]) + 2 * MARGIN
        canvas_h = float(out["height"]) + 2 * MARGIN
        return positions, canvas_w, canvas_h, _routes_from(out)
    except (ElkUnavailable, KeyError, TypeError, ValueError):
        positions, canvas_w, canvas_h = _python_layout(nodes, edges)
        return positions, canvas_w, canvas_h, {}
