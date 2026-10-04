"""types.json + specimen.json -> the document the daemon stores.

Two anchor families. `__specimen__` carries the whole document, which the page
renders. One anchor per field, `<fqn>#<field>`, exists so a comment thread attaches
to a field rather than to a position, and therefore survives a re-push after the
code moved.

A null is carried as an explicit `isNull` flag, never as a missing key. An absent key
is indistinguishable from an unknown one, and a null being a fact is the point of
the page.

Fix versus the plan this was written from: the plan's `_flatten` keyed captured
values by a bare field name (`out[path] = child` under a dotted-path prefix, then
looked the value back up by `field['name']` alone). That only matches when the
field belongs to the ROOT instance — any field reached through a nested object or a
list item (which is most of them: `Chart`, `CategoryRiskContribution`,
`CategoryAllocation`, ... in the real AnalyticsResult shape) produced a dotted
key like `charts[0].category` that `field['name']` == `'category'` never matches, so
`node` fell back to `{}` and every nested field silently rendered as `value: None,
isNull: False` — a blank cell wearing no `null` marker, which is exactly the
failure mode `references/page-format.md` says must never happen. `_flatten` here
keys by `(type_fqn, field_name)` instead, tracking the enclosing object's own
`type` as it walks, so a field is matched to the value captured for the same
class rather than to any field anywhere in the tree that happens to share its
name.

A type occurs many times in one instance tree — five chart entries, all
`CategoryRiskContribution`. One row still stands for one (type, field) pair, because
the anchor `<fqn>#<field>` is what makes a comment thread survive a re-push, and a
per-instance anchor would carry a list position that the next push can invalidate.
So `_flatten` collects every DISTINCT observation for a pair instead of letting the
last one win. That matters for the one row the reader came for: `SKILL.md` tells
the populator that an `@Nullable` field must carry `{"kind": "null"}` on one item,
and under last-wins that null vanished without trace whenever it was not the last
item of its type. Now it is always drawn — `values` carries every distinct
observation and the page renders them all.

What this still does NOT deliver is the spec's §7 line, "a category id appearing in
three sibling lists is visibly the same category in all three". That needs one row per
instance, which needs a per-instance anchor. The page shows that the pair took
three distinct values; it does not show which list item held which.
"""

from __future__ import annotations

_NULLABILITY_LABEL = {
    'nullable': '@Nullable',
    'non-null': '@NonNull',
    'unmarked': 'unmarked',
}

NOTE = ('Shapes read from source and checkable. Identifiers captured from the '
        'deployment named below. Numbers are illustrative.')


def anchor_for(fqn: str, field: str) -> str:
    return f'{fqn}#{field}'


def _short_source(path: str | None, line: int | None) -> str:
    if not path:
        return ''
    name = path.rsplit('/', 1)[-1]
    return f'{name}:{line}' if line else name


def _flatten(node: dict) -> dict[tuple[str, str], list[dict]]:
    """(type fqn, field name) -> every distinct scalar/null observed for it.

    Distinct means distinct in what the page shows: value, nullness and
    provenance. Order is the order the instance tree was walked, so the page is
    stable between two builds of the same specimen.
    """
    out: dict[tuple[str, str], list[dict]] = {}

    def record(key: tuple[str, str], child: dict) -> None:
        seen = out.setdefault(key, [])
        mark = (child.get('kind') == 'null', child.get('value'), child.get('provenance'))
        for other in seen:
            if (other.get('kind') == 'null', other.get('value'),
                    other.get('provenance')) == mark:
                return
        seen.append(child)

    def walk(current: dict) -> None:
        kind = current.get('kind')
        if kind == 'object':
            fqn = current.get('type')
            for name, child in current.get('fields', {}).items():
                if child.get('kind') in ('scalar', 'null'):
                    record((fqn, name), child)
                else:
                    walk(child)
        elif kind == 'list':
            for item in current.get('items', []):
                walk(item)

    walk(node)
    return out


def build_items(types_payload: dict, specimen: dict, leaves: dict | None = None) -> dict[str, dict]:
    values = _flatten(specimen.get('instance', {}))
    leaves = leaves or {}

    items: dict[str, dict] = {
        '__specimen__': {
            'root': types_payload['root'],
            'worktree': types_payload.get('worktree', ''),
            'commit': types_payload.get('commit', 'unknown'),
            'note': NOTE,
            # Where the `captured` identifiers came from. NOTE claims a real
            # deployment; leaves.json knows which one and when, and a claim the
            # page cannot support is the one thing this tool must not print.
            'capture': {
                'captured': leaves.get('captured', ''),
                'deployment': leaves.get('deployment', ''),
            },
            'types': types_payload['types'],
            'instance': specimen.get('instance', {}),
        }
    }

    for fqn, entry in sorted(types_payload['types'].items()):
        for field in entry.get('fields', []):
            observed = values.get((fqn, field['name'])) or []
            first = observed[0] if observed else {}
            is_null = first.get('kind') == 'null'
            items[anchor_for(fqn, field['name'])] = {
                'type': fqn,
                'field': field['name'],
                'declared': field['declared'],
                'nullability': field['nullability'],
                'nullabilityLabel': _NULLABILITY_LABEL.get(
                    field['nullability'], field['nullability']),
                'value': None if is_null else first.get('value'),
                'isNull': is_null,
                'provenance': None if is_null else first.get('provenance'),
                'values': [
                    {
                        'value': None if node.get('kind') == 'null' else node.get('value'),
                        'isNull': node.get('kind') == 'null',
                        'provenance': (None if node.get('kind') == 'null'
                                       else node.get('provenance')),
                    }
                    for node in observed
                ],
                'shapeFrom': _short_source(entry.get('source'), field.get('line')),
            }
    return items
