from skills.specimen.imports import FileImports, SourceIndex, read_imports, resolve

FIVE_TAXONS = [
    'com.example.export.store.Category',
    'com.example.export.pdf.Category',
    'com.example.trading.context.Category',
    'com.example.legacy.report.data.Category',
    'com.example.proposals.report.Category',
]


def index_with_five_categories():
    index = SourceIndex()
    for fqn in FIVE_TAXONS:
        index.add(fqn, f'/fake/{fqn.replace(".", "/")}.java')
    return index


def test_reads_package_and_explicit_imports():
    src = (
        'package com.example.analytics.model;\n'
        '\n'
        'import com.example.catalog.domain.Category;\n'
        'import java.util.List;\n'
    )
    imports = read_imports(src)
    assert imports.package == 'com.example.analytics.model'
    assert imports.explicit['Category'] == 'com.example.catalog.domain.Category'


def test_reads_wildcard_imports_separately():
    src = 'package a.b;\nimport java.util.*;\n'
    imports = read_imports(src)
    assert imports.wildcards == ('java.util',)
    assert imports.explicit == {}


def test_static_imports_are_ignored():
    src = 'package a.b;\nimport static org.assertj.core.api.Assertions.assertThat;\n'
    imports = read_imports(src)
    assert imports.explicit == {}


def test_explicit_import_wins_over_five_same_named_classes():
    """The whole reason this module exists."""
    src = (
        'package com.example.analytics.model;\n'
        'import com.example.catalog.domain.Category;\n'
    )
    got = resolve('Category', read_imports(src), index_with_five_categories())
    assert got.fqn == 'com.example.catalog.domain.Category'
    assert got.how == 'import'
    assert got.fqn not in FIVE_TAXONS


def test_same_package_wins_when_there_is_no_import():
    index = index_with_five_categories()
    src = 'package com.example.trading.context;\n'
    got = resolve('Category', read_imports(src), index)
    assert got.fqn == 'com.example.trading.context.Category'
    assert got.how == 'same-package'


def test_wildcard_import_resolves_only_when_the_index_knows_the_class():
    index = index_with_five_categories()
    src = 'package unrelated.pkg;\nimport com.example.trading.context.*;\n'
    got = resolve('Category', read_imports(src), index)
    assert got.fqn == 'com.example.trading.context.Category'
    assert got.how == 'wildcard'


def test_builtin_types_resolve_without_an_import():
    got = resolve('List', read_imports('package a.b;\n'), SourceIndex())
    assert got.fqn == 'java.util.List'
    assert got.how == 'builtin'


def test_unknown_simple_name_is_unresolved_never_guessed():
    """An unresolved name must NOT collapse onto one of the five Categories."""
    index = index_with_five_categories()
    src = 'package unrelated.pkg;\n'
    got = resolve('Category', read_imports(src), index)
    assert got.fqn is None
    assert got.how == 'unresolved'


def test_nested_types_are_indexed_under_outer_dollar_nested(tmp_path):
    """CategoryRiskContribution and Chart have no files of their own."""
    f = tmp_path / 'm/src/main/java/a/b'
    f.mkdir(parents=True)
    (f / 'Result.java').write_text(
        'package a.b;\n'
        'public record Result(java.util.List<Chart> charts) {\n'
        '    public record Chart(int x) {}\n'
        '}\n'
    )
    index = SourceIndex.scan(str(tmp_path))
    assert index.has('a.b.Result')
    assert index.has('a.b.Result$Chart')
    assert index.path_of('a.b.Result$Chart') == index.path_of('a.b.Result')


def test_a_nested_name_resolves_to_its_own_file_not_a_same_named_class_elsewhere(tmp_path):
    """The BIRT trap: a real Chart.java exists in the checkout, in an unrelated package.

    Without same-unit resolution, `Chart` inside AnalyticsResult binds to
    com.example.legacy.report.chart.Chart and the
    page describes a BIRT report template.
    """
    a = tmp_path / 'm/src/main/java/a/b'
    a.mkdir(parents=True)
    (a / 'Result.java').write_text(
        'package a.b;\n'
        'public record Result(java.util.List<Chart> charts) {\n'
        '    public record Chart(int x) {}\n'
        '}\n'
    )
    birt = tmp_path / 'm/src/main/java/z/birt'
    birt.mkdir(parents=True)
    (birt / 'Chart.java').write_text('package z.birt;\npublic record Chart(String decoy) {}\n')

    index = SourceIndex.scan(str(tmp_path))
    src = (a / 'Result.java').read_text()
    got = resolve('Chart', read_imports(src), index)
    assert got.fqn == 'a.b.Result$Chart'
    assert got.how == 'same-unit'
    assert got.fqn != 'z.birt.Chart'


