"""Resolve a simple Java type name to a fully qualified name.

Resolution is by import, never by name. a large codebase can contain five classes called
`Category`, and the one AnalyticsResult imports is a sixth that is not in the
worktree at all. A resolver that matched on simple name would bind to whichever of
the five it happened to index first and render a page describing an unrelated class,
confidently and silently.

When nothing resolves, this module says so. It never falls back to a same-named
class it happens to know about.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .javasrc import find_types

_PACKAGE = re.compile(r'^\s*package\s+([\w.]+)\s*;', re.MULTILINE)
_IMPORT = re.compile(r'^\s*import\s+(static\s+)?([\w.]+)(\.\*)?\s*;', re.MULTILINE)

_BUILTINS = {
    'String': 'java.lang.String', 'Integer': 'java.lang.Integer',
    'Long': 'java.lang.Long', 'Boolean': 'java.lang.Boolean',
    'Double': 'java.lang.Double', 'Object': 'java.lang.Object',
    'List': 'java.util.List', 'Set': 'java.util.Set', 'Map': 'java.util.Map',
    'Optional': 'java.util.Optional', 'Collection': 'java.util.Collection',
    'Locale': 'java.util.Locale', 'BigDecimal': 'java.math.BigDecimal',
}


@dataclass(frozen=True)
class FileImports:
    package: str
    explicit: dict[str, str]
    wildcards: tuple[str, ...]
    unit: dict[str, str]


@dataclass(frozen=True)
class Resolution:
    fqn: str | None
    how: str


def read_imports(src: str) -> FileImports:
    pkg_match = _PACKAGE.search(src)
    package = pkg_match.group(1) if pkg_match else ''
    explicit: dict[str, str] = {}
    wildcards: list[str] = []
    for is_static, path, star in _IMPORT.findall(src):
        if is_static:
            continue
        if star:
            wildcards.append(path)
        else:
            explicit[path.rsplit('.', 1)[-1]] = path
    return FileImports(package=package, explicit=explicit, wildcards=tuple(wildcards),
                       unit=unit_types(src, package))


def unit_types(src: str, package: str) -> dict[str, str]:
    """Simple name -> FQN for every type declared in this compilation unit.

    Nested types are keyed `<outer-fqn>$<Nested>`. They have no files of their own:
    CategoryRiskContribution and Chart both live inside AnalyticsResult.java,
    so without this the walk stops at the outer record.
    """
    decls = find_types(src)
    by_name = {d.name: d for d in decls}
    out: dict[str, str] = {}
    for d in decls:
        chain, cursor = [d.name], d.outer
        while cursor and cursor in by_name and len(chain) < 12:
            chain.append(cursor)
            cursor = by_name[cursor].outer
        chain.reverse()
        head = f'{package}.{chain[0]}' if package else chain[0]
        out[d.name] = head if len(chain) == 1 else head + '$' + '$'.join(chain[1:])
    return out


@dataclass
class SourceIndex:
    _paths: dict[str, str] = field(default_factory=dict)
    _by_simple: dict[str, list[str]] = field(default_factory=dict)

    def add_unit(self, src: str, package: str, path: str) -> None:
        for fqn in unit_types(src, package).values():
            self.add(fqn, path)

    def add(self, fqn: str, path: str) -> None:
        self._paths[fqn] = path
        simple = fqn.rsplit('.', 1)[-1]
        fqn_list = self._by_simple.setdefault(simple, [])
        if fqn not in fqn_list:
            fqn_list.append(fqn)

    def has(self, fqn: str) -> bool:
        return fqn in self._paths

    def path_of(self, fqn: str) -> str | None:
        return self._paths.get(fqn)

    def by_simple_name(self, simple: str) -> list[str]:
        return sorted(self._by_simple.get(simple, []))

    @classmethod
    def scan(cls, worktree: str) -> 'SourceIndex':
        index = cls()
        for root, dirs, files in os.walk(worktree):
            dirs[:] = [d for d in dirs if d not in {'build', '.git', 'node_modules'}]
            for name in files:
                if not name.endswith('.java'):
                    continue
                path = os.path.join(root, name)
                try:
                    with open(path, encoding='utf-8', errors='replace') as handle:
                        text = handle.read()
                except OSError:
                    continue
                pkg = _PACKAGE.search(text)
                if not pkg:
                    continue
                index.add(f'{pkg.group(1)}.{name[:-5]}', path)
                index.add_unit(text, pkg.group(1), path)
        return index


def nested_forms(fqn: str) -> list[str]:
    """Dotted nested imports, rewritten the way `SourceIndex` keys them.

    Java writes a nested type in an import with a dot:
    `import a.b.AnalyticsResult.CategoryAllocation;`. `SourceIndex` keys the
    same declaration `a.b.AnalyticsResult$CategoryAllocation`, because that is
    what `unit_types` produces. Without this rewrite `index.has()` misses, the walk
    records a leaf, and the page asserts that a package it is ALSO rendering fields
    from is not checked out. Dotted nested imports like this are common in large codebases,
    on the order of a thousand distinct ones -- not rare enough to treat as an edge
    case.

    A dot is rewritten only when the segments on both sides of it start with a
    capital, which is what distinguishes `Outer.Nested` from `package.Class`. Forms
    come back shallowest rewrite first, so `a.b.Outer.Mid.Inner` offers
    `a.b.Outer.Mid$Inner` before `a.b.Outer$Mid$Inner`.
    """
    parts = fqn.split('.')
    forms: list[str] = []
    for i in range(len(parts) - 1, 0, -1):
        if not (parts[i][:1].isupper() and parts[i - 1][:1].isupper()):
            break
        forms.append('.'.join(parts[:i]) + '$' + '$'.join(parts[i:]))
    return forms


def resolve(simple: str, imports: FileImports, index: SourceIndex) -> Resolution:
    if simple in imports.explicit:
        target = imports.explicit[simple]
        if not index.has(target):
            for candidate in nested_forms(target):
                if index.has(candidate):
                    return Resolution(candidate, 'import-nested')
        # Nothing resolved: keep the import verbatim. A type that is genuinely not
        # in this checkout must still resolve, so that it is recorded as a leaf
        # rather than dropped.
        return Resolution(target, 'import')

    if simple in imports.unit:
        return Resolution(imports.unit[simple], 'same-unit')

    if imports.package:
        candidate = f'{imports.package}.{simple}'
        if index.has(candidate):
            return Resolution(candidate, 'same-package')

    for prefix in imports.wildcards:
        candidate = f'{prefix}.{simple}'
        if index.has(candidate):
            return Resolution(candidate, 'wildcard')

    if simple in _BUILTINS:
        return Resolution(_BUILTINS[simple], 'builtin')

    return Resolution(None, 'unresolved')
