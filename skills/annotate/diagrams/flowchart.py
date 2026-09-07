"""Flowchart spec validator + server-side SVG renderer.

Called by server.py when rendering a block with kind == "flowchart". No
Mermaid.

Geometry comes from ``elk_layout``, which shells out to a ``node`` subprocess
and falls back to the pure-Python ``flowchart_layout`` when it cannot — so
``render`` is not free of I/O or of an external process. This module's own
drawing code is pure: it turns positions and routes into SVG. When ELK routed
an edge, that route is drawn as-is; on the fallback path (or for any edge ELK
didn't route), this module routes it itself — adjacent layers get a
vertical-tangent bezier that stays inside the row gap, layer-skipping edges
get routed down a side gutter instead of cutting through whatever sits
between them — and edge labels are nudged along their own path until they
stop colliding with nodes and with each other.
"""
from __future__ import annotations

import re
from collections import deque
from html import escape as _esc
from typing import Any

from . import flavours
from .elk_layout import layout
from .flowchart_layout import SIDE_GUTTER
from .text_metrics import line_h, text_px

# A node's `href` is written straight into an <a> that script.js injects with
# the page's own sanitizer deliberately bypassed — flowchart SVG is annotate's
# own drawing of a validated spec, so it is not run through sanitizeFreeHtml —
# which made `href="javascript:alert(1)"` in a flowchart spec a one-click
# script in the page. Only these four schemes reach the anchor. `#fragment`
# and `jetbrains:` are load-bearing: the first is the cross-block anchor
# createBlockSection scrolls to, the second is the jump-to-source link.
_ALLOWED_HREF_SCHEMES = ("http:", "https:", "mailto:", "jetbrains:")

# Chrome strips ASCII whitespace and control characters out of a URL attribute
# before it parses the scheme, so `java<TAB>script:` resolves to javascript:.
# Reading the scheme the same way is what makes this a scheme check rather
# than a spelling check.
_STRIPPED_FROM_URL = re.compile(r"[\x00-\x20\x7f]")


def _safe_href(href: Any) -> str | None:
    """`href` if a browser would resolve it to an allowed scheme, else None."""
    if not isinstance(href, str):
        return None
    collapsed = _STRIPPED_FROM_URL.sub("", href).lower()
    if not collapsed:
        return None
    if collapsed.startswith("#"):
        return href
    if collapsed.startswith(_ALLOWED_HREF_SCHEMES):
        return href
    return None


class ValidationError(ValueError):
    """Raised when a flowchart spec violates a structural rule."""


def validate(spec: dict[str, Any]) -> None:
    """Raise ValidationError if the spec is malformed; otherwise return None."""
    nodes = spec.get("nodes") or []
    edges = spec.get("edges") or []

    if len(nodes) < 1:
        raise ValidationError("flowchart requires at least 1 node")

    ids: set[str] = set()
    for n in nodes:
        nid = n.get("id")
        if not nid:
            raise ValidationError("node id required")
        if nid in ids:
            raise ValidationError(f"duplicate node id: {nid!r}")
        ids.add(nid)

    children: dict[str, list[str]] = {nid: [] for nid in ids}
    indeg: dict[str, int] = {nid: 0 for nid in ids}
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src not in ids:
            raise ValidationError(f"edge from unknown node {src!r}")
        if dst not in ids:
            raise ValidationError(f"edge to unknown node {dst!r}")
        children[src].append(dst)
        indeg[dst] += 1

    # cycle check via Kahn's algorithm
    q = deque([nid for nid in ids if indeg[nid] == 0])
    seen = 0
    ind = dict(indeg)
    while q:
        n = q.popleft(); seen += 1
        for c in children[n]:
            ind[c] -= 1
            if ind[c] == 0:
                q.append(c)
    if seen != len(ids):
        raise ValidationError("flowchart edges form a cycle (must be a DAG)")


_KNOWN_ROLES = {"entry", "code", "call", "decision", "success", "error"}

ARROW_GAP = 8         # stop the stroke short of the shape so the head sits clear
CORNER_R = 14         # rounded corner on gutter routes
LABEL_H = 20
LABEL_PAD_X = 9
LABEL_CLEAR = 4       # min gap between a label chip and any node or other chip


def _role_class(node: dict[str, Any]) -> str:
    role = node.get("role")
    return f"node-{role}" if role in _KNOWN_ROLES else "node-code"


def _defs() -> str:
    return (
        '<defs><marker id="fc-arrow" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#9aa3b0"/></marker></defs>'
    )


