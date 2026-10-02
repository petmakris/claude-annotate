"""Turn a watcher event into the facts needed to answer it.

The model writes the answer; this module makes sure the answer is grounded. It hands
back the field's declared type, its nullability, the file and line its shape was read
from, and its siblings — so "why is this null?" can be answered by comparing it to
the field next to it, which is usually the real answer.

An anchor this document does not know is reported as unknown. Answering about a field
that is not in types.json would be invention presented as fact.

Anchors are `<fqn>#<field>`, e.g.
`com.example.analytics.model.AnalyticsResult$CategoryRiskContribution#proposed`.
The fqn itself contains dots and, for a nested type, a `$`; only the field name is
guaranteed free of both. Splitting is on the FIRST `#`, via `str.partition`, so
neither character in the fqn confuses it.
"""

from __future__ import annotations

import json
import re

_BANNER = re.compile(
    r'WEBCOMPANION_EVENT\s+skill=(?P<skill>\S+)\s+sid=(?P<sid>\S+)\s+event_id=(?P<event_id>\S+)')


def parse_banner(line: str) -> dict:
    match = _BANNER.search(line)
    if not match:
        raise ValueError(f'not a WEBCOMPANION_EVENT banner: {line!r}')
    return match.groupdict()


def parse_payload(text: str) -> dict:
    start = text.find('---payload---')
    end = text.find('---end---', start + 1)
    if start == -1 or end == -1:
        raise ValueError('no ---payload--- / ---end--- block')
    body = json.loads(text[start + len('---payload---'):end].strip())
    return {'anchor': body.get('anchor', ''),
            'question': body.get('text', '')}


def _short_source(path: str | None, line: int | None) -> str:
    if not path:
        return ''
    name = path.rsplit('/', 1)[-1]
    return f'{name}:{line}' if line else name


def context_for(types_payload: dict, anchor: str) -> dict:
    fqn, _, field_name = anchor.partition('#')
    entry = types_payload['types'].get(fqn)
    if entry is None:
        return {'known': False,
                'reason': f'{fqn} is not in this specimen; nothing to answer from'}

    fields = entry.get('fields', [])
    field = next((f for f in fields if f['name'] == field_name), None)
    if field is None:
        return {'known': False,
                'reason': f'{fqn} has no field named {field_name} in this specimen'}

    return {
        'known': True,
        'type': fqn,
        'field': field_name,
        'declared': field['declared'],
        'nullability': field['nullability'],
        'source': entry.get('source'),
        'line': field.get('line'),
        'shapeFrom': _short_source(entry.get('source'), field.get('line')),
        'siblings': [
            {'name': f['name'], 'declared': f['declared'], 'nullability': f['nullability']}
            for f in fields if f['name'] != field_name
        ],
        'commit': types_payload.get('commit', 'unknown'),
        'worktree': types_payload.get('worktree', ''),
    }
