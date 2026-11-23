"""Turn the SVG of `map_svg.render(spec, uid, keyed=True)` into a list of shapes with final coordinates, for the
IntelliJ plugin to paint with Java2D. Every drawn element is kept; an element, class or path command this does not
know fails the build, so a change in map_svg cannot silently drop shapes.

Shapes (all coordinates absolute, in the SVG's own pixels):
  rect    x y w h r role(zone|box) tone dashed key
  path    points role(arrow|leader|legend) tone dashed arrow key     (a `line` becomes a two-point path)
  circle  x y r role(badge) tone dashed key
  text    x y anchor role size weight tone key runs[{text, mono}]
Text sizes and weights are those of vz.css."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

TONES = ("blue", "red", "green", "amber")
# class of a text element -> (role, size, weight); `nm` with an all-mono run is 14.5 (vz.css `.nm.mono`)
TEXT = {"ttl": ("title", 22, 700), "sub": ("subtitle", 13, 400), "zl": ("column", 12.5, 600),
        "nm": ("name", 15.5, 600), "sb": ("line", 13, 400), "lb": ("label", 13, 400),
        "zn": ("zone", 13, 600), "n": ("badge", 12.5, 700)}
SKIP = ("defs", "marker")
NUM = r"-?\d+(?:\.\d+)?"


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _classes(el, known: tuple, what: str) -> List[str]:
    cls = (el.get("class") or "").split()
    for c in cls:
        if c not in known and c not in TONES:
            raise ValueError(f"unknown class {c!r} on <{what}>")
    return cls


def _tone(cls: List[str]) -> str:
    return next((c for c in cls if c in TONES), "plain")


def _num(el, name: str) -> float:
    v = float(el.get(name, "0"))
    return int(v) if v == int(v) else v


def _points(d: str) -> List[List[float]]:
    parts = re.findall(r"([A-Za-z])\s*([^A-Za-z]*)", d)
    pts: List[List[float]] = []
    for cmd, args in parts:
        if cmd not in ("M", "L"):
            raise ValueError(f"unknown path command {cmd!r} in {d!r}")
        nums = re.findall(NUM, args)
        if len(nums) != 2:
            raise ValueError(f"path command {cmd} needs one point in {d!r}")
        x, y = (float(n) for n in nums)
        pts.append([int(x) if x == int(x) else x, int(y) if y == int(y) else y])
    if len(pts) < 2:
        raise ValueError(f"path with fewer than two points: {d!r}")
    return pts


def _runs(el, text_cls: List[str]) -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    if el.text:
        runs.append({"text": el.text, "mono": False})
    for t in el:
        if _tag(t) != "tspan":
            raise ValueError(f"unknown element <{_tag(t)}> inside <text>")
        tc = (t.get("class") or "").split()
        if tc != ["mono"]:
            raise ValueError(f"unknown class {' '.join(tc)!r} on <tspan>")
        runs.append({"text": t.text or "", "mono": True})
        if t.tail:
            runs.append({"text": t.tail, "mono": False})
    return runs


def _shape(el) -> Optional[Dict[str, Any]]:
    tag = _tag(el)
    key = el.get("data-key")
    if tag == "rect":
        cls = _classes(el, ("bx", "zone"), "rect")
        if "zone" in cls:
            role = "zone"
        elif "bx" in cls:
            role = "box"
        else:
            raise ValueError(f"unknown class {' '.join(cls)!r} on <rect>")
        return {"kind": "rect", "x": _num(el, "x"), "y": _num(el, "y"), "w": _num(el, "width"), "h": _num(el, "height"),
                "r": _num(el, "rx"), "role": role, "tone": _tone(cls), "dashed": role == "zone", "key": key}
    if tag == "path":
        cls = _classes(el, ("ar", "dash"), "path")
        if "ar" not in cls:
            raise ValueError(f"unknown class {' '.join(cls)!r} on <path>")
        return {"kind": "path", "points": _points(el.get("d", "")), "role": "arrow", "tone": _tone(cls),
                "dashed": "dash" in cls, "arrow": bool(el.get("marker-end")), "key": key}
    if tag == "line":
        cls = _classes(el, ("ar", "dash", "lk"), "line")
        pts = [[_num(el, "x1"), _num(el, "y1")], [_num(el, "x2"), _num(el, "y2")]]
        if "lk" in cls:
            return {"kind": "path", "points": pts, "role": "leader", "tone": "plain", "dashed": True,
                    "arrow": False, "key": key}
        if "ar" not in cls:
            raise ValueError(f"unknown class {' '.join(cls)!r} on <line>")
        return {"kind": "path", "points": pts, "role": "legend", "tone": _tone(cls), "dashed": "dash" in cls,
                "arrow": bool(el.get("marker-end")), "key": key}
    if tag == "circle":
        cls = _classes(el, ("bd", "solid", "dash"), "circle")
        if "bd" not in cls:
            raise ValueError(f"unknown class {' '.join(cls)!r} on <circle>")
        return {"kind": "circle", "x": _num(el, "cx"), "y": _num(el, "cy"), "r": _num(el, "r"), "role": "badge",
                "tone": "blue", "dashed": "dash" in cls, "key": key}
    if tag == "text":
        cls = _classes(el, tuple(TEXT) + ("mono",), "text")
        base = [c for c in cls if c in TEXT]
        if len(base) != 1:
            raise ValueError(f"unknown class {' '.join(cls)!r} on <text>")
        role, size, weight = TEXT[base[0]]
        runs = _runs(el, cls)
        if "mono" in cls:  # the whole text is mono (a name or line marked `mono`)
            runs = [dict(r, mono=True) for r in runs]
        if base[0] == "nm" and runs and all(r["mono"] for r in runs):
            size = 14.5
        anchor = el.get("text-anchor") or ("middle" if role == "badge" else "start")
        return {"kind": "text", "x": _num(el, "x"), "y": _num(el, "y"), "anchor": anchor, "role": role,
                "size": size, "weight": weight, "tone": _tone(cls), "key": key, "runs": runs}
    raise ValueError(f"unknown element <{tag}>")


def svg_to_drawing(svg: str) -> Dict[str, Any]:
    root = ET.fromstring(svg)
    if _tag(root) != "svg":
        raise ValueError(f"expected <svg>, got <{_tag(root)}>")
    vb = re.findall(NUM, root.get("viewBox", ""))
    if len(vb) != 4:
        raise ValueError("the svg has no viewBox")
    shapes = []
    for el in root:
        if _tag(el) in SKIP:
            continue
        shapes.append(_shape(el))
    return {"width": int(float(vb[2])), "height": int(float(vb[3])), "shapes": shapes}
