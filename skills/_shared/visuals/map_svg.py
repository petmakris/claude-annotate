"""Architecture map: spec validator and server-side SVG renderer.

A map is boxes on a grid of columns and rows, grouped by dashed zones and joined by labelled arrows,
in the look of the ai-building-blocks overview diagrams. One SVG reads in three ways:

- still: the whole structure at once, for a page, a PNG or a slide;
- build: the structure added one step at a time (each part's ``b``), the way a talk explains a system;
- route: one request travelling over the map (``layer: "route"`` arrows and each part's ``r``).

The author places boxes by column and row. This module measures every text in Inter and JetBrains Mono
(text_metrics, stage face), sizes boxes and grid tracks, routes arrows at right angles, finds each label
a spot clear of boxes, labels and arrows (widening a gap when there is none) and writes SVG classed for
vz.css. Nothing the author writes reaches the output except as escaped text: a spec holds words, and
`code` spans become a mono tspan.

Every drawn part carries ``data-p``; parts with a build or route step carry ``data-b`` / ``data-r``;
structure arrows and their labels carry ``data-base``, route arrows ``data-route``. vz-reveal.js and
tools/vz_check.py read only these.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from html import escape
from typing import Any

from . import text_metrics as tm

TONES = ("plain", "blue", "red", "green", "amber")
SIDES = ("left", "right", "top", "bottom")
PATHS = ("auto", "straight", "hv", "vh", "hvh", "vhv")

PAD = 24            # canvas margin
TITLE_Y = 38
SUB_GAP = 24
COL_GAP = 56        # the narrowest gap between columns; a labelled arrow can widen it
ROW_GAP = 44
BOX_MIN_W = 176
BOX_PAD_L = 18
BOX_PAD_R = 16
NAME_Y = 30         # baseline of the name, from the box top
LINE_STEP = 22
GAP_STEP = 10       # extra space before a line marked gap
BOX_PAD_B = 16
CHILD_GAP = 10
ZONE_PAD = 14
ZONE_LINE = 20
ZONE_FOOT = 16
ARROW_GAP = 4       # an arrowhead stops this far short of the box it enters
CHANNEL = 14        # spacing between arrows sharing a gap
BADGE_R = 11
LEGEND_ROW = 30
ZL_TRACK = 0.08     # letter-spacing of .zl, in em
LABEL_H = 18
ROW_LABEL_H = 26    # room above a row for its label
LABEL_LINE = 18     # line pitch of a label with more than one line
BEND = 40           # what a turn costs when routes are compared by length

CODE = re.compile(r"`([^`]+)`")
MARK = {"plain": "a", "blue": "b", "red": "r", "green": "g", "amber": "m"}


class ValidationError(ValueError):
    """Raised when a map spec breaks a structural rule."""


# ---------------------------------------------------------------- validation

def _tone(obj: dict, where: str) -> str:
    t = obj.get("tone", "plain") or "plain"
    if t not in TONES:
        raise ValidationError(f"{where}: unknown tone {t!r}; the tones are {', '.join(TONES)}")
    return t


def _step(obj: dict, key: str, where: str) -> None:
    v = obj.get(key)
    if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
        raise ValidationError(f"{where}: {key} must be a whole number 0 or more, got {v!r}")


def _text_field(obj: dict, key: str, where: str, required: bool = False) -> None:
    v = obj.get(key)
    if v is None and not required:
        return
    if not isinstance(v, str) or (required and not v):
        raise ValidationError(f"{where}: {key} must be text")


def validate(spec: dict[str, Any]) -> None:
    """Raise ValidationError if the spec is malformed; otherwise return None."""
    if not isinstance(spec, dict):
        raise ValidationError("a map spec is an object")
    for k in ("title", "subtitle", "aria"):
        _text_field(spec, k, "map")
    cols = spec.get("columns")
    boxes = spec.get("boxes") or []
    if not isinstance(cols, list) or not cols or not all(isinstance(c, str) for c in cols):
        raise ValidationError("map requires columns: a list of column labels")
    if not boxes:
        raise ValidationError("map requires at least 1 box")
    ids: dict[str, dict] = {}
    placed: set[str] = set()
    cells: dict[tuple[int, int], str] = {}

    def walk(box: Any, where: str, top: bool) -> None:
        if not isinstance(box, dict):
            raise ValidationError(f"{where}: a box is an object")
        bid = box.get("id")
        if not isinstance(bid, str) or not bid:
            raise ValidationError(f"{where}: id required")
        if bid in ids:
            raise ValidationError(f"duplicate box id: {bid!r}")
        ids[bid] = box
        _text_field(box, "name", f"box {bid!r}", True)
        _tone(box, f"box {bid!r}")
        _step(box, "b", f"box {bid!r}")
        _step(box, "r", f"box {bid!r}")
        _step(box, "n", f"box {bid!r}")
        for i, ln in enumerate(box.get("lines") or []):
            if isinstance(ln, str):
                continue
            w = f"box {bid!r} line {i}"
            if not isinstance(ln, dict):
                raise ValidationError(f"{w}: a line is text or an object with text")
            _text_field(ln, "text", w, True)
            _tone(ln, w)
            _step(ln, "b", w)
            _step(ln, "r", w)
        if top:
            placed.add(bid)
            for k in ("col", "row"):
                v = box.get(k)
                if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                    raise ValidationError(f"box {bid!r}: {k} must be a whole number 0 or more")
            span_c, span_r = box.get("cols", 1), box.get("rows", 1)
            if not isinstance(span_c, int) or not isinstance(span_r, int) or span_c < 1 or span_r < 1:
                raise ValidationError(f"box {bid!r}: cols and rows are whole numbers 1 or more")
            if box["col"] + span_c > len(cols):
                raise ValidationError(f"box {bid!r}: reaches column {box['col'] + span_c - 1}, but there are {len(cols)} columns")
            for c in range(box["col"], box["col"] + span_c):
                for r in range(box["row"], box["row"] + span_r):
                    if (c, r) in cells:
                        raise ValidationError(f"box {bid!r} overlaps box {cells[(c, r)]!r} at column {c}, row {r}")
                    cells[(c, r)] = bid
        for i, ch in enumerate(box.get("children") or []):
            walk(ch, f"box {bid!r} child {i}", False)

    for i, b in enumerate(boxes):
        walk(b, f"box {i}", True)

    rl = spec.get("row_labels")
    if rl is not None and (not isinstance(rl, list) or not all(x is None or isinstance(x, str) for x in rl)):
        raise ValidationError("row_labels is a list with a label or null for each row")

    for i, z in enumerate(spec.get("zones") or []):
        _tone(z, f"zone {i}")
        _step(z, "b", f"zone {i}")
        _step(z, "r", f"zone {i}")
        _text_field(z, "label", f"zone {i}")
        members = z.get("boxes") or []
        if not members:
            raise ValidationError(f"zone {i}: boxes required")
        for m in members:
            if m not in placed:
                raise ValidationError(f"zone {i}: {m!r} is not a box placed on the grid")

    for i, a in enumerate(spec.get("arrows") or []):
        where = f"arrow {i}"
        if not isinstance(a, dict):
            raise ValidationError(f"{where}: an arrow is an object")
        for end in ("from", "to"):
            if a.get(end) not in ids:
                raise ValidationError(f"{where}: unknown {end} box {a.get(end)!r}")
        if a["from"] == a["to"]:
            raise ValidationError(f"{where}: from and to are the same box")
        _tone(a, where)
        _text_field(a, "label", where)
        for k in ("b", "r", "n"):
            _step(a, k, where)
        if a.get("path", "auto") not in PATHS:
            raise ValidationError(f"{where}: unknown path {a.get('path')!r}; the paths are {', '.join(PATHS)}")
        if a.get("layer", "base") not in ("base", "route"):
            raise ValidationError(f"{where}: layer is base or route")
        for k in ("offset", "offset_to"):
            if a.get(k) is not None and not isinstance(a[k], (int, float)):
                raise ValidationError(f"{where}: {k} is a number of pixels")

    for i, l in enumerate(spec.get("legend") or []):
        _tone(l, f"legend {i}")
        _text_field(l, "label", f"legend {i}", True)


# ---------------------------------------------------------------- measuring

def _segments(text: str) -> list[tuple[str, bool]]:
    """Split text on `code` spans: [(piece, is_mono)]."""
    out, pos = [], 0
    for m in CODE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], False))
    return out or [("", False)]


WIDE = re.compile("[✓✗→←↔⇒…]")   # glyphs the font tables lack: the browser draws them from a fallback face, wider


def _width(text: str, style: str, mono: bool = False) -> float:
    mono_style = "vz-nm-mono" if style == "vz-nm" else "vz-mono"
    if not mono:
        text = WIDE.sub("M", text)
    with tm.face("stage"):
        if mono:
            return tm.text_px(text.replace("`", ""), mono_style)
        total = sum(tm.text_px(p, mono_style if m else style) for p, m in _segments(text))
        if style == "vz-zl":
            total += len(text) * ZL_TRACK * 12.5
        return total


def _line(ln: Any) -> dict:
    return {"text": ln} if isinstance(ln, str) else ln


def _content_w(box: dict) -> float:
    w = _width(box["name"], "vz-nm", bool(box.get("mono")))
    for ln in box.get("lines") or []:
        ln = _line(ln)
        w = max(w, _width(ln["text"], "vz-sb", bool(ln.get("mono"))))
    for ch in box.get("children") or []:
        w = max(w, _content_w(ch) + 8)
    return w + BOX_PAD_L + BOX_PAD_R


def _lines_bottom(box: dict) -> float:
    y = NAME_Y
    for ln in box.get("lines") or []:
        y += LINE_STEP + (GAP_STEP if _line(ln).get("gap") else 0)
    return y


def _content_h(box: dict) -> float:
    """Height of a box: its name, its lines, then its children stacked under them."""
    bottom = _lines_bottom(box) + BOX_PAD_B
    for ch in box.get("children") or []:
        top = bottom - BOX_PAD_B + CHILD_GAP + 8
        bottom = top + _content_h(ch) + 12
    return bottom


def _zone_lines(z: dict, width: float) -> list[str]:
    if not z.get("label"):
        return []
    with tm.face("stage"):
        return tm.wrap(z["label"], "vz-zn", max(80.0, width - 32))


# ---------------------------------------------------------------- layout

class _Box:
    __slots__ = ("spec", "x", "y", "w", "h", "parent")

    def __init__(self, spec: dict, x: float, y: float, w: float, h: float, parent: "_Box | None") -> None:
        self.spec, self.x, self.y, self.w, self.h, self.parent = spec, x, y, w, h, parent

    @property
    def r(self) -> float:
        return self.x + self.w

    @property
    def btm(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


class _Grid:
    __slots__ = ("boxes", "col_x", "col_w", "row_y", "row_h", "width", "label_y", "zone_lines", "gaps",
                 "row_labels", "row_label_y")


def _layout(spec: dict, extra: dict[int, float]) -> _Grid:
    cols = spec["columns"]
    top_boxes = spec["boxes"]
    n_cols = len(cols)
    n_rows = max(b["row"] + b.get("rows", 1) for b in top_boxes)
    gaps = [COL_GAP + extra.get(c, 0.0) for c in range(n_cols - 1)]

    col_w = [float(BOX_MIN_W)] * n_cols
    for b in top_boxes:
        if b.get("cols", 1) == 1:
            col_w[b["col"]] = max(col_w[b["col"]], _content_w(b), float(b.get("width", 0)))
    for c, label in enumerate(cols):
        col_w[c] = max(col_w[c], _width(label.upper(), "vz-zl") + 8)
    for b in top_boxes:
        span = b.get("cols", 1)
        if span > 1:
            have = sum(col_w[b["col"]:b["col"] + span]) + sum(gaps[b["col"]:b["col"] + span - 1])
            need = max(_content_w(b), float(b.get("width", 0)))
            if need > have:
                col_w[b["col"] + span - 1] += need - have

    col_x = []
    x = PAD + ZONE_PAD
    for c in range(n_cols):
        col_x.append(x)
        x += col_w[c] + (gaps[c] if c < n_cols - 1 else 0)

    heights = {b["id"]: _content_h(b) for b in top_boxes}
    row_h = [0.0] * n_rows
    for b in top_boxes:
        if b.get("rows", 1) == 1:
            row_h[b["row"]] = max(row_h[b["row"]], heights[b["id"]])
    for b in top_boxes:
        span = b.get("rows", 1)
        if span > 1:
            have = sum(row_h[b["row"]:b["row"] + span]) + ROW_GAP * (span - 1)
            if heights[b["id"]] > have:
                row_h[b["row"] + span - 1] += heights[b["id"]] - have

    by_id = {b["id"]: b for b in top_boxes}
    head = [0.0] * n_rows
    foot = [0.0] * n_rows
    zone_lines = []
    for z in spec.get("zones") or []:
        mem = [by_id[m] for m in z["boxes"]]
        c0 = min(m["col"] for m in mem)
        c1 = max(m["col"] + m.get("cols", 1) for m in mem)
        width = col_x[c1 - 1] + col_w[c1 - 1] - col_x[c0] + 2 * ZONE_PAD
        lines = _zone_lines(z, width)
        zone_lines.append(lines)
        top = min(m["row"] for m in mem)
        head[top] = max(head[top], 12 + ZONE_LINE * max(1, len(lines)))
        last = max(m["row"] + m.get("rows", 1) - 1 for m in mem)
        foot[last] = max(foot[last], ZONE_FOOT)

    row_labels = list(spec.get("row_labels") or []) + [None] * n_rows
    y = PAD
    if spec.get("title"):
        y = TITLE_Y + (SUB_GAP if spec.get("subtitle") else 0) + 10
    label_y = y + 22
    grid_top = label_y + 18
    row_y = []
    row_label_y = []
    y = grid_top
    for r in range(n_rows):
        if row_labels[r]:
            if r > 0:
                y += 6
            row_label_y.append(y + 4)
            y += ROW_LABEL_H
        else:
            row_label_y.append(None)
        y += head[r]
        row_y.append(y)
        y += row_h[r] + foot[r] + ROW_GAP

    placed: dict[str, _Box] = {}

    def place_children(parent: _Box) -> None:
        bottom = _lines_bottom(parent.spec) + BOX_PAD_B
        for ch in parent.spec.get("children") or []:
            top = bottom - BOX_PAD_B + CHILD_GAP + 8
            h = _content_h(ch)
            cb = _Box(ch, parent.x + BOX_PAD_L - 2, parent.y + top, parent.w - BOX_PAD_L - BOX_PAD_R + 4, h, parent)
            placed[ch["id"]] = cb
            place_children(cb)
            bottom = top + h + 12

    for b in top_boxes:
        c, r = b["col"], b["row"]
        span_c, span_r = b.get("cols", 1), b.get("rows", 1)
        w = sum(col_w[c:c + span_c]) + sum(gaps[c:c + span_c - 1])
        if span_r > 1 or b.get("fill"):
            h = row_y[r + span_r - 1] + row_h[r + span_r - 1] - row_y[r]
        else:
            h = heights[b["id"]]
        bx = _Box(b, col_x[c], row_y[r], w, h, None)
        placed[b["id"]] = bx
        place_children(bx)

    g = _Grid()
    g.boxes, g.col_x, g.col_w, g.row_y, g.row_h = placed, col_x, col_w, row_y, row_h
    g.width = col_x[-1] + col_w[-1] + ZONE_PAD + PAD
    g.label_y, g.zone_lines, g.gaps = label_y, zone_lines, gaps
    g.row_labels, g.row_label_y = row_labels[:n_rows], row_label_y
    return g


# ---------------------------------------------------------------- arrows

Pt = tuple
Seg = tuple


def _hits(seg: Seg, box: _Box, pad: float = 2) -> bool:
    (x1, y1), (x2, y2) = seg
    return min(x1, x2) < box.r - pad and max(x1, x2) > box.x + pad and min(y1, y2) < box.btm - pad and max(y1, y2) > box.y + pad


def _family(b: _Box) -> list[_Box]:
    out, p = [b], b.parent
    while p is not None:
        out.append(p)
        p = p.parent
    return out


def _gap_mid(g: _Grid, c: int) -> float:
    return g.col_x[c] + g.col_w[c] + g.gaps[c] / 2


def _channels(g: _Grid) -> tuple[list[float], list[float]]:
    """The free vertical lines (column gaps and the margins) and horizontal lines (row gaps and margins)."""
    xs = [g.col_x[0] - ZONE_PAD - 6] + [_gap_mid(g, c) for c in range(len(g.gaps))] + [g.col_x[-1] + g.col_w[-1] + ZONE_PAD + 6]
    ys = []
    for r in range(len(g.row_y) - 1):
        lo = max(b.btm for b in g.boxes.values() if b.parent is None and b.spec["row"] + b.spec.get("rows", 1) - 1 == r) \
            if any(b.parent is None and b.spec["row"] + b.spec.get("rows", 1) - 1 == r for b in g.boxes.values()) else g.row_y[r] + g.row_h[r]
        ys.append((lo + g.row_y[r + 1]) / 2)
    ys = [g.row_y[0] - 14] + ys + [max(b.btm for b in g.boxes.values()) + 16]
    return xs, ys


def _length(pts: list[Pt]) -> float:
    return sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) for p, q in zip(pts, pts[1:])) + BEND * (len(pts) - 2)


def _route(a: dict, A: _Box, B: _Box, g: _Grid, lanes: dict) -> list[Pt]:
    """Points of an orthogonal route from A to B: straight when the boxes face each other, else one turn,
    else the shortest clear path through a gap between columns or rows. `lanes` counts arrows already
    using each gap line, so arrows sharing a gap get their own lane."""
    if a.get("points"):
        return [(float(x), float(y)) for x, y in a["points"]]
    fam = _family(A) + _family(B)
    others = [b for b in g.boxes.values() if b not in fam and A not in _family(b) and B not in _family(b)]
    # a box that holds A or B is no obstacle, but the name and lines above its child are
    for child in (A, B):
        if child.parent is not None:
            par = child.parent
            others.append(_Box({"id": "_head"}, par.x, par.y, par.w, max(1.0, child.y - par.y - 6), None))
    off_a = float(a.get("offset", 0))
    off_b = float(a.get("offset_to", a.get("offset", 0)))

    def clear(pts: list[Pt]) -> bool:
        return not any(_hits(s, o) for s in zip(pts, pts[1:]) for o in others)

    def crossings(pts: list[Pt]) -> int:
        return sum(1 for s in zip(pts, pts[1:]) for o in others if _hits(s, o))

    cand: list[tuple[str, list[Pt]]] = []
    lo, hi = max(A.y, B.y), min(A.btm, B.btm)
    lx, hx = max(A.x, B.x), min(A.r, B.r)
    if hi - lo >= 24:
        y = (lo + hi) / 2 + off_a
        if B.x >= A.r:
            cand.append(("straight", [(A.r, y), (B.x - ARROW_GAP, y)]))
        elif B.r <= A.x:
            cand.append(("straight", [(A.x, y), (B.r + ARROW_GAP, y)]))
    if hx - lx >= 24:
        x = (lx + hx) / 2 + off_a
        if B.y >= A.btm:
            cand.append(("straight", [(x, A.btm), (x, B.y - ARROW_GAP)]))
        elif B.btm <= A.y:
            cand.append(("straight", [(x, A.y), (x, B.btm + ARROW_GAP)]))

    right, down = B.cx > A.cx, B.cy > A.cy
    ax, ay = (A.r if right else A.x), A.cy + off_a
    bx, by = B.cx + off_b, (B.y - ARROW_GAP) if down else (B.btm + ARROW_GAP)
    if (right and bx > ax + 20) or (not right and bx < ax - 20):
        cand.append(("hv", [(ax, ay), (bx, ay), (bx, by)]))
    ax2, ay2 = A.cx + off_a, (A.btm if down else A.y)
    bx2, by2 = (B.x - ARROW_GAP) if right else (B.r + ARROW_GAP), B.cy + off_b
    if (down and by2 > ay2 + 20) or (not down and by2 < ay2 - 20):
        cand.append(("vh", [(ax2, ay2), (ax2, by2), (bx2, by2)]))

    xs, ys = _channels(g)
    chan: list[tuple[str, list[Pt], tuple]] = []
    for gx in xs:
        k = lanes.get(("x", round(gx)), 0)
        x = gx + ((k + 1) // 2) * CHANNEL * (1 if k % 2 else -1)
        if A.x - 2 <= x <= A.r + 2 or B.x - 2 <= x <= B.r + 2:
            continue
        sa = A.r if x > A.r else A.x
        sb = (B.x - ARROW_GAP) if x < B.x else (B.r + ARROW_GAP)
        chan.append(("hvh", [(sa, A.cy + off_a), (x, A.cy + off_a), (x, B.cy + off_b), (sb, B.cy + off_b)], ("x", round(gx))))
    for gy in ys:
        k = lanes.get(("y", round(gy)), 0)
        y = gy + ((k + 1) // 2) * CHANNEL * (1 if k % 2 else -1)
        if A.y - 2 <= y <= A.btm + 2 or B.y - 2 <= y <= B.btm + 2:
            continue
        sa = A.btm if y > A.btm else A.y
        sb = (B.y - ARROW_GAP) if y < B.y else (B.btm + ARROW_GAP)
        chan.append(("vhv", [(A.cx + off_a, sa), (A.cx + off_a, y), (B.cx + off_b, y), (B.cx + off_b, sb)], ("y", round(gy))))

    want = a.get("path", "auto")
    pick = None
    if want != "auto":
        pool = [(n, p, None) for n, p in cand] + chan
        named = [c for c in pool if c[0] == want]
        if named:
            pick = min(named, key=lambda c: (crossings(c[1]), _length(c[1])))
    if pick is None:
        pick = next(((n, p, None) for n, p in cand if clear(p)), None)
    if pick is None:
        ok = sorted((c for c in chan if clear(c[1])), key=lambda c: _length(c[1]))
        pick = ok[0] if ok else None
    if pick is None:
        pick = (cand[0][0], cand[0][1], None) if cand else ("line", [(A.cx, A.cy), (B.cx, B.cy)], None)
    if pick[2] is not None:
        lanes[pick[2]] = lanes.get(pick[2], 0) + 1
    return pick[1]


def _spread(routed: list[tuple[dict, list[Pt]]]) -> None:
    """Arrows of one layer that leave from, or arrive at, the very same point are moved apart, so each
    keeps its own line. The run touching the shared point shifts sideways, 12 px per arrow."""
    for end in (0, -1):
        seen: dict[tuple, int] = {}
        for a, pts in routed:
            if a.get("points") or len(pts) < 3:
                continue
            key = (a.get("layer", "base"), round(pts[end][0]), round(pts[end][1]))
            k = seen.get(key, 0)
            seen[key] = k + 1
            if k == 0:
                continue
            d = 12 * ((k + 1) // 2) * (1 if k % 2 else -1)
            i, j = (0, 1) if end == 0 else (-1, -2)
            p, q = pts[i], pts[j]
            if abs(p[1] - q[1]) < 1:       # the run is horizontal: shift it up or down
                pts[i], pts[j] = (p[0], p[1] + d), (q[0], q[1] + d)
            else:                           # vertical: shift it left or right
                pts[i], pts[j] = (p[0] + d, p[1]), (q[0] + d, q[1])


def _rect_hits_seg(r: tuple[float, float, float, float], s: Seg) -> bool:
    x, y, w, h = r
    (x1, y1), (x2, y2) = s
    return min(x1, x2) < x + w and max(x1, x2) > x and min(y1, y2) < y + h and max(y1, y2) > y


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _label_spots(pts: list[Pt], w: float, badge: Pt | None, h: float = LABEL_H):
    """Candidate spots for a label of height `h` beside each run of its arrow: longest run first, positions
    nearest the run's middle first, every 12 px, on both sides. A spot never covers the arrow's own badge.
    Each spot is (rect, (x, first baseline, anchor))."""
    segs = sorted(zip(pts, pts[1:]), key=lambda s: -(abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1])))
    out = []
    for p, q in segs:
        horiz = abs(p[1] - q[1]) < 1
        lo, hi = (min(p[0], q[0]), max(p[0], q[0])) if horiz else (min(p[1], q[1]), max(p[1], q[1]))
        span = (w / 2 + 6) if horiz else (h / 2 + 4)
        if hi - lo < 2 * span:
            centres = [(lo + hi) / 2]
        else:
            mid = (lo + hi) / 2
            centres = sorted(_frange(lo + span, hi - span, 12), key=lambda c: abs(c - mid))
        for c in centres:
            if horiz:
                spots = [((c - w / 2, p[1] - h - 6, w, h), (c, p[1] - h - 6 + 13, "middle")),
                         ((c - w / 2, p[1] + 6, w, h), (c, p[1] + 20, "middle"))]
            else:
                spots = [((p[0] + 10, c - h / 2 - 4, w, h), (p[0] + 12, c - h / 2 + 9, "")),
                         ((p[0] - 12 - w, c - h / 2 - 4, w, h), (p[0] - 12, c - h / 2 + 9, "end"))]
            for rect, where in spots:
                if badge and _overlaps(rect, (badge[0] - BADGE_R - 4, badge[1] - BADGE_R - 4, 2 * BADGE_R + 8, 2 * BADGE_R + 8)):
                    continue
                out.append((rect, where))
    return out


def _free_spot(at: Pt, w: float, rects: list, segs: list, width: float, h: float = LABEL_H):
    """The free spot for a label of height `h` nearest `at`, searched outward in rings, or None."""
    best = None
    for dy in range(-140, 141, 10):
        for dx in range(-320, 321, 16):
            cx, cy = at[0] + dx, at[1] + dy
            rect = (cx - w / 2, cy - h / 2, w, h)
            if rect[0] < PAD or rect[0] + w > width - PAD or rect[1] < 8:
                continue
            d = dx * dx + 3 * dy * dy
            if best is not None and d >= best[0]:
                continue
            pad = (rect[0] - 6, rect[1] - 4, w + 12, h + 8)
            if any(_overlaps(pad, r) for r in rects) or any(_rect_hits_seg(pad, s) for s in segs):
                continue
            best = (d, (rect, (cx, cy - h / 2 + 13, "middle")))
    return best[1] if best else None


def _frange(a: float, b: float, step: float) -> list[float]:
    out, x = [], a
    while x <= b + 0.01:
        out.append(x)
        x += step
    return out or [a]


def _badge_at(pts: list[Pt]) -> Pt:
    """A step badge sits on the first run long enough to hold it, just after the run's start."""
    for p, q in zip(pts, pts[1:]):
        length = abs(p[0] - q[0]) + abs(p[1] - q[1])
        if length >= 4 * BADGE_R:
            k = min(BADGE_R + 10, length / 2) / length
            return (p[0] + (q[0] - p[0]) * k, p[1] + (q[1] - p[1]) * k)
    p, q = pts[0], pts[-1]
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)


