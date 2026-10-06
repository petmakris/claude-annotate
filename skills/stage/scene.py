"""A scene: one board, the keys of what the eye can land on in it, and the frames its verbs make.

Keys: node:<id>, edge:<a>-><b>#<n> (the n-th edge from a to b), group:<subgraph id>, line:<n>, row#<n>.
Verbs ([[+ k]], [[next]], [[all]], [[focus k]]) compile into full snapshot frames: frame 0 is the
opening state, one frame follows per place in the speech, and the rest frame shows everything with
no focus. A target that names nothing exactly is repaired or dropped, and every repair is reported.
Shared by talk and stage.py; no I/O.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

LATER = ("-", "mark", "strike", "callout", "morph")
AUTO_STEP_OVER = 3
FUZZY_RATIO = 0.8

_VERB = re.compile(r"(?:(?P<sym>[+-])|(?P<word>next|all|focus|mark|strike|callout|morph)(?![\w-]))\s*(?P<rest>.*)\Z",
                   re.IGNORECASE | re.DOTALL)
_TARGET = re.compile(r"none|(?:lines?\s+)?\d+(?:\s*[-–]\s*\d+)?|rows?\s+\S.*|nodes?\s+[\w.-]+"
                     r"|[\w.-]+?\s*-+>\s*[\w.-]+|[\w.-]+", re.IGNORECASE)
_LINES = re.compile(r"(?:lines?\s+)?(?P<a>\d+)(?:\s*[-–]\s*(?P<b>\d+))?", re.IGNORECASE)
_ROW = re.compile(r"rows?\s+(?:(?P<n>\d+)|\"(?P<q>[^\"]+)\"|“(?P<c>[^”]+)”|'(?P<s>[^']+)'|(?P<bare>\S.*))",
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


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).lower().strip()


def lines_model(numbers) -> SceneModel:
    return SceneModel("lines", [f"line:{n}" for n in numbers])


def rows_model(cells: list[str]) -> SceneModel:
    keys = [f"row#{i}" for i in range(1, len(cells) + 1)]
    names: dict[str, str] = {}
    for key, cell in zip(keys, cells):
        names.setdefault(fold(cell), key)
    return SceneModel("rows", keys, order=list(keys), names=names, can_hide=True)


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


def _label(shape: str) -> str:
    inner = shape.strip()
    while len(inner) >= 2 and inner[0] in "[({>/\\" and inner[-1] in "])}/\\":
        inner = inner[1:-1].strip()
    return inner.strip('"').strip()


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
    title = rest.strip().strip('"')
    return title, title


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
                    order.append(key)
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
        return Verb(name, count=int(rest) if rest.isdigit() and int(rest) > 0 else 1)
    if name == "all":
        return Verb(name, title=rest.rstrip(":").strip())
    title, targets = split_title(rest)
    return Verb(name, title=title, targets=split_targets(targets))


def _closest(model: SceneModel, raw: str) -> str | None:
    want = fold(raw)
    if want in model.names:
        return model.names[want]
    pool = {fold(k.split(":", 1)[1]): k for k in model.keys if k.startswith(("node:", "group:"))}
    pool.update(model.names)
    best, score = None, 0.0
    for name, key in pool.items():
        ratio = difflib.SequenceMatcher(None, want, name).ratio()
        if ratio > score:
            best, score = key, ratio
    return best if score >= FUZZY_RATIO else None


def _entity(model: SceneModel, raw: str) -> tuple[str | None, bool]:
    for key in (f"node:{raw}", f"group:{raw}"):
        if key in model.keys:
            return key, False
    return _closest(model, raw), True


def resolve(model: SceneModel, raw: str, title: str) -> tuple[list[str], str | None]:
    raw = raw.strip()
    dropped = f'"{raw}" in "{title}" matches nothing; dropped'
    if model.kind == "lines":
        m = _LINES.fullmatch(raw)
        if not m:
            return [], dropped
        a, b = sorted((int(m["a"]), int(m["b"] or m["a"])))
        keys = [f"line:{n}" for n in range(a, b + 1) if f"line:{n}" in model.keys]
        return (keys, None) if keys else ([], f'"{raw}" is outside the lines of "{title}"; dropped')
    if model.kind == "rows":
        m = _ROW.fullmatch(raw)
        if m and m["n"]:
            key = f"row#{m['n']}"
            if key in model.keys:
                return [key], None
            return [], f'"{title}" has {len(model.keys)} rows, not row {m["n"]}; dropped'
        text = (m["q"] or m["c"] or m["s"] or m["bare"]) if m else raw
        if fold(text) in model.names:
            return [model.names[fold(text)]], None
        key = _closest(model, text)
        return ([key], f'"{raw}" in "{title}" read as {key}') if key else ([], dropped)
    m = re.fullmatch(r"nodes?\s+(.+)", raw, re.IGNORECASE)
    ident = m[1].strip() if m else raw
    edge = _EDGE.fullmatch(ident)
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


def _snap(model: SceneModel, shown: set, focus: set) -> dict:
    return {"show": [k for k in model.keys if k in shown], "focus": [k for k in model.keys if k in focus]}


def auto_steps(model: SceneModel, sentences: int) -> list[list[Verb]]:
    if not model.can_hide or len(model.order) <= AUTO_STEP_OVER or sentences < 1:
        return []
    k = min(sentences, len(model.order))
    per = -(-len(model.order) // k)
    return [[Verb("next", count=per)] for _ in range(k)]


def compile_scene(model: SceneModel, groups: list[list[Verb]], title: str) -> tuple[dict | None, list[str]]:
    if not groups:
        return None, []
    notes, repairs = [], 0
    empty = model.can_hide and any(v.name in ("+", "next", "all") for g in groups for v in g)
    shown = set() if empty else set(model.keys)
    focus: set = set()
    frames = [_snap(model, shown, focus)]
    for group in groups:
        for verb in group:
            if verb.name == "next":
                left = [k for k in model.order if k not in shown]
                if not left:
                    notes.append(f'next in "{title}": everything is shown already')
                for k in left[:verb.count]:
                    _reveal(model, k, shown)
                continue
            if verb.name == "all":
                shown |= set(model.keys)
                continue
            if verb.name == "focus" and verb.keys is None and [t.lower() for t in verb.targets] == ["none"]:
                focus = set()
                continue
            keys = list(verb.keys or [])
            if verb.keys is None:
                for raw in verb.targets:
                    got, note = resolve(model, raw, title)
                    if note:
                        notes.append(note)
                        repairs += 1
                    keys += got
            for k in keys:
                _reveal(model, k, shown)
            if verb.name == "focus":
                focus = {d for k in keys for d in [k, *(model.down.get(k, []) if k.startswith("group:") else [])]}
        frames.append(_snap(model, shown, focus))
    never = [k for k in model.order if k not in shown]
    if empty and never:
        notes.append(f'{len(never)} of {len(model.order)} elements of "{title}" are never revealed; '
                     "they come in with the rest frame")
    frames.append(_snap(model, set(model.keys), set()))
    scene = {"kind": model.kind, "keys": model.keys, "frames": frames, "steps": len(frames) - 2,
             "rest": len(frames) - 1, "start": "empty" if empty else "full", "title": title, "repairs": repairs}
    return scene, notes
