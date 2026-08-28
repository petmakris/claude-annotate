"""dataflow.json validation.

The document is the contract between Claude and the page, so the rules that
keep the page usable — an anchor on every node, globally unique ids, edges that
point somewhere — are enforced here rather than trusted to the generator.
"""
from __future__ import annotations

import json

import pytest

from skills.dataflow import flow


def _node(**over):
    n = {"id": "ctl", "layer": "api", "role": "Controller", "name": "OrderController",
         "file": "src/main/java/Order.java", "line": 12}
    n.update(over)
    return n


def _doc(**over):
    d = {
        "seed": "Order", "question": "how does an order reach the database",
        "generated_ts": 1_700_000_000,
        "model": ["Orders are stored as rows, the policy as a blob."],
        "slices": [{"id": "main", "title": "Placing an order", "nodes": [
            _node(),
            _node(id="tbl", layer="db", role="Table", name="orders",
                  file="db/changelog-1.xml", line=7),
        ]}],
    }
    d.update(over)
    return d


def test_a_well_formed_document_validates():
    assert flow.validate(_doc()) == []


@pytest.mark.parametrize("field", ["seed", "question"])
def test_required_strings(field):
    assert any(field in e for e in flow.validate(_doc(**{field: "  "})))


def test_generated_ts_must_be_positive():
    assert any("generated_ts" in e for e in flow.validate(_doc(generated_ts=0)))


def test_node_ids_are_unique_across_the_whole_document():
    # Per-slice uniqueness is not enough: the thread anchor is node:<id>, so
    # two nodes sharing an id would share one thread.
    doc = _doc()
    doc["slices"].append({"id": "other", "title": "Other", "nodes": [
        _node(), _node(id="x", layer="db", role="Table", name="t",
                       file="db/c.xml", line=1)]})
    assert any("duplicate node id" in e for e in flow.validate(doc))


def test_every_node_needs_a_file_and_a_line():
    # A node without an anchor cannot be opened, which is the page's only route
    # into the code.
    doc = _doc()
    doc["slices"][0]["nodes"][0].pop("line")
    assert any("line must be a positive integer" in e for e in flow.validate(doc))
    doc = _doc()
    doc["slices"][0]["nodes"][0]["file"] = "/absolute/Order.java"
    assert any("project-relative" in e for e in flow.validate(doc))
    doc = _doc()
    doc["slices"][0]["nodes"][0]["file"] = "src/../../etc/passwd"
    assert any("dot path segments" in e for e in flow.validate(doc))


def test_layer_must_be_known():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["layer"] = "persistence"
    assert any("layer must be one of" in e for e in flow.validate(doc))


def test_implicit_is_only_meaningful_on_a_mapper():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["implicit"] = True
    assert any("implicit is only meaningful" in e for e in flow.validate(doc))
    doc = _doc()
    doc["slices"][0]["nodes"][0].update(layer="mapper", implicit=True)
    assert flow.validate(doc) == []


def test_edges_must_point_at_a_node_that_exists():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["edges"] = [{"to": "ghost", "label": "calls"}]
    assert any("unknown node 'ghost'" in e for e in flow.validate(doc))


def test_an_edge_may_not_point_at_its_own_node():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["edges"] = [{"to": "ctl", "label": "calls"}]
    assert any("its own node" in e for e in flow.validate(doc))


def test_edges_across_slices_are_allowed_and_may_be_joins():
    doc = _doc()
    doc["slices"].append({"id": "use", "title": "Using it", "nodes": [
        _node(id="usr", name="UserService", layer="application", role="Service"),
        _node(id="ut", layer="db", role="Table", name="u", file="db/c2.xml", line=3)]})
    doc["slices"][0]["nodes"][0]["edges"] = [{"to": "usr", "label": "read by", "join": True}]
    assert flow.validate(doc) == []


def test_member_line_may_be_absent_but_not_negative():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["members"] = [{"text": "one method"}]
    assert flow.validate(doc) == []
    doc["slices"][0]["nodes"][0]["members"] = [{"text": "bad", "line": -1}]
    assert any("non-negative integer" in e for e in flow.validate(doc))


def test_slice_and_node_counts_are_bounded():
    doc = _doc()
    doc["slices"][0]["nodes"] = [_node()]
    assert any("nodes" in e for e in flow.validate(doc))
    doc = _doc()
    doc["slices"][0]["nodes"] = [
        _node(id=f"n{i}") for i in range(flow.MAX_NODES + 1)]
    assert any(f"{flow.MIN_NODES}-{flow.MAX_NODES} nodes" in e
               for e in flow.validate(doc))


def test_model_claims_are_capped_and_non_empty():
    assert any("model[0]" in e for e in flow.validate(_doc(model=[" "])))
    assert any("at most" in e for e in
               flow.validate(_doc(model=["x"] * (flow.MAX_MODEL_CLAIMS + 1))))
    assert flow.validate(_doc(model=None)) == []


def test_write_and_load_round_trip(tmp_path):
    flow.write_flow(tmp_path, _doc())
    loaded = flow.load_flow(tmp_path)
    assert loaded["seed"] == "Order"
    assert flow.generated_ts(tmp_path) == 1_700_000_000
    assert flow.count_nodes(loaded) == 2
    assert flow.node_ids(loaded) == {"ctl", "tbl"}


def test_write_refuses_an_invalid_document(tmp_path):
    with pytest.raises(ValueError) as exc:
        flow.write_flow(tmp_path, _doc(seed=""))
    assert "seed" in str(exc.value)
    assert not (tmp_path / flow.FLOW_FILE).exists()


def test_load_survives_a_corrupt_file(tmp_path):
    (tmp_path / flow.FLOW_FILE).write_text("{not json")
    assert flow.load_flow(tmp_path) is None
    assert flow.generated_ts(tmp_path) == 0


def test_anchor_round_trip():
    assert flow.node_anchor("icm") == "node:icm"
    assert flow.valid_anchor("node:icm")
    assert flow.anchor_node_id("node:icm") == "icm"
    for bad in ("icm", "node:", "node:Icm", "node:../x", "step:1", None):
        assert not flow.valid_anchor(bad)


def test_written_document_is_indented_json(tmp_path):
    flow.write_flow(tmp_path, _doc())
    raw = (tmp_path / flow.FLOW_FILE).read_text()
    assert raw.startswith("{\n")
    json.loads(raw)
