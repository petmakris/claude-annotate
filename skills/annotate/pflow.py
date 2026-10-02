#!/usr/bin/env python3
"""pflow — compile a restricted subset of Python into an annotate flowchart spec.

The Python is never executed. It is parsed with `ast` (structure) and `tokenize`
(the trailing-comment tags), then lowered to the {nodes, edges} spec that
claude-annotate's `kind: "flowchart"` block already validates and renders.

Statement            -> node role
---------------------------------
def f(...)           -> entry      (label from the `# !` tag, else the name)
if / elif / else     -> decision   (label from the `# ?` tag, else the test's source)
raise X(...)         -> error
return X(...)        -> success
x = f(...)           -> code
f(...)               -> call

Trailing-comment tags, all optional:
    # ! <text>       entry label
    # ? <text>       decision label
    # id: <slug>     pin this node's id, so a reword does not orphan its comments
    # cache: <text>  sub-caption, marks a cache read
    # gate: <text>   sub-caption, marks a refusal gate
    # note: <text>   sub-caption, free text
    # ref: <Class:line>

Anything else is REFUSED with a line number rather than dropped. A flowchart that
quietly omits a branch is worse than no flowchart: it reads as complete.
"""
from __future__ import annotations

import ast, io, json, re, sys, tokenize
from typing import Any

TAG = re.compile(
    r"^#\s*(?:(?P<kind>id|cache|gate|note|ref)\s*:|(?P<sym>[!?]))\s*(?P<text>.+?)\s*$"
)

#: the flowchart block contract advises at most this many nodes before a chart
#: stops being legible inline. Exceeding it warns; it does not fail.
NODE_BUDGET = 15

ID_MAX = 20


class PflowError(Exception):
    """A source the subset refuses, reported at the line that caused it."""

    def __init__(self, message: str, line: int, filename: str = "<pflow>") -> None:
        self.line = line
        self.filename = filename
        self.reason = message
        super().__init__(f"{filename}:{line}: {message}")


def comment_tags(source: str, filename: str) -> dict[int, dict[str, str]]:
    """line number -> {tag kind: text} for every trailing comment we understand."""
    out: dict[int, dict[str, str]] = {}
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError) as exc:
        line = getattr(exc, "lineno", None) or 1
        raise PflowError("could not tokenize the source", line, filename) from exc
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        m = TAG.match(tok.string.strip())
        if not m:
            continue
        kind = m.group("kind") or {"!": "entry", "?": "decision"}[m.group("sym")]
        out.setdefault(tok.start[0], {})[kind] = m.group("text")
    return out


