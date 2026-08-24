"""The model is read-only. It computes addresses; it never emits HTML.

Line numbers are the load-bearing anchor: Claude reads the line range out of
the file rather than grepping the decoded text, because decks mix HTML
entities with their literal characters and a grep for "—" misses "&mdash;".
"""
from __future__ import annotations

from pathlib import Path

from skills.deck import model as model_module

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "mini-deck.html"


def _parsed():
    return model_module.parse_deck(FIXTURE.read_text(encoding="utf-8"))


def test_finds_every_slide_in_document_order():
    slides = _parsed()["slides"]
    assert [s["index"] for s in slides] == [1, 2, 3]


def test_slide_kind_is_derived_from_the_section_class():
    slides = _parsed()["slides"]
    assert [s["kind"] for s in slides] == ["cover", "divider", "content"]


def test_slide_index_ignores_the_num_span():
    # The fixture's .num values read 1, d, 2 — the harness renumbers them at
    # runtime, so they are never an identity.
    slides = _parsed()["slides"]
    assert slides[2]["index"] == 3


def test_title_prefers_title_then_dname_then_dkick():
    slides = _parsed()["slides"]
    assert slides[1]["title"] == "Mandatory documents"
    assert slides[2]["title"] == "The bank’s rules run in the bank’s system"


def test_component_children_are_addressable():
    els = _parsed()["slides"][2]["elements"]
    paths = [e["path"] for e in els]
    assert ".kick" in paths
    assert ".title" in paths
    assert ".conseq" in paths


def test_paragraphs_inside_a_component_are_addressable_individually():
    els = _parsed()["slides"][2]["elements"]
    paths = [e["path"] for e in els]
    assert ".pro > p:nth-of-type(1)" in paths
    assert ".pro > p:nth-of-type(2)" in paths


def test_speaker_note_items_are_addressable():
    els = _parsed()["slides"][2]["elements"]
    paths = [e["path"] for e in els]
    assert ".snotes > li:nth-of-type(1)" in paths
    assert ".snotes > li:nth-of-type(2)" in paths


def test_the_num_span_is_never_addressable():
    for slide in _parsed()["slides"]:
        assert all(".num" not in e["path"] for e in slide["elements"])


def test_line_numbers_point_at_the_real_source_lines():
    src = FIXTURE.read_text(encoding="utf-8").splitlines()
    el = next(e for e in _parsed()["slides"][2]["elements"]
              if e["path"] == ".pro > p:nth-of-type(2)")
    joined = "\n".join(src[el["line_start"] - 1:el["line_end"]])
    assert "Today we ask exactly once" in joined


def test_text_is_decoded_for_display_but_entities_survive_in_the_file():
    el = next(e for e in _parsed()["slides"][2]["elements"]
              if e["path"] == ".pro > p:nth-of-type(2)")
    # decoded, so the popup reads properly
    assert "—" in el["text"]
    # and the file is untouched — the model never rewrote it
    assert "&mdash;" in FIXTURE.read_text(encoding="utf-8")


def test_component_is_the_first_class_of_the_owning_block():
    els = _parsed()["slides"][2]["elements"]
    el = next(e for e in els if e["path"] == ".pro > p:nth-of-type(1)")
    assert el["component"] == "pro"


def test_every_element_carries_its_slide_number():
    for slide in _parsed()["slides"]:
        assert all(e["slide"] == slide["index"] for e in slide["elements"])


def test_inline_tags_do_not_split_a_sentence():
    el = next(e for e in _parsed()["slides"][2]["elements"]
              if e["path"] == ".pro > p:nth-of-type(1)")
    assert el["text"] == "Every proposal has to satisfy two independent sets of rules."


def test_block_tags_keep_neighbouring_cells_apart():
    # A table is one target; without a separator its cells would read "NowLater".
    html = ('<div class="deck"><section class="slide">'
            '<div class="tbl"><table><tr><th>Now</th><th>Later</th></tr>'
            '<tr><td>One</td><td>Two</td></tr></table></div>'
            '</section></div>')
    el = model_module.parse_deck(html)["slides"][0]["elements"][0]
    assert el["text"] == "Now Later One Two"


