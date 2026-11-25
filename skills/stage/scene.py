"""A scene: one board, the keys of what the eye can land on in it, and the frames its verbs make.

Keys: node:<id>, edge:<a>-><b>#<n> (the n-th edge from a to b), group:<subgraph id>, line:<n>, old:<n> (a line a
change removed, by its old number), row#<n>,
for a sequence spec actor:<id> and step:<id>, and for a map box:<id>, zone:<i> and route:<r> (a step of its
route). An edge shows as soon as both its ends do.
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
import os
import re
import unicodedata
from dataclasses import dataclass, field, replace
from html.entities import html5

LATER = ("-", "mark", "strike", "callout", "morph")
AUTO_STEP_OVER = 3
FUZZY_RATIO = 0.8

_VERB = re.compile(r"(?:(?P<sym>[+-])|(?P<word>next|all|focus|mark|strike|callout|morph)(?![\w-]))\s*(?P<rest>.*)\Z",
                   re.IGNORECASE | re.DOTALL)
_TARGET = re.compile(r"none|(?:old\s+)?(?:lines?\s+)?\d+(?:\s*[-–]\s*\d+)?|rows?\s+\S.*|(?:nodes?|box(?:es)?|zones?|routes?)\s+[\w.-]+"
                     r"|[\w.-]+?\s*-+>\s*[\w.-]+|[\w.-]+", re.IGNORECASE)
_LINES = re.compile(r"(?:(?P<old>old)\s+)?(?:lines?\s+)?(?P<a>\d+)(?:\s*[-–]\s*(?P<b>\d+))?", re.IGNORECASE)
_CELL = re.compile(r"cells?\s+(?P<r>.+?)\s*(?:/|,|×)\s*(?P<c>.+)", re.IGNORECASE)


_PAREN = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*\Z")


def _bare(text: str) -> str:
    """A name without its trailing parenthetical (a unit, a note): "Cost (USD)" is "cost"."""
    return fold(_PAREN.sub("", text.strip()))


def _by_text(names: list[str], text: str, owner: list | None = None) -> tuple[int | None, bool]:
    """Which of `names` (an index) a text says: its full text, else the text without its trailing parenthetical on
    either side, else a whole word of exactly one name, else a prefix of exactly one name or of one of its words (three letters at least).
    Two names that fit a step name nothing there (names of one `owner` count as one). The flag is true when the last, loose step was the one that read."""
    want = fold(text)
    if not want:
        return None, False
    owner = owner or list(range(len(names)))
    exact = [i for i, n in enumerate(names) if fold(n) == want]
    if exact:
        return exact[0], False  # the same header twice is read as its first
    hits = [i for i, n in enumerate(names) if _bare(n) == _bare(text) and _bare(n) != ""]
    if hits:
        return (hits[0], False) if len({owner[i] for i in hits}) == 1 else (None, False)
    for fit in (lambda n: want in re.findall(r"[^\W_]+", fold(n)), lambda n: len(want) >= 3 and (fold(n).startswith(want)
                                                    or any(w.startswith(want) for w in re.findall(r"[^\W_]+", fold(n))))):
        hits = [i for i, n in enumerate(names) if fit(n)]
        if len({owner[i] for i in hits}) == 1:
            return hits[0], True
        if hits:
            return None, False
    return None, False


def _column_read(model: "SceneModel", raw: str, table: int = 0) -> tuple[int | None, bool]:
    """A column by its number or its header (see _by_text), quoted or not, in the table `table` (counted from 0);
    the flag says it was read loosely, by a word or a prefix."""
    text = raw.strip().strip("\"'“”‘’").strip()
    if text.isdigit():
        return int(text), False
    heads = model.headers[table] if table < len(model.headers) else []
    if heads:
        i, loose = _by_text(heads, text)
        return (i + 1 if i is not None else None), loose
    return model.columns.get(fold(text)), False


def _column(model: "SceneModel", raw: str, table: int = 0) -> int | None:
    return _column_read(model, raw, table)[0]


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
    said_with: dict[str, list[str]] = field(default_factory=dict)  # a map's route step: the boxes it arrives at
    alias: dict[str, list[str]] = field(default_factory=dict)  # a part's other names, as words a sentence may say it with
    ambiguous: dict[str, list[str]] = field(default_factory=dict)  # a table's text that names more than one row, with the rows
    headers: list[list[str]] = field(default_factory=list)  # a table board's header cells, one list per table
    row_table: dict[str, int] = field(default_factory=dict)  # a table board's row key -> the table (from 0) it is in


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)).lower().strip()


def lines_model(numbers) -> SceneModel:
    return SceneModel("lines", [f"line:{n}" for n in numbers])


def change_model(hunks: list[dict]) -> SceneModel:
    """A change board's lines in the order they are shown: line:<n> by its new number, and old:<n> for a removed
    line by its old one, so a range of new lines takes the removed lines inside it."""
    keys = [f"line:{r['new']}" if r.get("new") is not None else f"old:{r['old']}" for h in hunks for r in h["lines"]]
    return SceneModel("lines", list(dict.fromkeys(keys)))


_TABLE_SEP = re.compile(r"^\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def split_cells(row: str) -> list[str]:
    """A markdown table row's cells: split at pipes that are not escaped (`\\|`) and not inside a `code span`;
    an escaped pipe reads as a pipe."""
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    cells, cur, i, tick = [], "", 0, 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and row[i + 1:i + 2] == "|":
            cur += "|"
            i += 2
            continue
        if ch == "`":
            run = len(row[i:]) - len(row[i:].lstrip("`"))
            if tick == 0 and "`" * run in row[i + run:]:
                tick = run
            elif tick == run:
                tick = 0
            cur += "`" * run
            i += run
            continue
        if ch == "|" and not tick:
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def plain_cell(cell: str) -> str:
    """A table cell as the stage shows it, as words: links become their text, and code and emphasis marks go."""
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", cell)
    t = t.replace("`", "")
    t = re.sub(r"(?<!\w)([*_]{1,3})(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", t)
    return html.unescape(re.sub(r"<[^>]*>", "", t)).strip()


def parse_tables(body: str) -> list[dict]:
    """Every markdown table of a board's body, in order: {header, rows}, each row padded to the header's width.
    A table is a header line, a separator line, and the lines after it up to the first blank one, with or without
    leading pipes, as the stage draws it. Lines inside a code fence are never a table."""
    lines = [ln.strip() for ln in body.splitlines()]
    tables, i, fenced = [], 0, False
    while i < len(lines):
        if _FENCE.match(lines[i]):
            fenced = not fenced
        if not fenced and i + 1 < len(lines) and "|" in lines[i] and _TABLE_SEP.match(lines[i + 1]) \
                and not _TABLE_SEP.match(lines[i]):
            head = split_cells(lines[i])
            rows, j = [], i + 2
            while j < len(lines) and lines[j]:
                rows.append(split_cells(lines[j]))
                j += 1
            width = max([len(head), *map(len, rows)])
            tables.append({"header": head + [""] * (width - len(head)),
                           "rows": [r + [""] * (width - len(r)) for r in rows]})
            i = j
            continue
        i += 1
    return tables


def body_model(body: str) -> "SceneModel":
    """The scene model of a table board's body, from its markdown: all of its tables, in order."""
    return tables_model([{"header": [plain_cell(c) for c in t["header"]],
                          "rows": [[plain_cell(c) for c in r] for r in t["rows"]]} for t in parse_tables(body)])


