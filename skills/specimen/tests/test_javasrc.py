from skills.specimen.javasrc import strip_noise, find_types


def test_line_comment_is_erased_and_length_is_preserved():
    src = 'class A {} // record Fake(int x)\n'
    out = strip_noise(src)
    assert len(out) == len(src)
    assert 'record' not in out
    assert 'class A {}' in out


def test_block_comment_is_erased_but_newlines_survive():
    src = 'class A {\n/* record Fake(\nint x) */\n}\n'
    out = strip_noise(src)
    assert out.count('\n') == src.count('\n')
    assert 'record' not in out


def test_string_literal_containing_a_keyword_is_erased():
    src = 'class A { String s = "record Fake(int x)"; }\n'
    out = strip_noise(src)
    assert 'record' not in out
    assert 'String s' in out


def test_text_block_is_erased():
    src = 'class A { String s = """\nrecord Fake(int x)\n"""; }\n'
    out = strip_noise(src)
    assert 'record' not in out
    assert out.count('\n') == src.count('\n')


def test_finds_a_record_with_its_line():
    src = '\n\npublic record CategoryValue(Category category, BigDecimal value) {}\n'
    decls = find_types(src)
    assert len(decls) == 1
    assert decls[0].name == 'CategoryValue'
    assert decls[0].kind == 'record'
    assert decls[0].line == 3
    assert decls[0].outer is None


def test_finds_nested_types_and_names_their_outer():
    src = (
        'public record Outer(int a) {\n'
        '    public record Inner(int b) {}\n'
        '    class Helper {}\n'
        '}\n'
    )
    decls = find_types(src)
    by_name = {d.name: d for d in decls}
    assert by_name['Outer'].outer is None
    assert by_name['Inner'].outer == 'Outer'
    assert by_name['Helper'].outer == 'Outer'
    assert by_name['Helper'].kind == 'class'


def test_captures_annotations_on_a_declaration():
    src = '@Value\npublic class RiskContribution {\n}\n'
    decls = find_types(src)
    assert decls[0].name == 'RiskContribution'
    assert 'Value' in decls[0].annotations


def test_finds_an_enum():
    src = 'public enum Side { BUY, SELL }\n'
    decls = find_types(src)
    assert decls[0].kind == 'enum'
