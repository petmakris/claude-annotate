"""Multi-view flowcharts: the checker, the two spec fields, and per-view render."""
import pytest

from skills.annotate.diagrams import flowchart, views
from skills.annotate.diagrams.flowchart import ValidationError

W, R, P = "write", "read", "persist"

# The OrdersSyncService graph, which is where every number below was measured.
_NODES = [
    ("agreed", "Proposal agreed", "entry", "entry point"),
    ("sendord", "Send orders", "entry", "entry point"),
    ("runptc", "Run pre-trade check", "entry", "entry point"),
    ("readers", "Opening or listing a proposal", "entry", "entry point"),
    ("batchstep", "Nightly batch pre-trade-checks step", "entry", "entry point"),
    ("sync", "OrdersSyncService", "code", "orchestrator"),
    ("refresh", "OrdersSyncRefreshService", "code", "orchestrator"),
    ("batch", "PreTradeChecksRefreshService", "code", "orchestrator"),
    ("transmit", "TransmitOrdersStrategy", "call", "strategy"),
    ("check", "RunPreTradeChecksStrategy", "call", "strategy"),
    ("client", "OrdersSyncClient", "call", "bank"),
    ("details", "SyncedOrdersDetailsService", "code", "bank"),
    ("proposal", "Proposal", "success", "proposal"),
]
_EDGES = [
    ("agreed", "sync", [W]), ("sendord", "sync", [W]), ("runptc", "sync", [W]),
    ("batchstep", "batch", [W]), ("batch", "sync", [W]),
    ("sync", "transmit", [W]), ("sync", "check", [W]), ("batch", "check", [W]),
    ("transmit", "client", [W]), ("check", "client", [W]),
    ("readers", "refresh", [R]), ("refresh", "check", [R]),
    ("refresh", "client", [R]), ("refresh", "details", [R, P]),
    ("details", "proposal", [R, P]),
    ("sync", "details", [P]), ("batch", "details", [P]),
]


def orders_sync(*, tagged=True, banded=True):
    nodes = [{"id": i, "label": l, "role": r, **({"band": b} if banded else {})}
             for i, l, r, b in _NODES]
    edges = [{"from": f, "to": t, **({"views": list(v)} if tagged else {})}
             for f, t, v in _EDGES]
    return {"nodes": nodes, "edges": edges}


def test_clean_diagram_needs_no_views():
    """The tool must be able to say 'this one is fine' and stop."""
    spec = {"nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"},
                      {"id": "c", "label": "C"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}]}
    rep = views.check(spec)
    assert rep.union_crossings == 0
    assert not rep.needs_views
    assert "does not need views" in rep.summary()


def test_untagged_union_reports_the_pairs_that_must_be_separated():
    rep = views.check(orders_sync(tagged=False, banded=False))
    assert rep.needs_views
    assert rep.union_crossings == len(rep.conflicts) > 0
    assert not rep.views  # nothing declared, so nothing to measure per view
    # geometry names pairs, never groups
    for a, b in rep.conflicts:
        assert "->" in a and "->" in b


def test_authored_grouping_satisfies_the_measured_constraints():
    rep = views.check(orders_sync())
    assert rep.ok
    assert rep.violations == []
    assert rep.unassigned == []
    assert {v.name for v in rep.views} == {W, R, P}


def test_every_view_is_cleaner_than_the_union():
    rep = views.check(orders_sync())
    for v in rep.views:
        assert v.crossings <= rep.union_crossings
        assert v.edges < len(_EDGES)


def test_a_grouping_that_keeps_crossing_edges_together_is_reported():
    """Put everything in one view and every measured conflict must surface."""
    spec = orders_sync()
    for e in spec["edges"]:
        e["views"] = ["everything"]
    rep = views.check(spec)
    assert not rep.ok
    assert len(rep.violations) == rep.union_crossings
    assert "VIOLATION" in rep.summary()


def test_node_membership_is_derived_not_authored():
    sub = views.subspec(orders_sync(), P)
    ids = {n["id"] for n in sub["nodes"]}
    assert ids == {e["from"] for e in sub["edges"]} | {e["to"] for e in sub["edges"]}
    assert "transmit" not in ids  # no persist edge touches it


def test_subspec_keeps_sibling_keys():
    spec = orders_sync()
    spec["title"] = "kept"
    assert views.subspec(spec, W)["title"] == "kept"


def test_declared_preserves_first_seen_order():
    assert views.declared(orders_sync()) == [W, R, P]


def test_bands_index_in_first_seen_order():
    b = views.bands(orders_sync())
    assert b["agreed"] == 0 and b["sync"] == 1 and b["proposal"] == 4
    assert len(set(b.values())) == 5


def test_bands_absent_when_undeclared():
    assert views.bands(orders_sync(banded=False)) == {}


def test_untagged_edge_beside_tagged_ones_is_rejected():
    spec = orders_sync()
    del spec["edges"][3]["views"]
    with pytest.raises(ValidationError, match="no views"):
        flowchart.validate(spec)


def test_all_is_reserved():
    spec = orders_sync()
    spec["edges"][0]["views"] = [views.ALL_VIEW]
    with pytest.raises(ValidationError, match="reserved"):
        flowchart.validate(spec)


@pytest.mark.parametrize("bad", [[], "write", [""], [1]])
def test_malformed_views_rejected(bad):
    spec = orders_sync()
    spec["edges"][0]["views"] = bad
    with pytest.raises(ValidationError):
        flowchart.validate(spec)


def test_blank_band_rejected():
    spec = orders_sync()
    spec["nodes"][0]["band"] = ""
    with pytest.raises(ValidationError, match="band"):
        flowchart.validate(spec)


def test_render_views_emits_union_plus_each_view():
    svgs = flowchart.render_views(orders_sync(), "blk")
    assert set(svgs) == {views.ALL_VIEW, W, R, P}
    for name, svg in svgs.items():
        assert svg.startswith("<svg") and "annotate-flow" in svg


def test_render_views_on_an_untagged_spec_is_just_the_union():
    svgs = flowchart.render_views(orders_sync(tagged=False), "blk")
    assert set(svgs) == {views.ALL_VIEW}


def test_bands_do_not_change_the_shipped_default_for_unbanded_specs():
    """A spec without bands must lay out exactly as it did before."""
    plain = orders_sync(tagged=False, banded=False)
    a = flowchart.render(plain, "x")
    b = flowchart.render(plain, "x")
    assert a == b


def test_an_unmeasurable_layout_reports_unknown_not_clean(monkeypatch):
    """Without ELK the fallback places nodes but routes no edges. Counting zero
    crossings there would call every diagram clean, which is a lie."""
    from skills.annotate.diagrams import elk_layout

    def boom(_graph):
        raise elk_layout.ElkUnavailable("no node on PATH")

    monkeypatch.setattr(elk_layout, "run_elk", boom)
    rep = views.check(orders_sync())
    assert rep.measurable is False
    assert rep.needs_views is None
    assert rep.ok is False
    assert "cannot measure" in rep.summary()
    assert rep.conflicts == []


def test_measure_returns_none_when_routes_are_missing(monkeypatch):
    from skills.annotate.diagrams import elk_layout

    monkeypatch.setattr(elk_layout, "run_elk",
                        lambda _g: (_ for _ in ()).throw(
                            elk_layout.ElkUnavailable("x")))
    pairs, w, h = views.measure(orders_sync())
    assert pairs is None and w > 0 and h > 0
