"""dataflow.json persistence for the dataflow skill.

One document per session at <state_dir>/dataflow.json:

    {
      "seed": "InteractionChannel",     # what the user asked about
      "question": "...",                # their words, verbatim
      "generated_ts": <int>,            # epoch seconds, bumped on (re)generation
      "model": ["...", "..."],          # the derived model, as claims
      "slices": [
        {"id": "config", "title": "Channel catalogue",
         "question": "which channels does this bank offer?",
         "nodes": [
           {"id": "icm", "layer": "domain", "role": "Domain",
            "name": "InteractionChannelManagement",
            "file": "advisory/.../InteractionChannelManagement.java", "line": 13,
            "summary": "...", "note": "...", "flag": "no JPA entity",
            "implicit": false,
            "members": [{"text": "public InteractionChannel(String code, ...)",
                          "line": 19, "tag": "record",
                          "detail": "markdown; makes the row expandable"}],
            "edges": [{"to": "psvc", "label": "read by", "join": true}]}
         ]}
      ]
    }

Every node carries a real `file` and `line`: the page's only way to reach code
is `POST /api/open`, so a node without an anchor is a node the reader cannot
follow. That is why `file`/`line` are required and not optional — including on
`implicit` mapper nodes, whose anchor is the place the framework is configured
rather than a mapper class that does not exist.

Node ids are unique across the WHOLE document, not per slice: a thread anchor
is `node:<id>`, and per-slice ids would make two nodes share one thread.

The document is frozen once written — only per-node threads change afterwards —
and is written atomically so a reader never sees a half-written file.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from skills._shared.web_companion.atomic import write_text_atomic

# The layer vocabulary. Deliberately small and framework-neutral: the server
# knows nothing about Java, Spring or DDD — SKILL.md owns that mapping.
# `mapper` is the only one with layout meaning: those nodes render on the arrow
# gutter between their neighbours rather than in the column.
LAYERS = ("api", "mapper", "application", "domain", "infra", "db")

MIN_SLICES, MAX_SLICES = 1, 4
MIN_NODES, MAX_NODES = 2, 24      # per slice
MAX_TOTAL_NODES = 48              # a runaway generator is a bug, not a diagram
MAX_MODEL_CLAIMS = 6
MAX_TAG_LEN = 12            # a member badge: GET, PUT, @Transactional, throws
MAX_SUMMARY_LEN = 180       # one line about the node, never a list of its members
MAX_ROUTES = 24             # traced properties held on one document
MIN_HOPS = 2                # a route with one point is not a path

FLOW_FILE = "dataflow.json"
_ANCHOR_RE = re.compile(r"^node:([a-z0-9][a-z0-9_-]{0,39})$")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def validate(doc: dict) -> list[str]:
    """Return a list of human-readable problems; empty means valid."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document must be an object"]
    for field in ("seed", "question"):
        if not isinstance(doc.get(field), str) or not doc[field].strip():
            errors.append(f"{field} must be a non-empty string")
    ts = doc.get("generated_ts")
    if not isinstance(ts, int) or isinstance(ts, bool) or ts <= 0:
        errors.append("generated_ts must be a positive integer")
    errors.extend(_model_errors(doc.get("model")))

    slices = doc.get("slices")
    if not isinstance(slices, list):
        return errors + ["slices must be a list"]
    if not MIN_SLICES <= len(slices) <= MAX_SLICES:
        errors.append(f"slices must contain {MIN_SLICES}-{MAX_SLICES} slices")

    seen_slice_ids: set[str] = set()
    node_ids: set[str] = set()
    edge_targets: list[tuple[str, str]] = []
    total_nodes = 0

    for i, sl in enumerate(slices):
        where = f"slices[{i}]"
        if not isinstance(sl, dict):
            errors.append(f"{where} must be an object")
            continue
        sid = sl.get("id")
        if not _is_id(sid):
            errors.append(f"{where} id must match [a-z0-9][a-z0-9_-]*")
        elif sid in seen_slice_ids:
            errors.append(f"{where} duplicate slice id {sid!r}")
        else:
            seen_slice_ids.add(sid)
        if not isinstance(sl.get("title"), str) or not sl["title"].strip():
            errors.append(f"{where} title must be a non-empty string")
        q = sl.get("question")
        if q is not None and (not isinstance(q, str) or not q.strip()):
            errors.append(f"{where} question, when present, must be non-empty")

        nodes = sl.get("nodes")
        if not isinstance(nodes, list):
            errors.append(f"{where} nodes must be a list")
            continue
        if not MIN_NODES <= len(nodes) <= MAX_NODES:
            errors.append(f"{where} must contain {MIN_NODES}-{MAX_NODES} nodes")
        total_nodes += len(nodes)
        for j, n in enumerate(nodes):
            errors.extend(_node_errors(f"{where}.nodes[{j}]", n, node_ids, edge_targets))

    if total_nodes > MAX_TOTAL_NODES:
        errors.append(f"the document must contain at most {MAX_TOTAL_NODES} nodes "
                      f"in total (got {total_nodes}) — narrow the question")

    # Cross-references last, once every id is known. A dangling edge renders as
    # a button that scrolls nowhere, which reads as a broken page rather than a
    # missing node.
    for owner, target in edge_targets:
        if target not in node_ids:
            errors.append(f"{owner} edge points at unknown node {target!r}")
    errors.extend(_route_errors(doc.get("routes"), slices))
    return errors


