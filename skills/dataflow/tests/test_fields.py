import json
import re
from pathlib import Path

import pytest

from skills.dataflow.fields import render

FIELDS = Path(__file__).resolve().parent.parent / "fields"


def _example():
    return json.loads((FIELDS / "example-order.json").read_text())


def test_example_renders_a_complete_document():
    out = render.render(_example())
    assert out.lstrip().lower().startswith("<!doctype html")
    assert "Order Field Provenance" in out


def test_output_has_no_external_references():
    # The file must render offline: no webfont, CDN, script src or remote image.
    out = render.render(_example())
    urls = [u for u in re.findall(r"https?://[^\s\"'<>)]+", out)
            if not u.startswith("http://www.w3.org/")]
    assert urls == []


def test_unknown_field_is_refused():
    spec = _example()
    spec["edges"].append({"from": "entity.nope", "to": "dto.total"})
    try:
        render.render(spec)
    except KeyError:
        return
    raise AssertionError("an edge naming an undeclared field must raise KeyError")


def test_card_loop_is_refused():
    spec = _example()
    spec["edges"].append({"from": "json.total", "to": "entity.id"})
    with pytest.raises(ValueError, match="cards feed each other in a loop: entity → dto → json → entity; "
                                         "draw the later stage of one of them as its own card"):
        render.render(spec)


def test_loop_entered_from_outside_names_only_the_loop():
    # The DFS starts at entity, walks into dto and json, and must report the loop it
    # closes there, without the path that led into it.
    spec = _example()
    spec["edges"].append({"from": "json.total", "to": "dto.total"})
    with pytest.raises(ValueError, match="loop: dto → json → dto;"):
        render.render(spec)


def test_edge_inside_one_card_is_refused():
    spec = _example()
    spec["edges"].append({"from": "dto.id", "to": "dto.total"})
    with pytest.raises(ValueError, match="edge dto.id → dto.total stays inside card 'dto'; a field cannot feed its own card"):
        render.render(spec)


def test_repeated_edge_is_refused():
    spec = _example()
    spec["edges"].append(dict(spec["edges"][0]))
    e = spec["edges"][0]
    with pytest.raises(ValueError, match=f"edge {e['from']} → {e['to']} appears twice"):
        render.render(spec)


def test_card_order_needs_no_topological_sort():
    # Listing the consumer first used to raise "must run left to right"; nothing in the
    # spec places a card any more.
    spec = _example()
    spec["cards"].reverse()
    assert render.render(spec).lstrip().lower().startswith("<!doctype html")


def test_legacy_slot_and_gaps_draw_with_a_note(tmp_path, monkeypatch, capsys):
    import sys
    plain = _example()
    legacy = _example()
    for i, c in enumerate(legacy["cards"]):
        c["slot"] = 7 - i                     # backwards: would have been refused
    legacy["gaps"] = {"1": 300}
    assert render.render(legacy) == render.render(plain)

    for spec, noted in ((legacy, True), (plain, False)):
        src = tmp_path / "s.json"
        src.write_text(json.dumps(spec))
        monkeypatch.setattr(sys, "argv", ["render.py", str(src)])
        assert render.main() == 0
        err = capsys.readouterr().err
        assert (render.LEGACY_NOTE in err) is noted, err
    assert render.LEGACY_NOTE == 'note: "slot" and "gaps" are no longer read; columns and gap widths come from the wires'


def test_unknown_lane_is_refused():
    spec = _example()
    spec["edges"][0]["lane"] = "sideways"
    with pytest.raises(ValueError):
        render.render(spec)


def test_unknown_rows_mode_is_refused():
    spec = _example()
    spec["cards"][0]["rows"] = "alphabetical"
    with pytest.raises(ValueError):
        render.render(spec)


def test_card_without_fields_is_refused():
    spec = _example()
    spec["cards"].append({"id": "empty", "name": "Empty", "fields": []})
    with pytest.raises(ValueError):
        render.render(spec)


@pytest.mark.parametrize("break_it", [
    lambda s: s["cards"].append(dict(s["cards"][0])),                       # duplicate card id
    lambda s: s["cards"][0]["fields"].append(dict(s["cards"][0]["fields"][0])),  # duplicate field id
    lambda s: s["cards"][0].update(slot=None),                               # slot not a number
    lambda s: s.update(cards=[], edges=[]),                                  # nothing to draw
])
def test_malformed_cards_are_refused_with_a_clear_error(break_it):
    spec = _example()
    break_it(spec)
    with pytest.raises(ValueError):
        render.render(spec)
