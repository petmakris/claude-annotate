"""types.json: the machine-read half of the page.

Every field carries a source file and a line. That is not a convention, it is the
reason the page can claim its shapes are checkable: any field that reaches the page
can be traced back to the line it was read from. A payload that breaks the rule is
refused here rather than rendered.
"""

from __future__ import annotations

import json
import os

from .typegraph import Node


class ProvenanceError(Exception):
    pass


def to_payload(entry_fqn: str, nodes: dict[str, Node], worktree: str, commit: str) -> dict:
    types: dict[str, dict] = {}
    for fqn, node in sorted(nodes.items()):
        entry: dict = {'kind': node.kind}
        if node.source:
            entry['source'] = node.source
        if node.line is not None:
            entry['line'] = node.line
        if node.reason:
            entry['reason'] = node.reason
        if node.accessors_observed:
            entry['accessors_observed'] = list(node.accessors_observed)
        if node.fields:
            entry['fields'] = [
                {
                    'name': f.name,
                    'declared': f.declared.raw,
                    'base': f.declared.base,
                    'args': list(f.declared.args),
                    'nullability': f.nullability,
                    'line': f.line,
                }
                for f in node.fields
            ]
        types[fqn] = entry
    return {'root': entry_fqn, 'worktree': worktree, 'commit': commit, 'types': types}


def provenance_errors(payload: dict) -> list[str]:
    errors: list[str] = []
    for fqn, entry in payload['types'].items():
        if entry['kind'] in ('leaf', 'unhandled'):
            if not entry.get('reason'):
                errors.append(f'{fqn}: {entry["kind"]} without a reason')
            continue
        if not entry.get('source'):
            errors.append(f'{fqn}: no source file')
        for f in entry.get('fields', []):
            if not f.get('line'):
                errors.append(f'{fqn}.{f["name"]}: no line')
    return errors


def write(path: str, payload: dict) -> None:
    errors = provenance_errors(payload)
    if errors:
        raise ProvenanceError('; '.join(errors))
    os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write('\n')
