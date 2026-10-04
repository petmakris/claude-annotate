"""The page itself, drawn by the real specimen.js against real extractor output.

Asserting the render in Python alone would mean re-stating specimen.js's kind
dispatch in the test, which would then agree with itself while the renderer was
wrong. That is exactly how `behaviour` shipped: `typegraph.classify` emits four
kinds, the page handled three, and every behaviour type — including the root the
user asked for — got an "unhandled" badge over an empty reason with all of its
field anchors orphaned. So the real file runs, over a DOM shim, against a
fixture that is verbatim `extract_types` output for a SERVICE entry.
"""

import functools
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from skills.specimen.document import build_items
from skills.specimen.leaves import load as load_leaves

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TYPES = json.loads((HERE / 'fixtures' / 'service-types.json').read_text())
SPECIMEN = json.loads((HERE / 'fixtures' / 'service-specimen.json').read_text())
LEAVES = load_leaves(str(HERE / 'fixtures' / 'leaves.json'))


def render(items: dict, hash_: str = '') -> dict:
    node = shutil.which('node')
    if node is None:
        pytest.skip('node is not installed; the page cannot be drawn here')
    bulk = {anchor: {'body': body, 'version': 1} for anchor, body in items.items()}
    # One file per call: under pytest-xdist a shared name let one worker delete
    # another's input mid-render.
    with tempfile.NamedTemporaryFile(
            'w', suffix='.json', prefix='render-input-', delete=False) as f:
        json.dump(bulk, f)
    payload = Path(f.name)
    try:
        done = subprocess.run(
            [node, str(HERE / 'js' / 'render-specimen.mjs'), str(payload), hash_],
            capture_output=True, text=True, timeout=60, check=False)
    finally:
        payload.unlink(missing_ok=True)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def items():
    return build_items(TYPES, SPECIMEN, LEAVES)


@functools.lru_cache(maxsize=None)
def _rendered(hash_: str) -> str:
    """The fixture is fixed and the render deterministic, so each view is drawn
    once per process and every test reads the same drawing. Kept as JSON text
    so each caller gets its own copy to poke at."""
    return json.dumps(render(items(), hash_))


def drawn():
    return json.loads(_rendered(''))


def tabled():
    return json.loads(_rendered('#table'))


def opened():
    """The table with every composite column opened. `#table/all` is a real,
    shareable state, which is also what makes it testable without a click."""
    return json.loads(_rendered('#table/all'))


def test_the_fixture_is_a_service_entry_with_all_four_kinds():
    kinds = {e['kind'] for e in TYPES['types'].values()}
    assert TYPES['root'] == 'com.example.reporting.AnalyticsQueryService'
    assert TYPES['types'][TYPES['root']]['kind'] == 'behaviour'
    assert {'data', 'behaviour', 'leaf', 'unhandled'} <= kinds


def test_every_anchor_build_items_emits_reaches_a_row_on_the_page():
    expected = set(items()) - {'__specimen__'}
    got = drawn()
    assert expected == set(got['anchors'])


def test_no_section_wears_a_badge_with_an_empty_reason():
    for section in drawn()['sections']:
        if section['badge'] is None:
            continue
        assert (section['reason'] or '').strip(), section


def test_the_root_the_user_asked_for_is_not_rendered_unhandled():
    sections = {s['fqn']: s for s in drawn()['sections']}
    root = sections[TYPES['root']]
    assert 'specimen-unhandled' not in root['className']
    assert 'specimen-behaviour' in root['className']
    assert root['rows'] == len(TYPES['types'][TYPES['root']]['fields'])


def test_behaviour_fields_are_rows_not_a_dropped_section():
    behaviours = [fqn for fqn, e in TYPES['types'].items() if e['kind'] == 'behaviour']
    assert len(behaviours) >= 3
    sections = {s['fqn']: s for s in drawn()['sections']}
    for fqn in behaviours:
        assert sections[fqn]['rows'] == len(TYPES['types'][fqn].get('fields', []))


