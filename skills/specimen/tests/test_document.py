import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.document import anchor_for, build_items

TYPES = {
    'root': 'app.Result', 'worktree': '/w', 'commit': 'abc1234',
    'types': {
        'app.Result': {
            'kind': 'data', 'source': '/w/app/Result.java', 'line': 19,
            'fields': [
                {'name': 'category', 'declared': 'Category', 'base': 'Category', 'args': [],
                 'nullability': 'non-null', 'line': 32},
                {'name': 'proposed', 'declared': 'RiskContribution', 'base': 'RiskContribution',
                 'args': [], 'nullability': 'nullable', 'line': 34},
                {'name': 'note', 'declared': 'String', 'base': 'String', 'args': [],
                 'nullability': 'unmarked', 'line': 35},
            ],
        },
        'com.ext.Category': {
            'kind': 'leaf', 'reason': 'no source in worktree; com.ext is not checked out here',
            'accessors_observed': ['getId', 'getName'],
        },
        'app.Mystery': {'kind': 'unhandled', 'reason': 'interface with three implementations'},
    },
}

SPECIMEN = {
    'root': 'app.Result',
    'instance': {
        'kind': 'object', 'type': 'app.Result',
        'fields': {
            'category': {'kind': 'scalar', 'value': 'CCY.EUR', 'provenance': 'captured'},
            'proposed': {'kind': 'null'},
            'note': {'kind': 'scalar', 'value': 'n/a', 'provenance': 'chosen'},
        },
    },
}


def items():
    return build_items(TYPES, SPECIMEN)


def test_anchor_is_fqn_hash_field():
    assert anchor_for('app.Result', 'proposed') == 'app.Result#proposed'


def test_the_whole_document_is_carried_under_one_anchor():
    assert '__specimen__' in items()
    assert items()['__specimen__']['root'] == 'app.Result'
    assert items()['__specimen__']['commit'] == 'abc1234'


def test_every_field_gets_its_own_anchor_so_a_thread_can_attach():
    got = items()
    assert 'app.Result#category' in got
    assert 'app.Result#proposed' in got
    assert 'app.Result#note' in got


def test_anchors_are_stable_across_two_builds():
    assert sorted(build_items(TYPES, SPECIMEN)) == sorted(build_items(TYPES, SPECIMEN))


def test_a_null_is_marked_as_null_not_left_empty():
    row = items()['app.Result#proposed']
    assert row['isNull'] is True
    assert row['value'] is None


def test_a_scalar_carries_its_provenance():
    assert items()['app.Result#category']['provenance'] == 'captured'
    assert items()['app.Result#note']['provenance'] == 'chosen'


def test_all_three_nullability_states_survive_into_the_document():
    got = items()
    assert got['app.Result#category']['nullability'] == 'non-null'
    assert got['app.Result#proposed']['nullability'] == 'nullable'
    assert got['app.Result#note']['nullability'] == 'unmarked'


def test_each_row_cites_the_line_its_shape_came_from():
    assert items()['app.Result#proposed']['shapeFrom'] == 'Result.java:34'


def test_a_leaf_keeps_its_reason_and_observed_accessors():
    leaf = items()['__specimen__']['types']['com.ext.Category']
    assert leaf['kind'] == 'leaf'
    assert 'no source in worktree' in leaf['reason']
    assert leaf['accessors_observed'] == ['getId', 'getName']


def test_an_unhandled_type_is_carried_not_dropped():
    assert 'app.Mystery' in items()['__specimen__']['types']


def test_the_document_says_the_numbers_are_illustrative():
    assert 'illustrative' in items()['__specimen__']['note'].lower()


# --- regression: a field reached through nesting must resolve too ---------
#
# The plan this file was built from flattened captured values by dotted path
# ("charts[0].category") and then looked them up by bare field name ("category"),
# which only ever matches a field that belongs to the root instance. Any field
# on a nested object or a list item — most of a real class's fields — silently
# fell back to `value: None, isNull: False`: a blank cell with no `null`
# marker, indistinguishable from a genuinely captured empty value. These tests
# pin the fix: values are matched by (type, field), tracking the enclosing
# object's own declared type while walking, not by field name alone.

NESTED_TYPES = {
    'root': 'app.Result', 'worktree': '/w', 'commit': 'abc1234',
    'types': {
        'app.Result': {
            'kind': 'data', 'source': '/w/app/Result.java', 'line': 10,
            'fields': [
                {'name': 'charts', 'declared': 'List<Chart>', 'base': 'List',
                 'args': ['Chart'], 'nullability': 'non-null', 'line': 11},
            ],
        },
        'app.Chart': {
            'kind': 'data', 'source': '/w/app/Chart.java', 'line': 4,
            'fields': [
                {'name': 'category', 'declared': 'Category', 'base': 'Category', 'args': [],
                 'nullability': 'non-null', 'line': 5},
                {'name': 'proposed', 'declared': 'RiskContribution',
                 'base': 'RiskContribution', 'args': [], 'nullability': 'nullable',
                 'line': 6},
            ],
        },
    },
}

