import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.imports import SourceIndex
from lib.javasrc import find_types
from lib.typegraph import AccessorObserver, build, classify


class FakeObserver:
    def observe(self, fqn):
        return ('getId', 'getName') if fqn.endswith('.Category') else ()


def write(tmp_path, fqn, body):
    path = tmp_path / (fqn.replace('.', '/') + '.java')
    path.parent.mkdir(parents=True, exist_ok=True)
    package = fqn.rsplit('.', 1)[0]
    path.write_text(f'package {package};\n{body}')
    return path


def decl_named(src, name):
    return next(d for d in find_types(src) if d.name == name)


def test_classify_record_is_data():
    assert classify(decl_named('public record R(int a) {}', 'R')) == 'data'


def test_classify_lombok_value_is_data():
    assert classify(decl_named('@Value\npublic class V {}', 'V')) == 'data'


def test_classify_enum_is_data():
    assert classify(decl_named('public enum E { A }', 'E')) == 'data'


def test_classify_plain_service_is_behaviour():
    assert classify(decl_named('public class QueryService {}', 'QueryService')) == 'behaviour'


def test_a_service_entry_reaches_data_through_a_nested_class_field(tmp_path):
    """The shape of the real AnalyticsQueryService.

    The outer class holds only collaborators. The single data field lives on an
    inner class. An extractor that stops at the entry's own fields renders an
    empty page for the exact class this tool exists to explain.
    """
    write(tmp_path, 'app.QueryService', (
        'import app.ClassificationRepository;\n'
        'import app.AnalyticsResult;\n'
        'public class QueryService {\n'
        '    private final ClassificationRepository classificationRepository;\n'
        '    class Data {\n'
        '        private final AnalyticsResult analyticsResult;\n'
        '    }\n'
        '}\n'
    ))
    write(tmp_path, 'app.ClassificationRepository', 'public class ClassificationRepository {}\n')
    write(tmp_path, 'app.AnalyticsResult', (
        'import app.Chart;\nimport java.util.List;\n'
        'public record AnalyticsResult(List<Chart> charts) {}\n'
    ))
    write(tmp_path, 'app.Chart', (
        'import app.CategoryRiskContribution;\nimport java.util.List;\n'
        'public record Chart(List<CategoryRiskContribution> riskContributions) {}\n'
    ))
    write(tmp_path, 'app.CategoryRiskContribution', (
        'import com.ext.Category;\n'
        'public record CategoryRiskContribution(@NonNull Category category,\n'
        '                                    @Nullable RiskContribution proposed) {}\n'
    ))

    index = SourceIndex.scan(str(tmp_path))
    nodes = build('app.QueryService', index, FakeObserver())

    assert nodes['app.QueryService'].kind == 'behaviour'
    assert 'app.CategoryRiskContribution' in nodes, 'nested-class walk failed'
    assert nodes['app.CategoryRiskContribution'].kind == 'data'
    got = {f.name: f.nullability for f in nodes['app.CategoryRiskContribution'].fields}
    assert got['proposed'] == 'nullable'


def test_a_nested_type_is_reached_and_read_from_its_outer_file(tmp_path):
    """Chart and CategoryRiskContribution have no files; they live in the outer's."""
    write(tmp_path, 'app.Result', (
        'import java.util.List;\n'
        'public record Result(List<Chart> charts) {\n'
        '    public record Chart(List<Row> rows) {}\n'
        '    public record Row(@Nullable String note) {}\n'
        '}\n'
    ))
    index = SourceIndex.scan(str(tmp_path))
    nodes = build('app.Result', index, FakeObserver())
    assert 'app.Result$Chart' in nodes, 'nested type not indexed or not resolved'
    assert 'app.Result$Row' in nodes
    assert nodes['app.Result$Row'].fields[0].nullability == 'nullable'


def test_an_external_type_becomes_a_leaf_with_observed_accessors(tmp_path):
    write(tmp_path, 'app.Holder', (
        'import com.ext.Category;\n'
        'public record Holder(Category category) {}\n'
    ))
    index = SourceIndex.scan(str(tmp_path))
    nodes = build('app.Holder', index, FakeObserver())
    leaf = nodes['com.ext.Category']
    assert leaf.kind == 'leaf'
    assert leaf.accessors_observed == ('getId', 'getName')
    assert 'no source in worktree' in leaf.reason