def test_the_page_names_the_deployment_its_captured_values_came_from():
    header = drawn()['header']
    assert LEAVES['deployment'] in header
    assert LEAVES['captured'] in header


# --- the @Nullable row that used to be overwritten -------------------------
#
# `_flatten` keys by (type, field) and the page draws one row per key. Under
# last-wins, a `{"kind": "null"}` on the FIRST of two CategoryRiskContribution
# items was replaced by the second item's scalar and vanished — while SKILL.md
# tells the populator that exactly that row is why the reader opened the page.

NULL_ROW = ('com.example.analytics.model.'
            'AnalyticsResult$CategoryRiskContribution#proposed')


def test_a_null_on_a_non_final_instance_is_not_overwritten():
    row = items()[NULL_ROW]
    assert [v['isNull'] for v in row['values']] == [True, False]
    assert [v['value'] for v in row['values']] == [None, '0.3100']


def test_that_null_is_visible_on_the_item_that_held_it():
    """The first of two CategoryRiskContribution items has `proposed` null.

    The table drew one row per (type, field) and had to list both observations
    side by side, unable to say which item held which. The tree draws each item
    separately, so the null sits on the item that actually has it.
    """
    rows = drawn()['rows'][NULL_ROW]
    assert len(rows) == 2
    first = ' '.join(c['text'] for c in rows[0]['cells'])
    second = ' '.join(c['text'] for c in rows[1]['cells'])
    assert 'null' in first and '0.3100' not in first
    assert '0.3100' in second and 'null' not in second
    assert 'specimen-row-null' in rows[0]['className']
    assert 'specimen-row-null' not in rows[1]['className']


# --- the tree ---------------------------------------------------------------


def find_node(node, label):
    if node.get('label') == label:
        return node
    for child in node.get('children', []):
        found = find_node(child, label)
        if found:
            return found
    return None


def cell(node, cls):
    """The text of the node's cell carrying `cls`, as a whole class token.

    Substring matching would make `specimen-null` match the nullability
    badge's `specimen-nullability-nullable`, so a test for "is a null drawn
    here" would pass on any @Nullable field whether or not it holds one.
    """
    match = next((c for c in node['cells'] if cls in c['className'].split()), None)
    return match['text'] if match else None


def test_the_tree_is_rooted_in_the_type_the_instance_actually_holds():
    """The document root is a service; the instance it carries is a result.

    A page that headed the tree with `types.root` would name a class that has
    none of the fields drawn underneath it.
    """
    tree = drawn()['tree']
    assert tree is not None, 'no instance tree was drawn'
    assert tree['type'] == ('com.example.analytics.model.'
                            'AnalyticsResult')
    assert tree['type'] != TYPES['root']


def test_a_nested_object_draws_its_own_fields_inside_its_parent():
    """`totalWealth` is a MarketValue, not a scalar.

    The table gave it an unset dash and a filename, which told the reader
    nothing about what a MarketValue holds. Its two fields belong under it.
    """
    node = find_node(drawn()['tree'], 'totalWealth')
    assert node is not None
    assert node['type'] == ('com.example.analytics.model.'
                            'AnalyticsResult$MarketValue')
    inside = {child['label']: child for child in node['children']}
    assert set(inside) == {'amount', 'currency'}
    assert cell(inside['amount'], 'specimen-value') == '1250000.00'
    assert cell(inside['currency'], 'specimen-value') == 'CHF'


def test_a_null_object_field_says_null_and_has_nothing_inside_it():
    node = find_node(drawn()['tree'], 'totalWealthAfter')
    assert node is not None
    assert cell(node, 'specimen-null') == 'null'
    assert node['children'] == []