def _text_lines(pos: dict[str, Any]) -> str:
    """Draw a node's (already wrapped) text lines, centred on the shape."""
    node, cx, cy = pos["node"], pos["cx"], pos["cy"]
    lines: list[tuple[str, str, str]] = pos["lines"]

    # Primary jump-to-source link line, in priority order ref > label > method
    # (sub is never the link target). An href a browser would resolve to a
    # scheme outside _ALLOWED_HREF_SCHEMES is dropped here rather than
    # escaped, which leaves primary_kind None — so the line is drawn as plain
    # text, exactly as it is for a `ref` that carried no href at all.
    href = _safe_href(node.get("href"))
    primary_kind = None
    if href:
        kinds = {kind for _, _, kind in lines}
        for candidate in ("ref", "label", "method"):
            if candidate in kinds:
                primary_kind = candidate
                break

    total_h = sum(line_h(cls) for cls, _, _ in lines)
    y = cy - total_h / 2
    out: list[str] = []
    for cls, txt, kind in lines:
        lh = line_h(cls)
        baseline = y + lh * 0.76
        # A ref is painted as a link — accent, underlined — by `.flow-ref`. It
        # may only look that way when it IS one: a ref with no href reads as
        # jump-to-source, and a reader who clicks it gets nothing (before the
        # node click handler was withdrawn, they got a comment composer). The
        # modifier class keeps the monospace, so the line still says where the
        # code lives, and drops the promise.
        css = cls
        if kind == "ref" and kind != primary_kind:
            css = f"{cls} flow-ref-plain"
        el = (f'<text class="{css}" x="{cx:.1f}" y="{baseline:.1f}" '
              f'text-anchor="middle">{_esc(txt)}</text>')
        if kind == primary_kind:
            el = f'<a href="{_esc(href, quote=True)}">{el}</a>'
        out.append(el)
        y += lh
    return "".join(out)


def _node_svg(pos: dict[str, Any], block_id: str) -> str:
    node = pos["node"]
    cx, cy, w, h = pos["cx"], pos["cy"], pos["w"], pos["h"]
    cls = _role_class(node)
    parts = [
        f'<g class="node {cls}" data-block-id="{_esc(block_id, quote=True)}" '
        f'data-node-id="{_esc(node["id"], quote=True)}">'
    ]
    if node.get("role") == "decision":
        hw, hh = w / 2, h / 2
        pts = (f'{cx:.1f},{cy - hh:.1f} {cx + hw:.1f},{cy:.1f} '
               f'{cx:.1f},{cy + hh:.1f} {cx - hw:.1f},{cy:.1f}')
        parts.append(f'<polygon class="node-shape" points="{pts}"/>')
    else:
        parts.append(f'<rect class="node-shape" x="{cx - w / 2:.1f}" y="{cy - h / 2:.1f}" '
                     f'width="{w:.1f}" height="{h:.1f}" rx="12"/>')
    parts.append(_text_lines(pos))
    parts.append('</g>')
    return "".join(parts)


def _bbox(pos: dict[str, Any]) -> tuple[float, float, float, float]:
    return (pos["cx"] - pos["w"] / 2, pos["cy"] - pos["h"] / 2,
            pos["cx"] + pos["w"] / 2, pos["cy"] + pos["h"] / 2)


def _overlaps(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float], pad: float = 0.0) -> bool:
    return not (a[2] + pad <= b[0] or b[2] + pad <= a[0]
                or a[3] + pad <= b[1] or b[3] + pad <= a[1])


def _bezier(p0, p1, p2, p3, n: int = 24) -> list[tuple[float, float]]:
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
        y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
        pts.append((x, y))
    return pts


def _rounded_polyline(points: list[tuple[float, float]], r: float) -> str:
    """Path data through ``points`` with quadratic corners of radius ``r``."""
    d = [f'M{points[0][0]:.1f},{points[0][1]:.1f}']
    for i in range(1, len(points) - 1):
        (px, py), (cx, cy), (nx, ny) = points[i - 1], points[i], points[i + 1]
        r1 = min(r, ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5 / 2)
        r2 = min(r, ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5 / 2)
        d.append(f'L{cx + (px - cx) / max(abs(px - cx) + abs(py - cy), 1e-6) * r1:.1f},'
                 f'{cy + (py - cy) / max(abs(px - cx) + abs(py - cy), 1e-6) * r1:.1f}')
        d.append(f'Q{cx:.1f},{cy:.1f} '
                 f'{cx + (nx - cx) / max(abs(nx - cx) + abs(ny - cy), 1e-6) * r2:.1f},'
                 f'{cy + (ny - cy) / max(abs(nx - cx) + abs(ny - cy), 1e-6) * r2:.1f}')
    d.append(f'L{points[-1][0]:.1f},{points[-1][1]:.1f}')
    return "".join(d)


