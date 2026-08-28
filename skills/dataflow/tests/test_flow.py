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


# ---------------------------------------------------------------- members
def test_a_member_may_carry_a_detail_and_a_tag():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["members"] = [
        {"text": "public ShareResultDto share(long id)", "line": 31,
         "tag": "POST", "detail": "Converts, then delegates."}]
    assert flow.validate(doc) == []


def test_a_blank_detail_is_refused():
    # An empty detail renders an expandable row that opens onto nothing.
    doc = _doc()
    doc["slices"][0]["nodes"][0]["members"] = [{"text": "m()", "detail": "  "}]
    assert any("detail" in e for e in flow.validate(doc))


def test_a_tag_is_a_badge_not_a_sentence():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["members"] = [
        {"text": "m()", "tag": "this is far too long to be a badge"}]
    assert any("badge" in e for e in flow.validate(doc))


def test_a_summary_that_lists_the_members_is_refused():
    # The layout exists to stop the node restating its own member list; length
    # is the mechanical proxy for "one line about the node".
    doc = _doc()
    doc["slices"][0]["nodes"][0]["summary"] = "x" * (flow.MAX_SUMMARY_LEN + 1)
    assert any("say what the node IS" in e for e in flow.validate(doc))
    doc["slices"][0]["nodes"][0]["summary"] = "The only HTTP way in or out."
    assert flow.validate(doc) == []


# ----------------------------------------------------------------- routes
def _routed():
    """A document with two field-carrying rows and a route over them."""
    doc = _doc()
    doc["slices"][0]["nodes"][0]["members"] = [
        {"text": "String code", "line": 12, "field": "code"}]
    doc["slices"][0]["nodes"][1]["members"] = [
        {"text": "code VARCHAR(255)", "line": 7, "field": "code"}]
    doc["routes"] = [{"id": "code", "label": "code", "title": "code → code",
                      "hops": [{"node": "ctl", "field": "code"},
                               {"node": "tbl", "field": "code",
                                "destination": True}]}]
    return doc


def test_a_route_over_field_carrying_rows_validates():
    assert flow.validate(_routed()) == []


def test_routes_are_optional():
    assert flow.validate(_doc()) == []


def test_a_hop_must_point_at_a_row_that_declares_that_field():
    # A hop that resolves to nothing highlights nothing, which reads as the
    # route being wrong about the code rather than about itself.
    doc = _routed()
    doc["routes"][0]["hops"][1]["field"] = "ghost"
    errors = flow.validate(doc)
    assert any("tbl.ghost" in e and "no member declares" in e for e in errors)


def test_a_hop_must_point_at_a_node_that_exists():
    doc = _routed()
    doc["routes"][0]["hops"][0]["node"] = "nowhere"
    assert any("nowhere.code" in e for e in flow.validate(doc))


def test_a_route_needs_more_than_one_hop():
    doc = _routed()
    doc["routes"][0]["hops"] = doc["routes"][0]["hops"][:1]
    assert any("not a path" in e for e in flow.validate(doc))


def test_route_ids_are_unique():
    doc = _routed()
    doc["routes"].append(dict(doc["routes"][0]))
    assert any("duplicate route id" in e for e in flow.validate(doc))


@pytest.mark.parametrize("flag", ["rename", "fork", "destination"])
def test_hop_flags_must_be_booleans(flag):
    doc = _routed()
    doc["routes"][0]["hops"][0][flag] = "yes"
    assert any(flag in e for e in flow.validate(doc))


def test_a_route_needs_a_label_and_a_title():
    doc = _routed()
    doc["routes"][0]["label"] = " "
    assert any("label" in e for e in flow.validate(doc))


def test_a_field_id_must_be_a_slug():
    doc = _doc()
    doc["slices"][0]["nodes"][0]["members"] = [{"text": "x", "field": "Not A Slug"}]
    assert any("field must match" in e for e in flow.validate(doc))