def test_a_field_the_instance_never_reached_is_unset_not_null():
    """Item [1] leaves `strategy` out entirely while item [0] sets it to null.
    An unset dash and a null badge are different facts and must not be drawn
    the same way."""
    allocation = find_node(drawn()['tree'], 'allocations')
    absent = next(c for c in allocation['children'][1]['children']
                  if c['label'] == 'strategy')
    assert cell(absent, 'specimen-unset') == '–'
    assert cell(absent, 'specimen-null') is None

    explicit = next(c for c in allocation['children'][0]['children']
                    if c['label'] == 'strategy')
    assert cell(explicit, 'specimen-null') == 'null'
    assert cell(explicit, 'specimen-unset') is None


def test_every_field_a_type_declares_is_drawn_even_where_the_instance_is_thin():
    """The shape is what the page is for, so an object node lists the type's
    declared fields, not only the keys the specimen happened to fill. Item [1]
    is the thin one: it has no `strategy` key at all."""
    allocation = find_node(drawn()['tree'], 'allocations')
    item = allocation['children'][1]
    declared = [f['name'] for f in TYPES['types'][
        'com.example.analytics.model.'
        'AnalyticsResult$CategoryAllocation']['fields']]
    assert [c['label'] for c in item['children']] == declared


def test_each_list_item_is_its_own_node():
    charts = find_node(drawn()['tree'], 'charts')
    assert charts['kind'] == 'list'
    assert len(charts['children']) == 1
    risk = find_node(charts, 'riskContributions')
    assert [c['kind'] for c in risk['children']] == ['object', 'object']


def test_every_field_node_in_the_tree_carries_its_type_and_field_anchor():
    """A per-instance anchor would carry a list index the next push can
    invalidate. Two items of one type therefore share one anchor."""
    risk = find_node(drawn()['tree'], 'riskContributions')
    anchors = [next(c['anchor'] for c in item['children'] if c['label'] == 'proposed')
               for item in risk['children']]
    assert anchors == [NULL_ROW, NULL_ROW]


def test_a_field_row_names_the_source_line_its_shape_was_read_from():
    """The line is what the editor button opens; without it the button has
    nowhere to go."""
    node = find_node(drawn()['tree'], 'totalWealth')
    assert cell(node, 'specimen-shape-from') == 'AnalyticsResult.java:19'


def test_types_the_tree_never_reaches_still_get_a_block():
    """Asset and Currency appear nowhere in this instance. Dropping them would
    be how the page becomes confidently wrong about what the class touches."""
    sections = {s['fqn'] for s in drawn()['sections']}
    assert 'com.example.inventory.domain.Asset' in sections
    assert 'com.example.money.Currency' in sections


def test_a_type_the_tree_does_reach_is_not_repeated_as_a_block_below():
    reached = 'com.example.analytics.model.AnalyticsResult'
    sections = {s['fqn'] for s in drawn()['sections']}
    assert reached not in sections

def test_a_node_says_what_is_inside_it_without_being_expanded():
    """A reader skimming a long tree should not have to open a node to learn
    that a MarketValue is an amount and a currency. The preview is rendered
    always and shown by CSS only while the node is closed."""
    node = find_node(drawn()['tree'], 'totalWealth')
    assert cell(node, 'specimen-preview') == '{amount: 1250000.00, currency: CHF}'


def test_a_preview_names_the_nulls_it_is_hiding():
    """The null is the row the reader came for, so it has to survive being
    summarised."""
    charts = find_node(drawn()['tree'], 'charts')
    risk = find_node(charts, 'riskContributions')
    assert cell(risk['children'][0], 'specimen-preview') == '{category: 1294, proposed: null}'


def test_every_row_carries_a_deliberate_comment_control():
    """Commenting is something the reader goes for, not something a click on a
    row lands on. The row keeps the anchor, so the composer still opens next to
    the row rather than inside its meta group, but only this control lets the
    click reach the runtime."""
    tree = drawn()['tree']
    rows = []

    def collect(node):
        if node.get('anchor'):
            rows.append(node)
        for child in node.get('children', []):
            collect(child)

    collect(tree)
    assert rows
    for row in rows:
        assert cell(row, 'specimen-ask') == '✻', row['label']