def _route_errors(routes: object, slices: object) -> list[str]:
    """A route is one property's path, as a list of rows that already exist.

    Every hop names a (node, field) pair, and both must resolve — a hop that
    points at nothing highlights nothing, which reads to the user as the route
    being wrong about the code rather than the document being wrong about
    itself.
    """
    if routes is None:
        return []
    if not isinstance(routes, list):
        return ["routes must be a list"]
    if len(routes) > MAX_ROUTES:
        return [f"routes must contain at most {MAX_ROUTES} routes"]

    # (node_id, field) -> exists
    known: set[tuple[str, str]] = set()
    if isinstance(slices, list):
        for sl in slices:
            if not isinstance(sl, dict):
                continue
            for n in sl.get("nodes", []) or []:
                if not isinstance(n, dict) or not isinstance(n.get("id"), str):
                    continue
                for m in n.get("members", []) or []:
                    if isinstance(m, dict) and isinstance(m.get("field"), str):
                        known.add((n["id"], m["field"]))

    errors: list[str] = []
    seen: set[str] = set()
    for i, r in enumerate(routes):
        where = f"routes[{i}]"
        if not isinstance(r, dict):
            errors.append(f"{where} must be an object")
            continue
        rid = r.get("id")
        if not _is_id(rid):
            errors.append(f"{where} id must match [a-z0-9][a-z0-9_-]*")
        elif rid in seen:
            errors.append(f"{where} duplicate route id {rid!r}")
        else:
            seen.add(rid)
        for field in ("label", "title"):
            if not isinstance(r.get(field), str) or not r[field].strip():
                errors.append(f"{where} {field} must be a non-empty string")
        note = r.get("note")
        if note is not None and (not isinstance(note, str) or not note.strip()):
            errors.append(f"{where} note, when present, must be non-empty")
        hops = r.get("hops")
        if not isinstance(hops, list):
            errors.append(f"{where} hops must be a list")
            continue
        if len(hops) < MIN_HOPS:
            errors.append(f"{where} must have at least {MIN_HOPS} hops "
                          "— a single point is not a path")
        for j, h in enumerate(hops):
            hw = f"{where}.hops[{j}]"
            if not isinstance(h, dict):
                errors.append(f"{hw} must be an object")
                continue
            node, field = h.get("node"), h.get("field")
            if not _is_id(node) or not _is_id(field):
                errors.append(f"{hw} must name a node and a field")
                continue
            if (node, field) not in known:
                errors.append(f"{hw} points at {node}.{field}, which no member "
                              "declares — add `field` to that member row")
            for opt in ("rename", "fork", "destination"):
                if opt in h and not isinstance(h[opt], bool):
                    errors.append(f"{hw} {opt} must be a boolean")
    return errors


def _model_errors(model: object) -> list[str]:
    if model is None:
        return []
    if not isinstance(model, list):
        return ["model must be a list of strings"]
    if len(model) > MAX_MODEL_CLAIMS:
        return [f"model must contain at most {MAX_MODEL_CLAIMS} claims"]
    return [f"model[{i}] must be a non-empty string"
            for i, m in enumerate(model)
            if not isinstance(m, str) or not m.strip()]


def _node_errors(where: str, n: object, node_ids: set[str],
                 edge_targets: list[tuple[str, str]]) -> list[str]:
    errors: list[str] = []
    if not isinstance(n, dict):
        return [f"{where} must be an object"]
    nid = n.get("id")
    if not _is_id(nid):
        errors.append(f"{where} id must match [a-z0-9][a-z0-9_-]*")
    elif nid in node_ids:
        errors.append(f"{where} duplicate node id {nid!r} "
                      "(ids are unique across the whole document)")
    else:
        node_ids.add(nid)
    if n.get("layer") not in LAYERS:
        errors.append(f"{where} layer must be one of {list(LAYERS)}")
    for field in ("role", "name"):
        if not isinstance(n.get(field), str) or not n[field].strip():
            errors.append(f"{where} {field} must be a non-empty string")
    errors.extend(_file_errors(where, n.get("file")))
    line = n.get("line")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        errors.append(f"{where} line must be a positive integer "
                      "(every node must be openable in the editor)")
    for field in ("summary", "note", "flag"):
        v = n.get(field)
        if v is not None and (not isinstance(v, str) or not v.strip()):
            errors.append(f"{where} {field}, when present, must be non-empty")
    # A summary that enumerates the members is the duplication this layout
    # exists to remove: the reader reads the endpoints twice and the node's
    # own claim not at all. Length is the only mechanical proxy for "one line".
    summary = n.get("summary")
    if isinstance(summary, str) and len(summary) > MAX_SUMMARY_LEN:
        errors.append(f"{where} summary must be at most {MAX_SUMMARY_LEN} characters "
                      f"— say what the node IS; the members list what it has")
    if "implicit" in n and not isinstance(n["implicit"], bool):
        errors.append(f"{where} implicit must be a boolean")
    if n.get("implicit") and n.get("layer") != "mapper":
        errors.append(f"{where} implicit is only meaningful on a mapper node")

    members = n.get("members")
    if members is not None:
        if not isinstance(members, list):
            errors.append(f"{where} members must be a list")
        else:
            for k, m in enumerate(members):
                errors.extend(_member_errors(f"{where}.members[{k}]", m))

    edges = n.get("edges")
    if edges is not None:
        if not isinstance(edges, list):
            errors.append(f"{where} edges must be a list")
        else:
            for k, e in enumerate(edges):
                w = f"{where}.edges[{k}]"
                if not isinstance(e, dict):
                    errors.append(f"{w} must be an object")
                    continue
                to = e.get("to")
                if not _is_id(to):
                    errors.append(f"{w} to must be a node id")
                else:
                    edge_targets.append((w, to))
                    if to == nid:
                        errors.append(f"{w} points at its own node")
                if not isinstance(e.get("label"), str) or not e["label"].strip():
                    errors.append(f"{w} label must be a non-empty string")
                if "join" in e and not isinstance(e["join"], bool):
                    errors.append(f"{w} join must be a boolean")
    return errors


