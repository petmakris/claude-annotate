import pytest

from skills.annotate.explain import (
    ExplainError, compile_spec, label_html, LADDER_MAX,
)


CODE = (
    "private Amount adjustMarketValue(BigDecimal quantity, BigDecimal lotSize) {\n"
    "    return ofNullable(this.priceInReferenceCurrency)\n"
    "        .map(p -> p.multiply(quantity.multiply(lotSize)))\n"
    "        .orElse(null);\n"
    "}\n"
)


def spec(**over):
    base = {
        "project": "portfolios", "file": "ValuedPosition.java", "line": 261,
        "lang": "java", "code": CODE,
        "notes": [{"line": 2, "span": "priceInReferenceCurrency", "label": "ref ccy"}],
    }
    base.update(over)
    return base


# The same computation written twice, in two currencies: the snippet that made
# a note-with-several-spans necessary. A label saying "both times" while only
# one of the two is underlined is a claim the pane does not back up.
TWICE = (
    "private Amount adjustMarketValue(BigDecimal quantity, BigDecimal lotSize) {\n"
    "    return ofNullable(this.priceInReferenceCurrency)\n"
    "        .map(p -> p.multiply(quantity.multiply(lotSize)))\n"
    "        .orElse(null);\n"
    "}\n"
    "\n"
    "private Amount adjustMarketValueInPositionCurrency(BigDecimal quantity, BigDecimal lotSize) {\n"
    "    return ofNullable(this.dirtyPriceInPositionCurrency)\n"
    "        .map(p -> p.multiply(quantity.multiply(lotSize)))\n"
    "        .orElse(null);\n"
    "}\n"
)
CALC = "p.multiply(quantity.multiply(lotSize))"


# --- the span is quoted, and this module finds it ------------------------

def test_span_resolves_to_its_column_and_length():
    view = compile_spec(spec())
    mark = view["groups"][0]["marks"][0]
    # "    return ofNullable(this." is 27 characters.
    assert (mark["col"], mark["len"]) == (27, len("priceInReferenceCurrency"))


def test_absent_span_is_refused_and_names_the_line():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[
            {"line": 2, "span": "priceInPortfolioCurrency", "label": "x"}]))
    assert "does not occur on line 2" in str(e.value)


def test_ambiguous_span_is_refused_rather_than_guessed():
    # `multiply` appears twice on line 3; picking the first silently would
    # underline the wrong call.
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[{"line": 3, "span": "multiply", "label": "x"}]))
    assert "occurs 2 times" in str(e.value)


def test_nth_disambiguates():
    view = compile_spec(spec(notes=[
        {"line": 3, "span": "multiply", "nth": 2, "label": "x"}]))
    col = view["groups"][0]["marks"][0]["col"]
    assert CODE.split("\n")[2][col:col + 8] == "multiply"
    assert col == CODE.split("\n")[2].find("multiply", CODE.split("\n")[2].find("multiply") + 1)


def test_nth_beyond_the_hits_is_refused():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[
            {"line": 3, "span": "multiply", "nth": 5, "label": "x"}]))
    assert "which has 2" in str(e.value)


def test_line_outside_the_snippet_is_refused():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[{"line": 99, "span": "return", "label": "x"}]))
    assert "outside the snippet" in str(e.value)


def test_tabs_are_expanded_before_columns_are_measured():
    # One tab is one character but four `ch`, so a column counted over raw
    # tabs would paint the underline short of its span.
    view = compile_spec(spec(code="\tint x = compute();\n", notes=[
        {"line": 1, "span": "compute", "label": "x"}]))
    assert view["rows"][0]["text"].startswith("    ")
    assert view["groups"][0]["marks"][0]["col"] == view["rows"][0]["text"].index("compute")


# --- the presentation follows from the count -----------------------------

def test_one_or_two_marks_on_a_line_use_the_ladder():
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "ofNullable", "label": "a"},
        {"line": 2, "span": "priceInReferenceCurrency", "label": "b"},
    ]))
    assert view["groups"][0]["mode"] == "drop"
    assert len(view["groups"][0]["marks"]) == 2


def test_a_third_mark_switches_that_line_to_badges():
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "return", "label": "a"},
        {"line": 2, "span": "ofNullable", "label": "b"},
        {"line": 2, "span": "priceInReferenceCurrency", "label": "c"},
    ]))
    assert len(view["groups"][0]["marks"]) == LADDER_MAX + 1
    assert view["groups"][0]["mode"] == "badge"


