"""One check of the words a diagram board draws, shared by the flowchart, sequence and map: a label is a few words
(LABEL_MAX characters), a sub or a line of detail one short sentence (SUB_MAX), and a whole spec has a size (SPEC_MAX
characters as JSON). Each refusal names the board part, the field, how long it is and the most it may be. The three
boards call `check_flowchart`, `check_sequence` and `check_map` from their own validators, with their own error class.
Pure functions, no I/O."""
from __future__ import annotations

import json
from typing import Any

LABEL_MAX = 60     # characters: a name, a step's label, an arrow's label, a column or zone title
SUB_MAX = 120      # characters: a sub, a line under a name, one line of detail
SPEC_MAX = 80_000  # characters of JSON: a board bigger than this is a document, not a picture


def check_text(text: Any, where: str, field: str, err: type[Exception], most: int = LABEL_MAX) -> None:
    """Refuse `text` when it is longer than `most` characters. Anything that is not text is left to the board's own check."""
    if isinstance(text, str) and len(text) > most:
        kind = "a label is a few words" if most == LABEL_MAX else "a sub is one short sentence"
        raise err(f"{where}: {field} is {len(text)} characters, at most {most}: {kind}, say it shorter")


def check_size(spec: Any, err: type[Exception]) -> None:
    """Refuse a spec whose JSON is longer than SPEC_MAX characters."""
    try:
        size = len(json.dumps(spec, default=str))
    except (TypeError, ValueError):
        return
    if size > SPEC_MAX:
        raise err(f"the spec is {size} characters, at most {SPEC_MAX}: cut it to the parts that carry the point")


def _items(spec: Any, key: str) -> list[dict]:
    v = spec.get(key) if isinstance(spec, dict) else None
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def check_flowchart(spec: dict, err: type[Exception]) -> None:
    check_size(spec, err)
    for n in _items(spec, "nodes"):
        where = f"node {n.get('id')!r}"
        check_text(n.get("label"), where, "label", err)
        check_text(n.get("sub"), where, "sub", err, SUB_MAX)
    for e in _items(spec, "edges"):
        check_text(e.get("label"), f"edge {e.get('from')}->{e.get('to')}", "label", err)
    for g in _items(spec, "groups"):
        check_text(g.get("label"), f"group {g.get('id')!r}", "label", err)


def check_sequence(spec: dict, err: type[Exception]) -> None:
    check_size(spec, err)
    for a in _items(spec, "actors"):
        check_text(a.get("label"), f"actor {a.get('id')!r}", "label", err)
    for s in _items(spec, "steps"):
        where = f"step {s.get('id')}"
        check_text(s.get("label"), where, "label", err)
        check_text(s.get("sub"), where, "sub", err, SUB_MAX)
    for p in _items(spec, "phases"):
        check_text(p.get("label"), f"phase {p.get('id')}", "label", err)


def check_map(spec: dict, err: type[Exception]) -> None:
    check_size(spec, err)
    cols = spec.get("columns")
    for i, c in enumerate(cols if isinstance(cols, list) else []):
        check_text(c, f"column {i}", "label", err)

    def box(b: dict) -> None:
        where = f"box {b.get('id')!r}"
        check_text(b.get("name"), where, "name", err)
        for ln in b.get("lines") or []:
            check_text(ln.get("text") if isinstance(ln, dict) else ln, where, "line", err, SUB_MAX)
        for ch in _items(b, "children"):
            box(ch)

    for b in _items(spec, "boxes"):
        box(b)
    for i, z in enumerate(_items(spec, "zones")):
        check_text(z.get("label"), f"zone {i}", "label", err)
    for i, a in enumerate(_items(spec, "arrows")):
        lab = a.get("label")
        for ln in (lab.split("\n") if isinstance(lab, str) else []):
            check_text(ln, f"arrow {i}", "label", err)
