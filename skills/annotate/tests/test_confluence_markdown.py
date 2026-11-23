"""Markdown to Confluence's HTML format.

Two rules decide every case below. Confluence's format is an ADF-mapped HTML
subset, so anything outside it (`<ac:…>`, a bare `<div>`, a style attribute)
is not "degraded" — it renders as visible junk or is dropped. And a construct
this converter does not understand must RAISE, because a publish that quietly
loses a paragraph is worse than one that refuses to run."""
import pytest

from skills.annotate.confluence.markdown_html import (
    UnsupportedMarkdown, to_html)


def test_paragraphs():
    assert to_html("one\n\ntwo") == "<p>one</p><p>two</p>"


def test_inline_marks():
    assert to_html("**b** and *i* and `c`") == \
        "<p><strong>b</strong> and <em>i</em> and <code>c</code></p>"


def test_a_link():
    assert to_html("see [docs](https://x.test/a)") == \
        '<p>see <a href="https://x.test/a">docs</a></p>'


def test_inline_text_is_escaped():
    assert to_html("a < b & c") == "<p>a &lt; b &amp; c</p>"


def test_code_spans_are_escaped_too():
    assert to_html("`<T>`") == "<p><code>&lt;T&gt;</code></p>"


def test_bullet_list():
    assert to_html("- one\n- two") == "<ul><li><p>one</p></li><li><p>two</p></li></ul>"


def test_ordered_list_carries_its_start():
    assert to_html("3. c\n4. d") == \
        '<ol start="3"><li><p>c</p></li><li><p>d</p></li></ol>'


def test_fenced_code_keeps_its_language():
    assert to_html("```java\nint x = 1;\n```") == \
        '<pre><code class="language-java">int x = 1;</code></pre>'


def test_fenced_code_without_a_language():
    assert to_html("```\nplain\n```") == "<pre><code>plain</code></pre>"


def test_fenced_code_is_escaped_but_not_marked_up():
    assert to_html("```\n**not bold** <x>\n```") == \
        "<pre><code>**not bold** &lt;x&gt;</code></pre>"


def test_heading():
    assert to_html("### Deep") == "<h3>Deep</h3>"


def test_blockquote():
    assert to_html("> quoted") == "<blockquote><p>quoted</p></blockquote>"


def test_pipe_table_with_a_header():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |"
    assert to_html(md) == (
        "<table><thead><tr><th><p>a</p></th><th><p>b</p></th></tr></thead>"
        "<tbody><tr><td><p>1</p></td><td><p>2</p></td></tr></tbody></table>")


def test_table_cells_carry_inline_marks():
    md = "| a |\n| --- |\n| `x` |"
    assert "<td><p><code>x</code></p></td>" in to_html(md)


def test_raw_html_is_refused_not_dropped():
    # pushing.md allows inline HTML in a markdown block, with inline styles and
    # custom classes. None of that survives ADF conversion, so it must stop the
    # publish rather than arrive as a differently-shaped page.
    with pytest.raises(UnsupportedMarkdown) as e:
        to_html('<table class="weigh-up"><tr><td>x</td></tr></table>')
    assert "HTML" in str(e.value)


def test_an_image_is_refused():
    # A markdown image points at a URL Confluence cannot resolve; pictures on a
    # published page are attachments, built by images.py.
    with pytest.raises(UnsupportedMarkdown):
        to_html("![alt](cat.png)")


def test_nothing_emits_storage_format():
    md = "# H\n\ntext\n\n| a |\n| --- |\n| 1 |\n\n```java\nx\n```"
    out = to_html(md)
    assert "<ac:" not in out and "<ri:" not in out


def test_a_tag_with_a_space_after_the_bracket_still_raises():
    # `_HTML_TAG` must not decide on the opening bracket alone — a tag
    # written with whitespace after `<` is still a tag and must not slip
    # past the guard as if it were prose.
    with pytest.raises(UnsupportedMarkdown):
        to_html('< div class="x">')


def test_a_closing_tag_with_a_space_after_the_bracket_raises():
    with pytest.raises(UnsupportedMarkdown):
        to_html("</ div>")


def test_a_lone_angle_bracket_is_not_html():
    assert to_html("a < b & c") == "<p>a &lt; b &amp; c</p>"


def test_comparison_operators_on_both_sides_are_not_html():
    # A naive "line has both < and >" check would wrongly flag this.
    assert to_html("1 < 2 and 3 > 2") == "<p>1 &lt; 2 and 3 &gt; 2</p>"


def test_code_span_with_angle_brackets_is_still_not_html():
    assert to_html("`<T>`") == "<p><code>&lt;T&gt;</code></p>"


# --- Ordinary CommonMark the live page renders and this converter must not
# --- silently flatten. Each of these produced a differently-shaped page with
# --- no error anywhere, which is exactly what the subset exists to prevent.

def test_a_nested_bullet_list_keeps_its_nesting():
    # Flattening three <li> into one level is a different document.
    assert to_html("- a\n  - b\n- c") == (
        "<ul><li><p>a</p><ul><li><p>b</p></li></ul></li>"
        "<li><p>c</p></li></ul>")


def test_a_nested_ordered_list_inside_a_bullet():
    assert to_html("- a\n  1. one\n  2. two") == (
        '<ul><li><p>a</p><ol start="1"><li><p>one</p></li>'
        "<li><p>two</p></li></ol></li></ul>")


def test_a_lazy_continuation_line_stays_in_its_list_item():
    # Splitting the list in two around a stray <p> renumbers it for the reader.
    assert to_html("1. a\n   continued\n2. b") == (
        '<ol start="1"><li><p>a continued</p></li><li><p>b</p></li></ol>')


def test_a_blank_line_does_not_split_one_list_into_two():
    assert to_html("- a\n\n- b") == \
        "<ul><li><p>a</p></li><li><p>b</p></li></ul>"


def test_a_thematic_break_becomes_a_rule():
    assert to_html("a\n\n---\n\nb") == "<p>a</p><hr /><p>b</p>"


def test_a_setext_heading_is_refused_rather_than_read_as_prose():
    # Rare, and ambiguous against `---`, so it stops the publish instead of
    # arriving as a paragraph where the author wrote a heading.
    for md in ("Title\n===", "Title\n---"):
        with pytest.raises(UnsupportedMarkdown) as e:
            to_html(md)
        assert "setext" in str(e.value)


def test_a_pipe_inside_a_code_span_does_not_split_a_table_row():
    md = "| a | b |\n| --- | --- |\n| `x|y` | 2 |"
    out = to_html(md)
    assert "<td><p><code>x|y</code></p></td>" in out
    assert "<td><p>2</p></td>" in out


def test_an_escaped_pipe_is_a_literal_pipe_in_a_cell():
    md = "| a |\n| --- |\n| x \\| y |"
    assert "<td><p>x | y</p></td>" in to_html(md)


def test_a_link_href_is_escaped_once_not_twice():
    # Double-escaping turns every query string into a broken link.
    assert to_html("[docs](https://x.test/a?b=1&c=2)") == \
        '<p><a href="https://x.test/a?b=1&amp;c=2">docs</a></p>'


def test_a_bare_pipe_row_without_a_divider_is_prose_not_a_hang():
    assert to_html("| a | b |") == "<p>| a | b |</p>"
