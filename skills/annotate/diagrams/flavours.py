"""The house set of layout variants, and the gate that decides which ship.

The house set holds a single entry, `layered`, tuned by eye against a real
13-node diagram: `compact` was rejected for edge and label overlap, and
`wide`/`tree` were not wanted either. `layered` is never dropped: it is the
default rendering and the thing `base["svg"]` holds.

The variant machinery — `select()`, `viable()`, `render_variants()`, the
`svgs`/`flavours` keys in render.py, and the control in static/script.js —
stays in place. With one surviving variant, render.py's `len(names) > 1`
guard simply stops emitting the control, so adding a second flavour back is a
one-line change to `HOUSE_SET`.

This module is a leaf. It knows ELK option strings and geometry, and nothing
about rendering, so `elk_layout` and `flowchart` can both import it.
"""
from __future__ import annotations

from typing import Any

# Shared by every layered variant. Values are strings because that is what ELK
# reads them as. The spacing entries below are the values the user tuned live
# in the option explorer against a real 13-node graph: narrower and taller
# than the previous defaults (1011 x 844 vs 1099 x 714) at the same 4 edge
# crossings. elk.spacing.edgeNode (80, up from 22) — edge-to-node clearance —
# does most of that work.
BASE: dict[str, str] = {
    "elk.algorithm": "layered",
    "elk.direction": "DOWN",
    "elk.edgeRouting": "ORTHOGONAL",
    "elk.spacing.edgeNode": "80",
    "elk.spacing.nodeNode": "12",
    "elk.spacing.edgeEdge": "11",
    "elk.spacing.edgeLabel": "0",
    "elk.layered.spacing.nodeNodeBetweenLayers": "65",
    "elk.layered.spacing.edgeNodeBetweenLayers": "26",
    "elk.layered.spacing.edgeEdgeBetweenLayers": "36",
    "elk.layered.spacing.baseValue": "12",
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES",
}

HOUSE_SET: tuple[tuple[str, dict[str, str]], ...] = (
    ("layered", {}),
)

_BY_NAME = dict(HOUSE_SET)

# Two canvases this close on both axes are the same picture to a reader.
DUPLICATE_TOLERANCE = 0.05

DEFAULT = "layered"


def options(variant: str) -> dict[str, str]:
    """Full ELK option map for one house-set variant."""
    if variant not in _BY_NAME:
        valid = ", ".join(name for name, _ in HOUSE_SET)
        raise ValueError(f"unknown flavour variant {variant!r}; valid: {valid}")
    return {**BASE, **_BY_NAME[variant]}


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
