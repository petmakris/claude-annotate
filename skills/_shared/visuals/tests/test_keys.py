"""With keyed=True, every part the eye can land on carries a data-key the stage's frame engine reads."""
import html
import re

from skills._shared.visuals import flowchart, sequence

SEQ = {"actors": [{"id": "p", "label": "Page"}, {"id": "s", "label": "Server\nmain"}],
       "phases": [{"id": "ph", "label": "Send", "start_at": "s1"}],
       "steps": [{"id": "s0", "from": "p", "to": "s", "arrow": "band", "label": "auth"},
                 {"id": "s1", "from": "p", "to": "s", "arrow": "request", "label": "POST", "note": "4ms"},
                 {"id": "s-2.x", "from": "s", "to": "s", "arrow": "self", "label": "store"}]}
FLOW = {"nodes": [{"id": "a", "role": "entry", "label": "Start"}, {"id": "b", "role": "decision", "label": "ok?"},
                  {"id": "c", "role": "success", "label": "Done"}],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c", "label": "yes"}, {"from": "a", "to": "c"}]}


def keys(markup):
    return [html.unescape(k) for k in re.findall(r'data-key="([^"]+)"', markup)]


def test_a_keyed_sequence_names_its_actors_steps_and_phase_labels():
    found = keys(sequence.render(SEQ, "b", keyed=True))
    assert found.count("actor:p") == 1 and found.count("actor:s") == 1
    assert [k for k in found if k.startswith("step:")] == ["step:s1", "step:s0", "step:s1", "step:s-2.x"]


def test_a_keyed_sequence_key_names_each_row_and_its_phase():
    assert keys(sequence.render_key(SEQ, "b", keyed=True)) == ["step:s1", "step:s1", "step:s-2.x"]


def test_a_keyed_flowchart_names_its_nodes_edges_and_edge_labels():
    found = keys(flowchart.render(FLOW, "b", keyed=True))
    assert sorted(k for k in set(found) if k.startswith("node:")) == ["node:a", "node:b", "node:c"]
    assert found.count("edge:a->b#0") == 1 and found.count("edge:a->c#0") == 1
    assert found.count("edge:b->c#0") == 2


def test_unkeyed_output_has_no_keys():
    assert "data-key" not in sequence.render(SEQ, "b") + sequence.render_key(SEQ, "b") + flowchart.render(FLOW, "b")
