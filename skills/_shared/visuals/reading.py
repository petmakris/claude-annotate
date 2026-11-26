"""What a screen reader says of a drawn board: the lines behind a map, a graph or a bars board.

The drawing is one svg image, so the connections it shows are also given as a list the stage keeps out of sight but in the
accessibility tree. This module makes the list from the spec, where the arrows and rows are known: one item per arrow with the
names of both ends, its label and whether it is dashed, one per bars row with its value, and for a graph the nodes a change
adds, leaves behind or removes. The items are data (`kind` and the words of the spec); the stage puts the connecting words
round them in the page's language (words.js, keys `read.*`). Pure functions, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from . import bars_svg


def _plain(text: Any) -> str:
    """A name as it is said: backtick marks gone, line breaks and runs of spaces one space."""
    return re.sub(r"\s+", " ", str(text or "").replace("`", "")).strip()


def _boxes(boxes: list[dict], out: dict[str, str]) -> None:
    for b in boxes:
        out[b["id"]] = _plain(b.get("name")) or b["id"]
        _boxes(b.get("children") or [], out)


def map_reading(spec: dict[str, Any]) -> dict[str, Any]:
    names: dict[str, str] = {}
    _boxes(spec.get("boxes") or [], names)
    items = []
    for a in spec.get("arrows") or []:
        item = {"kind": "edge", "from": names.get(a["from"], a["from"]), "to": names.get(a["to"], a["to"]), "label": _plain(a.get("label"))}
        if a.get("dash"):
            item["dashed"] = True
        items.append(item)
    return {"title": "arrows", "items": items}


def graph_reading(spec: dict[str, Any]) -> dict[str, Any]:
    names = {n["id"]: _plain(n.get("label")) or n["id"] for n in spec.get("nodes") or []}
    items = [{"kind": "link", "from": names[e["from"]], "to": names[e["to"]], "label": _plain(e.get("label"))}
             for e in spec.get("edges") or []]
    for n in spec.get("nodes") or []:
        if n.get("state", "same") != "same":
            items.append({"kind": "state", "label": names[n["id"]], "state": n["state"]})
    return {"title": "arrows", "items": items}


def bars_reading(spec: dict[str, Any]) -> dict[str, Any]:
    unit, dec = spec["unit"], bars_svg._decimal(spec)
    items = []
    for b in spec.get("bars") or []:
        item = {"kind": "bar", "label": _plain(b["label"]), "value": bars_svg._chip_text(b["value"], unit, dec)}
        if b.get("note"):
            item["note"] = _plain(b["note"])
        items.append(item)
    t = spec.get("threshold")
    if t:
        items.append({"kind": "threshold", "label": _plain(t.get("label")), "value": bars_svg._chip_text(t["value"], unit, dec)})
    return {"title": "values", "items": items}


READING = {"map": map_reading, "graph": graph_reading, "bars": bars_reading}


def reading(tool: str, spec: dict[str, Any]) -> dict[str, Any]:
    """The reading list of a drawn board (`map`, `graph` or `bars`): {title, items}."""
    return READING[tool](spec)