def rows_model(cells: list[str], header: list[str] | None = None) -> SceneModel:
    """A table's rows known only by their first cell (a board's other cells unknown): see tables_model."""
    return tables_model([{"header": list(header or []), "rows": [[c] for c in cells]}], width=len(header or []))


def tables_model(tables: list[dict], width: int | None = None) -> SceneModel:
    """A table board's keys, over every table of it, rows numbered across them from 1 (`row#<n>`).
    With its header, every cell is a key too (`cell#<row>.<column>`, the column counted from 1 in its own
    table), so one cell can be the one being said; a cell brings its row, and a row brings the rows before it, so
    the table never shows a gap. A column is `col#<c>` (`col#<table>.<c>` with more than one table, both from 1)
    and brings the rows of its table. A row is named by its first cell, by any other cell whose text is in
    no other row, and by its first and second cell together ("Azure / Cost"); a text that names two rows or more
    is kept in `ambiguous`, never guessed. Columns are named by their header (`columns` for the first table,
    kept apart from the parts' names, so a row named in words never matches a column)."""
    keys: list[str] = []
    names: dict[str, str] = {}
    seen: dict[str, list[str]] = {}
    up: dict[str, list[str]] = {}
    down: dict[str, list[str]] = {}
    columns: dict[str, int] = {}
    row_table: dict[str, int] = {}
    colkeys: list[str] = []
    n = 0
    for t, table in enumerate(tables):
        head = table["header"]
        cols = width if width is not None else max([len(head), *(len(r) for r in table["rows"])] or [0])
        first = n
        for c, h in enumerate(head, 1):
            if t == 0 and fold(h):
                columns.setdefault(fold(h), c)
        for row in table["rows"]:
            n += 1
            key = f"row#{n}"
            keys.append(key)
            row_table[key] = t
            if n > 1:
                up[key] = [f"row#{n - 1}"]  # a row brings the rows before it, across tables too
            texts = {fold(x) for x in row if fold(x)}
            for text in texts:
                seen.setdefault(text, [])
                if key not in seen[text]:
                    seen[text].append(key)
            if len(row) >= 2 and fold(row[0]) and fold(row[1]):
                for sep in (" / ", " ", " - ", " · "):
                    seen.setdefault(fold(row[0] + sep + row[1]), []).append(key)
            for c in range(1, cols + 1):
                up[f"cell#{n}.{c}"] = [key]
                down.setdefault(key, []).append(f"cell#{n}.{c}")  # a row shown shows its cells
        rows_of_table = [f"row#{r}" for r in range(first + 1, n + 1)]
        for c in range(1, cols + 1):
            ck = f"col#{c}" if len(tables) == 1 else f"col#{t + 1}.{c}"
            colkeys.append(ck)
            down[ck] = rows_of_table
    # the first cell names its row first: a text some row starts with, and no other row does, is that row's
    for key, row in zip(keys, [r for table in tables for r in table["rows"]]):
        if fold(row[0]) and len(seen.get(fold(row[0]), [])) == 1:
            names[fold(row[0])] = key
    ambiguous: dict[str, list[str]] = {}
    for text, rows in seen.items():
        if len(rows) == 1:
            names.setdefault(text, rows[0])
        else:
            ambiguous[text] = rows
            names.pop(text, None)
    return SceneModel("rows", keys + [k for k in up if k.startswith("cell#")] + colkeys, order=list(keys), up=up, down=down,
                      names=names, can_hide=True, columns=columns, ambiguous=ambiguous,
                      headers=[list(t["header"]) for t in tables], row_table=row_table)


_HEADER = re.compile(r"\A\s*(?:graph|flowchart)\b(?:[ \t]+(?:TB|TD|BT|RL|LR)\b)?", re.IGNORECASE)
_ID = re.compile(r"\w+(?:[-.]\w+)*")
_AMP = re.compile(r"\s*&\s*")
_CLASS = re.compile(r":::[\w-]+")
_LINK = re.compile(r"\s*(?:(?P<open><?(?:--|==|-\.))\s+(?P<text>[^\n]+?)\s+(?P<close>-{2,}>|-{3,}|={2,}>|={3,}|\.-+>|\.-+)"
                   r"|(?P<arrow><?(?:-{2,}|={2,}|-\.+-|~{3,})[->ox]?))\s*(?:\|(?P<label>[^|]*)\|)?\s*")


def _link_style(link: re.Match) -> dict | None:
    """How a Mermaid link is drawn on the map: dashed for a dotted one (`-.->`), a head at both ends for
    `<-->`, none for an open line (`---`); None for an invisible link (`~~~`), which is no arrow at all."""
    token = link["open"] + link["close"] if link["open"] else link["arrow"]
    if "~" in token:
        return None
    head = token[-1] in ">xo"
    return {**({"line": "dashed"} if "." in token else {}),
            **({"heads": "both"} if head and token.startswith("<") else {} if head else {"heads": "none"})}
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
_STATE_KIND = re.compile(r"state\s+(?P<id>[\w.-]+)\s*<<(?P<kind>choice|fork|join)>>\Z", re.IGNORECASE)
_STATE_DESC = re.compile(r"(?P<id>[\w.-]+)\s*:\s*(?P<label>.+)\Z")


