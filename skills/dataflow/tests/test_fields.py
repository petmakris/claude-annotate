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


def test_backward_edge_is_refused():
    spec = _example()
    spec["edges"].append({"from": "json.total", "to": "entity.id"})
    with pytest.raises(ValueError):
        render.render(spec)


def test_same_column_edge_is_refused():
    spec = _example()
    spec["edges"].append({"from": "dto.id", "to": "dto.total"})
    with pytest.raises(ValueError):
        render.render(spec)


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
    spec["cards"].append({"id": "empty", "slot": 3, "name": "Empty", "fields": []})
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