def test_behaviour_classes_reached_by_a_field_are_recorded_but_not_expanded(tmp_path):
    write(tmp_path, 'app.Entry', (
        'import app.Repo;\npublic class Entry { private final Repo repo; }\n'
    ))
    write(tmp_path, 'app.Repo', (
        'import app.Deep;\npublic class Repo { private final Deep deep; }\n'
    ))
    write(tmp_path, 'app.Deep', 'public record Deep(int x) {}\n')
    index = SourceIndex.scan(str(tmp_path))
    nodes = build('app.Entry', index, FakeObserver())
    assert nodes['app.Repo'].kind == 'behaviour'
    assert 'app.Deep' not in nodes, 'walk must stop at a collaborator, not cross the app'


def test_a_cycle_terminates(tmp_path):
    write(tmp_path, 'app.A', 'import app.B;\npublic record A(B b) {}\n')
    write(tmp_path, 'app.B', 'import app.A;\npublic record B(A a) {}\n')
    index = SourceIndex.scan(str(tmp_path))
    nodes = build('app.A', index, FakeObserver())
    assert set(nodes) == {'app.A', 'app.B'}


def test_accessor_observer_reads_real_call_sites(tmp_path):
    write(tmp_path, 'app.User', (
        'import com.ext.Category;\n'
        'public class User {\n'
        '    void go(Category category) { category.getId(); category.getName(); }\n'
        '}\n'
    ))
    index = SourceIndex.scan(str(tmp_path))
    observed = AccessorObserver(index).observe('com.ext.Category')
    assert observed == ('getId', 'getName')


def test_bounded_wildcard_reaches_its_bound(tmp_path):
    write(tmp_path, 'app.Holder', (
        'import app.Category;\nimport java.util.List;\n'
        'public record Holder(List<? extends Category> taxa) {}\n'
    ))
    write(tmp_path, 'app.Category', 'public record Category(int id) {}\n')
    index = SourceIndex.scan(str(tmp_path))
    nodes = build('app.Holder', index, FakeObserver())
    assert 'app.Category' in nodes, 'bounded wildcard must still reach its bound type'
    assert nodes['app.Category'].kind == 'data'


def test_bare_wildcard_reaches_nothing_and_does_not_crash(tmp_path):
    write(tmp_path, 'app.Holder', (
        'import java.util.List;\n'
        'public record Holder(List<?> items) {}\n'
    ))
    index = SourceIndex.scan(str(tmp_path))
    nodes = build('app.Holder', index, FakeObserver())
    assert set(nodes) == {'app.Holder'}


def test_accessor_observer_does_not_mix_in_a_same_named_variable_of_another_type(tmp_path):
    """A `category` reused in a sibling method, with no Category declaration of its own,
    must not contaminate this type's accessor list -- the real case was a
    lambda parameter `category -> category.allocations()` unrelated to any `Category category`
    declaration elsewhere in the file."""
    write(tmp_path, 'app.User', (
        'import com.ext.Category;\n'
        'public class User {\n'
        '    void go(Category category) { category.getId(); }\n'
        '    void other() { list.stream().flatMap(category -> category.allocations()); }\n'
        '}\n'
    ))
    index = SourceIndex.scan(str(tmp_path))
    observed = AccessorObserver(index).observe('com.ext.Category')
    assert observed == ('getId',)


def test_a_leaf_reason_names_a_package_never_an_enclosing_type():
    """A dotted nested import that resolved nowhere keeps its verbatim form.
    Chopping one segment off it would name `...domain.Category` as a package and
    assert something untrue about the checkout."""
    from lib.typegraph import _package_of
    assert _package_of('com.example.catalog.domain.Category.CategoryId') == \
        'com.example.catalog.domain'
    assert _package_of('com.example.inventory.domain.Asset') == 'com.example.inventory.domain'


def test_observed_accessors_drop_object_methods_and_setters(tmp_path):
    """equals/hashCode/toString are answered by every Java object, so observing
    them names no field of the absent type and coverage_gaps() would report a
    gap no capture could ever close. A setter writes rather than reads."""
    write(tmp_path, 'app.Use', (
        'class Use {\n'
        '    void go() {\n'
        '        Category category = load();\n'
        '        category.getId();\n'
        '        category.equals(other);\n'
        '        category.hashCode();\n'
        '        category.toString();\n'
        '        category.setName("x");\n'
        '        category.settle();\n'
        '    }\n'
        '}\n'
    ))
    index = SourceIndex.scan(str(tmp_path))
    got = AccessorObserver(index).observe('com.ext.Category')
    assert 'getId' in got
    assert 'settle' in got  # `set` without a capital after it is not a setter
    for excluded in ('equals', 'hashCode', 'toString', 'setName'):
        assert excluded not in got
