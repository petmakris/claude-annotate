"""Turn Java source text into a list of type declarations.

This module knows about text and nothing about Java meaning. It does not resolve
types, read fields or follow imports. Keeping it that way is what makes it testable
against three-line fixtures.

Offsets returned by find_types index into the STRIPPED source, not the original.
strip_noise preserves length and newline positions exactly so that a line number
computed from a stripped offset is correct for the original file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TypeDecl:
    name: str
    kind: str
    line: int
    annotations: tuple[str, ...]
    outer: str | None
    header_start: int
    body_start: int
    body_end: int


def strip_noise(src: str) -> str:
    """Replace comments and literals with spaces, preserving length and newlines.

    A string literal can contain the word "record"; a comment routinely does. Either
    one would otherwise be found as a declaration.
    """
    out = list(src)
    i, n = 0, len(src)

    def blank(start: int, stop: int) -> None:
        for k in range(start, min(stop, n)):
            if out[k] != '\n':
                out[k] = ' '

    while i < n:
        two = src[i:i + 2]
        if two == '//':
            j = src.find('\n', i)
            j = n if j == -1 else j
            blank(i, j)
            i = j
        elif two == '/*':
            j = src.find('*/', i + 2)
            j = n if j == -1 else j + 2
            blank(i, j)
            i = j
        elif src[i:i + 3] == '"""':
            j = src.find('"""', i + 3)
            j = n if j == -1 else j + 3
            blank(i, j)
            i = j
        elif src[i] in '"\'':
            quote = src[i]
            j = i + 1
            while j < n and src[j] != quote:
                j += 2 if src[j] == '\\' else 1
            blank(i, min(j + 1, n))
            i = min(j + 1, n)
        else:
            i += 1
    return ''.join(out)


_DECL = re.compile(
    r'\b(?P<kind>record|class|interface|enum)\s+(?P<name>[A-Z][A-Za-z0-9_]*)'
)
_ANNOTATION = re.compile(r'@([A-Z][A-Za-z0-9_]*)')
_MODIFIERS = {
    'public', 'private', 'protected', 'static', 'final', 'abstract',
    'sealed', 'non-sealed', 'strictfp', 'default',
}


def _annotations_before(stripped: str, start: int) -> tuple[str, ...]:
    """Annotations in the run of modifiers and annotations preceding a declaration."""
    head = stripped.rfind(';', 0, start)
    brace = max(stripped.rfind('{', 0, start), stripped.rfind('}', 0, start))
    begin = max(head, brace) + 1
    return tuple(_ANNOTATION.findall(stripped[begin:start]))


def _is_declaration(stripped: str, match: re.Match[str]) -> bool:
    """Reject `new Foo()`-style noise: a declaration is preceded by a modifier,
    an annotation, a brace, a semicolon, or the start of the file."""
    before = stripped[:match.start()].rstrip()
    if not before:
        return True
    if before[-1] in '{};':
        return True
    last = before.split()[-1]
    return last in _MODIFIERS or last.startswith('@') or last.endswith(')')


def find_types(src: str) -> list[TypeDecl]:
    stripped = strip_noise(src)
    decls: list[TypeDecl] = []

    for m in _DECL.finditer(stripped):
        if not _is_declaration(stripped, m):
            continue
        body_start = stripped.find('{', m.end())
        if body_start == -1:
            continue
        decls.append(
            TypeDecl(
                name=m.group('name'),
                kind=m.group('kind'),
                line=stripped.count('\n', 0, m.start()) + 1,
                annotations=_annotations_before(stripped, m.start()),
                outer=None,
                header_start=m.start(),
                body_start=body_start,
                body_end=_matching_brace(stripped, body_start),
            )
        )

    return _assign_outers(decls)


def _matching_brace(stripped: str, open_index: int) -> int:
    depth = 0
    for i in range(open_index, len(stripped)):
        if stripped[i] == '{':
            depth += 1
        elif stripped[i] == '}':
            depth -= 1
            if depth == 0:
                return i
    return len(stripped) - 1


def _assign_outers(decls: list[TypeDecl]) -> list[TypeDecl]:
    """A declaration's outer is the innermost other declaration containing it."""
    ordered = sorted(decls, key=lambda d: d.header_start)
    result: list[TypeDecl] = []
    for d in ordered:
        containers = [
            o for o in ordered
            if o is not d and o.body_start < d.header_start < o.body_end
        ]
        outer = max(containers, key=lambda o: o.body_start).name if containers else None
        result.append(
            TypeDecl(
                name=d.name, kind=d.kind, line=d.line, annotations=d.annotations,
                outer=outer, header_start=d.header_start,
                body_start=d.body_start, body_end=d.body_end,
            )
        )
    return result