# --- the table view ---------------------------------------------------------
#
# The tree shows structure. What it cannot do is put the same field of three
# list items next to each other, because they are pages apart once each item is
# expanded. The table is the view for that, and for scanning a lot of values at
# once, so it is a flat row per field OCCURRENCE with the path that reached it.


def test_the_tree_is_the_view_a_bare_url_opens():
    assert drawn()['tree'] is not None
    assert tabled()['tree'] is None


def table_in(drawing, simple_name):
    match = [t for t in drawing['tables'] if t['type'].endswith(simple_name)]
    assert len(match) == 1, [t['type'] for t in drawing['tables']]
    return match[0]


def table_for(simple_name):
    return table_in(tabled(), simple_name)


ALLOCATION = 'com.example.analytics.model.AnalyticsResult$CategoryAllocation'
MARKET_VALUE = 'com.example.analytics.model.AnalyticsResult$MarketValue'


def test_the_table_draws_one_row_per_record():
    """Two CategoryRiskContribution instances, so two ROWS — not two rows per
    field. The point of leaving the tree is to see records under each other."""
    assert len(table_for('$CategoryRiskContribution')['rows']) == 2


def test_a_record_table_has_a_column_per_field_the_type_declares():
    declared = [f['name'] for f in TYPES['types'][
        'com.example.analytics.model.'
        'AnalyticsResult$CategoryRiskContribution']['fields']]
    assert [c['name'] for c in table_for('$CategoryRiskContribution')['columns']] == declared


def test_records_of_one_type_line_up_under_each_other():
    """The null on the first item and the value on the second sit in the same
    column, one row apart — which is the comparison the tree cannot show."""
    table = table_for('$CategoryRiskContribution')
    column = [c['name'] for c in table['columns']].index('proposed')
    assert [r['cells'][column]['text'] for r in table['rows']] == ['null', '0.3100']


def test_a_record_row_says_which_instance_it_is():
    table = table_for('$CategoryRiskContribution')
    assert [r['path'] for r in table['rows']] == ['charts[0].riskContributions[0]',
                                                  'charts[0].riskContributions[1]']


def test_a_column_carries_the_field_anchor_because_a_column_is_a_field():
    """In a record table the (type, field) pair IS the column, so that is where
    the comment control belongs — one thread per column, not one per cell."""
    table = table_for('$CategoryRiskContribution')
    column = next(c for c in table['columns'] if c['name'] == 'proposed')
    assert column['anchor'] == NULL_ROW


def test_the_table_view_reaches_every_anchor_the_tree_does():
    """Switching view must not drop a comment thread's home."""
    expected = set(items()) - {'__specimen__'}
    assert expected == set(tabled()['anchors'])


# --- nested columns ---------------------------------------------------------
#
# `CategoryAllocation.current` is an `Allocation`, whose `marketValue` is a
# `MarketValue`. Three levels. A composite column opens into its fields as real
# columns under a spanning header, so a value three levels down can still be
# read straight down the page — which is the only reason to be in the table
# rather than the tree.


def test_a_composite_column_is_one_column_until_it_is_opened():
    """Closed is the default: the table starts as narrow as the type is wide."""
    table = table_for('$CategoryAllocation')
    assert [c['path'] for c in table['columns']] == [
        'category', 'current', 'proposed', 'strategy']
    assert table['groups'] == []
    assert table['headerRows'] == 1


def test_opening_the_groups_splits_composites_into_real_columns():
    table = table_in(opened(), '$CategoryAllocation')
    assert [c['path'] for c in table['columns']] == [
        'category',
        'current.allocationInPortfolio', 'current.allocationInGroup',
        'current.marketValue.amount', 'current.marketValue.currency',
        'proposed.allocationInPortfolio', 'proposed.allocationInGroup',
        'proposed.marketValue.amount', 'proposed.marketValue.currency',
        'strategy.allocationInPortfolio', 'strategy.allocationInGroup',
    ]


