"""Walk from an entry class to every data type it reaches.

The entry may be any class. A data class is populated directly. A behaviour class
has its own fields, its NESTED classes' fields, and its method signatures read, and
the data types those mention become the roots instead.

Walking nested classes is required, not a nicety. AnalyticsQueryService
holds three fields and all three are collaborators; the only data field in the file
is AnalyticsResult on its inner class.

The walk expands data classes only. A collaborator reached from a field is recorded
and left unexpanded, which is what keeps the graph from swallowing the application.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from .fields import Field, TypeRef, fields_of, parse_type_ref, signature_types
from .imports import SourceIndex, read_imports, resolve
from .javasrc import TypeDecl, find_types, strip_noise

_DATA_ANNOTATIONS = {'Value', 'Data', 'Entity'}
_CONTAINERS = {'List', 'Set', 'Collection', 'Optional', 'Map'}

# Calls that say nothing about the shape of a type with no source here. Every
# Java object answers equals/hashCode/toString, so observing them names no
# field, and `coverage_gaps()` then reports them as keys leaves.json is missing
# — a gap that can never be closed by any capture. A setter is excluded for the
# opposite reason: it writes, so the value it carries is the checkout's, not the
# deployment's, and the capture has no key for it either.
_UNINFORMATIVE_ACCESSORS = {'equals', 'hashCode', 'toString'}


@dataclass
class Node:
    fqn: str
    kind: str
    source: str | None = None
    line: int | None = None
    fields: list[Field] = dc_field(default_factory=list)
    reason: str | None = None
    accessors_observed: tuple[str, ...] = ()


def classify(decl: TypeDecl) -> str:
    if decl.kind in ('record', 'enum'):
        return 'data'
    if set(decl.annotations) & _DATA_ANNOTATIONS:
        return 'data'
    return 'behaviour'


def _matching_close(stripped: str, open_idx: int, opener: str, closer: str) -> int:
    depth = 0
    for j in range(open_idx, len(stripped)):
        if stripped[j] == opener:
            depth += 1
        elif stripped[j] == closer:
            depth -= 1
            if depth == 0:
                return j
    return len(stripped) - 1


def _enclosing_block(stripped: str, pos: int) -> tuple[int, int]:
    """The block offset `pos` should be searched within, as (open, close).

    A local/field declaration's scope is the brace block it sits in, found by
    walking backward for the nearest unmatched `{`. A parameter declaration sits
    inside a still-open `(...)` when scanned backward; its scope is the method
    BODY that parameter list introduces, not the block the method itself sits in
    -- otherwise a sibling method's unrelated same-named variable would leak in.
    """
    i = pos - 1
    paren_depth = 0
    brace_depth = 0
    while i >= 0:
        ch = stripped[i]
        if ch == ')':
            paren_depth += 1
        elif ch == '(':
            if paren_depth == 0:
                close_paren = _matching_close(stripped, i, '(', ')')
                brace_open = stripped.find('{', close_paren)
                if brace_open == -1:
                    return 0, len(stripped)
                return brace_open, _matching_close(stripped, brace_open, '{', '}')
            paren_depth -= 1
        elif ch == '}':
            brace_depth += 1
        elif ch == '{':
            if brace_depth == 0:
                return i, _matching_close(stripped, i, '{', '}')
            brace_depth -= 1
        i -= 1
    return 0, len(stripped)


class AccessorObserver:
    """Which methods the checkout actually calls on a type that has no source here.

    Finds declarations of that type (`Category category`), then the methods called on the
    names they bind, scoped to the brace block the declaration sits in. Scoping
    matters: a same-named variable of a different type in an unrelated method
    (`.flatMap(category -> category.allocations())` on some other `category`) must not
    contaminate this type's accessor list. The result is what the code uses, which
    is honest, and not the class's full surface, which is unknowable from here.
    """

    def __init__(self, index: SourceIndex) -> None:
        self._index = index
        self._files: list[str] | None = None
        self._raw_cache: dict[str, str] = {}
        self._stripped_cache: dict[str, str] = {}

    def _all_files(self) -> list[str]:
        if self._files is None:
            self._files = sorted({p for p in (self._index.path_of(f) for f in self._index_fqns()) if p})
        return self._files

    def _index_fqns(self):
        return list(self._index._paths)  # noqa: SLF001 - same package, deliberate

    def _raw_text(self, path: str) -> str:
        if path not in self._raw_cache:
            try:
                with open(path, encoding='utf-8', errors='replace') as handle:
                    self._raw_cache[path] = handle.read()
            except OSError:
                self._raw_cache[path] = ''
        return self._raw_cache[path]

    def _stripped_text(self, path: str) -> str:
        if path not in self._stripped_cache:
            self._stripped_cache[path] = strip_noise(self._raw_text(path))
        return self._stripped_cache[path]

    def observe(self, fqn: str) -> tuple[str, ...]:
        simple = fqn.rsplit('.', 1)[-1]
        methods: set[str] = set()
        declares = re.compile(r'\b' + re.escape(simple) + r'\s+([a-z]\w*)\b')
        for path in self._all_files():
            text = self._raw_text(path)
            if not text:
                continue
            if fqn not in text and f'import {fqn};' not in text:
                if simple not in text:
                    continue
            stripped = self._stripped_text(path)
            for match in declares.finditer(stripped):
                var = match.group(1)
                _, close = _enclosing_block(stripped, match.start())
                scope = stripped[match.end():close]
                for call in re.findall(r'\b' + re.escape(var) + r'\.(\w+)\s*\(', scope):
                    if call in _UNINFORMATIVE_ACCESSORS:
                        continue
                    if call.startswith('set') and len(call) > 3 and call[3].isupper():
                        continue
                    methods.add(call)
        return tuple(sorted(methods))


def _load(path: str) -> tuple[str, str, list[TypeDecl]]:
    with open(path, encoding='utf-8', errors='replace') as handle:
        src = handle.read()
    return src, strip_noise(src), find_types(src)


_WILDCARD_BOUND = re.compile(r'^\?\s+(?:extends|super)\s+(.+)$')


def _referenced_bases(ref: TypeRef) -> list[str]:
    """Unwrap containers: List<Chart> contributes Chart, not List.

    A bounded wildcard arg (`List<? extends Category>`) contributes its bound
    (`Category`). A bare `?` (`List<?>`) names no type and contributes nothing.
    """
    if ref.base in _CONTAINERS and ref.args:
        out: list[str] = []
        for arg in ref.args:
            arg = arg.strip()
            if arg == '?':
                continue
            bound = _WILDCARD_BOUND.match(arg)
            if bound:
                arg = bound.group(1).strip()
            out.extend(_referenced_bases(parse_type_ref(arg)))
        return out
    return [ref.base]


def _package_of(fqn: str) -> str:
    """The package a leaf's absent source would live in.

    A leaf reached through a dotted nested import that resolved nowhere keeps the
    import verbatim (`...classification.domain.Category.CategoryId`). Chopping one segment off
    that would name `...classification.domain.Category` as a package, which is not one; the
    reason would then assert something untrue about the checkout. Trailing
    capitalised segments are type names, so they are all dropped.
    """
    parts = fqn.split('.')
    while len(parts) > 1 and parts[-1][:1].isupper():
        parts.pop()
    return '.'.join(parts)


def build(entry_fqn: str, index: SourceIndex, observer) -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    queue: list[str] = [entry_fqn]
    seen: set[str] = set()

    while queue:
        fqn = queue.pop(0)
        if fqn in seen:
            continue
        seen.add(fqn)

        path = index.path_of(fqn)
        if path is None:
            nodes[fqn] = Node(
                fqn=fqn, kind='leaf',
                reason=f'no source in worktree; {_package_of(fqn)} is not checked out here',
                accessors_observed=observer.observe(fqn),
            )
            continue

        src, stripped, decls = _load(path)
        imports = read_imports(src)
        # 'a.b.Result$Chart' -> the file is Result.java, the declaration is Chart.
        simple = fqn.rsplit('.', 1)[-1].rsplit('$', 1)[-1]
        decl = next((d for d in decls if d.name == simple), None)
        if decl is None:
            nodes[fqn] = Node(fqn=fqn, kind='unhandled', source=path,
                              reason='no type declaration matching the file name')
            continue

        kind = classify(decl)
        own = fields_of(decl, stripped)
        nodes[fqn] = Node(fqn=fqn, kind=kind, source=path, line=decl.line, fields=own)

        if kind == 'behaviour' and fqn != entry_fqn:
            continue  # a collaborator is recorded, never expanded

        refs: list[TypeRef] = [f.declared for f in own]
        if kind == 'behaviour':
            refs.extend(signature_types(decl, stripped))
            for nested in decls:
                if nested.outer == simple:
                    refs.extend(f.declared for f in fields_of(nested, stripped))
                    refs.extend(signature_types(nested, stripped))

        for ref in refs:
            for base in _referenced_bases(ref):
                if not base or not base[0].isupper():
                    continue
                target = resolve(base, imports, index)
                if target.how == 'unresolved':
                    # A dotted nested type declared in source, never imported
                    # (`Classification.ClassificationId` on a field, with only `Classification`
                    # imported), resolves nowhere: not an import, not this
                    # compilation unit, not the package, not a wildcard. Recording
                    # nothing here would drop it from the graph silently, which is
                    # exactly the failure this kind exists to rule out. Keyed by
                    # `base` so the same unresolved name seen again collapses onto
                    # the one node instead of spamming a duplicate per occurrence.
                    if base not in nodes:
                        nodes[base] = Node(
                            fqn=base, kind='unhandled',
                            reason=(f"'{base}' could not be resolved through "
                                    "the file's imports, its compilation unit, "
                                    "its package, or a wildcard"),
                        )
                    continue
                if target.fqn and target.fqn.startswith(('java.', 'javax.', 'jakarta.')):
                    continue
                if target.fqn:
                    queue.append(target.fqn)

    return nodes