# ---------------------------------------------------------------- drawing

def _attrs(b: Any = None, r: Any = None, *, base: bool = False, route: bool = False, key: str = "") -> str:
    out = ' data-p="1"'
    if key:
        out += f' data-key="{escape(key, quote=True)}"'
    if b is not None:
        out += f' data-b="{int(b)}"'
    if r is not None:
        out += f' data-r="{int(r)}"'
    if base:
        out += ' data-base="1"'
    if route:
        out += ' data-route="1"'
    return out


def _text(cls: str, x: float, y: float, text: str, extra: str = "", anchor: str = "") -> str:
    """A text element; `code` spans become mono tspans. Everything is escaped."""
    a = f' text-anchor="{anchor}"' if anchor else ""
    parts = _segments(text)
    if len(parts) == 1 and not parts[0][1]:
        body = escape(parts[0][0], quote=False)
    else:
        body = "".join(f'<tspan class="mono">{escape(p, quote=False)}</tspan>' if m else escape(p, quote=False) for p, m in parts)
    return f'<text class="{cls}" x="{x:.0f}" y="{y:.0f}"{a}{extra}>{body}</text>'


def _cls(*names: str) -> str:
    return " ".join(n for n in names if n and n != "plain")


def _markers(uid: str) -> str:
    heads = [("a", "ah"), ("b", "ah blue"), ("r", "ah red"), ("g", "ah green"), ("m", "ah amber"), ("on", "ah on")]
    return "<defs>" + "".join(
        f'<marker id="{uid}-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="{4.4 if k == "on" else 7}" '
        f'markerHeight="{4.4 if k == "on" else 7}" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="{c}"/></marker>'
        for k, c in heads) + "</defs>"


