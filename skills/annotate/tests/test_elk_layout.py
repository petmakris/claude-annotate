"""ELK geometry, and the fallback that makes it optional."""
from unittest import mock

import pytest

from skills.annotate.diagrams import elk_layout, flavours


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


def test_layout_puts_every_edge_route_point_inside_the_canvas():
    nodes, edges = _graph()
    _, w, h, routes = elk_layout.layout(nodes, edges)
    assert routes  # otherwise this test asserts nothing
    for pts in routes.values():
        for x, y in pts:
            assert 0 <= x <= w
            assert 0 <= y <= h


def test_a_registered_variant_can_still_change_direction(monkeypatch):
    # HOUSE_SET now ships "layered" only, but elk_layout itself is agnostic
    # to what the house set contains — it just asks flavours for whatever
    # variant name it is given. This registers a throwaway "wide" entry to
    # prove that plumbing still works, independent of the house set's
    # current single flavour.
    monkeypatch.setitem(flavours._BY_NAME, "wide", {"elk.direction": "RIGHT"})
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


def test_run_elk_raises_elk_unavailable_for_non_serializable_graph():
    graph = {"id": "root", "children": [{"id": "a", "bad": object()}]}
    with pytest.raises(elk_layout.ElkUnavailable):
        elk_layout.run_elk(graph)


def test_a_malformed_edge_is_skipped_without_discarding_elk_positions():
    nodes, edges = _graph()
    out = {
        "width": 200.0,
        "height": 200.0,
        "children": [
            {"id": "a", "x": 0.0, "y": 0.0, "width": 40.0, "height": 20.0},
            {"id": "b", "x": 0.0, "y": 80.0, "width": 40.0, "height": 20.0},
            {"id": "c", "x": 0.0, "y": 160.0, "width": 40.0, "height": 20.0},
        ],
        "edges": [
            {
                "id": "e0",
                "sections": [{
                    "startPoint": {"x": 20.0, "y": 20.0},
                    "endPoint": {"x": 20.0, "y": 80.0},
                }],
            },
            # Malformed: a section that is not a dict at all. This must be
            # skipped on its own, not discard the ELK positions above.
            {"id": "e1", "sections": ["not-a-section"]},
        ],
    }
    with mock.patch.object(elk_layout, "run_elk", return_value=out):
        positions, w, h, routes = elk_layout.layout(nodes, edges)

    # Positions came from ELK's reply (out["children"]), not the Python
    # fallback: the fallback would not reproduce these exact coordinates.
    assert positions["a"]["cx"] == 20.0 + elk_layout.MARGIN
    assert positions["b"]["cy"] == 90.0 + elk_layout.MARGIN
    assert set(routes) == {0}
    assert routes[0][0] == (20.0 + elk_layout.MARGIN, 20.0 + elk_layout.MARGIN)


def test_layout_falls_back_when_elk_returns_a_non_dict():
    nodes, edges = _graph()
    for bogus in ([], None):
        with mock.patch.object(elk_layout, "run_elk", return_value=bogus):
            positions, w, h, routes = elk_layout.layout(nodes, edges)
        assert set(positions) == {"a", "b", "c"}
        assert routes == {}