def _member_errors(where: str, m: object) -> list[str]:
    """A member is one row: a real signature, and optionally what it does.

    Rows carry the signature verbatim — return type included — because the
    reader is looking for the method they are about to open, and a paraphrase
    is not the thing they will find in the file. `detail` makes the row
    expandable in place, which is what keeps a node one list instead of a
    summary that restates the list underneath it.
    """
    if not isinstance(m, dict):
        return [f"{where} must be an object"]
    errors = []
    if not isinstance(m.get("text"), str) or not m["text"].strip():
        errors.append(f"{where} text must be a non-empty string")
    line = m.get("line")
    # Absent or 0 means "no jump target" — a member that describes the node
    # rather than sitting on one line. Anything else must be a real line.
    if line is not None and (not isinstance(line, int) or isinstance(line, bool)
                             or line < 0):
        errors.append(f"{where} line must be a non-negative integer or absent")
    detail = m.get("detail")
    if detail is not None and (not isinstance(detail, str) or not detail.strip()):
        errors.append(f"{where} detail, when present, must be a non-empty string")
    tag = m.get("tag")
    if tag is not None:
        if not isinstance(tag, str) or not tag.strip():
            errors.append(f"{where} tag, when present, must be a non-empty string")
        elif len(tag) > MAX_TAG_LEN:
            errors.append(f"{where} tag must be at most {MAX_TAG_LEN} characters "
                          f"— it is a badge, not a sentence")
    # `field` makes this row addressable by a route. It is the whole merge
    # between the class view and the property view: a route is an ordered list
    # of rows that already exist, not a second diagram drawn beside them.
    field = m.get("field")
    if field is not None and not _is_id(field):
        errors.append(f"{where} field must match [a-z0-9][a-z0-9_-]*")
    return errors


def _file_errors(where: str, file: object) -> list[str]:
    if not isinstance(file, str) or not file.strip():
        return [f"{where} file must be a non-empty project-relative path"]
    if file.startswith("/"):
        return [f"{where} file must be project-relative, not absolute"]
    if any(p in ("", ".", "..") for p in file.split("/")):
        return [f"{where} file must not contain empty or dot path segments"]
    return []


def _is_id(v: object) -> bool:
    return isinstance(v, str) and _ID_RE.match(v) is not None


def write_flow(state_dir: Path, doc: dict) -> None:
    """Validate and atomically write <state_dir>/dataflow.json. Raises ValueError."""
    errors = validate(doc)
    if errors:
        raise ValueError("; ".join(errors))
    write_text_atomic(Path(state_dir) / FLOW_FILE, json.dumps(doc, indent=2))


def load_flow(state_dir: Path) -> dict | None:
    p = Path(state_dir) / FLOW_FILE
    try:
        doc = json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


def generated_ts(state_dir: Path) -> int:
    doc = load_flow(state_dir)
    if not doc:
        return 0
    ts = doc.get("generated_ts")
    return ts if isinstance(ts, int) and not isinstance(ts, bool) else 0


def node_ids(doc: dict) -> set[str]:
    return {n["id"]
            for sl in doc.get("slices", []) if isinstance(sl, dict)
            for n in sl.get("nodes", []) if isinstance(n, dict)
            and isinstance(n.get("id"), str)}


def node_anchor(node_id: str) -> str:
    return f"node:{node_id}"


def valid_anchor(anchor: str) -> bool:
    return isinstance(anchor, str) and _ANCHOR_RE.match(anchor) is not None


def anchor_node_id(anchor: str) -> str | None:
    m = _ANCHOR_RE.match(anchor) if isinstance(anchor, str) else None
    return m.group(1) if m else None


def count_nodes(doc: dict) -> int:
    return sum(len(sl.get("nodes", []))
               for sl in doc.get("slices", []) if isinstance(sl, dict))