def arrow_keys(spec: dict[str, Any]) -> list[str]:
    """Each arrow's key, in spec order: a structure arrow is ``edge:<from>-><to>#<n>`` (the n-th from that box to
    that one, counted from 0), a route arrow ``route:<r>``, the route step it belongs to (1 when it has none)."""
    seen: dict[tuple[str, str], int] = {}
    out = []
    for a in spec.get("arrows") or []:
        if a.get("layer", "base") == "route":
            out.append(f"route:{a['r'] if a.get('r') is not None else 1}")
        else:
            pair = (a["from"], a["to"])
            out.append(f"edge:{pair[0]}->{pair[1]}#{seen.get(pair, 0)}")
            seen[pair] = seen.get(pair, 0) + 1
    return out


def _draw(spec: dict, uid: str, g: _Grid, keyed: bool = False) -> tuple[list[str], dict[int, float], float]:
    """Draw everything. Returns the parts, the extra width each gap needs for a label that found no spot, and the width.
    `keyed` stamps each part's key on it (see render)."""
    out: list[str] = []
    width = g.width
    if spec.get("title"):
        out.append(_text("ttl", PAD, TITLE_Y, spec["title"]))
        width = max(width, PAD * 2 + _width(spec["title"], "vz-ttl"))
        if spec.get("subtitle"):
            out.append(_text("sub", PAD, TITLE_Y + SUB_GAP, spec["subtitle"]))
            width = max(width, PAD * 2 + _width(spec["subtitle"], "vz-sb"))
    head_rects: list[tuple[float, float, float, float]] = []
    for c, label in enumerate(spec["columns"]):
        if label:
            out.append(_text("zl", g.col_x[c], g.label_y, label.upper()))
            head_rects.append((g.col_x[c] - 2, g.label_y - 14, _width(label.upper(), "vz-zl") + 4, 18))
    for label, y in zip(g.row_labels, g.row_label_y):
        if label and y is not None:
            out.append(_text("zl", PAD, y + 12, label.upper()))
            head_rects.append((PAD - 2, y - 2, _width(label.upper(), "vz-zl") + 4, 18))

    obstacles: list[tuple[float, float, float, float]] = list(head_rects)
    zone_edges: list[Seg] = []
    for zi, (z, lines) in enumerate(zip(spec.get("zones") or [], g.zone_lines)):
        mem = [g.boxes[m] for m in z["boxes"]]
        head = 12 + ZONE_LINE * max(1, len(lines))
        x0 = min(b.x for b in mem) - ZONE_PAD
        y0 = min(b.y for b in mem) - head
        x1 = max(b.r for b in mem) + ZONE_PAD
        y1 = max(b.btm for b in mem) + ZONE_FOOT - 4
        zr = z.get("r", min((g.boxes[m].spec["r"] for m in z["boxes"] if g.boxes[m].spec.get("r") is not None), default=None))
        zb = z.get("b", min((g.boxes[m].spec["b"] for m in z["boxes"] if g.boxes[m].spec.get("b") is not None), default=None))
        att = _attrs(zb, zr, key=f"zone:{zi}" if keyed else "")
        zone_edges += [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x0, y1), (x1, y1)), ((x0, y0), (x0, y1))]
        out.append(f'<rect class="{_cls("zone", z.get("tone", "plain"))}" x="{x0:.0f}" y="{y0:.0f}" width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" rx="10"{att}/>')
        for i, ln in enumerate(lines):
            out.append(_text(_cls("zn", z.get("tone", "plain")), x0 + 16, y0 + 20 + ZONE_LINE * i, ln, att))
            obstacles.append((x0 + 14, y0 + 6 + ZONE_LINE * i, _width(ln, "vz-zn") + 4, ZONE_LINE))

    badges: list[str] = []

    def draw_box(bx: _Box, inh_b: Any, inh_r: Any) -> None:
        s = bx.spec
        b, r = s.get("b", inh_b), s.get("r", inh_r)
        key = f"box:{s['id']}" if keyed else ""
        att = _attrs(b, r, key=key)
        out.append(f'<rect class="{_cls("bx", s.get("tone", "plain"))}" x="{bx.x:.0f}" y="{bx.y:.0f}" width="{bx.w:.0f}" '
                   f'height="{bx.h:.0f}" rx="{6 if bx.parent else 8}"{att}/>')
        out.append(_text(_cls("nm", "mono" if s.get("mono") else ""), bx.x + BOX_PAD_L, bx.y + NAME_Y, s["name"], att))
        if s.get("n") is not None:
            # a route step that happens inside this box, with no arrow to carry its number
            cx, cy = bx.r - BADGE_R - 8, bx.y + BADGE_R + 8
            badges.append(f'<circle class="bd solid" cx="{cx:.0f}" cy="{cy:.0f}" r="{BADGE_R}"{att}/>')
            badges.append(f'<text class="n" x="{cx:.0f}" y="{cy + 4.5:.1f}"{att}>{int(s["n"])}</text>')
        y = bx.y + NAME_Y
        for ln in s.get("lines") or []:
            ln = _line(ln)
            y += LINE_STEP + (GAP_STEP if ln.get("gap") else 0)
            la = _attrs(ln.get("b", b), ln.get("r", r), key=key)
            out.append(_text(_cls("sb", "mono" if ln.get("mono") else "", ln.get("tone", "plain")), bx.x + BOX_PAD_L, y, ln["text"], la))
        for ch in s.get("children") or []:
            draw_box(g.boxes[ch["id"]], b, r)

    for b in spec["boxes"]:
        draw_box(g.boxes[b["id"]], None, None)

    lanes: dict[int, int] = {}
    routed: list[tuple[dict, list[Pt]]] = []
    for a in spec.get("arrows") or []:
        routed.append((a, _route(a, g.boxes[a["from"]], g.boxes[a["to"]], g, lanes)))
    def layer_of(a: dict) -> str:
        return a.get("layer", "base")

    _spread(routed)
    segs_by = {"base": list(zone_edges), "route": list(zone_edges)}
    for a, pts in routed:
        segs_by[layer_of(a)].extend(zip(pts, pts[1:]))
    box_rects = [(b.x - 2, b.y - 2, b.w + 4, b.h + 4) for b in g.boxes.values() if b.parent is None]
    labels_by = {"base": list(obstacles), "route": list(obstacles)}
    need: dict[int, float] = {}
    top_labels: list[str] = []

    keys = arrow_keys(spec) if keyed else [""] * len(routed)
    for (a, pts), key in zip(routed, keys):
        tone = a.get("tone", "plain")
        route = a.get("layer", "base") == "route"
        att = _attrs(a.get("b"), a.get("r"), base=not route, route=route, key=key)
        d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        out.append(f'<path class="{_cls("ar", tone, "dash" if a.get("dash") else "")}" d="{d}" marker-end="url(#{uid}-{MARK[tone]})"{att}/>')
        badge = None
        if a.get("n") is not None:
            badge = _badge_at(pts)
            top_labels.append(f'<circle class="{_cls("bd", "dash" if a.get("dash") else "solid")}" cx="{badge[0]:.0f}" cy="{badge[1]:.0f}" r="{BADGE_R}"{att}/>')
            top_labels.append(f'<text class="n" x="{badge[0]:.0f}" y="{badge[1] + 4.5:.1f}"{att}>{int(a["n"])}</text>')
            labels_by[layer_of(a)].append((badge[0] - BADGE_R, badge[1] - BADGE_R, 2 * BADGE_R, 2 * BADGE_R))
        if a.get("label"):
            mono = bool(a.get("mono"))
            label_lines = [ln for ln in a["label"].split("\n") if ln.strip()] or [a["label"]]
            w = max(_width(ln, "vz-sb", mono) for ln in label_lines)
            own = list(zip(pts, pts[1:]))
            spot = None
            lh = LABEL_H + LABEL_LINE * (len(label_lines) - 1)
            for rect, where in _label_spots(pts, w, badge, lh):
                if rect[0] < 4 or rect[1] < 4 or rect[0] + rect[2] > g.width - 4:
                    continue
                if any(_overlaps(rect, b) for b in box_rects + labels_by[layer_of(a)]):
                    continue
                if any(_rect_hits_seg(rect, s) for s in segs_by[layer_of(a)] if s not in own):
                    continue
                spot = (rect, where)
                break
            if spot is None and route and badge:
                # a route label needs no gap of its own: put it in the nearest free spot by its badge,
                # with a thin line back to the badge
                spot = _free_spot(badge, w, box_rects + labels_by["route"], segs_by["route"], width, lh)
                if spot is not None:
                    (rx, ry, rw, rh), _ = spot
                    ex = min(max(badge[0], rx), rx + rw)
                    ey = min(max(badge[1], ry), ry + rh)
                    top_labels.append(f'<line class="lk" x1="{badge[0]:.0f}" y1="{badge[1]:.0f}" x2="{ex:.0f}" y2="{ey:.0f}"{att}/>')
            if spot is None:
                # ask for a wider gap where the longest run lies
                (p, q) = max(own, key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
                mx = (p[0] + q[0]) / 2
                run = abs(p[0] - q[0])
                for c in range(len(g.gaps)):
                    lo = g.col_x[c] + g.col_w[c]
                    if lo - 2 <= mx <= lo + g.gaps[c] + 2:
                        want = w + 24 + (2 * BADGE_R + 24 if badge else 0)
                        need[c] = max(need.get(c, 0.0), max(16.0, want - run))
                cands = _label_spots(pts, w, badge, lh)
                spot = cands[0] if cands else ((pts[0][0], pts[0][1] - 24, w, LABEL_H), (pts[0][0], pts[0][1] - 10, ""))
            rect, (tx, ty, anchor) = spot
            labels_by[layer_of(a)].append(rect)
            lcls = _cls("lb", "mono" if mono else "")
            for k, ln in enumerate(label_lines):
                top_labels.append(_text(lcls, tx, ty + LABEL_LINE * k, ln, att, anchor))
    out.extend(top_labels)
    out.extend(badges)
    return out, need, width


def render(spec: dict[str, Any], uid: str, keyed: bool = False) -> str:
    """Validate and draw `spec` as one SVG string. `uid` prefixes every id, so maps can share a page.

    With `keyed`, every part also carries ``data-key``, for a page that reveals and lights parts by key (the
    stage): ``zone:<i>`` (its place in ``zones``), ``box:<id>`` on a box, its name and its lines (a child box
    has its own), and on an arrow, its badge and its label the key ``arrow_keys`` gives it. Without it the
    output is exactly what it was before keys existed."""
    validate(spec)
    if not re.fullmatch(r"[A-Za-z][\w-]{0,40}", uid or ""):
        raise ValidationError(f"uid {uid!r}: letters, digits, - and _, starting with a letter")
    extra: dict[int, float] = {}
    for _ in range(4):
        g = _layout(spec, extra)
        out, need, width = _draw(spec, uid, g, keyed)
        if not need:
            break
        for c, more in need.items():
            extra[c] = extra.get(c, 0.0) + max(8.0, more)

    bottom = max(b.btm for b in g.boxes.values()) + (ZONE_FOOT if spec.get("zones") else 0)
    legend = spec.get("legend") or []
    if legend:
        y = bottom + 36
        x = PAD
        for item in legend:
            tone = item.get("tone", "plain")
            step = len(item["label"]) and _width(item["label"], "vz-sb") + 44 + 30
            if x + step > width - PAD and x > PAD:
                x, y = PAD, y + LEGEND_ROW
            if item.get("kind") == "note":
                out.append(_text("sb", x, y, item["label"]))
                x += _width(item["label"], "vz-sb") + 30
                continue
            if item.get("kind") == "box":
                out.append(f'<rect class="{_cls("bx", tone)}" x="{x}" y="{y - 12}" width="28" height="16" rx="4"/>')
            else:
                out.append(f'<line class="{_cls("ar", tone, "dash" if item.get("dash") else "")}" x1="{x}" y1="{y - 4}" '
                           f'x2="{x + 34}" y2="{y - 4}" marker-end="url(#{uid}-{MARK[tone]})"/>')
            out.append(_text("sb", x + 44, y, item["label"]))
            x += step
        bottom = y + 8
    height = bottom + PAD
    aria = escape(spec.get("aria") or spec.get("title") or "Architecture map", quote=True)
    return (f'<svg class="vz" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="{aria}" data-vz="map">'
            + _markers(uid) + "".join(out) + "</svg>")


def step_counts(spec: dict[str, Any]) -> tuple[int, int]:
    """(last build step, last route step) of a map, 0 when it has none."""
    nb = nr = 0

    def take(o: dict) -> None:
        nonlocal nb, nr
        if isinstance(o.get("b"), int):
            nb = max(nb, o["b"])
        if isinstance(o.get("r"), int):
            nr = max(nr, o["r"])

    def walk(b: dict) -> None:
        take(b)
        for ln in b.get("lines") or []:
            if isinstance(ln, dict):
                take(ln)
        for ch in b.get("children") or []:
            walk(ch)

    for b in spec.get("boxes") or []:
        walk(b)
    for z in spec.get("zones") or []:
        take(z)
    for a in spec.get("arrows") or []:
        take(a)
    return nb, nr
