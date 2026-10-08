"""A scene: one board, the keys of what the eye can land on in it, and the frames its verbs make.

Keys: node:<id>, edge:<a>-><b>#<n> (the n-th edge from a to b), group:<subgraph id>, line:<n>, old:<n> (a line a
change removed, by its old number), row#<n>,
and for a sequence spec actor:<id> and step:<id>. An edge shows as soon as both its ends do.
Verbs ([[+ k]], [[next]], [[all]], [[focus k]]) compile into full snapshot frames: frame 0 is the
opening state, one frame follows per place in the speech, and the rest frame shows everything with
no focus. Every frame also names what is being said in it (`cur`), so the page draws that and guesses
nothing: what the frame points at, else what it revealed, with the arrow that arrived into it; frame 0
and the rest frame name nothing. A reveal with no point of its own clears the focus. A target that
names nothing exactly is repaired or dropped, and every repair is reported.
Shared by talk and stage.py; no I/O.
"""
from __future__ import annotations

import difflib
import html
import re
import unicodedata
from dataclasses import dataclass, field
from html.entities import html5

LATER = ("-", "mark", "strike", "callout", "morph")
AUTO_STEP_OVER = 3
FUZZY_RATIO = 0.8

_VERB = re.compile(r"(?:(?P<sym>[+-])|(?P<word>next|all|focus|mark|strike|callout|morph)(?![\w-]))\s*(?P<rest>.*)\Z",
                   re.IGNORECASE | re.DOTALL)
_TARGET = re.compile(r"none|(?:old\s+)?(?:lines?\s+)?\d+(?:\s*[-–]\s*\d+)?|rows?\s+\S.*|nodes?\s+[\w.-]+"
                     r"|[\w.-]+?\s*-+>\s*[\w.-]+|[\w.-]+", re.IGNORECASE)
_LINES = re.compile(r"(?:(?P<old>old)\s+)?(?:lines?\s+)?(?P<a>\d+)(?:\s*[-–]\s*(?P<b>\d+))?", re.IGNORECASE)
_CELL = re.compile(r"cells?\s+(?P<r>.+?)\s*(?:/|,|×)\s*(?P<c>.+)", re.IGNORECASE)


def _column(model: "SceneModel", raw: str) -> int | None:
    """A column by its number or its header, quoted or not."""
    text = raw.strip().strip("\"'“”‘’").strip()
    if text.isdigit():
        return int(text)
    return model.columns.get(fold(text))


_ROW = re.compile(r"rows?\s+(?:(?P<n>\d+)(?:\s*[-–]\s*(?P<n2>\d+))?|\"(?P<q>[^\"]+)\"|“(?P<c>[^”]+)”|'(?P<s>[^']+)'|(?P<bare>\S.*))",
                  re.IGNORECASE)
_EDGE = re.compile(r"(?P<a>[\w.-]+?)\s*-+>\s*(?P<b>[\w.-]+)")


@dataclass
class Verb:
    name: str
    title: str = ""
    targets: list[str] = field(default_factory=list)
    count: int = 1
    keys: list[str] | None = None


@dataclass
class SceneModel:
    kind: str
    keys: list[str]
    order: list[str] = field(default_factory=list)
    up: dict[str, list[str]] = field(default_factory=dict)
    down: dict[str, list[str]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    edges: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    can_hide: bool = False
    columns: dict[str, int] = field(default_factory=dict)  # a table's columns by header, apart from its parts' names


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).lower().strip()


def lines_model(numbers) -> SceneModel:
    return SceneModel("lines", [f"line:{n}" for n in numbers])


def change_model(hunks: list[dict]) -> SceneModel:
    """A change board's lines in the order they are shown: line:<n> by its new number, and old:<n> for a removed
    line by its old one, so a range of new lines takes the removed lines inside it."""
    keys = [f"line:{r['new']}" if r.get("new") is not None else f"old:{r['old']}" for h in hunks for r in h["lines"]]
    return SceneModel("lines", list(dict.fromkeys(keys)))


def rows_model(cells: list[str], header: list[str] | None = None) -> SceneModel:
    """A table's rows, named by their first cell. With its header, every cell is a key too
    (`cell#<row>.<column>`, both counted from 1), so one cell can be the one being said; a cell
    brings its row, and a column is named by its header (kept in `columns`, never among the parts' names, so
    a row named in words never matches a column)."""
    keys = [f"row#{i}" for i in range(1, len(cells) + 1)]
    names: dict[str, str] = {}
    for key, cell in zip(keys, cells):
        names.setdefault(fold(cell), key)
    up: dict[str, list[str]] = {}
    cols = len(header or [])
    columns: dict[str, int] = {}
    for c, head in enumerate(header or [], 1):
        if fold(head):
            columns.setdefault(fold(head), c)
    down: dict[str, list[str]] = {}
    for r in range(1, len(cells) + 1):
        for c in range(1, cols + 1):
            up[f"cell#{r}.{c}"] = [f"row#{r}"]
            down.setdefault(f"row#{r}", []).append(f"cell#{r}.{c}")  # a row shown shows its cells
    return SceneModel("rows", keys + list(up), order=list(keys), up=up, down=down, names=names, can_hide=True,
                      columns=columns)


