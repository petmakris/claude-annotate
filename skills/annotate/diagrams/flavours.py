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