def test_marks_are_numbered_left_to_right_whatever_order_they_were_written():
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "priceInReferenceCurrency", "label": "right"},
        {"line": 2, "span": "return", "label": "left"},
    ]))
    marks = view["groups"][0]["marks"]
    assert [m["n"] for m in marks] == [1, 2]
    assert marks[0]["col"] < marks[1]["col"]
    assert "left" in marks[0]["labelHtml"]


# --- ranges ---------------------------------------------------------------

def test_a_range_note_becomes_a_bracket_not_a_mark():
    view = compile_spec(spec(notes=[{"lines": [2, 4], "label": "whole thing"}]))
    assert view["groups"] == []
    assert view["ranges"] == [{"from": 2, "to": 4, "labelHtml": "whole thing"}]


def test_overlapping_ranges_are_refused():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[
            {"lines": [1, 3], "label": "a"}, {"lines": [2, 4], "label": "b"}]))
    assert "overlap" in str(e.value)


def test_touching_ranges_are_allowed():
    view = compile_spec(spec(notes=[
        {"lines": [1, 2], "label": "a"}, {"lines": [3, 4], "label": "b"}]))
    assert [r["from"] for r in view["ranges"]] == [1, 3]


def test_range_outside_the_snippet_is_refused():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[{"lines": [1, 99], "label": "a"}]))
    assert "outside the snippet" in str(e.value)


# --- shape ----------------------------------------------------------------

def test_a_block_with_no_notes_is_refused_as_a_fenced_block_in_disguise():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[]))
    assert "at least one note" in str(e.value)


def test_missing_code_is_refused():
    with pytest.raises(ExplainError):
        compile_spec(spec(code="   "))


def test_header_joins_file_and_line():
    assert compile_spec(spec())["loc"] == "ValuedPosition.java:261"
    assert compile_spec(spec(line=None))["loc"] == "ValuedPosition.java"


def test_blank_rows_are_marked_so_the_renderer_can_shrink_them():
    view = compile_spec(spec(code="a\n\nb\n", notes=[
        {"line": 3, "span": "b", "label": "x"}]))
    assert [r["blank"] for r in view["rows"]] == [False, True, False]


def test_trailing_blank_lines_are_dropped_not_rendered():
    view = compile_spec(spec(code="a\n\n\n", notes=[
        {"line": 1, "span": "a", "label": "x"}]))
    assert len(view["rows"]) == 1


# --- a note may own several spans -----------------------------------------

def test_a_note_may_mark_several_spans():
    view = compile_spec(spec(code=TWICE, notes=[
        {"spans": [{"line": 3, "span": CALC}, {"line": 9, "span": CALC}],
         "label": "**the same multiplication**, both times"}]))
    step = view["walk"][0]
    assert [(m["line"], m["len"]) for m in step["marks"]] == [
        (3, len(CALC)), (9, len(CALC))]


def test_the_second_span_is_underlined_without_reprinting_the_label():
    # Both occurrences are marked, but the prose is written once: a label
    # repeated under every twin is the same sentence twice in one pane.
    view = compile_spec(spec(code=TWICE, notes=[
        {"spans": [{"line": 3, "span": CALC}, {"line": 9, "span": CALC}],
         "label": "**the same multiplication**, both times"}]))
    by_line = {g["line"]: g for g in view["groups"]}
    assert "the same multiplication" in by_line[3]["marks"][0]["labelHtml"]
    assert by_line[9]["marks"][0]["labelHtml"] == ""
    assert by_line[9]["marks"][0]["echo"] is True


def test_an_echo_does_not_push_its_line_into_badge_mode():
    # Line 9 ends up carrying three marks, but two of them are echoes with
    # nothing to say. Counting those would switch the line to numbered badges
    # to unstack labels that were never going to be stacked.
    view = compile_spec(spec(code=TWICE, notes=[
        {"spans": [{"line": 3, "span": CALC}, {"line": 9, "span": CALC}],
         "label": "**calc**"},
        {"spans": [{"line": 2, "span": "priceInReferenceCurrency"},
                   {"line": 9, "span": "quantity"}],
         "label": "**the quantity**"},
        {"line": 9, "span": "lotSize", "label": "**the lot**"},
    ]))
    by_line = {g["line"]: g for g in view["groups"]}
    assert len(by_line[9]["marks"]) == LADDER_MAX + 1
    assert by_line[9]["mode"] == "drop"
    assert [m.get("n") for m in by_line[9]["marks"] if not m["echo"]] == [1]