_HEADER = re.compile(r"\A\s*(?:graph|flowchart)\b(?:[ \t]+(?:TB|TD|BT|RL|LR)\b)?", re.IGNORECASE)
_ID = re.compile(r"\w+(?:[-.]\w+)*")
_AMP = re.compile(r"\s*&\s*")
_CLASS = re.compile(r":::[\w-]+")
_LINK = re.compile(r"\s*(?:<?(?:--|==|-\.)\s+(?P<text>[^\n]+?)\s+(?:-{2,}>|-{3,}|={2,}>|={3,}|\.-+>|\.-+)"
                   r"|<?(?:-{2,}|={2,}|-\.+-|~{3,})[->ox]?)\s*(?:\|(?P<label>[^|]*)\|)?\s*")
_SKIP = re.compile(r"(?:direction|classDef|class|style|linkStyle|click|accTitle|accDescr)\b", re.IGNORECASE)
_CLOSE = {"[": "]", "(": ")", "{": "}", ">": "]"}


def _statements(body: str) -> list[str] | None:
    text = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("%%")).strip()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        text = text[end + 4:].strip() if end >= 0 else text
    m = _HEADER.match(text)
    if not m:
        return None
    out, cur, quoted = [], "", False
    for c in text[m.end():]:
        if c == '"':
            quoted = not quoted
        if c in ";\n" and not quoted:
            out.append(cur.strip())
            cur = ""
        else:
            cur += c
    out.append(cur.strip())
    return [s for s in out if s]


def _shape_end(s: str, i: int) -> int:
    if s.startswith("@{", i):
        j = s.find("}", i)
        return len(s) if j < 0 else j + 1
    stack, quoted, j = [_CLOSE[s[i]]], False, i + 1
    while j < len(s) and stack:
        c = s[j]
        if c == '"':
            quoted = not quoted
        elif not quoted and c in "[({":
            stack.append(_CLOSE[c])
        elif not quoted and c == stack[-1]:
            stack.pop()
        j += 1
    return j


_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_CODE = re.compile(r"#(?:(?P<n>\d+)|(?P<name>[a-zA-Z]\w*));")
_STRONG = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_EM = re.compile(r"(?<![\w*])[*_](?=\S)(.+?)(?<=\S)[*_](?![\w*])")
_FIELD = re.compile(r"""\blabel\s*:\s*(?:"(?P<d>(?:[^"\\]|\\.)*)"|'(?P<s>(?:[^'\\]|\\.)*)'|(?P<bare>[^,}]*))""")


