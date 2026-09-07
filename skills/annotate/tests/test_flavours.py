"""House-set presets and the viability gate."""
import pytest

from skills.annotate.diagrams import flavours


def _positions(boxes):
    """boxes: {id: (cx, cy, w, h)} -> the subset of the positions shape used here."""
    return {k: {"cx": cx, "cy": cy, "w": w, "h": h}
            for k, (cx, cy, w, h) in boxes.items()}


def test_house_set_order_is_layered_compact_wide_tree():
    assert [name for name, _ in flavours.HOUSE_SET] == \
        ["layered", "compact", "wide", "tree"]


def test_options_merge_base_with_the_variant():
    assert flavours.options("layered")["elk.algorithm"] == "layered"
    assert flavours.options("compact")["elk.spacing.nodeNode"] == "22"
    assert flavours.options("wide")["elk.direction"] == "RIGHT"
    assert flavours.options("tree")["elk.algorithm"] == "mrtree"


def test_options_raises_for_an_unknown_variant():
    with pytest.raises(ValueError, match="nonsense"):
        flavours.options("nonsense")


def test_options_resolves_every_house_set_name():
    for name, _ in flavours.HOUSE_SET:
        assert flavours.options(name)["elk.algorithm"] in ("layered", "mrtree")


def test_pins_entries_only_for_the_layered_algorithm():
    assert flavours.pins_entries("layered") is True
    assert flavours.pins_entries("compact") is True
    assert flavours.pins_entries("wide") is True
    assert flavours.pins_entries("tree") is False


def test_viable_rejects_a_missing_route():
    pos = _positions({"a": (50, 20, 80, 30), "b": (50, 120, 80, 30)})
    assert flavours.viable(pos, {0: [(0, 0), (0, 10)]}, edge_count=1) is True
    assert flavours.viable(pos, {}, edge_count=1) is False


def test_viable_rejects_a_one_point_route():
    pos = _positions({"a": (50, 20, 80, 30)})
    assert flavours.viable(pos, {0: [(0, 0)]}, edge_count=1) is False


def test_viable_rejects_overlapping_nodes():
    pos = _positions({"a": (50, 20, 80, 30), "b": (55, 25, 80, 30)})
    assert flavours.viable(pos, {0: [(0, 0), (0, 10)]}, edge_count=1) is False


def test_select_keeps_layered_even_when_it_fails_the_gate():
    results = [("layered", _positions({"a": (5, 5, 80, 30), "b": (6, 6, 80, 30)}),
                100.0, 100.0, {})]
    assert flavours.select(results, edge_count=1) == ["layered"]


def test_select_drops_a_near_duplicate_canvas():
    pos = _positions({"a": (50, 20, 80, 30), "b": (50, 120, 80, 30)})
    routes = {0: [(0, 0), (0, 10)]}
    results = [
        ("layered", pos, 1000.0, 900.0, routes),
        ("compact", pos, 1020.0, 890.0, routes),   # within 5% on both axes
        ("wide", pos, 2100.0, 480.0, routes),
    ]
    assert flavours.select(results, edge_count=1) == ["layered", "wide"]


def test_select_drops_an_unroutable_variant():
    pos = _positions({"a": (50, 20, 80, 30), "b": (50, 120, 80, 30)})
    results = [
        ("layered", pos, 1000.0, 900.0, {0: [(0, 0), (0, 10)]}),
        ("tree", pos, 400.0, 300.0, {}),
    ]
    assert flavours.select(results, edge_count=1) == ["layered"]