def test_a_bad_quote_inside_spans_is_refused_like_any_other():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(code=TWICE, notes=[
            {"spans": [{"line": 3, "span": CALC}, {"line": 9, "span": "nope"}],
             "label": "x"}]))
    assert "does not occur on line 9" in str(e.value)


def test_a_note_cannot_quote_both_ways_at_once():
    with pytest.raises(ExplainError) as e:
        compile_spec(spec(notes=[
            {"line": 2, "span": "ofNullable",
             "spans": [{"line": 2, "span": "return"}], "label": "x"}]))
    assert "either" in str(e.value)


# --- the walk -------------------------------------------------------------

def test_the_walk_follows_the_authored_order_not_the_file_order():
    # Reading order is the argument's order. Step 1 here is on line 8 because
    # that is where the explanation starts, not where the file does.
    view = compile_spec(spec(code=TWICE, notes=[
        {"line": 8, "span": "dirtyPriceInPositionCurrency", "label": "**position currency**"},
        {"line": 2, "span": "priceInReferenceCurrency", "label": "**reference currency**"},
    ]))
    assert [s["marks"][0]["line"] for s in view["walk"]] == [8, 2]
    assert [s["n"] for s in view["walk"]] == [1, 2]


def test_a_step_carries_its_lead_in_for_the_counter():
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "priceInReferenceCurrency",
         "label": "**reference currency.** Already FX-converted."}]))
    assert view["walk"][0]["lead"] == "reference currency"


def test_a_lead_in_reaches_the_counter_as_plain_text():
    # The lead is lifted out of the label's markdown and printed in a step
    # counter, which renders no markup — so an identifier in the lead-in
    # arrived with its backticks showing: "step 1 of 3 — the same division
    # `normalize` does". Caught on a real page, not in a test fixture.
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "priceInReferenceCurrency",
         "label": "**the same division `normalize` does** — one layer later."}]))
    assert view["walk"][0]["lead"] == "the same division normalize does"


def test_a_stressed_word_in_a_lead_in_loses_its_markers_too():
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "priceInReferenceCurrency",
         "label": "**the *whole* position** — every share of it."}]))
    assert view["walk"][0]["lead"] == "the whole position"


def test_a_label_with_no_lead_in_walks_without_one():
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "priceInReferenceCurrency", "label": "already converted"}]))
    assert view["walk"][0]["lead"] == ""


def test_a_range_is_a_step_too():
    view = compile_spec(spec(notes=[
        {"line": 2, "span": "ofNullable", "label": "**one**"},
        {"lines": [2, 4], "label": "**together**"},
    ]))
    assert [s["kind"] for s in view["walk"]] == ["span", "range"]
    assert view["walk"][1]["from"] == 2 and view["walk"][1]["to"] == 4


def test_every_note_reaches_the_walk_in_one_step_each():
    view = compile_spec(spec(code=TWICE, notes=[
        {"line": 2, "span": "priceInReferenceCurrency", "label": "a"},
        {"spans": [{"line": 3, "span": CALC}, {"line": 9, "span": CALC}], "label": "b"},
        {"lines": [7, 11], "label": "c"},
    ]))
    assert len(view["walk"]) == 3


# --- labels ---------------------------------------------------------------

def test_label_markdown_is_restricted_to_bold_italic_and_code():
    assert label_html("**a** and *b* and `c`") == "<b>a</b> and <em>b</em> and <code>c</code>"


def test_bold_is_not_eaten_by_the_italic_rule():
    # `**x**` read as italic-first comes out as <em></em>x<em></em>. A real
    # push shipped `*several*` with its asterisks showing, which is what added
    # italic here; getting the order wrong would trade one bug for a worse one.
    assert label_html("**only**") == "<b>only</b>"
    assert label_html("**a** then *b*") == "<b>a</b> then <em>b</em>"


def test_an_italic_run_does_not_span_a_bold_one():
    assert label_html("*a* x **b** y *c*") == "<em>a</em> x <b>b</b> y <em>c</em>"


def test_a_lone_asterisk_is_left_alone():
    assert label_html("2 * 3 = 6") == "2 * 3 = 6"


def test_label_html_is_escaped():
    # A label is model-authored prose that lands in innerHTML; anything not in
    # the restricted subset has to arrive as text.
    assert label_html('<img src=x onerror="y">') == (
        "&lt;img src=x onerror=&quot;y&quot;&gt;")


def test_label_escaping_runs_before_the_subset_so_code_cannot_smuggle_tags():
    assert label_html("`<b>x</b>`") == "<code>&lt;b&gt;x&lt;/b&gt;</code>"