def test_an_explicit_import_still_beats_a_same_named_nested_type():
    """Documents the chosen order. Java's own shadowing rule is the other way
    round for a member type inside its enclosing class body; no real file
    exercises the difference, and import-first keeps 'resolution is by import'
    literally true. See the plan's Known Order note."""
    src = (
        'package a.b;\n'
        'import com.ext.Chart;\n'
        'public record Result(Chart c) {\n'
        '    public record Chart(int x) {}\n'
        '}\n'
    )
    got = resolve('Chart', read_imports(src), SourceIndex())
    assert got.fqn == 'com.ext.Chart'
    assert got.how == 'import'


def test_scan_builds_an_index_from_a_worktree(tmp_path):
    f = tmp_path / 'mod' / 'src' / 'main' / 'java' / 'a' / 'b'
    f.mkdir(parents=True)
    (f / 'Thing.java').write_text('package a.b;\npublic record Thing(int x) {}\n')
    index = SourceIndex.scan(str(tmp_path))
    assert index.has('a.b.Thing')
    assert index.by_simple_name('Thing') == ['a.b.Thing']


# --- dotted nested imports -------------------------------------------------
#
# Java writes a nested type in an import with a dot; SourceIndex keys it with a
# `$`. Before the rewrite below, resolve() handed back the dot form verbatim,
# index.path_of() missed, and typegraph.build wrote a leaf whose reason said the
# package was "not checked out here" — on the same page that was already
# rendering that package's fields from source. a real checkout can carry thousands of distinct
# dotted nested imports, so this was not an edge case.

def _write(tmp_path, rel, text):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_one_level_dotted_nested_import_resolves_to_the_dollar_key(tmp_path):
    _write(tmp_path, 'm/src/main/java/a/b/Result.java',
           'package a.b;\n'
           'public record Result(int x) {\n'
           '    public record CategoryAllocation(int y) {}\n'
           '}\n')
    index = SourceIndex.scan(str(tmp_path))
    src = 'package z.q;\nimport a.b.Result.CategoryAllocation;\n'
    got = resolve('CategoryAllocation', read_imports(src), index)
    assert got.fqn == 'a.b.Result$CategoryAllocation'
    assert got.how == 'import-nested'
    assert index.path_of(got.fqn) is not None


def test_two_level_dotted_nested_import_resolves(tmp_path):
    _write(tmp_path, 'm/src/main/java/a/b/Result.java',
           'package a.b;\n'
           'public record Result(int x) {\n'
           '    public record Mid(int y) {\n'
           '        public record Inner(int z) {}\n'
           '    }\n'
           '}\n')
    index = SourceIndex.scan(str(tmp_path))
    src = 'package z.q;\nimport a.b.Result.Mid.Inner;\n'
    got = resolve('Inner', read_imports(src), index)
    assert got.fqn == 'a.b.Result$Mid$Inner'
    assert got.how == 'import-nested'


def test_a_genuinely_external_dotted_import_still_becomes_a_leaf(tmp_path):
    """com.example...Category.CategoryId is in no local repo. The rewrite must not
    invent a resolution for it; it stays the verbatim import, which is what
    makes typegraph record it as a leaf with an honest reason."""
    _write(tmp_path, 'm/src/main/java/a/b/Result.java',
           'package a.b;\npublic record Result(int x) {}\n')
    index = SourceIndex.scan(str(tmp_path))
    src = ('package a.b;\n'
           'import com.example.catalog.domain.Category.CategoryId;\n')
    got = resolve('CategoryId', read_imports(src), index)
    assert got.fqn == 'com.example.catalog.domain.Category.CategoryId'
    assert got.how == 'import'
    assert not index.has(got.fqn)


def test_the_rewrite_only_touches_capitalised_segment_pairs():
    from skills.specimen.imports import nested_forms
    assert nested_forms('a.b.Outer.Nested') == ['a.b.Outer$Nested']
    assert nested_forms('a.b.Outer.Mid.Inner') == [
        'a.b.Outer.Mid$Inner', 'a.b.Outer$Mid$Inner']
    assert nested_forms('a.b.Plain') == []
