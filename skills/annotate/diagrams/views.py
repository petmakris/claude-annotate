"""Multi-view flowcharts: geometry forbids, meaning groups.

A diagram that answers several questions at once pays for it in crossings, and
a layered layout cannot help because it minimises crossings over the union of
every question's edges. Splitting the edges by question fixes it; deciding
which question an edge answers is not something geometry can do.

So the work divides. This module measures which edge pairs cross and therefore
MUST NOT share a view, verifies an authored grouping against those
measurements, and splits a spec into one subspec per view. It never invents a
grouping and never names one: a colouring of the conflict graph is
geometrically valid and semantically meaningless, so naming stays with the
author, who knows the domain.

The two authored fields are ``views`` on an edge (a set, because an edge can
answer more than one question) and ``band`` on a node (the role axis, which
holds its order across views so a reader can compare them side by side).
Absent both, everything here is inert and a spec renders exactly as before.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

ALL_VIEW = "all"


def declared(spec: dict[str, Any]) -> list[str]:
    """View names in first-seen edge order; empty when the spec declares none."""
    seen: list[str] = []
    for e in spec.get("edges") or []:
        for v in e.get("views") or ():
            if v not in seen:
                seen.append(v)
    return seen


def bands(spec: dict[str, Any]) -> dict[str, int]:
    """Node id to band index, in first-seen order. Empty when none declared."""
    order: list[str] = []
    for n in spec.get("nodes") or []:
        b = n.get("band")
        if b is not None and b not in order:
            order.append(b)
    if not order:
        return {}
    idx = {b: i for i, b in enumerate(order)}
    return {n["id"]: idx[n["band"]] for n in spec["nodes"] if n.get("band") is not None}


def _pairs(edges: list[dict[str, Any]],
           routes: dict[int, list[tuple[float, float]]]) -> list[tuple[int, int]]:
    """Indices of every edge pair whose routes cross. Edges sharing an endpoint
    are skipped: they meet at a node, which is not a crossing."""
    from .flowchart import _segments_intersect

    segs = {i: [(p[j], p[j + 1]) for j in range(len(p) - 1)]
            for i, p in routes.items() if len(p) >= 2}
    out = []
    for a, b in itertools.combinations(sorted(segs), 2):
        ea, eb = edges[a], edges[b]
        if {ea["from"], ea["to"]} & {eb["from"], eb["to"]}:
            continue
        if any(_segments_intersect(s0, s1, t0, t1)
               for s0, s1 in segs[a] for t0, t1 in segs[b]):
            out.append((a, b))
    return out


def measure(spec: dict[str, Any], variant: str | None = None
            ) -> tuple[list[tuple[int, int]], float, float]:
    """Lay the spec out for real and return (crossing pairs, width, height).

    Nothing here reasons about what a layout will look like. Every claim this
    module makes comes from a rendered layout, because predictions about
    layered drawings are wrong often enough to be worthless.
    """
    from . import flavours
    from .elk_layout import layout

    nodes = spec.get("nodes") or []
    edges = spec.get("edges") or []
    _, w, h, routes = layout(nodes, edges, variant or flavours.DEFAULT)
    return _pairs(edges, routes), w, h


@dataclass
class ViewReport:
    """What one view costs, measured."""
    name: str
    nodes: int
    edges: int
    crossings: int
    width: float
    height: float


@dataclass
class Report:
    """The verdict on a spec's grouping. ``ok`` means it is fit to ship."""
    union_crossings: int
    union_size: tuple[float, float]
    conflicts: list[tuple[str, str]] = field(default_factory=list)
    violations: list[tuple[str, str, list[str]]] = field(default_factory=list)
    unassigned: list[str] = field(default_factory=list)
    views: list[ViewReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations and not self.unassigned

    @property
    def needs_views(self) -> bool:
        """A clean diagram needs nothing. Saying so is the point."""
        return self.union_crossings > 0

    def summary(self) -> str:
        lines = [f"union: {self.union_crossings} crossing"
                 f"{'' if self.union_crossings == 1 else 's'}, "
                 f"{self.union_size[0]:.0f}x{self.union_size[1]:.0f}"]
        if not self.needs_views:
            lines.append("no crossings — this diagram does not need views")
            return "\n".join(lines)
        if not self.views:
            lines.append(f"{len(self.conflicts)} pair"
                         f"{'' if len(self.conflicts) == 1 else 's'} must be separated:")
            lines += [f"    {a}  X  {b}" for a, b in self.conflicts]
            return "\n".join(lines)
        for v in self.views:
            lines.append(f"  {v.name:<12} {v.nodes:>2} nodes {v.edges:>2} edges  "
                         f"{v.width:.0f}x{v.height:.0f}  {v.crossings} crossings")
        for a, b, shared in self.violations:
            lines.append(f"  VIOLATION {a} and {b} cross but share {sorted(shared)}")
        for e in self.unassigned:
            lines.append(f"  UNASSIGNED {e} belongs to no view")
        return "\n".join(lines)


def _name(e: dict[str, Any]) -> str:
    return f'{e["from"]}->{e["to"]}'


def subspec(spec: dict[str, Any], view: str) -> dict[str, Any]:
    """The spec restricted to one view. Node membership is derived: a node is
    present when one of its edges is, so it is never authored twice."""
    edges = [e for e in spec.get("edges") or [] if view in (e.get("views") or ())]
    keep = {e["from"] for e in edges} | {e["to"] for e in edges}
    nodes = [n for n in spec.get("nodes") or [] if n["id"] in keep]
    out = {k: v for k, v in spec.items() if k not in ("nodes", "edges")}
    out["nodes"], out["edges"] = nodes, edges
    return out


def check(spec: dict[str, Any], variant: str | None = None) -> Report:
    """Measure the union, then every declared view, and report what is wrong."""
    edges = spec.get("edges") or []
    pairs, w, h = measure(spec, variant)
    rep = Report(union_crossings=len(pairs), union_size=(w, h),
                 conflicts=[(_name(edges[a]), _name(edges[b])) for a, b in pairs])

    names = declared(spec)
    if not names:
        return rep

    for i, e in enumerate(edges):
        if not (e.get("views") or ()):
            rep.unassigned.append(_name(e))
    for a, b in pairs:
        shared = set(edges[a].get("views") or ()) & set(edges[b].get("views") or ())
        if shared:
            rep.violations.append((_name(edges[a]), _name(edges[b]), sorted(shared)))

    for v in names:
        sub = subspec(spec, v)
        if not sub["edges"]:
            continue
        vp, vw, vh = measure(sub, variant)
        rep.views.append(ViewReport(v, len(sub["nodes"]), len(sub["edges"]),
                                    len(vp), vw, vh))
    return rep