def mermaid_spec(body: str) -> dict | None:
    """A Mermaid graph, flowchart or state diagram as a flowchart spec, for the stage to draw as its map;
    None for any other kind of Mermaid. Every label is the words it shows (`_text`, no markup); a subgraph is a
    group of its parts, with no box (`_ungroup`); a link keeps its look (`_link_style`); `{...}` shapes and a
    state's `<<choice>>` are decisions; in a state
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
        starts, ends, kinds = set(), set(), {}
        for raw in text.splitlines()[1:]:
            st = raw.strip()
            if not st or _SKIP.match(st) or st in ("{", "}") or st.lower().startswith(("note", "end note")):
                continue
            if m := _STATE_AS.match(st):
                node(m["id"], _text(m["label"]))
            elif m := _STATE_KIND.match(st):
                kinds[m["id"]] = m["kind"].lower()
                node(m["id"])
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
        for ident, kind in kinds.items():  # a choice is a decision, wherever it stands; a fork or join says what it does
            if kind == "choice":
                nodes[ident]["role"] = "decision"
            else:
                nodes[ident].setdefault("sub", "splits into paths that run at once" if kind == "fork" else "waits for every path")
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
            chain, links, i = [], [], 0
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
                links.append((_text(link["text"] or link["label"] or ""), _link_style(link)))
                i = link.end()
            for (left, right), (label, style) in zip(zip(chain, chain[1:]), links):
                for a, _ in left:
                    for b, _ in right:
                        if style is not None:
                            edges.append({"from": a, "to": b, **({"label": label} if label else {}), **style})
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


_SEQ_HEAD = re.compile(r"\A\s*sequenceDiagram\b", re.IGNORECASE)
_SEQ_ACTOR = re.compile(r"(?:participant|actor)\s+(?P<id>[\w.-]+)(?:\s+as\s+(?P<label>.+))?\Z", re.IGNORECASE)
_SEQ_MSG = re.compile(r"(?P<a>\w+(?:[-.]\w+)*)\s*(?P<arrow><<-->>|<<->>|-->>|->>|-->|->|--x|-x|--\)|-\))\s*[+-]?\s*"
                      r"(?P<b>\w+(?:[-.]\w+)*)\s*(?::(?P<text>.*))?\Z")
_SEQ_NOTE = re.compile(r"note\s+(?:over|left\s+of|right\s+of)\s+(?P<a>[\w.-]+)(?:\s*,\s*(?P<b>[\w.-]+))?\s*:(?P<text>.*)\Z",
                       re.IGNORECASE)
_SEQ_OPEN = re.compile(r"(?P<kind>loop|alt|opt|par)\b\s*(?P<text>.*)\Z", re.IGNORECASE)
_SEQ_SKIP = re.compile(r"(?:autonumber|activate|deactivate)\b", re.IGNORECASE)


def mermaid_sequence_spec(body: str) -> dict | None:
    """A Mermaid sequenceDiagram as a sequence spec, for the stage to draw as its lanes; None for any other kind.
    A participant or actor is an actor (`as` gives its label); a solid message is a request and a dashed one an
    event, one to itself a self step; a note is a band across the actors it is over; `loop`, `opt`, and `alt` or
    `par` with their `else` and `and` branches are boxes. ValueError names anything else it would have to drop
    (a box inside a box, `critical`, `break`, `rect`, `box`, `create`), so nothing is lost without a word."""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith("%%")]
    if not lines or not _SEQ_HEAD.match(lines[0]):
        return None
    actors: dict[str, dict] = {}
    steps: list[dict] = []
    groups: list[dict] = []
    spec: dict = {}
    box: dict | None = None  # the box being read, with the branch it is on

    def actor(ident: str, label: str = "") -> str:
        a = actors.setdefault(ident, {"id": ident, "label": ident})
        if label:
            a["label"] = label
        return ident

    def step(**fields) -> None:
        s = {"id": f"s{len(steps) + 1}", **fields}
        if box:
            s["group"] = box["group"]["id"]
            if "branches" in box["group"]:
                s["branch"] = box["branch"]
        steps.append(s)

    for st in lines[1:]:
        low = st.lower()
        if _SEQ_SKIP.match(st):
            continue
        if low.startswith("title"):
            spec["title"] = _text(st[5:].lstrip(" :"))
        elif m := _SEQ_ACTOR.match(st):
            actor(m["id"], _text(m["label"] or ""))
        elif m := _SEQ_MSG.match(st):
            a, b, text = actor(m["a"]), actor(m["b"]), _text(m["text"] or "")
            arrow = "self" if a == b else "event" if m["arrow"].lstrip("<").startswith("--") else "request"
            step(**{"from": a, "to": b, "arrow": arrow, **({"label": text} if text else {})})
        elif m := _SEQ_NOTE.match(st):
            a, b = actor(m["a"]), actor(m["b"] or m["a"])
            step(**{"from": a, "to": b, "arrow": "band", "label": _text(m["text"])})
        elif m := _SEQ_OPEN.match(st):
            if box:
                raise ValueError(f"{m['kind'].lower()} inside {box['kind']} has no box of its own on the lanes")
            kind, cond = m["kind"].lower(), _text(m["text"]) or m["kind"].lower()
            group = {"id": f"g{len(groups) + 1}", "kind": kind,
                     **({"branches": [cond]} if kind in ("alt", "par") else {"label": cond})}
            groups.append(group)
            box = {"kind": kind, "group": group, "branch": 0}
        elif box and re.match(r"(?:else|and)\b", low) and "branches" in box["group"]:
            box["group"]["branches"].append(_text(st[4 if low.startswith("else") else 3:]) or "else")
            box["branch"] += 1
        elif low == "end" and box:
            box = None
        else:
            raise ValueError(f"the line {st[:40]!r} has no place on the lanes")
    if box:
        raise ValueError(f"the {box['kind']} has no end")
    return {**spec, "actors": list(actors.values()), "steps": steps, **({"groups": groups} if groups else {})}


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


MODES = ("mode:both", "mode:before", "mode:after")  # the sides of a compare sequence the voice can point at (lanes.js)


OUTCOME = "outcome:end"  # a sequence's closing outcome box, a part of its scene like a step


def sequence_model(spec: dict) -> SceneModel:
    """A sequence spec: its actors, then its steps, which come in order and each bring their actors."""
    actors = [f"actor:{a['id']}" for a in spec["actors"]]
    steps = [f"step:{s['id']}" for s in spec["steps"]]
    up = {f"step:{s['id']}": list(dict.fromkeys([f"actor:{s['from']}", f"actor:{s['to']}"])) for s in spec["steps"]}
    # a compare board's moved step brings its before row, which no sentence names on its own
    gone = {f"step:{s['replaces']}" for s in spec["steps"] if s.get("replaces")}
    alias: dict[str, list[str]] = {}
    old = {s["id"]: s for s in spec["steps"]}
    for s in spec["steps"]:
        if s.get("replaces"):
            up[f"step:{s['id']}"].append(f"step:{s['replaces']}")
            alias[f"step:{s['id']}"] = [str(old[s["replaces"]].get("label", ""))]  # the old words name the row too
        elif s.get("change") == "changed" and s.get("before") and s["before"].get("label") != s.get("label"):
            alias[f"step:{s['id']}"] = [str(s["before"].get("label", ""))]
    steps = [k for k in steps if k not in gone]
    outcome = spec.get("outcome")
    names: dict[str, str] = {}
    # a sentence names the step as it stands now: a row with no after step (a compare board's) only after the others
    for s in sorted(spec["steps"], key=lambda s: s.get("change") in ("removed", "moved") and "after" not in s):
        names.setdefault(fold(str(s.get("label", ""))), f"step:{s['id']}")
    for a in spec["actors"]:
        names.setdefault(fold(str(a.get("label", "")).replace("\n", " ")), f"actor:{a['id']}")
    names.pop("", None)
    tail: list[str] = []
    if isinstance(outcome, dict):  # the box that closes the diagram comes in last, and a point can name it
        tail = [OUTCOME]
        names.setdefault(fold(str(outcome.get("title", ""))), OUTCOME)
        names.pop("", None)
    steps = steps + tail
    if spec.get("compare"):  # a compare board's views are keys too, so the voice can point at one
        keys = actors + [f"step:{s['id']}" for s in spec["steps"]] + tail + list(MODES)
        return SceneModel("sequence", keys, order=steps, up=up, names=names, can_hide=True, alias=alias)
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


def map_model(spec: dict) -> SceneModel:
    """An architecture map (map_svg): its boxes and zones in build order, then the steps of its route.

    The build order is each part's `b` (a part with none comes first; a child takes its box's, a zone its first
    box's), then the order the spec lists them in. A child box rides in with the box it sits in, unless its own
    `b` is later; a zone brings its boxes. A structure arrow (`edge:<from>-><to>#<n>`) shows once both its
    boxes do, as on a flowchart. A route step (`route:<r>`, every route arrow with that `r`) brings the boxes
    its arrows join, and is said with the boxes it arrives at. Parts are named by a box's name, a zone's label,
    and a route step's arrow labels and caption title."""
    from skills._shared.visuals.map_svg import arrow_keys

    plain = lambda t: fold(str(t or "").replace("`", ""))  # noqa: E731
    up: dict[str, list[str]] = {}
    down: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    built: list[tuple[int, int, int, str]] = []  # (b, box 0 or zone 1, place, key)
    first_b: dict[str, int] = {}

    def walk(box: dict, parent: str | None, inherited: int | None) -> None:
        key = f"box:{box['id']}"
        b = box.get("b", inherited)
        first_b[box["id"]] = b or 0
        built.append((b or 0, 0, len(built), key))
        names.setdefault(plain(box.get("name")), key)
        if parent:
            up[key] = [parent]
            if b == inherited:
                down.setdefault(parent, []).append(key)
        for child in box.get("children") or []:
            walk(child, key, b)

    for box in spec.get("boxes") or []:
        walk(box, None, None)
    for i, z in enumerate(spec.get("zones") or []):
        key = f"zone:{i}"
        b = z.get("b", min((first_b.get(m, 0) for m in z.get("boxes") or []), default=0))
        built.append((b or 0, 1, len(built), key))
        down[key] = [f"box:{m}" for m in z.get("boxes") or []]
        if z.get("label"):
            names.setdefault(plain(z["label"]), key)
    order = [key for *_, key in sorted(built)]
    edges: dict[tuple[str, str], list[str]] = {}
    route: dict[str, list[dict]] = {}
    for a, key in zip(spec.get("arrows") or [], arrow_keys(spec)):
        if key.startswith("route:"):
            route.setdefault(key, []).append(a)
        else:
            up[key] = [f"box:{a['from']}", f"box:{a['to']}"]
            edges.setdefault((a["from"], a["to"]), []).append(key)
    steps = sorted(route, key=lambda k: int(k.split(":")[1]))
    captions = (spec.get("captions") or {}).get("route") or []
    said_with: dict[str, list[str]] = {}
    for key in steps:
        arrows = route[key]
        up[key] = list(dict.fromkeys(f"box:{a[end]}" for a in arrows for end in ("from", "to")))
        said_with[key] = list(dict.fromkeys(f"box:{a['to']}" for a in arrows))
        for a in arrows:
            if a.get("label"):
                names.setdefault(plain(a["label"]), key)
        r = int(key.split(":")[1])
        if 1 <= r <= len(captions) and isinstance(captions[r - 1], dict) and captions[r - 1].get("title"):
            names.setdefault(plain(captions[r - 1]["title"]), key)
    names.pop("", None)
    keys = [k for k in order if k.startswith("zone:")] + [k for k in order if k.startswith("box:")] \
        + [k for pair in edges.values() for k in pair] + steps
    return SceneModel("map", keys, order=order + steps, up=up, down=down, names=names, edges=edges, can_hide=True,
                      said_with=said_with)