def _text(raw: str) -> str:
    """A Mermaid label as the words it shows: a `<br>` is a space (the map wraps a long name itself), an
    entity code (`#quot;`, `#9829;`) or an HTML entity is its character, and a markdown string ("`...`") is
    its text without the backticks and the ** and * of its emphasis. Any other `<` or `>` is text, as the
    stage draws it in a Mermaid diagram."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    if len(text) >= 2 and text[0] == text[-1] == "`":
        text = _EM.sub(r"\1", _STRONG.sub(lambda m: m[1] or m[2], text[1:-1].replace("\n", " ")))
    text = _BR.sub(" ", text)
    text = _CODE.sub(lambda m: f"&#{m['n']};" if m["n"] else f"&{m['name']};" if m["name"] + ";" in html5 else m[0], text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _label(shape: str) -> str:
    inner = shape.strip()
    if inner.startswith("@{"):  # Mermaid 11's `id@{ shape: rect, label: "Store" }`: its label field, or none
        m = _FIELD.search(inner)
        return _text(m["d"] if m["d"] is not None else m["s"] if m["s"] is not None else m["bare"]) if m else ""
    while len(inner) >= 2 and inner[0] in "[({>/\\" and inner[-1] in "])}/\\":
        inner = inner[1:-1].strip()
    return _text(inner)


def _node_group(s: str, i: int) -> tuple[list[tuple[str, str]], int]:
    found = []
    while True:
        while i < len(s) and s[i] in " \t":
            i += 1
        m = _ID.match(s, i)
        if not m:
            return found, i
        ident, i, label = m.group(), m.end(), ""
        if i < len(s) and (s[i] in "[({>" or s.startswith("@{", i)):
            j = _shape_end(s, i)
            label, i = _label(s[i:j]), j
        k = _CLASS.match(s, i)
        if k:
            i = k.end()
        found.append((ident, label))
        k = _AMP.match(s, i)
        if not k:
            return found, i
        i = k.end()


def _subgraph(rest: str) -> tuple[str, str]:
    m = _ID.match(rest)
    if m and (m.end() == len(rest) or rest[m.end()] in " \t["):
        return m.group(), _label(rest[m.end():]) or m.group()
    title = _text(rest)
    return title, title


_STATE_HEAD = re.compile(r"\A\s*stateDiagram(?:-v2)?\b", re.IGNORECASE)
_STATE_EDGE = re.compile(r"(?P<a>\[\*\]|[\w.-]+)\s*-->\s*(?P<b>\[\*\]|[\w.-]+)\s*(?::\s*(?P<label>.+))?\Z")
_STATE_AS = re.compile(r'state\s+"(?P<label>[^"]+)"\s+as\s+(?P<id>[\w.-]+)\Z', re.IGNORECASE)
_STATE_DESC = re.compile(r"(?P<id>[\w.-]+)\s*:\s*(?P<label>.+)\Z")


def mermaid_spec(body: str) -> dict | None:
    """A Mermaid graph, flowchart or state diagram as a flowchart spec, for the stage to draw as its map;
    None for any other kind of Mermaid. Every label is the words it shows (`_text`, no markup); a subgraph is a
    group of its parts, with no box (`_ungroup`); `{...}` shapes are decisions; in a state
    diagram `[*] --> X` makes X where it starts and `X --> [*]` makes X an end."""
    text = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("%%")).strip()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(ident: str, label: str = "") -> dict:
        n = nodes.setdefault(ident, {"id": ident, "role": "code", "label": ident})
        if label:
            n["label"] = label
        return n

    if _STATE_HEAD.match(text):
        starts, ends = set(), set()
        for raw in text.splitlines()[1:]:
            st = raw.strip()
            if not st or _SKIP.match(st) or st in ("{", "}") or st.lower().startswith(("note", "end note")):
                continue
            if m := _STATE_AS.match(st):
                node(m["id"], _text(m["label"]))
            elif m := _STATE_EDGE.match(st):
                a, b = m["a"], m["b"]
                if a == "[*]" and b != "[*]":
                    starts.add(b); node(b)
                elif b == "[*]" and a != "[*]":
                    ends.add(a); node(a)
                elif a != "[*]":
                    node(a); node(b)
                    edges.append({"from": a, "to": b, **({"label": _text(m["label"])} if m["label"] else {})})
            elif m := _STATE_DESC.match(st):
                node(m["id"])["sub"] = _text(m["label"])
        for ident in starts:
            nodes[ident]["role"] = "entry"
        for ident in ends - starts:
            nodes[ident]["role"] = "success"
    else:
        statements = _statements(body)
        if statements is None:
            return None
        decisions = set()
        groups: dict[str, str] = {}  # a subgraph's id and its label
        member: dict[str, str] = {}  # a node or subgraph and the subgraph it was first written in
        stack: list[str] = []
        for st in statements:
            low = st.lower()
            if low == "end":
                if stack:
                    stack.pop()
                continue
            if low.startswith("subgraph"):
                ident, label = _subgraph(st[len("subgraph"):].strip())
                groups.setdefault(ident, label)
                if stack and ident not in member:
                    member[ident] = stack[-1]
                stack.append(ident)
                continue
            if _SKIP.match(st):
                continue
            decisions |= {d[1] for d in re.finditer(r"([\w][\w.-]*)\s*\{(?!\{)", st)}
            chain, labels, i = [], [], 0
            while True:
                found, i = _node_group(st, i)
                if not found:
                    break
                chain.append(found)
                for ident, label in found:
                    node(ident, label)
                    if stack and ident not in member and ident not in groups:
                        member[ident] = stack[-1]
                link = _LINK.match(st, i)
                if not link or link.end() == i:
                    break
                labels.append(_text(link["text"] or link["label"] or ""))
                i = link.end()
            for (left, right), label in zip(zip(chain, chain[1:]), labels):
                for a, _ in left:
                    for b, _ in right:
                        edges.append({"from": a, "to": b, **({"label": label} if label else {})})
        edges, kept = _ungroup(nodes, edges, groups, member)
        for ident in decisions & set(nodes):
            nodes[ident]["role"] = "decision"
        has_in = {e["to"] for e in edges}
        sources = [i for i in nodes if i not in has_in]
        for ident in sources or list(nodes)[:1]:
            if nodes[ident]["role"] == "code":
                nodes[ident]["role"] = "entry"
    if not nodes:
        return None
    spec = {"nodes": list(nodes.values()), "edges": edges}
    if not _STATE_HEAD.match(text) and kept:
        spec["groups"] = kept
    return spec


def _ungroup(nodes: dict[str, dict], edges: list[dict], groups: dict[str, str], member: dict[str, str]
             ) -> tuple[list[dict], list[dict]]:
    """Mermaid subgraphs on a map, which draws no boxes: an arrow into a subgraph goes to each of its parts
    that nothing inside it leads to, and one out of it leaves each part that leads nowhere inside it (the
    innermost subgraph first), so no part is cut off and none is made up from the subgraph's id. Each part
    says which subgraph it is in under its label, and the subgraphs are kept (`groups`, with their parts) so
    a verb can name one. A subgraph with no parts stays one part, named by its label."""
    inside: dict[str, list[str]] = {g: [] for g in groups}
    for ident in nodes:
        if ident in groups:
            continue
        g = member.get(ident)
        while g is not None:
            inside[g].append(ident)
            g = member.get(g)
    def depth(g: str) -> int:
        n = 0
        while g in member:
            g, n = member[g], n + 1
        return n

    for g in sorted(groups, key=depth, reverse=True):
        parts = inside[g]
        if not parts:
            node = nodes.setdefault(g, {"id": g, "role": "code", "label": groups[g]})
            if node["label"] == g:
                node["label"] = groups[g]
            continue
        nodes.pop(g, None)
        within = [e for e in edges if e["from"] in parts and e["to"] in parts]
        heads = [p for p in parts if not any(e["to"] == p for e in within)] or parts[:1]
        tails = [p for p in parts if not any(e["from"] == p for e in within)] or parts[-1:]
        out: list[dict] = []
        for e in edges:
            for a in (tails if e["from"] == g else [e["from"]]):
                for b in (heads if e["to"] == g else [e["to"]]):
                    out.append({**e, "from": a, "to": b})
        edges = out
    for ident, g in member.items():
        if ident in nodes and ident not in groups and "sub" not in nodes[ident]:
            nodes[ident]["sub"] = "in " + groups[g]
    kept = [{"id": g, "label": groups[g], "nodes": inside[g]} for g in groups if inside[g]]
    return edges, kept


def flowchart_model(body: str) -> SceneModel | None:
    statements = _statements(body)
    if statements is None:
        return None
    groups: list[str] = []
    nodes: list[str] = []
    edges: list[tuple[str, str, str]] = []
    order: list[str] = []
    labels: dict[str, str] = {}
    member: dict[str, str] = {}
    parent: dict[str, str] = {}
    stack: list[str] = []
    pairs: dict[tuple[str, str], int] = {}

    def see(ident: str, label: str) -> None:
        if ident in groups:
            return
        if ident not in nodes:
            nodes.append(ident)
            order.append(f"node:{ident}")
        if label:
            labels[ident] = label
        if stack and ident not in member:
            member[ident] = stack[-1]

    for st in statements:
        low = st.lower()
        if low == "end":
            if stack:
                stack.pop()
            continue
        if low.startswith("subgraph"):
            ident, label = _subgraph(st[len("subgraph"):].strip())
            if ident not in groups:
                groups.append(ident)
            labels[ident] = label
            if stack:
                parent[ident] = stack[-1]
            stack.append(ident)
            continue
        if _SKIP.match(st):
            continue
        chain, i = [], 0
        while True:
            found, i = _node_group(st, i)
            if not found:
                break
            chain.append(found)
            for ident, label in found:
                see(ident, label)
            link = _LINK.match(st, i)
            if not link or link.end() == i:
                break
            i = link.end()
        for left, right in zip(chain, chain[1:]):
            for a, _ in left:
                for b, _ in right:
                    n = pairs.get((a, b), 0)
                    pairs[(a, b)] = n + 1
                    key = f"edge:{a}->{b}#{n}"
                    edges.append((a, b, key))
    if not nodes and not groups:
        return None

    def ref(ident: str) -> str:
        return f"group:{ident}" if ident in groups else f"node:{ident}"

    up: dict[str, list[str]] = {}
    for ident, g in member.items():
        up[ref(ident)] = [f"group:{g}"]
    for g, p in parent.items():
        up[f"group:{g}"] = [f"group:{p}"]
    edge_map: dict[tuple[str, str], list[str]] = {}
    for a, b, key in edges:
        up[key] = [ref(a), ref(b)]
        edge_map.setdefault((a, b), []).append(key)
    down: dict[str, list[str]] = {}
    for g in groups:
        kids, todo = [], [g]
        while todo:
            cur = todo.pop()
            kids += [f"node:{n}" for n, owner in member.items() if owner == cur and n not in groups]
            subs = [s for s, owner in parent.items() if owner == cur]
            kids += [f"group:{s}" for s in subs]
            todo += subs
        down[f"group:{g}"] = kids
    names: dict[str, str] = {}
    for ident, label in labels.items():
        names.setdefault(fold(label), ref(ident))
    keys = [f"group:{g}" for g in groups] + [f"node:{n}" for n in nodes] + [k for _, _, k in edges]
    return SceneModel("flowchart", keys, order=order, up=up, down=down, names=names, edges=edge_map, can_hide=True)


def split_targets(text: str) -> list[str]:
    return [t.strip() for t in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*\Z)', text) if t.strip()]


def split_title(rest: str) -> tuple[str, str]:
    colons = [i for i, c in enumerate(rest) if c == ":" and rest[:i].count('"') % 2 == 0]
    for i in colons:
        targets = split_targets(rest[i + 1:])
        if targets and all(_TARGET.fullmatch(t) for t in targets):
            return rest[:i].strip(), rest[i + 1:].strip()
    if colons:
        return rest[:colons[-1]].strip(), rest[colons[-1] + 1:].strip()
    return "", rest.strip()


def parse_verb(marker: str) -> Verb | None:
    m = _VERB.match(marker.strip())
    if not m:
        return None
    name, rest = m["sym"] or m["word"].lower(), m["rest"].strip()
    if name in LATER:
        return Verb(name)
    if name == "next":
        count = re.search(r"(?:\A|[\s:])(\d+)\s*\Z", rest)
        title = (rest[: count.start()] if count else rest).strip(" :")
        return Verb(name, title=title, count=int(count[1]) if count and int(count[1]) > 0 else 1)
    if name == "all":
        return Verb(name, title=rest.strip(" :"))
    title, targets = split_title(rest)
    return Verb(name, title=title, targets=split_targets(targets))


def sequence_model(spec: dict) -> SceneModel:
    """A sequence spec: its actors, then its steps, which come in order and each bring their actors."""
    actors = [f"actor:{a['id']}" for a in spec["actors"]]
    steps = [f"step:{s['id']}" for s in spec["steps"]]
    up = {f"step:{s['id']}": list(dict.fromkeys([f"actor:{s['from']}", f"actor:{s['to']}"])) for s in spec["steps"]}
    names: dict[str, str] = {}
    for s in spec["steps"]:
        names.setdefault(fold(str(s.get("label", ""))), f"step:{s['id']}")
    for a in spec["actors"]:
        names.setdefault(fold(str(a.get("label", "")).replace("\n", " ")), f"actor:{a['id']}")
    names.pop("", None)
    return SceneModel("sequence", actors + steps, order=steps, up=up, names=names, can_hide=True)


def flowchart_spec_model(spec: dict) -> SceneModel:
    """A flowchart spec: its nodes in order; its edges follow their ends. A group (a Mermaid subgraph, which
    the map draws no box for) is a key that brings and lights its nodes."""
    nodes = [f"node:{n['id']}" for n in spec["nodes"]]
    groups = [g for g in spec.get("groups") or [] if g.get("id")]
    seen: dict[tuple[str, str], int] = {}
    edge_map: dict[tuple[str, str], list[str]] = {}
    up: dict[str, list[str]] = {}
    for e in spec.get("edges") or []:
        pair = (e["from"], e["to"])
        key = f"edge:{pair[0]}->{pair[1]}#{seen.get(pair, 0)}"
        seen[pair] = seen.get(pair, 0) + 1
        edge_map.setdefault(pair, []).append(key)
        up[key] = [f"node:{pair[0]}", f"node:{pair[1]}"]
    names: dict[str, str] = {}
    for n in spec["nodes"]:
        for text in (n.get("label"), n.get("method"), n.get("ref")):
            if text:
                names.setdefault(fold(str(text)), f"node:{n['id']}")
    down = {f"group:{g['id']}": [f"node:{i}" for i in g.get("nodes") or [] if f"node:{i}" in nodes] for g in groups}
    for g in groups:
        if g.get("label"):
            names.setdefault(fold(str(g["label"])), f"group:{g['id']}")
    return SceneModel("flowchart", list(down) + nodes + list(up), order=nodes, up=up, down=down, names=names,
                      edges=edge_map, can_hide=True)


ENTITY_PREFIXES = {"sequence": ("step:", "actor:")}


def _prefixes(model: SceneModel) -> tuple[str, ...]:
    return ENTITY_PREFIXES.get(model.kind, ("node:", "group:"))


def _closest(model: SceneModel, raw: str) -> str | None:
    want = fold(raw)
    if want in model.names:
        return model.names[want]
    pool = {fold(k.split(":", 1)[1]): k for k in model.keys if k.startswith(_prefixes(model))}
    pool.update(model.names)
    best, score = None, 0.0
    for name, key in pool.items():
        ratio = difflib.SequenceMatcher(None, want, name).ratio()
        if ratio > score:
            best, score = key, ratio
    return best if score >= FUZZY_RATIO else None


def _entity(model: SceneModel, raw: str) -> tuple[str | None, bool]:
    raw = re.sub(r'\A(["“\'])(.*)["”\']\Z', r"\2", raw.strip())
    for key in (p + raw for p in _prefixes(model)):
        if key in model.keys:
            return key, False
    if fold(raw) in model.names:
        return model.names[fold(raw)], False
    return _closest(model, raw), True


def resolve(model: SceneModel, raw: str, title: str) -> tuple[list[str], str | None]:
    raw = raw.strip()
    dropped = f'"{raw}" in "{title}" matches nothing; dropped'
    if model.kind == "lines":
        m = _LINES.fullmatch(raw)
        if not m:
            return [], dropped
        a, b = sorted((int(m["a"]), int(m["b"] or m["a"])))
        if m["old"]:
            keys = [f"old:{n}" for n in range(a, b + 1) if f"old:{n}" in model.keys]
            return (keys, None) if keys else ([], f'"{raw}" is not a removed line of "{title}"; dropped')
        # from the first line of the range to its last as they are shown, with any removed line between them
        inside = [i for i, k in enumerate(model.keys) if k.startswith("line:") and a <= int(k[5:]) <= b]
        keys = model.keys[inside[0]:inside[-1] + 1] if inside else []
        return (keys, None) if keys else ([], f'"{raw}" is outside the lines of "{title}"; dropped')
    if model.kind == "rows" and (cell := _CELL.fullmatch(raw)):
        row, _ = resolve(model, "row " + cell["r"].strip(), title)
        col = _column(model, cell["c"])
        key = f"cell#{row[0].split('#')[1]}.{col}" if row and col else None
        return ([key], None) if key in model.keys else ([], dropped)
    if model.kind == "rows":
        m = _ROW.fullmatch(raw)
        if m and m["n"]:
            a, b = sorted((int(m["n"]), int(m["n2"] or m["n"])))
            keys = [f"row#{n}" for n in range(a, b + 1)]
            if all(k in model.keys for k in keys):
                return keys, None
            said = f"row {a}" if a == b else f"rows {a}-{b}"
            return [], f'"{title}" has {len(model.order)} rows, not {said}; dropped'
        text = (m["q"] or m["c"] or m["s"] or m["bare"]) if m else raw
        if fold(text) in model.names:
            return [model.names[fold(text)]], None
        key = _closest(model, text)
        return ([key], f'"{raw}" in "{title}" read as {key}') if key else ([], dropped)
    m = re.fullmatch(r"(?:nodes?|steps?)\s+(.+)", raw, re.IGNORECASE)
    if m is None and model.kind == "sequence":
        actor = re.fullmatch(r"actors?\s+(.+)", raw, re.IGNORECASE)
        if actor and f"actor:{actor[1].strip()}" in model.keys:
            return [f"actor:{actor[1].strip()}"], None
    ident = m[1].strip() if m else raw
    edge = _EDGE.fullmatch(ident) or re.fullmatch(r"(?P<a>.+?)\s*-+>\s*(?P<b>[^>]+)", ident)
    if edge:
        (a, fuzzy_a), (b, fuzzy_b) = _entity(model, edge["a"]), _entity(model, edge["b"])
        if a is None or b is None:
            return [], dropped
        ia, ib = a.split(":", 1)[1], b.split(":", 1)[1]
        if (ia, ib) in model.edges:
            return model.edges[(ia, ib)], (f'"{raw}" in "{title}" read as {ia}->{ib}' if fuzzy_a or fuzzy_b else None)
        if (ib, ia) in model.edges:
            return model.edges[(ib, ia)], f'"{raw}" in "{title}" read as {ib}->{ia}: that edge only goes the other way'
        return [], dropped
    key, fuzzy = _entity(model, ident)
    if key is None:
        return [], dropped
    return [key], (f'"{raw}" in "{title}" read as {key}' if fuzzy else None)


def _reveal(model: SceneModel, key: str, shown: set) -> None:
    stack = [key] + (model.down.get(key, []) if key.startswith("group:") else [])
    while stack:
        k = stack.pop()
        if k not in shown:
            shown.add(k)
            stack.extend(model.up.get(k, []))
            if k.startswith("row#"):  # a row is shown whole, however it came in
                stack.extend(model.down.get(k, []))


def _arrows(model: SceneModel, shown: set) -> None:
    for k in model.keys:
        if k.startswith("edge:") and k not in shown and all(u in shown for u in model.up.get(k, ["?"])):
            shown.add(k)


def _snap(model: SceneModel, shown: set, focus: set, cur: list | None = None) -> dict:
    _arrows(model, shown)
    return {"show": [k for k in model.keys if k in shown], "focus": [k for k in model.keys if k in focus],
            "cur": list(cur or [])}


def _said(model: SceneModel, keys: list[str], before: set, shown: set) -> list[str]:
    """What a frame draws as being said: these parts (a cell as its row, an arrow with the end it brought
    in), and on a flowchart the arrow that arrived with this frame into the last node of them, else one
    that arrived out of it."""
    _arrows(model, shown)
    new = [k for k in model.keys if k in shown and k not in before]
    cur: list[str] = []
    for k in keys:
        if k.startswith("cell#"):
            k = model.up[k][0]
        if k.startswith("edge:"):
            cur += [end for end in model.up[k] if end in new]
        cur.append(k)
    cur = list(dict.fromkeys(cur))
    node = next((k for k in reversed(cur) if k.startswith("node:")), None)
    if model.kind == "flowchart" and node and not any(k.startswith("edge:") for k in cur):
        edges = [k for k in new if k.startswith("edge:")]
        edge = next((e for e in edges if model.up[e][1] == node), None) or next((e for e in edges if model.up[e][0] == node), None)
        if edge:
            cur.append(edge)
    return cur


# Words too common to name a part by.
_STOP = frozenset("""a an and are as at be but by can did does for from had has have her his how into its just not now
off once one only our out over she than that the their them then there these they this those too two very was way
were what when where which who why will with you your yours it's is it of on or so to in up we us he if do no all
any each few more most other some such own same both here""".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W_]+", fold(text)) if len(w) >= 3 and w not in _STOP]


def _same(a: str, b: str) -> bool:
    """One word said for another: the same word, or a form of it (send, sends; share, sharing;
    implement, implementation)."""
    a, b = sorted((a, b), key=len)
    stem = a[:-1] if len(a) > 4 and a[-1] in "se" else a
    return a == b or (len(stem) >= 4 and b.startswith(stem))


def part_names(model: SceneModel) -> dict[str, list[list[str]]]:
    """Each part's names as words: its labels (and a node's ref or method), and an id that is a word."""
    out: dict[str, list[list[str]]] = {}
    for name, key in model.names.items():
        if _words(name):
            out.setdefault(key, []).append(_words(name))
    for key in model.order:
        ident = key.split(":", 1)[1] if key.startswith(("node:", "step:", "group:")) else ""
        if len(ident) >= 3 and not re.fullmatch(r"[a-z]?\d+", ident, re.IGNORECASE) and _words(ident):
            out.setdefault(key, []).append(_words(ident))
    return out


def names_part(sentence: list[str], names: list[list[str]]) -> bool:
    """A sentence names a part when it says more than half of the words of one of its names."""
    return any(sum(any(_same(w, s) for s in sentence) for w in name) > len(name) // 2 for name in names)


def auto_steps(model: SceneModel, sentences: list[str], pointed: dict[int, list[str]] | None = None
               ) -> tuple[dict[int, list[list[str]]], list[str]]:
    """A board with no reveals of its own, brought in over the sentences said about it.

    Each part arrives with the first sentence that names it (a sequence's steps keep their order), or with
    the sentence that points at it when that comes first. The parts no sentence names fill the sentences
    that name nothing, in order and spread evenly, between the named parts around them; with no sentence
    left there, they come in with the next named part. A first sentence that names nothing is the board's
    introduction and brings nothing, unless no sentence names anything and there are no more sentences
    than parts. `pointed` holds, per sentence index, the parts the board's own points light there.
    Returns, per sentence index, the reveals for it (each a list of keys; the last is what the sentence
    is about), and the parts that came in by order rather than by name."""
    parts, m = model.order, len(sentences)
    if not model.can_hide or len(parts) <= AUTO_STEP_OVER or m < 1:
        return {}, []
    words, names = [_words(s) for s in sentences], part_names(model)
    point_at: dict[str, int] = {}
    for i in sorted(pointed or {}):
        for k in (pointed or {})[i]:
            part = model.up.get(k, [k])[0] if k.startswith("cell#") else k
            if part in parts:
                point_at.setdefault(part, i)
    anchor: dict[str, int] = {}
    by_name: set[str] = set()
    floor = 0
    for p in parts:
        lo = floor if model.kind == "sequence" else 0
        hit = next((i for i in range(lo, min(m, point_at.get(p, m))) if names_part(words[i], names.get(p, []))), None)
        if hit is not None:
            anchor[p] = hit
            by_name.add(p)
        elif p in point_at:
            anchor[p] = point_at[p]
        if p in anchor and model.kind == "sequence":
            floor = max(floor, anchor[p])
    busy = set(anchor.values()) | set(point_at.values())
    intro = 0 not in busy and (bool(anchor) or m > len(parts))
    free = [i for i in range(m) if i not in busy and not (i == 0 and intro)]
    fills: dict[int, list[list[str]]] = {}
    rides: dict[int, list[str]] = {}
    later: list[str] = []
    run: list[str] = []
    for j, p in enumerate([*parts, None]):
        if p is not None and p not in anchor:
            run.append(p)
            continue
        if run:
            before = [anchor[q] for q in parts[:j] if q in anchor]
            lo, hi = (before[-1] if before else -1), (anchor[p] if p is not None else m)
            window = [i for i in free if lo < i < hi]
            if window:
                k = min(len(window), len(run))
                for i in range(k):
                    fills[window[i]] = [run[i * len(run) // k:(i + 1) * len(run) // k]]
                free = [i for i in free if i not in window[:k]]
            else:
                rides.setdefault(hi if p is not None else max(lo, 0), []).extend(run)
            later += run
            run = []
    plan: dict[int, list[list[str]]] = {}
    for i in range(m):
        own = [p for p in parts if anchor.get(p) == i]  # a pointed part too: the board still starts empty
        steps = [s for s in ([rides.get(i, [])] + fills.get(i, []) + [own]) if s]
        if steps:
            plan[i] = steps
    return plan, later


def compile_scene(model: SceneModel, groups: list[list[Verb]], title: str) -> tuple[dict | None, list[str]]:
    if not groups:
        return None, []
    notes, repairs = [], 0
    # every target is resolved first, so the board starts empty only when a reveal really reveals something:
    # a board whose every [[+ X]] named nothing starts whole, rather than staying blank through the answer
    named: dict[int, list[str]] = {}
    for verb in (v for g in groups for v in g):
        if verb.name in ("next", "all") or (verb.name == "focus" and verb.keys is None
                                            and [t.lower() for t in verb.targets] == ["none"]):
            continue
        named[id(verb)] = list(verb.keys or [])
        if verb.keys is None:
            for raw in verb.targets:
                got, note = resolve(model, raw, title)
                if note:
                    notes.append(note)
                    repairs += 1
                named[id(verb)] += got
    empty = model.can_hide and any(v.name in ("next", "all") or (v.name == "+" and named[id(v)])
                                   for g in groups for v in g)
    shown = set() if empty else set(model.keys)
    focus: set = set()
    frames = [_snap(model, shown, focus)]
    for group in groups:
        before = set(shown)
        revealed: list[str] | None = None  # what the group's last reveal named
        pointed: list[str] | None = None   # what its last focus named
        for verb in group:
            if verb.name == "next":
                left = [k for k in model.order if k not in shown]
                if not left:
                    notes.append(f'next in "{title}": everything is shown already')
                for k in left[:verb.count]:
                    _reveal(model, k, shown)
                revealed = left[:verb.count]
                continue
            if verb.name == "all":
                shown |= set(model.keys)
                revealed = []
                continue
            if verb.name == "focus" and verb.keys is None and [t.lower() for t in verb.targets] == ["none"]:
                focus, pointed = set(), None
                continue
            keys = named[id(verb)]
            for k in keys:
                _reveal(model, k, shown)
            if verb.name == "focus":
                focus = {d for k in keys for d in [k, *(model.down.get(k, []) if k.startswith("group:") else [])]}
                pointed = keys
            else:
                revealed = keys
        # A point is what is being said, whatever the group also revealed. A reveal with no point of its
        # own clears the old focus, so nothing lit is left behind on a part the voice has left.
        if pointed is None and revealed is not None:
            focus = set()
        said = pointed if pointed is not None else revealed or []
        frames.append(_snap(model, shown, focus, _said(model, said, before, shown)))
    never = [k for k in model.order if k not in shown]
    if empty and never:
        notes.append(f'{len(never)} of {len(model.order)} elements of "{title}" are never revealed; '
                     "they come in with the rest frame")
    frames.append(_snap(model, set(model.keys), set()))
    scene = {"kind": model.kind, "keys": model.keys, "frames": frames, "steps": len(frames) - 2,
             "rest": len(frames) - 1, "start": "empty" if empty else "full", "title": title, "repairs": repairs}
    return scene, notes