def _sample_polyline(points: list[tuple[float, float]], n: int = 24) -> list[tuple[float, float]]:
    segs = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    lens = [(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5) for a, b in segs]
    total = sum(lens) or 1.0
    out = []
    for i in range(n + 1):
        target = total * i / n
        acc = 0.0
        for (a, b), ln in zip(segs, lens):
            if acc + ln >= target or (a, b) is segs[-1]:
                t = (target - acc) / ln if ln else 0.0
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
                break
            acc += ln
    return out


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


def _route(src: dict[str, Any], dst: dict[str, Any],
           canvas_w: float) -> tuple[str, list[tuple[float, float]]]:
    """Path data and sample points for one edge."""
    if dst["layer"] - src["layer"] <= 1:
        # Adjacent rows: vertical-tangent bezier. Control points share the
        # endpoints' x, so the curve stays inside the row gap and cannot bulge
        # sideways across a sibling node.
        p0 = (src["cx"], src["cy"] + src["h"] / 2)
        p3 = (dst["cx"], dst["cy"] - dst["h"] / 2 - ARROW_GAP)
        my = (p0[1] + p3[1]) / 2
        d = (f'M{p0[0]:.1f},{p0[1]:.1f} C{p0[0]:.1f},{my:.1f} '
             f'{p3[0]:.1f},{my:.1f} {p3[0]:.1f},{p3[1]:.1f}')
        return d, _bezier(p0, (p0[0], my), (p3[0], my), p3)

    # Layer-skipping edge: leave sideways, run down the gutter, come back in.
    left = src["cx"] <= canvas_w / 2
    sign = -1 if left else 1
    xg = (SIDE_GUTTER / 2) if left else (canvas_w - SIDE_GUTTER / 2)
    x1 = src["cx"] + sign * src["w"] / 2
    x2 = dst["cx"] + sign * (dst["w"] / 2 + ARROW_GAP)
    pts = [(x1, src["cy"]), (xg, src["cy"]), (xg, dst["cy"]), (x2, dst["cy"])]
    return _rounded_polyline(pts, CORNER_R), _sample_polyline(pts)


def _label_rect(label: str, at: tuple[float, float]) -> tuple[float, float, float, float]:
    w = text_px(label, "edge-label") + 2 * LABEL_PAD_X
    return (at[0] - w / 2, at[1] - LABEL_H / 2, at[0] + w / 2, at[1] + LABEL_H / 2)


def _clamp(rect: tuple[float, float, float, float],
           canvas_w: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = rect
    dx = 0.0
    if x0 < LABEL_CLEAR:
        dx = LABEL_CLEAR - x0
    elif x1 > canvas_w - LABEL_CLEAR:
        dx = canvas_w - LABEL_CLEAR - x1
    return (x0 + dx, y0, x1 + dx, y1)


def _place_label(label: str, samples: list[tuple[float, float]],
                 obstacles: list[tuple[float, float, float, float]],
                 canvas_w: float) -> tuple[float, float, float, float]:
    """Pick the point along the edge whose label chip collides least.

    Candidates walk outwards from the middle of the edge, so an uncrowded edge
    keeps the natural mid-edge placement and only a contested one drifts. Chips
    are kept inside the canvas — a gutter route runs close enough to the edge
    that an unclamped chip would hang off the side of the diagram.
    """
    n = len(samples) - 1
    order = sorted(range(len(samples)), key=lambda i: abs(i - n / 2))
    best = None
    for i in order:
        rect = _clamp(_label_rect(label, samples[i]), canvas_w)
        clashes = sum(1 for o in obstacles if _overlaps(rect, o, LABEL_CLEAR))
        if clashes == 0:
            return rect
        if best is None or clashes < best[0]:
            best = (clashes, rect)
    return best[1]


def _label_svg(label: str, rect: tuple[float, float, float, float]) -> str:
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) / 2
    return (f'<g class="edge-label"><rect x="{x0:.1f}" y="{y0:.1f}" '
            f'width="{x1 - x0:.1f}" height="{y1 - y0:.1f}" rx="10"/>'
            f'<text x="{cx:.1f}" y="{(y0 + y1) / 2 + 3.5:.1f}" '
            f'text-anchor="middle">{_esc(label)}</text></g>')


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
            # Swallow a variant that fails to lay out — that is what the
            # viability gate below is for. The default is the one exception:
            # flavours.select can only keep "layered" out of what it is
            # given, so a failure there must propagate instead of silently
            # letting a non-default variant become the block's default.
            if name == flavours.DEFAULT:
                raise
            continue
        laid[name] = (positions, w, h, routes)
        results.append((name, positions, w, h, routes))

    names = flavours.select(results, len(edges))
    svgs = {name: _draw(spec, block_id, *laid[name]) for name in names}
    return svgs, names