def parts_model(parts: list[dict]) -> SceneModel:
    """A scene's parts, in page order. A part brings the part it sits in; a part brings the parts inside it,
    except those the answer reveals on their own (compile_scene drops those from `down`)."""
    keys = [f"part:{p['id']}" for p in parts]
    up = {f"part:{p['id']}": [f"part:{p['parent']}"] for p in parts if p.get("parent")}
    down: dict[str, list[str]] = {}
    for child, (parent,) in up.items():
        down.setdefault(parent, []).append(child)
    names: dict[str, str] = {}
    for p in parts:
        if fold(p.get("name") or ""):
            names.setdefault(fold(p["name"]), f"part:{p['id']}")
    return SceneModel("parts", keys, order=list(keys), up=up, down=down, names=names, can_hide=True)


def bars_model(spec: dict) -> SceneModel:
    """A bars board (bars_svg): one key per bar, `bar:<id>`, in the order the spec lists them. A bar is named by its label,
    so a sentence that says it brings it in; `rows A-B` counts the bars as they are listed."""
    bars = [b for b in spec.get("bars") or [] if b.get("id")]
    keys = [f"bar:{b['id']}" for b in bars]
    names: dict[str, str] = {}
    for b, key in zip(bars, keys):
        names.setdefault(fold(str(b.get("label", ""))), key)
    names.pop("", None)
    return SceneModel("bars", keys, order=list(keys), names=names, can_hide=True)