NESTED_SPECIMEN = {
    'root': 'app.Result',
    'instance': {
        'kind': 'object', 'type': 'app.Result',
        'fields': {
            'charts': {
                'kind': 'list', 'element': 'app.Chart',
                'items': [
                    {
                        'kind': 'object', 'type': 'app.Chart',
                        'fields': {
                            'category': {'kind': 'scalar', 'value': 'EUR',
                                      'provenance': 'captured'},
                            'proposed': {'kind': 'null'},
                        },
                    },
                ],
            },
        },
    },
}


def test_a_field_on_a_nested_list_item_resolves_its_captured_value():
    got = build_items(NESTED_TYPES, NESTED_SPECIMEN)
    row = got['app.Chart#category']
    assert row['isNull'] is False
    assert row['value'] == 'EUR'
    assert row['provenance'] == 'captured'


def test_a_null_on_a_nested_list_item_is_still_marked_null_not_blank():
    got = build_items(NESTED_TYPES, NESTED_SPECIMEN)
    row = got['app.Chart#proposed']
    assert row['isNull'] is True
    assert row['value'] is None


def test_a_field_name_shared_by_two_types_does_not_cross_contaminate():
    # Both app.Result-level and app.Chart-level walks pass through this tree;
    # 'category' only exists on app.Chart here, and app.Result has no field of
    # that name, so an accidental global-by-name lookup would either miss or,
    # worse, hand app.Result's row app.Chart's value. Neither happens: the
    # anchor for a field app.Result does not declare is simply absent.
    got = build_items(NESTED_TYPES, NESTED_SPECIMEN)
    assert 'app.Result#category' not in got
    assert got['app.Chart#category']['value'] == 'EUR'


# --- one row per (type, field), every observation kept ---------------------
#
# The instance tree holds many objects of the same type. Keying by (type, field)
# and letting the last one win threw away every earlier observation, including
# the `{"kind": "null"}` SKILL.md tells the populator to put on exactly one item.
# The anchor stays one per (type, field) — it is what makes a comment thread
# survive a re-push — but the row now carries every distinct observation.

REPEATED_SPECIMEN = {
    'root': 'app.Result',
    'instance': {
        'kind': 'object', 'type': 'app.Result',
        'fields': {
            'charts': {
                'kind': 'list', 'element': 'app.Chart',
                'items': [
                    {'kind': 'object', 'type': 'app.Chart', 'fields': {
                        'category': {'kind': 'scalar', 'value': 'EUR',
                                  'provenance': 'captured'},
                        'proposed': {'kind': 'null'}}},
                    {'kind': 'object', 'type': 'app.Chart', 'fields': {
                        'category': {'kind': 'scalar', 'value': 'CHF',
                                  'provenance': 'captured'},
                        'proposed': {'kind': 'scalar', 'value': '0.31',
                                     'provenance': 'chosen'}}},
                    {'kind': 'object', 'type': 'app.Chart', 'fields': {
                        'category': {'kind': 'scalar', 'value': 'EUR',
                                  'provenance': 'captured'},
                        'proposed': {'kind': 'null'}}},
                ],
            },
        },
    },
}


def test_a_null_on_a_non_final_instance_survives():
    row = build_items(NESTED_TYPES, REPEATED_SPECIMEN)['app.Chart#proposed']
    assert [v['isNull'] for v in row['values']] == [True, False]
    assert row['isNull'] is True


def test_repeated_identical_observations_are_shown_once():
    row = build_items(NESTED_TYPES, REPEATED_SPECIMEN)['app.Chart#category']
    assert [v['value'] for v in row['values']] == ['EUR', 'CHF']


def test_the_anchor_set_is_unchanged_by_repetition():
    one = sorted(build_items(NESTED_TYPES, NESTED_SPECIMEN))
    many = sorted(build_items(NESTED_TYPES, REPEATED_SPECIMEN))
    assert one == many


def test_the_document_names_the_capture_its_identifiers_came_from():
    leaves = {'captured': '2026-09-16T09:47:09Z', 'deployment': 'example capture'}
    doc = build_items(TYPES, SPECIMEN, leaves)['__specimen__']
    assert doc['capture']['deployment'] == 'example capture'
    assert doc['capture']['captured'] == '2026-09-16T09:47:09Z'


def test_without_a_capture_the_document_claims_no_deployment():
    doc = build_items(TYPES, SPECIMEN)['__specimen__']
    assert doc['capture'] == {'captured': '', 'deployment': ''}
