from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.javasrc import find_types, strip_noise
from lib.fields import fields_of, parse_type_ref, signature_types


def parse(src):
    stripped = strip_noise(src)
    return {d.name: d for d in find_types(src)}, stripped


def test_parse_type_ref_plain():
    ref = parse_type_ref('BigDecimal')
    assert (ref.base, ref.args) == ('BigDecimal', ())


def test_parse_type_ref_single_arg():
    ref = parse_type_ref('List<Chart>')
    assert (ref.base, ref.args) == ('List', ('Chart',))


def test_parse_type_ref_splits_only_at_depth_zero():
    ref = parse_type_ref('Map<CategoryId, List<Chart>>')
    assert ref.base == 'Map'
    assert ref.args == ('CategoryId', 'List<Chart>')


def test_parse_type_ref_normalizes_varargs():
    ref = parse_type_ref('Category...')
    assert ref.base == 'Category'
    assert ref.raw == 'Category...'
    assert ref.args == ()


def test_record_components_carry_three_nullability_states():
    """CategoryRiskContribution's real shape, and the reason the tool exists."""
    src = (
        'public record CategoryRiskContribution(@NonNull Category category,\n'
        '                                    @NonNull RiskContribution current,\n'
        '                                    @Nullable RiskContribution proposed,\n'
        '                                    String note) {}\n'
    )
    decls, stripped = parse(src)
    got = {f.name: f for f in fields_of(decls['CategoryRiskContribution'], stripped)}
    assert got['category'].nullability == 'non-null'
    assert got['current'].nullability == 'non-null'
    assert got['proposed'].nullability == 'nullable'
    assert got['note'].nullability == 'unmarked'


def test_unmarked_is_never_collapsed_into_non_null():
    src = 'public record R(String a) {}\n'
    decls, stripped = parse(src)
    assert fields_of(decls['R'], stripped)[0].nullability == 'unmarked'


def test_record_component_lines_are_real():
    src = (
        'public record R(@NonNull Category category,\n'
        '                @Nullable RiskContribution proposed) {}\n'
    )
    decls, stripped = parse(src)
    got = {f.name: f for f in fields_of(decls['R'], stripped)}
    assert got['category'].line == 1
    assert got['proposed'].line == 2


def test_lombok_value_class_fields_are_found():
    """RiskContribution's real shape: bare fields, no modifiers, generated getters."""
    src = (
        '@Value\n'
        'public class RiskContribution {\n'
        '    BigDecimal totalContribution;\n'
        '    List<PositionContribution> positionContributions;\n'
        '\n'
        '    private RiskContribution(BigDecimal t, List<PositionContribution> p) {}\n'
        '    static RiskContribution empty() { return null; }\n'
        '}\n'
    )
    decls, stripped = parse(src)
    got = fields_of(decls['RiskContribution'], stripped)
    assert [f.name for f in got] == ['totalContribution', 'positionContributions']
    assert got[1].declared.base == 'List'
    assert got[1].declared.args == ('PositionContribution',)


def test_constructors_and_methods_are_not_mistaken_for_fields():
    src = (
        '@Value\npublic class A {\n'
        '    BigDecimal x;\n'
        '    public BigDecimal getSomething() { return x; }\n'
        '}\n'
    )
    decls, stripped = parse(src)
    assert [f.name for f in fields_of(decls['A'], stripped)] == ['x']


def test_private_final_fields_of_a_service_are_found():
    src = (
        'public class AnalyticsQueryService {\n'
        '    private final ClassificationRepository classificationRepository;\n'
        '    private final ClassificationsProperties classificationsProperties;\n'
        '}\n'
    )
    decls, stripped = parse(src)
    assert [f.name for f in fields_of(decls['AnalyticsQueryService'], stripped)] == [
        'classificationRepository', 'classificationsProperties',
    ]


def test_nested_class_fields_do_not_leak_into_the_outer_class():
    src = (
        'public class Outer {\n'
        '    private final ClassificationRepository repo;\n'
        '    class Inner {\n'
        '        private final AnalyticsResult analyticsResult;\n'
        '    }\n'
        '}\n'
    )
    decls, stripped = parse(src)
    assert [f.name for f in fields_of(decls['Outer'], stripped)] == ['repo']
    assert [f.name for f in fields_of(decls['Inner'], stripped)] == ['analyticsResult']


def test_signature_types_cover_params_and_return_and_skip_generic_block():
    src = (
        'public class S {\n'
        '    public Map<CategoryId, BigDecimal> getProposedCategoryRiskContributions('
        'AggregationDescription desc) { return null; }\n'
        '}\n'
    )
    decls, stripped = parse(src)
    bases = {t.base for t in signature_types(decls['S'], stripped)}
    assert 'Map' in bases
    assert 'AggregationDescription' in bases


def test_signature_types_never_read_the_body():
    """Chart is touched only inside the body and must NOT appear here."""
    src = (
        'public class S {\n'
        '    public Map<CategoryId, BigDecimal> go(AggregationDescription desc) {\n'
        '        Chart chart = pick();\n'
        '        return null;\n'
        '    }\n'
        '}\n'
    )
    decls, stripped = parse(src)
    assert 'Chart' not in {t.base for t in signature_types(decls['S'], stripped)}
