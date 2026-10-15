"""With keyed=True, every part the eye can land on carries a data-key the stage's frame engine reads."""
import html
import re

from skills._shared.visuals import flowchart

FLOW = {"nodes": [{"id": "a", "role": "entry", "label": "Start"}, {"id": "b", "role": "decision", "label": "ok?"},
                  {"id": "c", "role": "success", "label": "Done"}],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "yes"}, {"from": "a", "to": "c"}]}


def keys(markup):
    return [html.unescape(k) for k in re.findall(r'data-key="([^"]+)"', markup)]


def test_a_keyed_flowchart_names_its_nodes_edges_and_edge_labels():
    found = keys(flowchart.render(FLOW, "b", keyed=True))
    assert sorted(k for k in set(found) if k.startswith("node:")) == ["node:a", "node:b", "node:c"]
    assert found.count("edge:a->b#0") == 1 and found.count("edge:a->c#0") == 1
    assert found.count("edge:b->c#0") == 2


def test_unkeyed_output_has_no_keys():
    assert "data-key" not in flowchart.render(FLOW, "b")