def graph_model(spec: dict) -> SceneModel:
    """A graph board (graph_svg): its nodes by how many parents deep they are, then lane; an edge shows once both its
    nodes do. With a before and an after (some node not `same`) the two frames are keys too (`mode:before`,
    `mode:after`, `mode:both`), so the voice can point at one."""
    from skills._shared.visuals import graph_svg

    layer = graph_svg.layout(spec)["layer"]
    nodes = sorted(spec["nodes"], key=lambda n: layer[n["id"]])
    keys = [f"node:{n['id']}" for n in nodes]
    up: dict[str, list[str]] = {}
    edges: dict[tuple[str, str], list[str]] = {}
    for e, key in zip(spec.get("edges") or [], graph_svg.edge_keys(spec)):
        up[key] = [f"node:{e['from']}", f"node:{e['to']}"]
        edges.setdefault((e["from"], e["to"]), []).append(key)
    names: dict[str, str] = {}
    for n in nodes:
        for text in (n.get("label"), n.get("sub")):
            if text:
                names.setdefault(fold(str(text)), f"node:{n['id']}")
    modes = list(MODES) if graph_svg.has_frames(spec) else []
    return SceneModel("graph", keys + [k for pair in edges.values() for k in pair] + modes, order=keys, up=up, names=names,
                      edges=edges, can_hide=True)


ENTITY_PREFIXES = {"sequence": ("step:", "actor:"), "parts": ("part:",), "map": ("box:", "zone:", "route:"),
                   "bars": ("bar:",)}


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


_NUMS = r"\d+(?:\s*[-–]\s*\d+)?"
_ROW_LIST = re.compile(rf"rows?\s+(?P<list>{_NUMS}(?:\s*,\s*{_NUMS})+)", re.IGNORECASE)
_COLUMN = re.compile(r"col(?:umn)?s?\.?\s+(?P<list>.+)", re.IGNORECASE)
_CELLS = re.compile(r"cells\s+(?P<list>.+)", re.IGNORECASE)


def _says(rows: list[str]) -> str:
    nums = [r.split("#")[1] for r in rows]
    return "rows " + " and ".join(nums) if len(nums) == 2 else "rows " + ", ".join(nums[:-1]) + " and " + nums[-1]


def _column_key(model: SceneModel, raw: str) -> tuple[str | None, bool]:
    """A column's key and whether it was read loosely: a number, a header, or `table.column` over several tables;
    a header names its first table that has it."""
    text = raw.strip().strip("\"'“”‘’").strip()
    many = len(model.headers) > 1
    pair = re.fullmatch(r"(\d+)\.(\d+)", text)
    key, loose = None, False
    if pair and many:
        key = f"col#{pair[1]}.{pair[2]}"
    elif text.isdigit():
        key = f"col#1.{text}" if many else f"col#{text}"
    else:
        for step in (False, True):  # a whole header first in every table, a loose word or prefix after
            for t, heads in enumerate(model.headers):
                c, was = _column_read(model, text, t)
                if c and was == step:
                    key, loose = (f"col#{t + 1}.{c}" if many else f"col#{c}"), was
                    break
            if key:
                break
    return (key, loose) if key in model.keys else (None, False)


def _row_by_text(model: SceneModel, word: str) -> tuple[str | None, bool]:
    """A row named by its text without a trailing parenthetical, else by a whole word or a prefix of one name that
    belongs to one row only (see _by_text). A text a second row has too names nothing."""
    texts = list(model.names)
    i, loose = _by_text(texts, word, [model.names[t] for t in texts])
    return (model.names[texts[i]], loose) if i is not None else (None, False)


def _span(keys: list[str]) -> str:
    nums = [int(k.split("#")[1]) for k in keys]
    if len(nums) == 1:
        return f"row {nums[0]}"
    return f"rows {nums[0]}-{nums[-1]}" if nums == list(range(nums[0], nums[-1] + 1)) else "rows " + ", ".join(map(str, nums))


def _resolve_row(model: SceneModel, text: str, raw: str, title: str, dropped: str) -> tuple[list[str], str | None]:
    """One row: by its number, else by text (a first cell, any cell no other row has, or the first and second cell
    together), a quoted text first. Text that names more than one row is refused, never guessed."""
    quoted = re.fullmatch(r"(?:\"(.+)\"|“(.+)”|'(.+)')", text.strip())
    word = next((g for g in quoted.groups() if g), None) if quoted else text.strip()
    if not quoted and word.isdigit() and not (int(word) > len(model.order) and fold(word) in model.names):
        key = f"row#{int(word)}"
        if key in model.keys:
            return [key], None
        return [], f'"{title}" has {len(model.order)} rows, not row {int(word)}; dropped'
    if fold(word) in model.ambiguous:
        return [], (f'"{raw}" in "{title}" names {_says(model.ambiguous[fold(word)])}; '
                    'say the row by its number, or by its first and second cell like "first / second"; dropped')
    if fold(word) in model.names:
        return [model.names[fold(word)]], None
    key, loose = _row_by_text(model, word)
    if key:
        return [key], (f'"{raw}" in "{title}" read as {key}' if loose else None)
    key = _closest(model, word)
    return ([key], f'"{raw}" in "{title}" read as {key}') if key else ([], dropped)


