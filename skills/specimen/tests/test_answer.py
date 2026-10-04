import pytest

from skills.specimen.answer import context_for, parse_banner, parse_payload

TYPES = {
    'root': 'app.Result', 'worktree': '/w', 'commit': 'abc1234',
    'types': {
        'app.Result': {
            'kind': 'data', 'source': '/w/app/Result.java', 'line': 19,
            'fields': [
                {'name': 'current', 'declared': 'RiskContribution', 'base': 'RiskContribution',
                 'args': [], 'nullability': 'non-null', 'line': 33},
                {'name': 'proposed', 'declared': 'RiskContribution', 'base': 'RiskContribution',
                 'args': [], 'nullability': 'nullable', 'line': 34},
            ],
        },
    },
}


def test_parse_banner_pulls_sid_and_event_id():
    got = parse_banner('WEBCOMPANION_EVENT skill=specimen sid=sid-1 event_id=ev-9')
    assert got == {'skill': 'specimen', 'sid': 'sid-1', 'event_id': 'ev-9'}


def test_parse_banner_rejects_a_line_that_is_not_a_banner():
    with pytest.raises(ValueError):
        parse_banner('some unrelated log line')


def test_parse_payload_extracts_anchor_and_question():
    text = (
        'WEBCOMPANION_EVENT skill=specimen sid=sid-1 event_id=ev-9\n'
        '---payload---\n'
        '{"anchor": "app.Result#proposed", "text": "why is this null here?"}\n'
        '---end---\n'
    )
    got = parse_payload(text)
    assert got['anchor'] == 'app.Result#proposed'
    assert got['question'] == 'why is this null here?'


def test_context_names_the_field_and_where_its_shape_came_from():
    got = context_for(TYPES, 'app.Result#proposed')
    assert got['type'] == 'app.Result'
    assert got['field'] == 'proposed'
    assert got['nullability'] == 'nullable'
    assert got['shapeFrom'] == 'Result.java:34'
    assert got['source'] == '/w/app/Result.java'
    assert got['line'] == 34


def test_context_includes_the_sibling_fields_so_the_answer_can_compare():
    got = context_for(TYPES, 'app.Result#proposed')
    siblings = {s['name']: s['nullability'] for s in got['siblings']}
    assert siblings == {'current': 'non-null'}


def test_context_for_an_unknown_anchor_says_so_rather_than_inventing():
    got = context_for(TYPES, 'app.Nope#missing')
    assert got['known'] is False
    assert 'app.Nope' in got['reason']


def test_context_for_a_known_type_but_unknown_field_says_so():
    got = context_for(TYPES, 'app.Result#nosuch')
    assert got['known'] is False
    assert 'nosuch' in got['reason']


def test_context_for_unknown_type_and_unknown_field_reasons_are_distinguishable():
    unknown_type = context_for(TYPES, 'app.Nope#missing')
    unknown_field = context_for(TYPES, 'app.Result#nosuch')
    assert unknown_type['reason'] != unknown_field['reason']


def test_context_handles_a_nested_type_anchor_with_a_dollar_in_the_fqn():
    types_payload = {
        'root': 'app.Result', 'worktree': '/w', 'commit': 'abc1234',
        'types': {
            'app.Result$Inner': {
                'kind': 'data', 'source': '/w/app/Result.java', 'line': 40,
                'fields': [
                    {'name': 'value', 'declared': 'String', 'base': 'String',
                     'args': [], 'nullability': 'nullable', 'line': 41},
                ],
            },
        },
    }
    got = context_for(types_payload, 'app.Result$Inner#value')
    assert got['known'] is True
    assert got['type'] == 'app.Result$Inner'
    assert got['field'] == 'value'


def test_parse_payload_raises_when_there_is_no_payload_block():
    with pytest.raises(ValueError):
        parse_payload('WEBCOMPANION_FINISHED skill=specimen sid=sid-1')
