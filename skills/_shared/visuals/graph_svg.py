"""Graph: what happens to commits or to a tree. Spec validator and server-side SVG renderer.

A graph board draws a commit graph or a tree, and what a change does to it: the same graph before and
after, side by side, with the commits a change adds, leaves behind or removes marked. It is the board for
"what does rebase do to history", "what does a split do to a B-tree", "what does a delete leave". Only
commit graphs and trees: nothing here is a flowchart (use that for a process), and no node has two parents
that are not older than it (a cycle is refused).

    {"title": "A rebase copies your commits onto the new tip",
     "nodes": [{"id": "a", "label": "A", "lane": "main"}, {"id": "b", "label": "B", "lane": "main"},
               {"id": "c", "label": "C", "lane": "main", "sub": "new tip"},
               {"id": "d", "label": "D", "lane": "old work", "state": "ghost"},
               {"id": "d2", "label": "D copy", "lane": "feature", "state": "new"}],
     "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "b", "to": "d"}, {"from": "c", "to": "d2"}]}

- A node is ``{id, label, lane, state?, sub?}``. ``lane`` is the row it sits in (a branch name, or a level of
  a tree): lanes run top to bottom in the order they first appear, or in ``lanes``. Leave ``lane`` out of every
  node and the rows are made for you, one per leaf, as a tree is drawn. Its column is how many parents deep it is.
- ``state`` is ``same`` (default), ``new`` (in the after only), ``ghost`` (in the before as it was, and in the
  after faint and dashed, still there but no longer reached) or ``struck`` (in the before as it was, in the after
  struck through, removed). With every node ``same`` there is one frame, no before and after.
- An edge is ``{from, to, label?}``: from the parent (older) to the child. It is a plain line, no head, since
  time runs left to right.
- Nodes of a frame that share a column and lane stack in that lane; give a ghost its own lane to keep it clear.

With before and after the SVG holds both frames, ``<g data-frame="before">`` and ``<g data-frame="after">``,
side by side, and ``data-vb`` on the SVG gives each frame's own viewBox (``before``, ``after``, ``both``) for a
page that shows one at a time (a phone). A node is keyed ``node:<id>`` in both frames, an edge ``edge:<a>-><b>#0``.
Pure functions, no I/O. Nothing the author writes reaches the output except as escaped text.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

from . import text_metrics as tm
from .flowchart_layout import assign_layers
from .map_svg import TONES, _attrs, _cls, _markers, _text, _width

STATES = ("same", "new", "ghost", "struck")
PAD = 24
TITLE_Y = 38
HEAD_H = 34           # room for the BEFORE / AFTER heading over each frame
NODE_H = 40
NODE_H_SUB = 58
NODE_MIN_W = 84
COL_GAP = 52
LANE_GAP = 26
LANE_LABEL_GAP = 18
FRAME_GAP = 64
MAX_NODES = 40


class ValidationError(ValueError):
    """Raised when a graph spec breaks a rule. The message names the node by its id."""


def _text_field(obj: dict, key: str, where: str, required: bool = False) -> None:
    v = obj.get(key)
    if v is None and not required:
        return
    if not isinstance(v, str) or (required and not v.strip()):
        raise ValidationError(f"{where}: {key} must be text")


def _find_cycle(ids: list[str], edges: list[dict]) -> list[str] | None:
    kids: dict[str, list[str]] = {i: [] for i in ids}
    for e in edges:
        kids[e["from"]].append(e["to"])
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(n: str) -> list[str] | None:
        state[n] = 1
        stack.append(n)
        for c in kids[n]:
            if state.get(c) == 1:
                return stack[stack.index(c):] + [c]
            if c not in state and (found := visit(c)):
                return found
        stack.pop()
        state[n] = 2
        return None

    for n in ids:
        if n not in state and (found := visit(n)):
            return found
    return None


def validate(spec: dict[str, Any]) -> None:
    """Raise ValidationError if the spec is malformed; otherwise return None."""
    if not isinstance(spec, dict):
        raise ValidationError("a graph spec is an object")
    for k in ("title", "subtitle", "aria"):
        _text_field(spec, k, "graph")
    nodes = spec.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValidationError("graph needs at least 1 node: nodes is a list of {id, label, lane}")
    if len(nodes) > MAX_NODES:
        raise ValidationError(f"graph has {len(nodes)} nodes, at most {MAX_NODES}: draw only the part that changes")
    ids: list[str] = []
    lanes_used = 0
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            raise ValidationError(f"node {i}: a node is an object")
        nid = n.get("id")
        if not isinstance(nid, str) or not nid:
            raise ValidationError(f"node {i}: id required")
        if nid in ids:
            raise ValidationError(f"duplicate node id: {nid!r}")
        ids.append(nid)
        where = f"node {nid!r}"
        _text_field(n, "label", where, True)
        _text_field(n, "sub", where)
        _text_field(n, "lane", where)
        lanes_used += n.get("lane") is not None
        if n.get("state", "same") not in STATES:
            raise ValidationError(f"{where}: unknown state {n.get('state')!r}; the states are {', '.join(STATES)}")
    if lanes_used not in (0, len(nodes)):
        missing = next(n["id"] for n in nodes if n.get("lane") is None)
        raise ValidationError(f"node {missing!r}: no lane. Give every node a lane (its row), or none at all to draw a tree")
    lanes = spec.get("lanes")
    if lanes is not None:
        if not isinstance(lanes, list) or not all(isinstance(x, str) for x in lanes):
            raise ValidationError("lanes is a list of lane names, top to bottom")
        for n in nodes:
            if n.get("lane") is not None and n["lane"] not in lanes:
                raise ValidationError(f"node {n['id']!r}: lane {n['lane']!r} is not in lanes {lanes}")
    edges = spec.get("edges") or []
    if not isinstance(edges, list):
        raise ValidationError("edges is a list of {from, to}")
    seen: set[tuple[str, str]] = set()
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            raise ValidationError(f"edge {i}: an edge is an object")
        for end in ("from", "to"):
            if e.get(end) not in ids:
                raise ValidationError(f"edge {i}: unknown {end} node {e.get(end)!r}; the nodes are {', '.join(ids)}")
        if e["from"] == e["to"]:
            raise ValidationError(f"edge {i}: node {e['from']!r} cannot be its own parent")
        if (e["from"], e["to"]) in seen:
            raise ValidationError(f"edge {e['from']!r} -> {e['to']!r} is given twice")
        seen.add((e["from"], e["to"]))
        _text_field(e, "label", f"edge {i}")
    cycle = _find_cycle(ids, edges)
    if cycle:
        raise ValidationError("the edges go round a cycle: " + " -> ".join(cycle)
                              + ". A commit graph and a tree have none: an edge runs from the older node to the newer")


def has_frames(spec: dict[str, Any]) -> bool:
    """True when some node is not ``same``: the board is a before and an after."""
    return any(n.get("state", "same") != "same" for n in spec["nodes"])


def frame_nodes(spec: dict[str, Any], frame: str) -> list[str]:
    """The ids drawn in a frame: the before holds what was there, the after what is there now (a ghost and a struck
    node too, marked)."""
    return [n["id"] for n in spec["nodes"] if frame == "after" or n.get("state", "same") != "new"]


def _auto_lanes(nodes: list[dict], edges: list[dict]) -> dict[str, int]:
    """One row per leaf, in the order the spec lists them; a parent sits on the row of its first child."""
    kids: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    has_parent = set()
    for e in edges:
        kids[e["from"]].append(e["to"])
        has_parent.add(e["to"])
    row: dict[str, int] = {}
    counter = [0]

    def place(n: str) -> int:
        if n in row:
            return row[n]
        if not kids[n]:
            row[n] = counter[0]
            counter[0] += 1
        else:
            first = [place(c) for c in kids[n]]
            row[n] = first[0]
        return row[n]

    for n in nodes:
        if n["id"] not in has_parent:
            place(n["id"])
    for n in nodes:
        place(n["id"])
    return row


def layout(spec: dict[str, Any]) -> dict[str, Any]:
    """Every node's column (how many parents deep) and lane (row), the lane names, and the widths: the same positions
    in both frames, so a node stays where it was."""
    validate(spec)
    nodes, edges = spec["nodes"], spec.get("edges") or []
    ids = [n["id"] for n in nodes]
    layer = assign_layers(ids, edges)
    if all(n.get("lane") is None for n in nodes):
        rows = _auto_lanes(nodes, edges)
        names = [f"row {i + 1}" for i in range(max(rows.values()) + 1)]
        lane = {i: rows[i] for i in ids}
        shown_names = [""] * len(names)  # a tree's rows are not named
    else:
        names = list(spec.get("lanes") or [])
        for n in nodes:
            if n["lane"] not in names:
                names.append(n["lane"])
        lane = {n["id"]: names.index(n["lane"]) for n in nodes}
        shown_names = names
    return {"layer": layer, "lane": lane, "names": names, "shown": shown_names}


def _size(n: dict) -> tuple[float, float]:
    w = _width(n["label"], "vz-nm") + 28
    if n.get("sub"):
        w = max(w, _width(n["sub"], "vz-sb") + 28)
    return max(NODE_MIN_W, w), NODE_H_SUB if n.get("sub") else NODE_H


def _frame(spec: dict, geo: dict, frame: str, ox: float, oy: float, keyed: bool, label_w: float) -> tuple[list[str], float, float]:
    """Draw one frame with its top-left at (ox, oy). Returns its parts and its width and height."""
    nodes = {n["id"]: n for n in spec["nodes"]}
    present = frame_nodes(spec, frame)
    layer, lane = geo["layer"], geo["lane"]
    cols = sorted({layer[i] for i in present})
    width_of = {c: max(_size(nodes[i])[0] for i in present if layer[i] == c) for c in cols}
    x_of: dict[int, float] = {}
    x = ox + label_w
    for c in cols:
        x_of[c] = x
        x += width_of[c] + COL_GAP
    frame_w = x - COL_GAP - ox
    # nodes sharing a column and lane stack inside that lane
    stack: dict[tuple[int, int], int] = {}
    slot: dict[str, int] = {}
    for i in present:
        k = (layer[i], lane[i])
        slot[i] = stack.get(k, 0)
        stack[k] = slot[i] + 1
    lanes_used = sorted({lane[i] for i in present})
    depth = {ln: max([s for (c, l), s in stack.items() if l == ln] + [1]) for ln in lanes_used}
    row_h = max(_size(nodes[i])[1] for i in present)
    y_of: dict[int, float] = {}
    y = oy
    for ln in lanes_used:
        y_of[ln] = y
        y += depth[ln] * (row_h + 12) - 12 + LANE_GAP
    frame_h = y - LANE_GAP - oy

    out: list[str] = [f'<g data-frame="{frame}">']
    for ln in lanes_used:
        if geo["shown"][ln]:
            out.append(_text("zl", ox, y_of[ln] + row_h / 2 + 4, geo["shown"][ln].upper()))
    pos: dict[str, tuple[float, float, float, float]] = {}
    for i in present:
        w, h = _size(nodes[i])
        cx = x_of[layer[i]] + (width_of[layer[i]] - w) / 2
        py = y_of[lane[i]] + slot[i] * (row_h + 12) + (row_h - h) / 2
        pos[i] = (cx, py, w, h)

    def state_of(i: str) -> str:
        s = nodes[i].get("state", "same")
        return s if frame == "after" or s == "same" else "same"

    seen_pairs: dict[tuple[str, str], int] = {}
    for e in spec.get("edges") or []:
        a, b = e["from"], e["to"]
        n = seen_pairs.get((a, b), 0)
        seen_pairs[(a, b)] = n + 1
        if a not in pos or b not in pos:
            continue
        ax, ay, aw, ah = pos[a]
        bx, by, bw, bh = pos[b]
        x1, y1, x2, y2 = ax + aw, ay + ah / 2, bx, by + bh / 2
        mid = (x1 + x2) / 2
        d = f"M{x1:.0f},{y1:.0f} L{x2:.0f},{y2:.0f}" if abs(y1 - y2) < 1 else \
            f"M{x1:.0f},{y1:.0f} L{mid:.0f},{y1:.0f} L{mid:.0f},{y2:.0f} L{x2:.0f},{y2:.0f}"
        faint = state_of(a) in ("ghost", "struck") or state_of(b) in ("ghost", "struck")
        key = f"edge:{a}->{b}#{n}" if keyed else ""
        out.append(f'<path class="{_cls("ed", "faint" if faint else "")}" d="{d}"{_attrs(key=key)}/>')
        if e.get("label"):
            out.append(_text("lb", mid, (y1 + y2) / 2 - 6, e["label"], _attrs(key=key), "middle"))
    for i in present:
        n = nodes[i]
        px, py, w, h = pos[i]
        s = state_of(i)
        att = _attrs(key=f"node:{i}" if keyed else "")
        tone = {"new": "green", "struck": "red"}.get(s, "plain")
        out.append(f'<rect class="{_cls("bx", "nd", tone, "gh" if s == "ghost" else "")}" x="{px:.0f}" y="{py:.0f}" width="{w:.0f}" '
                   f'height="{h:.0f}" rx="8"{att}/>')
        ty = py + (h / 2 + 5 if not n.get("sub") else 24)
        out.append(_text(_cls("nm", "gh" if s == "ghost" else "", "st" if s == "struck" else ""), px + w / 2, ty, n["label"], att, "middle"))
        if n.get("sub"):
            out.append(_text("sb", px + w / 2, py + 42, n["sub"], att, "middle"))
        if s == "struck":
            out.append(f'<line class="stk" x1="{px + 8:.0f}" y1="{py + h / 2:.0f}" x2="{px + w - 8:.0f}" y2="{py + h / 2:.0f}"{att}/>')
        if s == "new":
            out.append(_text("tg green", px + w - 6, py - 5, "NEW", att, "end"))
    out.append("</g>")
    return out, frame_w, frame_h


def render(spec: dict[str, Any], uid: str, keyed: bool = False) -> str:
    """Validate and draw `spec` as one SVG string. `uid` prefixes every id. With `keyed`, nodes and edges carry their
    keys (``node:<id>``, ``edge:<a>-><b>#<n>``) in both frames, for the stage's frames."""
    validate(spec)
    if not re.fullmatch(r"[A-Za-z][\w-]{0,40}", uid or ""):
        raise ValidationError(f"uid {uid!r}: letters, digits, - and _, starting with a letter")
    geo = layout(spec)
    out: list[str] = []
    top = PAD
    if spec.get("title"):
        top += 30
        out.append(_text("ttl", PAD, top, spec["title"]))
        top += 10
    if spec.get("subtitle"):
        top += 22
        out.append(_text("sub", PAD, top, spec["subtitle"]))
    framed = has_frames(spec)
    with tm.face("stage"):
        label_w = max([_width(n.upper(), "vz-zl") for n in geo["shown"] if n] + [0])
    label_w = label_w + LANE_LABEL_GAP if label_w else 0
    head = HEAD_H if framed else 12
    y0 = top + head
    vb: dict[str, tuple[float, float, float, float]] = {}
    if framed:
        parts_b, wb, hb = _frame(spec, geo, "before", PAD, y0, keyed, label_w)
        ox = PAD + wb + FRAME_GAP
        parts_a, wa, ha = _frame(spec, geo, "after", ox, y0, keyed, label_w)
        out.append(_text("zl", PAD, y0 - 14, "BEFORE"))
        out.append(_text("zl", ox, y0 - 14, "AFTER"))
        out += parts_b + parts_a
        total_w, total_h = ox + wa + PAD, y0 + max(hb, ha) + PAD
        title_h = top - PAD
        vb = {"before": (0, title_h, PAD + wb + PAD, total_h - title_h),
              "after": (ox - PAD, title_h, wa + 2 * PAD, total_h - title_h),
              "both": (0, 0, total_w, total_h)}
    else:
        parts, wf, hf = _frame(spec, geo, "after", PAD, y0, keyed, label_w)
        out += parts
        total_w, total_h = PAD + wf + PAD, y0 + hf + PAD
        total_w = max(total_w, PAD * 2 + _width(spec.get("title") or "", "vz-ttl"))
        vb = {"both": (0, 0, total_w, total_h)}
    aria = escape(spec.get("aria") or spec.get("title") or "Graph", quote=True)
    vbs = "".join(f' data-vb-{k}="{v[0]:.0f} {v[1]:.0f} {v[2]:.0f} {v[3]:.0f}"' for k, v in vb.items())
    return (f'<svg class="vz vzg" viewBox="0 0 {total_w:.0f} {total_h:.0f}" role="img" aria-label="{aria}" data-vz="graph" '
            f'data-frames="{"2" if framed else "1"}"{vbs}>' + _markers(uid) + "".join(out) + "</svg>")


def node_keys(spec: dict[str, Any]) -> list[str]:
    return [f"node:{n['id']}" for n in spec.get("nodes") or []]


def edge_keys(spec: dict[str, Any]) -> list[str]:
    """Each edge's key in spec order: the n-th edge from a node to another counts from 0, as on a map."""
    seen: dict[tuple[str, str], int] = {}
    out = []
    for e in spec.get("edges") or []:
        pair = (e["from"], e["to"])
        out.append(f"edge:{pair[0]}->{pair[1]}#{seen.get(pair, 0)}")
        seen[pair] = seen.get(pair, 0) + 1
    return out


__all__ = ["ValidationError", "validate", "render", "layout", "has_frames", "frame_nodes", "node_keys", "edge_keys", "TONES"]
