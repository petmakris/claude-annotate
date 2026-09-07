"""ELK geometry, and the fallback that makes it optional."""
from unittest import mock

from skills.annotate.diagrams import elk_layout


def _graph():
    nodes = [
        {"id": "a", "role": "entry", "label": "start"},
        {"id": "b", "role": "code", "ref": "F:1", "method": "m()"},
        {"id": "c", "role": "success", "label": "done"},
    ]
    edges = [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "ok"}]
    return nodes, edges


def test_layout_returns_positions_canvas_and_routes():
    nodes, edges = _graph()
    positions, w, h, routes = elk_layout.layout(nodes, edges)

    assert set(positions) == {"a", "b", "c"}
    for p in positions.values():
        assert {"cx", "cy", "w", "h", "role", "node", "lines", "layer"} <= set(p)
        assert p["w"] > 0 and p["h"] > 0
    assert w > 0 and h > 0
    assert set(routes) == {0, 1}
    for pts in routes.values():
        assert len(pts) >= 2
        assert all(len(pt) == 2 for pt in pts)


def test_layout_puts_every_node_inside_the_canvas():
    nodes, edges = _graph()
    positions, w, h, _ = elk_layout.layout(nodes, edges)
    for p in positions.values():
        assert p["cx"] - p["w"] / 2 >= 0
        assert p["cy"] - p["h"] / 2 >= 0
        assert p["cx"] + p["w"] / 2 <= w
        assert p["cy"] + p["h"] / 2 <= h


def test_wide_variant_is_wider_than_it_is_tall_relative_to_layered():
    nodes, edges = _graph()
    _, dw, dh, _ = elk_layout.layout(nodes, edges, variant="layered")
    _, ww, wh, _ = elk_layout.layout(nodes, edges, variant="wide")
    assert ww / wh > dw / dh


def test_layout_falls_back_to_python_when_elk_is_unavailable():
    nodes, edges = _graph()
    with mock.patch.object(elk_layout, "run_elk",
                           side_effect=elk_layout.ElkUnavailable("no node")):
        positions, w, h, routes = elk_layout.layout(nodes, edges)
    assert set(positions) == {"a", "b", "c"}
    assert w > 0 and h > 0
    assert routes == {}


def test_layout_falls_back_when_elk_returns_nonsense():
    nodes, edges = _graph()
    with mock.patch.object(elk_layout, "run_elk", return_value={"children": []}):
        positions, w, h, routes = elk_layout.layout(nodes, edges)
    assert set(positions) == {"a", "b", "c"}
    assert routes == {}


def test_layout_falls_back_when_elk_returns_a_non_dict():
    nodes, edges = _graph()
    for bogus in ([], None):
        with mock.patch.object(elk_layout, "run_elk", return_value=bogus):
            positions, w, h, routes = elk_layout.layout(nodes, edges)
        assert set(positions) == {"a", "b", "c"}
        assert routes == {}