class Compiler:
    def __init__(self, source: str, filename: str = "<pflow>") -> None:
        self.src = source
        self.filename = filename
        self.tags: dict[int, dict[str, str]] = {}   # filled in compile(), after ast.parse
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.used: set[str] = set()
        self.pinned: dict[str, int] = {}          # explicit id -> line that claimed it
        self.warnings: list[str] = []

    def refuse(self, message: str, line: int) -> "PflowError":
        return PflowError(message, line, self.filename)

    # -- ids -------------------------------------------------------------
    def derive(self, hint: str) -> str:
        """Content-derived id, whole words only — a half-word id reads as a typo."""
        base = ""
        for word in re.sub(r"[^a-z0-9]+", " ", hint.lower()).split():
            if base and len(base) + 1 + len(word) > ID_MAX:
                break
            base = f"{base}-{word}" if base else word
        return base or "n"

    def mint(self, hint: str, line: int) -> str:
        tags = self.tags.get(line, {})
        if "id" in tags:
            pinned = tags["id"].strip()
            if pinned in self.pinned:
                raise self.refuse(
                    f"duplicate node id {pinned!r}, already pinned at line {self.pinned[pinned]}",
                    line,
                )
            if pinned in self.used:
                raise self.refuse(f"duplicate node id {pinned!r}", line)
            self.pinned[pinned] = line
            self.used.add(pinned)
            return pinned

        base = self.derive(hint)
        cand, i = base, 2
        while cand in self.used:
            cand, i = f"{base}-{i}", i + 1
        self.used.add(cand)
        return cand

    def add(self, role: str, hint: str, line: int, **fields: str) -> str:
        tags = self.tags.get(line, {})
        node: dict[str, Any] = {"id": self.mint(hint, line), "role": role}
        node.update({k: v for k, v in fields.items() if v})

        for kind, prefix in (("cache", "cache: "), ("gate", "gate: "), ("note", "")):
            if kind in tags:
                node["sub"] = prefix + tags[kind]
                break
        if "ref" in tags:
            node["ref"] = tags["ref"]

        node["line"] = line          # the anchor: which source line produced this node
        self.nodes.append(node)
        return node["id"]

    def link(self, opens: list[tuple[str, str | None]], target: str) -> None:
        for src, label in opens:
            edge = {"from": src, "to": target}
            if label:
                edge["label"] = label
            self.edges.append(edge)

    # -- statements ------------------------------------------------------
    def walk(self, body: list[ast.stmt]) -> tuple[str | None, list[tuple[str, str | None]]]:
        first: str | None = None
        opens: list[tuple[str, str | None]] = []

        for st in body:
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
                continue                                     # docstring

            line = st.lineno
            if first is not None and not opens:
                raise self.refuse(
                    "unreachable — the previous statement already returns or raises", line
                )

            if isinstance(st, ast.If):
                # not `first or self.compile_if(...)`: that short-circuits, and every
                # `if` after the first would never be compiled at all.
                nid, opens = self.compile_if(st, opens)
                first = first or nid
                continue

            nid = self.simple(st, line)
            terminal = isinstance(st, (ast.Return, ast.Raise))
            self.link(opens, nid)
            first = first or nid
            opens = [] if terminal else [(nid, None)]

        return first, opens

    def compile_if(
        self, st: ast.If, opens: list[tuple[str, str | None]]
    ) -> tuple[str, list[tuple[str, str | None]]]:
        line = st.lineno
        label = self.tags.get(line, {}).get("decision") or self.snippet(st.test)
        nid = self.add("decision", label, line, label=label)
        self.link(opens, nid)

        bfirst, bopens = self.walk(st.body)
        if bfirst:
            self.edges.append({"from": nid, "to": bfirst, "label": "yes"})

        if st.orelse:
            efirst, eopens = self.walk(st.orelse)
            if efirst:
                self.edges.append({"from": nid, "to": efirst, "label": "no"})
            return nid, bopens + eopens
        return nid, bopens + [(nid, "no")]

    def simple(self, st: ast.stmt, line: int) -> str:
        if isinstance(st, ast.Raise):
            name = self.callee(st.exc)
            return self.add("error", name, line, label=name, method=self.snippet(st.exc))

        if isinstance(st, ast.Return):
            name = self.callee(st.value)
            return self.add("success", name, line, label=name, method=self.snippet(st.value))

        if isinstance(st, ast.Assign):
            if not isinstance(st.value, ast.Call):
                raise self.refuse(
                    "an assignment must be a call, as in `x = do_something()` — "
                    "a pflow step is something that happens",
                    line,
                )
            return self.add("code", self.callee(st.value), line, method=self.snippet(st.value))

        if isinstance(st, ast.Expr):
            if not isinstance(st.value, ast.Call):
                raise self.refuse("a bare statement must be a call, as in `do_something()`", line)
            return self.add("call", self.callee(st.value), line, method=self.snippet(st.value))

        raise self.refuse(self.why_unsupported(st), line)

    def why_unsupported(self, st: ast.stmt) -> str:
        loop = ("a flowchart block must be a DAG — annotate rejects a spec whose edges "
                "form a cycle, and a loop needs a back edge. Collapse the repetition "
                "into a single step, or split the flow.")
        if isinstance(st, ast.For):
            return "a `for` loop cannot be drawn: " + loop
        if isinstance(st, (ast.While,)):
            return "a `while` loop cannot be drawn: " + loop
        if isinstance(st, (ast.With, ast.AsyncWith)):
            return "`with` blocks are not part of the pflow subset — the flow is the steps, not the scoping"
        if isinstance(st, (ast.Try,)):
            return ("`try`/`except` is not part of the pflow subset — draw the failure as an "
                    "explicit `raise` on the branch that produces it")
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return "a nested `def` is not supported — one pflow flow is one function"
        if isinstance(st, ast.ClassDef):
            return "a `class` is not supported — pflow describes a flow, not a type"
        return f"`{type(st).__name__}` is not part of the pflow subset"

    # -- source helpers --------------------------------------------------
    def snippet(self, node: ast.AST | None) -> str:
        if node is None:
            return ""
        text = ast.unparse(node)
        return text if len(text) <= 46 else text[:43] + "..."

    def callee(self, node: ast.AST | None) -> str:
        if isinstance(node, ast.Call):
            node = node.func
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Name):
            return node.id
        return "step"

    # -- entry point -----------------------------------------------------
    def compile(self) -> dict[str, Any]:
        # parse before tokenizing: ast reports a syntax error at the line that caused
        # it, where tokenize would blame line 1 of a source it could not even scan.
        try:
            tree = ast.parse(self.src, filename=self.filename)
        except SyntaxError as exc:
            raise self.refuse(exc.msg or "could not parse", exc.lineno or 1) from exc
        self.tags = comment_tags(self.src, self.filename)

        title = ast.get_docstring(tree) or "flow"
        fn = next((n for n in tree.body if isinstance(n, ast.FunctionDef)), None)
        if fn is None:
            raise self.refuse("no `def` found — a pflow source is one function", 1)

        tags = self.tags.get(fn.lineno, {})
        label = tags.get("entry") or fn.name
        entry = self.add("entry", label, fn.lineno, label=label)

        first, _ = self.walk(fn.body)
        if first:
            self.edges.append({"from": entry, "to": first})

        if len(self.nodes) > NODE_BUDGET:
            self.warnings.append(
                f"{len(self.nodes)} nodes: the flowchart block contract advises at most "
                f"{NODE_BUDGET} before a chart stops being legible inline — consider "
                f"splitting the flow"
            )
        return {"title": title, "nodes": self.nodes, "edges": self.edges,
                "warnings": self.warnings}


def compile_source(source: str, filename: str = "<pflow>") -> dict[str, Any]:
    return Compiler(source, filename).compile()


def compile_file(path: str) -> dict[str, Any]:
    with open(path) as fh:
        return compile_source(fh.read(), filename=path)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: pflow.py <source.py>", file=sys.stderr)
        return 2
    try:
        spec = compile_file(argv[1])
    except PflowError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for warning in spec["warnings"]:
        print("warning: " + warning, file=sys.stderr)
    print(json.dumps({k: v for k, v in spec.items() if k != "warnings"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
