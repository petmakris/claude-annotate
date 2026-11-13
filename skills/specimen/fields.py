"""Extract fields and method signature types from a type declaration.

Two declaration shapes are supported because both appear in the first aggregate this
tool targets: records, and Lombok @Value / @Data classes whose fields carry no
modifiers at all.

Nullability is recorded in three states. `unmarked` is not a synonym for `non-null`;
collapsing them would let the page assert a guarantee the code does not make.

Method BODIES are never read. signature_types returns only what a declaration
promises, which is a spec decision and not a shortcut.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .javasrc import TypeDecl

_NULLABLE = {'Nullable', 'CheckForNull'}
_NON_NULL = {'NonNull', 'Nonnull', 'NotNull'}

_KEYWORDS = {
    'public', 'private', 'protected', 'static', 'final', 'abstract', 'transient',
    'volatile', 'synchronized', 'native', 'default', 'return', 'new', 'if', 'for',
    'while', 'switch', 'throw', 'else', 'case', 'this', 'super', 'record', 'class',
}


@dataclass(frozen=True)
class TypeRef:
    raw: str
    base: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class Field:
    name: str
    declared: TypeRef
    nullability: str
    line: int


def _split_depth_zero(text: str, sep: str = ',') -> list[str]:
    parts, depth, current = [], 0, []
    for ch in text:
        if ch in '<(':
            depth += 1
        elif ch in '>)':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if ''.join(current).strip():
        parts.append(''.join(current))
    return [p.strip() for p in parts if p.strip()]


def parse_type_ref(text: str) -> TypeRef:
    raw = text.strip()
    if '<' not in raw:
        return TypeRef(raw=raw, base=raw.replace('[]', '').replace('...', '').strip(), args=())
    base = raw[:raw.index('<')].strip()
    inner = raw[raw.index('<') + 1:raw.rindex('>')]
    return TypeRef(raw=raw, base=base, args=tuple(_split_depth_zero(inner)))


def _nullability(annotations: list[str]) -> str:
    if any(a in _NULLABLE for a in annotations):
        return 'nullable'
    if any(a in _NON_NULL for a in annotations):
        return 'non-null'
    return 'unmarked'


def _line_at(stripped: str, offset: int) -> int:
    return stripped.count('\n', 0, offset) + 1


def _component_list(decl: TypeDecl, stripped: str) -> tuple[str, int] | None:
    """The text between a record's parentheses, and where it starts."""
    open_paren = stripped.find('(', decl.header_start)
    if open_paren == -1 or open_paren > decl.body_start:
        return None
    depth, i = 0, open_paren
    while i < len(stripped):
        if stripped[i] == '(':
            depth += 1
        elif stripped[i] == ')':
            depth -= 1
            if depth == 0:
                return stripped[open_paren + 1:i], open_paren + 1
        i += 1
    return None


def _parse_declaration(text: str) -> tuple[str, str, str] | None:
    """`@NonNull Category category` -> (nullability, 'Category', 'category')."""
    annotations = re.findall(r'@([A-Z]\w*)', text)
    without = re.sub(r'@[A-Z]\w*(\([^)]*\))?', ' ', text).strip()
    without = re.sub(r'\bfinal\b|\bprivate\b|\bpublic\b|\bprotected\b|\bstatic\b|\btransient\b|\bvolatile\b', ' ', without)
    tokens = _split_depth_zero(without, ' ')
    tokens = [t for t in tokens if t]
    if len(tokens) < 2:
        return None
    name = tokens[-1].strip()
    type_text = ' '.join(tokens[:-1]).strip()
    if not re.fullmatch(r'[A-Za-z_]\w*', name) or name in _KEYWORDS:
        return None
    if not type_text or type_text.split('<')[0].split('[')[0] in _KEYWORDS:
        return None
    return _nullability(annotations), type_text, name


def _record_fields(decl: TypeDecl, stripped: str) -> list[Field]:
    found = _component_list(decl, stripped)
    if not found:
        return []
    text, start = found
    fields, cursor = [], 0
    for chunk in _split_depth_zero(text):
        offset = text.index(chunk, cursor)
        cursor = offset + len(chunk)
        parsed = _parse_declaration(chunk)
        if parsed:
            nullability, type_text, name = parsed
            fields.append(Field(name, parse_type_ref(type_text), nullability,
                                _line_at(stripped, start + offset)))
    return fields


def _own_body_spans(decl: TypeDecl, stripped: str) -> list[tuple[int, int]]:
    """The parts of this type's body that are not inside a nested brace block."""
    spans, depth, chunk_start = [], 0, decl.body_start + 1
    for i in range(decl.body_start + 1, decl.body_end):
        if stripped[i] == '{':
            if depth == 0:
                spans.append((chunk_start, i + 1))
            depth += 1
        elif stripped[i] == '}':
            depth -= 1
            if depth == 0:
                chunk_start = i + 1
    spans.append((chunk_start, decl.body_end))
    return spans


_FIELD_STATEMENT = re.compile(r'[^;{}]+;')


def _class_fields(decl: TypeDecl, stripped: str) -> list[Field]:
    """Field declarations directly in this body, skipping methods and initialisers.

    Line numbers come from the match offset, not from arithmetic over split text,
    so they stay true when a declaration spans lines.
    """
    fields = []
    for start, stop in _own_body_spans(decl, stripped):
        for m in _FIELD_STATEMENT.finditer(stripped[start:stop]):
            statement = m.group(0)[:-1]
            if '(' in statement or '=' in statement or not statement.strip():
                continue
            parsed = _parse_declaration(statement)
            if parsed:
                nullability, type_text, name = parsed
                lead = len(statement) - len(statement.lstrip())
                fields.append(Field(name, parse_type_ref(type_text), nullability,
                                    _line_at(stripped, start + m.start() + lead)))
    return fields


def fields_of(decl: TypeDecl, stripped: str) -> list[Field]:
    if decl.kind == 'record':
        return _record_fields(decl, stripped)
    return _class_fields(decl, stripped)


_METHOD = re.compile(r'(?P<sig>[\w<>,\[\]\s.?]+?)\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(\{|;|throws)')


def signature_types(decl: TypeDecl, stripped: str) -> list[TypeRef]:
    """Return and parameter types of methods declared directly in this body.

    Method bodies are never inspected. A type touched only inside a body is found
    later, by walking transitively from a field, or not at all.
    """
    refs: list[TypeRef] = []
    for start, stop in _own_body_spans(decl, stripped):
        for m in _METHOD.finditer(stripped[start:stop]):
            head = re.sub(r'^\s*<[^>]*>', ' ', m.group('sig'))
            head = re.sub(r'@[A-Z]\w*(\([^)]*\))?', ' ', head)
            tokens = [t for t in _split_depth_zero(head, ' ') if t and t not in _KEYWORDS]
            if tokens:
                refs.append(parse_type_ref(tokens[-1]))
            for param in _split_depth_zero(m.group('params')):
                parsed = _parse_declaration(param)
                if parsed:
                    refs.append(parse_type_ref(parsed[1]))
    return refs