def _resolve_rows(model: SceneModel, raw: str, title: str, dropped: str) -> tuple[list[str], str | None]:
    """A table board's targets: row N, rows A-B, rows 2,5, row "text", cell R / C, cells R / C; R / C, column X."""
    if (m := _CELLS.fullmatch(raw)):
        keys, notes = [], []
        for item in (i for i in re.split(r"\s*;\s*", m["list"]) if i.strip()):
            got, note = _resolve_rows(model, "cell " + item, title, f'"{item.strip()}" in "{title}" matches nothing; dropped')
            keys += [k for k in got if k not in keys]
            notes += [note] if note else []
        return keys, "; ".join(notes) or None
    if (cell := _CELL.fullmatch(raw)):
        row, note = _resolve_row(model, cell["r"], raw, title, dropped)
        if not row and any(c and not loose for c, loose in (_column_read(model, cell["r"], t)
                                                           for t in range(max(1, len(model.headers))))):
            swapped, _ = _resolve_row(model, cell["c"], raw, title, dropped)  # written column first, then row
            if swapped:
                row, note = swapped, None
                cell = {"r": cell["c"], "c": cell["r"]}
        if not row:
            return [], note
        r = int(row[0].split("#")[1])
        col, loose = _column_read(model, cell["c"], model.row_table.get(row[0], 0))
        key = f"cell#{r}.{col}" if col else None
        if key not in model.keys:
            return [], dropped
        if loose:
            heads = model.headers[model.row_table.get(row[0], 0)]
            note = "; ".join(x for x in (note, f'"{cell["c"].strip()}" in "{title}" read as column "{heads[col - 1]}"') if x)
        return [key], note
    if (m := _COLUMN.fullmatch(raw)):
        keys, notes = [], []
        for item in (i for i in re.split(r"\s*[,;]\s*", m["list"]) if i.strip()):
            key, loose = _column_key(model, item)
            if key is None:
                notes.append(f'no column {item.strip()} in "{title}"')
                continue
            if loose:
                t, _, c = key.removeprefix("col#").rpartition(".")
                head = model.headers[int(t) - 1 if t else 0][int(c) - 1]
                notes.append(f'"{item.strip()}" in "{title}" read as column "{head}"')
            if key not in keys:
                keys.append(key)
        return keys, "; ".join(notes) or None
    if (m := _ROW_LIST.fullmatch(raw)):
        keys = []
        for part in m["list"].split(","):
            a, _, b = part.replace("–", "-").partition("-")
            lo, hi = sorted((int(a), int(b or a)))
            keys += [f"row#{k}" for k in range(lo, hi + 1) if f"row#{k}" not in keys]
        if all(k in model.keys for k in keys):
            return keys, None
        kept = [k for k in keys if k in model.keys]
        if kept:
            return kept, f'"{title}" has {len(model.order)} rows, so {raw.strip()} is read as {_span(kept)}'
        return [], f'"{title}" has {len(model.order)} rows, not {raw.strip()}; dropped'
    m = _ROW.fullmatch(raw)
    if m and m["n"]:
        a, b = sorted((int(m["n"]), int(m["n2"] or m["n"])))
        keys = [f"row#{n}" for n in range(a, b + 1)]
        if all(k in model.keys for k in keys):
            return keys, None
        if a == b and fold(m["n"]) in model.names:
            return [model.names[fold(m["n"])]], None  # a row whose first cell is the number
        said = f"row {a}" if a == b else f"rows {a}-{b}"
        kept = [k for k in keys if k in model.keys]
        if kept:  # a range that runs past the table is cut at its end
            return kept, f'"{title}" has {len(model.order)} rows, so {said} is read as {_span(kept)}'
        return [], f'"{title}" has {len(model.order)} rows, not {said}; dropped'
    text = (m["q"] or m["c"] or m["s"] or m["bare"]) if m else raw
    return _resolve_row(model, '"' + text + '"', raw, title, dropped)


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
    if model.kind == "rows":
        return _resolve_rows(model, raw, title, dropped)
    if model.kind == "map":  # box ID, zone N, route N
        named = re.fullmatch(r"(box|zone|route)(?:e?s)?\s+(.+)", raw, re.IGNORECASE)
        if named and f"{named[1].lower()}:{named[2].strip()}" in model.keys:
            return [f"{named[1].lower()}:{named[2].strip()}"], None
    if model.kind == "sequence" and OUTCOME in model.keys and re.fullmatch(r"(?:the\s+)?outcome", raw, re.IGNORECASE):
        return [OUTCOME], None
    if model.kind == "bars" and (rows := re.fullmatch(r"rows?\s+(\d+)(?:\s*[-–]\s*(\d+))?", raw, re.IGNORECASE)):
        a, b = sorted((int(rows[1]), int(rows[2] or rows[1])))
        if 1 <= a and b <= len(model.order):
            return model.order[a - 1:b], None
        return [], f'"{title}" has {len(model.order)} bars, not {"row " + str(a) if a == b else f"rows {a}-{b}"}; dropped'
    side = "both" if raw.lower() == "merged" else raw.lower()   # merged: the name the side by side board replaced
    if model.kind in ("sequence", "graph") and f"mode:{side}" in model.keys:  # before, after or both
        return [f"mode:{side}"], None
    m = re.fullmatch(r"(?:nodes?|steps?|parts?|bars?|box(?:es)?)\s+(.+)", raw, re.IGNORECASE)
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
            # a row is shown whole, a part with what it holds, a map's box with its children and a zone with its boxes
            if k.startswith(("row#", "col#", "part:", "box:", "zone:")):
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
    for k in list(cur):
        cur += model.said_with.get(k, [])  # a map's route step with the boxes it arrives at
    cur = list(dict.fromkeys(cur))
    node = next((k for k in reversed(cur) if k.startswith(("node:", "box:"))), None)
    if model.kind in ("flowchart", "map", "graph") and node and not any(k.startswith("edge:") for k in cur):
        edges = [k for k in new if k.startswith("edge:")]
        edge = next((e for e in edges if model.up[e][1] == node), None) or next((e for e in edges if model.up[e][0] == node), None)
        if edge:
            cur.append(edge)
    return cur