def test_the_header_grows_one_row_per_level_opened():
    """Depth 3 means three header rows, and the spanning headers say how many
    leaf columns each level owns."""
    table = table_in(opened(), '$CategoryAllocation')
    assert table['headerRows'] == 3
    spans = {g['path']: g['colspan'] for g in table['groups']}
    assert spans == {'current': 4, 'proposed': 4, 'strategy': 2,
                     'current.marketValue': 2, 'proposed.marketValue': 2}


def test_a_nested_column_carries_the_anchor_of_the_type_that_declares_it():
    """`amount` is declared by MarketValue, not by CategoryAllocation. Anchoring it
    to the enclosing record would put the thread on a field that type has not
    got."""
    table = table_in(opened(), '$CategoryAllocation')
    deep = next(c for c in table['columns'] if c['path'] == 'current.marketValue.amount')
    assert deep['anchor'] == MARKET_VALUE + '#amount'


def test_a_group_header_is_itself_a_field_and_can_be_commented_on():
    table = table_in(opened(), '$CategoryAllocation')
    anchors = {g['path']: g['anchor'] for g in table['groups']}
    assert anchors['current'] == ALLOCATION + '#current'
    assert anchors['current.marketValue'] == (
        'com.example.analytics.model.'
        'AnalyticsResult$Allocation#marketValue')


def test_a_null_object_spans_every_column_its_group_owns():
    """Item [1]'s `proposed` is null. Four empty cells would read as four empty
    fields; one cell across the group says the OBJECT is absent."""
    table = table_in(opened(), '$CategoryAllocation')
    row = table['rows'][1]
    spanned = [c for c in row['cells'] if c['colspan'] == 4]
    assert len(spanned) == 1
    assert spanned[0]['text'] == 'null'


def test_a_field_absent_from_the_instance_is_not_a_null_in_the_table_either():
    """Item [1] has no `strategy` key at all, so its two leaf columns are unset
    dashes, not a spanning null."""
    table = table_in(opened(), '$CategoryAllocation')
    row = table['rows'][1]
    assert [c['text'] for c in row['cells'][-2:]] == ['–', '–']


def test_opening_a_group_never_loses_an_anchor():
    expected = set(items()) - {'__specimen__'}
    assert expected == set(opened()['anchors'])


# --- copyable type names ----------------------------------------------------
#
# The page names a lot of classes, and the next thing done with a class name is
# usually to open it. Every type name is a pill that copies the name IntelliJ's
# "navigate to class" wants: fully qualified, and with the nested-class `$`
# written as a dot, because that is the form the IDE accepts and `$` is not.


def pills_of(drawing):
    return {p['copy'] for p in drawing['pills']}


def test_a_type_name_copies_its_fully_qualified_name():
    assert ('com.example.analytics.model.'
            'AnalyticsResult.MarketValue') in pills_of(drawn())


def test_a_nested_class_is_copied_with_dots_not_a_dollar():
    """`Outer$Inner` is what the JVM and the extractor call it. `Outer.Inner` is
    what an IDE's class search accepts, and pasting the `$` form finds
    nothing."""
    for copied in pills_of(drawn()):
        assert '$' not in copied, copied


def test_a_type_with_no_source_still_offers_its_name():
    """A leaf has no file to jump to, so copying its name is the only way to go
    and look at it."""
    assert 'com.example.inventory.domain.Asset' in pills_of(drawn())


def test_a_type_the_page_cannot_qualify_copies_the_name_it_has():
    """`BigDecimal` is not in this type graph. Half a name is still what the
    reader would type, and inventing a package for it would be worse."""
    assert 'BigDecimal' in pills_of(drawn())


def test_the_table_view_offers_the_same_names():
    assert ('com.example.analytics.model.'
            'AnalyticsResult.MarketValue') in pills_of(tabled())


def test_every_pill_carries_a_name_to_copy():
    for pill in drawn()['pills']:
        assert pill['copy'].strip(), pill
