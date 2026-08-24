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