def test_every_element_carries_an_ordinal():
    for slide in _parsed()["slides"]:
        assert all(e["ord"] == 0 for e in slide["elements"]), \
            "the fixture has no duplicate addresses"


def test_repeated_blocks_are_told_apart_by_ordinal():
    # Real decks put several boxes with the same class on one slide.
    html = ('<div class="deck"><section class="slide">'
            '<div class="stg">first</div><div class="stg">second</div>'
            '<div class="stg">third</div></section></div>')
    els = model_module.parse_deck(html)["slides"][0]["elements"]
    assert [(e["path"], e["ord"], e["text"]) for e in els] == [
        (".stg", 0, "first"), (".stg", 1, "second"), (".stg", 2, "third")]


def test_a_repeated_leaf_path_is_numbered_by_its_owning_block():
    html = ('<div class="deck"><section class="slide">'
            '<div class="ctxp"><ul><li>a</li><li>b</li></ul></div>'
            '<div class="ctxp"><ul><li>c</li><li>d</li></ul></div>'
            '</section></div>')
    els = model_module.parse_deck(html)["slides"][0]["elements"]
    assert [(e["path"], e["ord"], e["text"]) for e in els] == [
        (".ctxp > li:nth-of-type(1)", 0, "a"),
        (".ctxp > li:nth-of-type(2)", 0, "b"),
        (".ctxp > li:nth-of-type(1)", 1, "c"),
        (".ctxp > li:nth-of-type(2)", 1, "d")]


def test_the_title_is_the_first_of_a_repeated_title_block():
    html = ('<div class="deck"><section class="slide">'
            '<div class="title">first</div><div class="title">second</div>'
            '</section></div>')
    assert model_module.parse_deck(html)["slides"][0]["title"] == "first"


DEMO = Path(__file__).resolve().parents[1] / "demo" / "sample-deck.html"


def test_the_demo_deck_parses_into_every_shape_the_model_addresses():
    slides = model_module.parse_deck(DEMO.read_text(encoding="utf-8"))["slides"]
    assert [s["kind"] for s in slides] == [
        "cover", "divider", "content", "content", "divider", "content"]
    paths = {e["path"] for s in slides for e in s["elements"]}
    for expected in (".title", ".dname", ".conseq", ".tbl",
                     ".pro > p:nth-of-type(1)", ".bullets > li:nth-of-type(1)",
                     ".snotes > li:nth-of-type(1)"):
        assert expected in paths, expected


def test_no_two_elements_on_a_slide_share_an_address():
    # (path, ord) is what a comment travels as. Two elements sharing one would
    # send the wrong line range to Claude.
    for source in (FIXTURE, DEMO):
        for slide in model_module.parse_deck(
                source.read_text(encoding="utf-8"))["slides"]:
            keys = [(e["path"], e["ord"]) for e in slide["elements"]]
            assert len(keys) == len(set(keys)), (source.name, slide["index"], keys)


# --- malformed and adversarial markup -------------------------------------
# Decks are hand-written single files. Every case below was a real defect.

def _els(html):
    return [e for s in model_module.parse_deck(html)["slides"]
            for e in s["elements"]]


def _wrap(inner):
    return '<div class="deck"><section class="slide">\n' + inner + '\n</section></div>'


def test_a_text_only_block_survives_a_same_class_block_that_had_leaves():
    els = _els(_wrap('<div class="col"><p>has a paragraph</p></div>\n'
                     '<div class="col">plain text</div>'))
    assert [(e["path"], e["text"]) for e in els] == [
        (".col > p:nth-of-type(1)", "has a paragraph"),
        (".col", "plain text")]


def test_the_block_ordinal_is_not_the_path_ordinal():
    # .col#0 as an address is the slide's SECOND .col block. Conflating the
    # two numbers made the browser highlight one element and Claude edit
    # another.
    els = _els(_wrap('<div class="col"><p>x</p></div>\n<div class="col">plain</div>'))
    plain = next(e for e in els if e["path"] == ".col")
    assert plain["ord"] == 0
    assert plain["block_ord"] == 1