# Words too common to name a part by.
_STOP = frozenset("""a an and are as at be but by can did does for from had has have her his how into its just not now
off once one only our out over she than that the their them then there these they this those too two very was way
were what when where which who why will with you your yours it's is it of on or so to in up we us he if do no all
any each few more most other some such own same both here first finally""".split())


def _words(text: str) -> list[str]:
    # a short word that holds a digit (L1, S3, v2) names a part, as "L1 cache" and "L2 cache" must be told apart
    return [w for w in re.findall(r"[^\W_]+", fold(text)) if (len(w) >= 3 or (len(w) == 2 and any(c.isdigit() for c in w)))
            and w not in _STOP]


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
    for key, texts in model.alias.items():
        out.setdefault(key, []).extend(_words(t) for t in texts if _words(t))
    for key in model.order:
        ident = key.split(":", 1)[1] if key.startswith(("node:", "step:", "group:", "part:", "box:", "bar:")) else ""
        if len(ident) >= 3 and not re.fullmatch(r"[a-z]?\d+", ident, re.IGNORECASE) and _words(ident):
            out.setdefault(key, []).append(_words(ident))
    return out


def _near(a: str, b: str) -> bool:
    """One distinctive word said for another, in any alphabet: the same word, a plain inflection of a short one
    (hit, hits), or words that share a prefix of five letters, or of four that is 70 percent of the longer (both of five or more)."""
    a, b = sorted((a, b), key=len)
    if a == b:
        return True
    if len(a) < 4:
        return len(a) == 3 and b in (a + "s", a + "es", a + "d", a + "ed")
    n = len(os.path.commonprefix([a, b]))
    return n >= 5 or (n >= 4 and len(a) >= 5 and n >= 0.7 * len(b))


def distinctive(model: SceneModel) -> dict[str, frozenset]:
    """Per part, the words of its names that no other part's names hold, in that form or a close one (ask, asks):
    a word that names this part alone. A short word (under five letters) counts only when it is the one word of its
    name that tells the part from the others (hit, miss in "Cache hit" and "Cache miss"): next to a longer
    distinctive word, a short one ("puts" in "puts up the boards") is as likely a common verb."""
    names = part_names(model)
    held = {key: {w for words in texts for w in words} for key, texts in names.items()}
    held["~"] = {w for text in model.ambiguous for w in _words(text)}  # a table text two rows share names none of them
    out: dict[str, frozenset] = {}
    for key, texts in names.items():
        alone = {w for words in texts for w in words
                 if not any(o != key and any(_same(w, x) or _near(w, x) for x in theirs) for o, theirs in held.items())}
        keep: set[str] = set()
        for words in texts:
            mine = [w for w in words if w in alone]
            # in a sentence-long name (a table row's text) only the long words count
            keep |= {w for w in mine if len(w) >= 5 or (len(mine) == 1 and len(words) <= 3)}
        out[key] = frozenset(keep)
    return out


def _said_as(word: str, said: str, dist=frozenset()) -> bool:
    return _same(word, said) or (word in dist and _near(word, said))


def names_part(sentence: list[str], names: list[list[str]], dist=frozenset()) -> bool:
    """A sentence names a part when it says more than half of the words of one of its names, or a word of them that
    no other part holds (`dist`, see distinctive), in the same word or a close form of it."""
    return any(sum(any(_said_as(w, s, dist) for s in sentence) for w in name) > len(name) // 2
               or any(w in dist and any(_said_as(w, s, dist) for s in sentence) for w in name) for name in names)


def _ambiguous_said(model: SceneModel, words: list[str]) -> int:
    """The most words of a table text that names more than one row which a sentence says whole, else 0."""
    best = 0
    for text in model.ambiguous:
        ws = _words(text)
        if ws and all(any(_same(w, s) for s in words) for w in ws):
            best = max(best, len(ws))
    return best


def said_parts(model: SceneModel, sentences: list[str]) -> dict[int, list[str]]:
    """A diagram too small to step (AUTO_STEP_OVER parts or fewer) still follows the voice: it shows whole, and
    each sentence that names a part marks it as being said. Per sentence index, the one part it names most
    fully: the largest share of one of its names said, then the most words of it ("Copy Production" is the copy,
    not Production). A table does the same by its rows, named by their cells and never by a column header; a
    text that two rows have names neither."""
    if model.kind not in ("flowchart", "sequence", "map", "bars", "graph", "rows") or len(model.order) < 2:
        return {}
    names, dist = part_names(model), distinctive(model)
    out: dict[int, list[str]] = {}
    for i, sentence in enumerate(sentences):
        words = _words(sentence)
        best, score = None, (0.0, 0)
        for p in model.order:
            if not names_part(words, names.get(p, []), dist.get(p, frozenset())):
                continue
            for name in names.get(p, []):
                said = sum(any(_said_as(w, s, dist.get(p, frozenset())) for s in words) for w in name)
                if (said / len(name), said) >= score:
                    best, score = p, (said / len(name), said)
        if best and model.kind == "rows" and _ambiguous_said(model, words) >= score[1]:
            best = None  # a text two rows share is said as much as the row's own: the voice names no one row
        if best:
            out[i] = [best]
    return out


def auto_steps(model: SceneModel, sentences: list[str], pointed: dict[int, list[str]] | None = None
               ) -> tuple[dict[int, list[list[str]]], list[str]]:
    """A board with no reveals of its own, brought in over the sentences said about it.

    Each part arrives with the first sentence that names it (a sequence's steps keep their order), or with
    the sentence that points at it when that comes first. A part no sentence names is never lit by order: it
    comes in with the rest frame, and is listed in the second result (unnamed_parts says where the order would
    have put it). Only a sequence's steps and a table's rows, which are ordered by nature, fill the sentences
    that name nothing, each after the one named before it. A sentence that names a part is never given to another. A first
    sentence that names nothing is the board's introduction and brings nothing, unless no sentence names
    anything and there are no more sentences than parts. `pointed` holds, per sentence index, the parts the
    board's own points light there.
    Returns, per sentence index, the reveals for it (each a list of keys; the last is what the sentence
    is about), and the parts no sentence named."""
    plan, later, _ = _place(model, sentences, pointed)
    return plan, later


