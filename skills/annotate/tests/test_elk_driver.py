"""The Node side of ELK: a graph in, a laid-out graph out."""
import pytest

from skills.annotate.diagrams.elk_layout import ElkUnavailable, run_elk


def _graph():
    return {
        "id": "root",
        "layoutOptions": {"elk.algorithm": "layered", "elk.direction": "DOWN",
                          "elk.edgeRouting": "ORTHOGONAL"},
        "children": [
            {"id": "a", "width": 120.0, "height": 40.0},
            {"id": "b", "width": 120.0, "height": 40.0},
        ],
        "edges": [{"id": "e0", "sources": ["a"], "targets": ["b"]}],
    }


def test_run_elk_positions_nodes_and_routes_the_edge():
    out = run_elk(_graph())

    kids = {c["id"]: c for c in out["children"]}
    assert set(kids) == {"a", "b"}
    for c in kids.values():
        assert isinstance(c["x"], (int, float))
        assert isinstance(c["y"], (int, float))
    # DOWN means b sits below a
    assert kids["b"]["y"] > kids["a"]["y"]
    assert out["width"] > 0 and out["height"] > 0

    sections = out["edges"][0]["sections"]
    assert sections
    assert "startPoint" in sections[0] and "endPoint" in sections[0]


def test_run_elk_raises_elk_unavailable_on_a_malformed_graph():
    with pytest.raises(ElkUnavailable):
        run_elk({"id": "root", "children": [{"id": "a"}],
                 "edges": [{"id": "e0", "sources": ["ghost"], "targets": ["a"]}]})