def test_blocks_with_different_leaf_counts_keep_their_own_block_ordinal():
    els = _els(_wrap('<div class="stg"><p>b1 p1</p></div>\n'
                     '<div class="stg"><p>b2 p1</p><p>b2 p2</p></div>'))
    assert [(e["path"], e["ord"], e["block_ord"], e["text"]) for e in els] == [
        (".stg > p:nth-of-type(1)", 0, 0, "b1 p1"),
        (".stg > p:nth-of-type(1)", 1, 1, "b2 p1"),
        (".stg > p:nth-of-type(2)", 0, 1, "b2 p2")]


def test_a_paragraph_inside_a_list_item_does_not_close_the_item():
    els = _els(_wrap('<div class="body"><ul><li><p>inner</p>\ntrailing</li></ul>\n'
                     '<p>sibling</p></div>'))
    assert [(e["path"], e["text"]) for e in els] == [
        (".body > li:nth-of-type(1)", "inner trailing"),
        (".body > p:nth-of-type(1)", "sibling")]


def test_an_unclosed_list_item_does_not_swallow_the_rest_of_the_slide():
    els = _els(_wrap('<ul class="bul"><li>one<li>two</ul>\n'
                     '<div class="title">Title after the list</div>'))
    assert [e["path"] for e in els] == [
        ".bul > li:nth-of-type(1)", ".bul > li:nth-of-type(2)", ".title"]


def test_an_svg_drawn_without_self_closing_tags_does_not_unbalance_the_slide():
    els = _els(_wrap('<div class="diag"><svg><line x1="0"><polygon points="0"></svg></div>\n'
                     '<div class="title">Title after svg</div>'))
    assert [e["path"] for e in els] == [".diag", ".title"]


def test_stray_end_tags_are_ignored_rather_than_raising():
    els = _els(_wrap('<div class="pro"><p>text</p></div></div></section>'))
    assert [e["text"] for e in els] == ["text"]


def test_style_and_script_bodies_are_not_element_text():
    els = _els(_wrap('<div class="pro"><style>.x{color:red}</style>Real text</div>'))
    assert [e["text"] for e in els] == ["Real text"]


def test_template_contents_are_skipped_because_the_browser_cannot_see_them():
    els = _els(_wrap('<div class="pro"><template><p>hidden</p></template><p>real</p></div>'))
    assert [(e["path"], e["text"]) for e in els] == [
        (".pro > p:nth-of-type(1)", "real")]


def test_a_self_closed_br_separates_words():
    els = _els(_wrap('<div class="pro">alpha<br/>beta</div>'))
    assert els[0]["text"] == "alpha beta"


def test_a_nested_slide_section_does_not_end_the_slide_it_sits_in():
    els = _els(_wrap('<div class="k">outer</div>\n'
                     '<section class="slide"><div class="j">inner</div></section>\n'
                     '<div class="m">after inner</div>'))
    assert [e["text"] for e in els][-1] == "after inner"
    assert len(model_module.parse_deck(
        _wrap('<section class="slide"></section>'))["slides"]) == 1


def test_an_unfinished_document_still_yields_what_it_opened():
    els = _els('<div class="deck"><section class="slide">\n<div class="k">only</div>')
    assert [e["text"] for e in els] == ["only"]


def test_every_element_names_its_block_and_its_leaf():
    for e in _els(_wrap('<div class="pro"><p>a</p></div>\n<div class="k">b</div>')):
        assert e["block_class"] and isinstance(e["block_ord"], int)
    els = _els(_wrap('<div class="pro"><p>a</p></div>\n<div class="k">b</div>'))
    assert (els[0]["leaf_tag"], els[0]["leaf_n"]) == ("p", 1)
    assert (els[1]["leaf_tag"], els[1]["leaf_n"]) == (None, None)