def unnamed_parts(model: SceneModel, sentences: list[str], pointed: dict[int, list[str]] | None = None) -> list[dict]:
    """The parts no sentence names, each as {key, label, sentence}: the sentence the order would have put it with
    (empty when none), so the author can say the part's own words there."""
    _, later, landed = _place(model, sentences, pointed)
    labels: dict[str, str] = {}
    for text, key in model.names.items():
        labels.setdefault(key, text)
    return [{"key": k, "label": labels.get(k) or k.split(":", 1)[-1],
             "sentence": " ".join(sentences[landed[k]].split()) if landed.get(k) is not None and landed[k] < len(sentences) else ""}
            for k in later]


def _place(model: SceneModel, sentences: list[str], pointed: dict[int, list[str]] | None
           ) -> tuple[dict[int, list[list[str]]], list[str], dict[str, int]]:
    parts, m = model.order, len(sentences)
    # a scene always steps: a page must never come up whole at once
    if not model.can_hide or len(parts) <= (1 if model.kind == "parts" else AUTO_STEP_OVER) or m < 1:
        return {}, [], {}
    words, names, dist = [_words(s) for s in sentences], part_names(model), distinctive(model)

    def says(i: int, p: str) -> bool:
        return names_part(words[i], names.get(p, []), dist.get(p, frozenset()))

    if model.kind == "map":
        # a map follows its route only when the answer follows the request: a sentence or a point names a step of it
        route = [p for p in parts if p.startswith("route:")]
        said = {k for keys in (pointed or {}).values() for k in keys}
        if not any(p in said or any(says(i, p) for i in range(m)) for p in route):
            parts = [p for p in parts if p not in route]
    point_at: dict[str, int] = {}
    for i in sorted(pointed or {}):
        for k in (pointed or {})[i]:
            part = model.up.get(k, [k])[0] if k.startswith("cell#") else k
            if part in parts:
                point_at.setdefault(part, i)
    anchor: dict[str, int] = {}
    floor = 0
    for p in parts:
        lo = floor if model.kind == "sequence" else 0
        hit = next((i for i in range(lo, min(m, point_at.get(p, m))) if says(i, p)), None)
        if hit is not None:
            anchor[p] = hit
        elif p in point_at:
            anchor[p] = point_at[p]
        elif model.kind in ("parts", "map") and model.up.get(p, [None])[0] in anchor \
                and p in model.down.get(model.up[p][0], []):
            anchor[p] = anchor[model.up[p][0]]  # a part no sentence names rides in with the part it sits in
        if p in anchor and model.kind == "sequence":
            floor = max(floor, anchor[p])
    named = {i for i in range(m) if any(says(i, p) for p in parts)}  # a sentence that names a part is that part's
    busy = set(anchor.values()) | set(point_at.values()) | named
    intro = 0 not in busy and (bool(anchor) or m > len(parts))
    free = [i for i in range(m) if i not in busy and not (i == 0 and intro)]
    fills: dict[int, list[list[str]]] = {}
    rides: dict[int, list[str]] = {}
    later: list[str] = []
    landed: dict[str, int] = {}
    run: list[str] = []
    for j, p in enumerate([*parts, None]):
        if p is not None and p not in anchor:
            run.append(p)
            continue
        if run:
            before = [anchor[q] for q in parts[:j] if q in anchor]
            lo, hi = (before[-1] if before else -1), (anchor[p] if p is not None else m)
            window = [i for i in free if lo < i < hi]
            # the order places a part only where the items are ordered by nature: a sequence's steps, a table's rows
            keep = model.kind in ("sequence", "rows")
            if window:
                k = min(len(window), len(run))
                for i in range(k):
                    chunk = run[i * len(run) // k:(i + 1) * len(run) // k]
                    landed.update({q: window[i] for q in chunk})
                    if keep:
                        fills[window[i]] = [chunk]
                if keep:
                    free = [i for i in free if i not in window[:k]]
            else:
                at = hi if p is not None else max(lo, 0)
                landed.update({q: at for q in run})
                if keep:
                    rides.setdefault(at, []).extend(run)
            later += run
            run = []
    plan: dict[int, list[list[str]]] = {}
    for i in range(m):
        own = [p for p in parts if anchor.get(p) == i]  # a pointed part too: the board still starts empty
        steps = [s for s in ([rides.get(i, [])] + fills.get(i, []) + [own]) if s]
        if steps:
            plan[i] = steps
    return plan, later, landed


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
    if model.kind in ("parts", "map"):  # a part revealed or pointed at on its own does not come in with its parent
        alone = {k for keys in named.values() for k in keys}
        model = replace(model, down={k: [c for c in v if c not in alone] for k, v in model.down.items()})
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
            if verb.name == "all":  # on a map, the whole structure: its route is followed step by step
                shown |= {k for k in model.keys if not (model.kind == "map" and k.startswith("route:"))}
                revealed = []
                continue
            if verb.name == "focus" and verb.keys is None and [t.lower() for t in verb.targets] == ["none"]:
                focus, pointed = set(), None
                continue
            keys = named[id(verb)]
            for k in keys:
                _reveal(model, k, shown)
            if verb.name == "focus":
                focus = {d for k in keys for d in [k, *(model.down.get(k, []) if k.startswith(("group:", "zone:")) else []),
                                                   *model.said_with.get(k, [])]}
                pointed = keys
            else:
                revealed = keys
        # A point is what is being said, whatever the group also revealed. A reveal with no point of its
        # own clears the old focus, so nothing lit is left behind on a part the voice has left.
        if pointed is None and revealed is not None:
            focus = set()
        said = pointed if pointed is not None else revealed or []
        frames.append(_snap(model, shown, focus, _said(model, said, before, shown)))
    never = [k for k in model.order if k not in shown and not k.startswith("route:")]  # a map's route is followed or not
    if empty and never:
        notes.append(f'{len(never)} of {len(model.order)} elements of "{title}" are never revealed; '
                     "they come in with the rest frame")
    frames.append(_snap(model, set(model.keys), set()))
    scene = {"kind": model.kind, "keys": model.keys, "frames": frames, "steps": len(frames) - 2,
             "rest": len(frames) - 1, "start": "empty" if empty else "full", "title": title, "repairs": repairs}
    return scene, notes
