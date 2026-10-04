"""Real values for the types that are not on this machine.

Leaf types — ones that come from a jar or another repository — have no source
in the checkout. They are, however, ordinary data behind the system's API, so a project
profile can capture them once and keep them beside its profile.md.

This module is read-only at run time. The capture is a manual act; nothing here
touches the network.
"""

from __future__ import annotations

import json


def load(path: str) -> dict:
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def instances_for(leaves: dict, fqn: str) -> list[dict]:
    return leaves.get('types', {}).get(fqn, {}).get('instances', [])


def accessor_to_key(accessor: str) -> str:
    for prefix in ('get', 'is'):
        if accessor.startswith(prefix) and len(accessor) > len(prefix) and accessor[len(prefix)].isupper():
            rest = accessor[len(prefix):]
            return rest[0].lower() + rest[1:]
    return accessor


def missing_leaves(types_payload: dict, leaves: dict) -> list[str]:
    captured_types = leaves.get('types', {})
    missing = []
    for fqn, entry in types_payload['types'].items():
        if entry.get('kind') != 'leaf':
            continue
        if fqn not in captured_types:
            missing.append(fqn)
        else:
            instances = captured_types.get(fqn, {}).get('instances', [])
            if not instances:
                missing.append(fqn)
    return sorted(missing)


def coverage_gaps(types_payload: dict, leaves: dict) -> list[str]:
    """Accessors the checkout calls that the capture has no key for.

    A gap is not a failure. It means the page will show that accessor's value as
    unknown, and it is better said out loud than silently omitted.
    """
    gaps: list[str] = []
    for fqn, entry in sorted(types_payload['types'].items()):
        if entry.get('kind') != 'leaf':
            continue
        keys = set()
        for instance in instances_for(leaves, fqn):
            keys.update(instance)
        if not keys:
            continue
        for accessor in entry.get('accessors_observed', []):
            if accessor_to_key(accessor) not in keys:
                gaps.append(f'{fqn}.{accessor}')
    return gaps
