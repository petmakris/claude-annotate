"""A before/after sequence (compare.py): how its two sides line up row by row, its checks, and the scene keys that
let the voice point at a side. The lanes' own behaviour is in test_stage_page.py."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from skills.stage import model, scene

UI, SVC, RC = ({"id": "ui", "label": "Proposal report"}, {"id": "svc", "label": "Report service", "sub": "ServiceBacktestingService"},
               {"id": "rc", "label": "Service"})
CLIENT = {"id": "cl", "label": "Service client", "role": "PMP's module", "sub": "RealizedMeasuresFacadeClient"}
SHARED = {"id": "sm", "label": "Shared backtesting module", "role": "PMP and PSIM"}


def step(sid, a, b, label, arrow=None, **kw):
    return {"id": sid, "from": a, "to": b, "arrow": arrow or ("self" if a == b else "request"), "label": label, **kw}


# the example, the proposal report's backtesting request: on master the report service calls the Service client in
# PMP's module, which builds the requests with fixed lists and returns ready-made timeseries; with the PR a shared
# module takes its place, is given quarterly and the measure lists, returns raw values, and the report service
# builds the timeseries itself. The Service requests are the same on both sides.
SPEC = {"title": "Backtesting request", "compare": {
    "before": {"label": "master", "actors": [UI, SVC, CLIENT, RC], "steps": [
        step("b1", "ui", "svc", "asks for the backtest"),
        step("b2", "svc", "cl", "asks for the backtest data", sub="fetch(proposal)"),
        step("b3", "cl", "cl", "builds the requests with fixed lists, always quarterly"),
        step("b4", "cl", "rc", "asks for the ex-post measures"),
        step("b5", "cl", "rc", "asks for the backtest series"),
        step("b6", "cl", "svc", "returns report timeseries", "event", reply_to="b2"),
        step("b7", "svc", "ui", "returns the timeseries", "event", reply_to="b1")]},
    "after": {"label": "with the PR", "actors": [UI, SVC, SHARED, RC], "steps": [
        step("b1", "ui", "svc", "asks for the backtest"),
        step("b2", "svc", "sm", "asks for the backtest data", sub="fetch(proposal, QUARTERLY, measures)"),
        step("b3", "sm", "sm", "builds the requests with the lists it is given"),
        step("b4", "sm", "rc", "asks for the ex-post measures"),
        step("b5", "sm", "rc", "asks for the backtest series"),
        step("b6", "sm", "svc", "returns raw values", "event", reply_to="b2"),
        step("c1", "svc", "svc", "builds the report timeseries", sub="ReportBacktestTimeseries"),
        step("b7", "svc", "ui", "returns the timeseries", "event", reply_to="b1")]}}}


def flat(spec=SPEC):
    return model.visual_source("sequence", json.dumps(spec))["spec"]


def rows(spec=SPEC):
    """Each row as (its key, its change, the before step's id or None for a gap, the after step's id or None)."""
    return [(s["id"], s["change"], (s.get("before") or {}).get("id"), (s.get("after") or {}).get("id")) for s in flat(spec)["steps"]]


def test_the_two_flows_line_up_row_by_row_with_a_gap_where_a_side_has_no_step():
    assert rows() == [
        ("b1", "same", "b1", "b1"),
        ("b2", "changed", "b2", "b2"),
        ("b3", "changed", "b3", "b3"),
        ("b4", "same", "b4", "b4"),      # the same request, sent by the module that replaced the client
        ("b5", "same", "b5", "b5"),
        ("b6", "changed", "b6", "b6"),
        ("c1", "added", None, "c1"),     # the report service builds the timeseries itself: a gap on the left
        ("b7", "same", "b7", "b7")]


def test_each_side_keeps_its_own_actors_steps_and_replies_and_each_step_knows_its_row():
    got = flat()
    assert got["compare"]["before"]["label"] == "master" and got["compare"]["after"]["label"] == "with the PR"
    assert [(a["id"], a["change"]) for a in got["compare"]["before"]["actors"]] == [
        ("ui", "same"), ("svc", "same"), ("cl", "removed"), ("rc", "same")]
    assert [(a["id"], a["change"]) for a in got["compare"]["after"]["actors"]] == [
        ("ui", "same"), ("svc", "same"), ("sm", "added"), ("rc", "same")]
    b6 = got["steps"][5]
    assert (b6["before"]["from"], b6["before"]["reply_to"], b6["before"]["row"]) == ("cl", "b2", "b6")
    assert (b6["after"]["from"], b6["after"]["reply_to"], b6["after"]["row"]) == ("sm", "b2", "b6")
    assert [a["id"] for a in got["actors"]] == ["ui", "svc", "cl", "sm", "rc"]   # every actor is a key of the scene


def test_a_changed_step_marks_the_words_that_differ_on_each_side():
    got = {s["id"]: s for s in flat()["steps"]}
    assert got["b2"]["before"]["marks"] == {"sub": [["fetch(proposal)", False]]}
    assert got["b2"]["after"]["marks"] == {"sub": [["fetch(proposal", False], [", QUARTERLY, measures", True], [")", False]]}
    assert got["b6"]["before"]["marks"] == {"label": [["returns ", False], ["report timeseries", True]]}
    assert got["b6"]["after"]["marks"] == {"label": [["returns ", False], ["raw values", True]]}
    assert "marks" not in got["b4"]["after"] and "marks" not in got["b1"]["before"]


def test_a_step_between_other_actors_that_are_on_both_sides_is_moved_and_stands_twice():
    spec = json.loads(json.dumps(SPEC))
    spec["compare"]["after"]["steps"][2].update({"from": "svc", "to": "svc"})   # b3 now runs on the report service
    got = rows(spec)
    assert ("was~b3", "moved", "b3", None) in got and ("b3", "moved", None, "b3") in got
    assert got.index(("was~b3", "moved", "b3", None)) == got.index(("b3", "moved", None, "b3")) - 1
    assert next(s for s in flat(spec)["steps"] if s["id"] == "b3")["replaces"] == "was~b3"


def test_a_step_that_changed_place_in_the_order_is_moved_and_each_side_keeps_its_own_order():
    spec = json.loads(json.dumps(SPEC))
    after = spec["compare"]["after"]["steps"]
    after[3], after[4] = after[4], after[3]   # the PR sends the backtest request before the ex-post one
    got = rows(spec)
    assert [r[2] for r in got if r[2]] == ["b1", "b2", "b3", "b4", "b5", "b6", "b7"]
    assert [r[3] for r in got if r[3]] == ["b1", "b2", "b3", "b5", "b4", "b6", "c1", "b7"]
    assert [r[1] for r in got].count("moved") == 2


def test_a_step_on_one_side_only_faces_a_gap_on_the_other():
    spec = json.loads(json.dumps(SPEC))
    del spec["compare"]["after"]["steps"][2]   # the PR no longer builds the requests in the middle
    assert ("b3", "removed", "b3", None) in rows(spec)


def test_steps_with_other_ids_and_the_same_words_are_matched_and_a_replaced_actor_keeps_them_one_row():
    spec = json.loads(json.dumps(SPEC))
    spec["compare"]["after"]["steps"][3]["id"] = "z4"
    assert rows(spec)[3] == ("z4", "same", "b4", "z4")


def test_a_spec_without_compare_is_read_exactly_as_before():
    plain = {"actors": [UI, SVC], "steps": [step("s1", "ui", "svc", "asks")]}
    assert flat(plain) == plain


@pytest.mark.parametrize("change,message", [
    (lambda s: s["compare"].pop("after"), 'compare needs "before" and "after"'),
    (lambda s: s["compare"].update(later={}), "compare: later not supported"),
    (lambda s: s.update(steps=[]), "compare does not take steps beside it"),
    (lambda s: s.update(outcome={"title": "x"}), "compare does not take outcome beside it"),
    (lambda s: s["compare"]["before"].update(phases=[]), "compare.before: phases not supported"),
    (lambda s: s["compare"]["after"].update(actors=[UI]), "compare.after: sequence requires at least 2 actors"),
    (lambda s: s["compare"]["before"]["steps"][0].update(to="nobody"), "compare.before: step b1: unknown to actor 'nobody'"),
    (lambda s: s["compare"].update(before="master"), "compare.before must be an object"),
])
def test_a_malformed_compare_spec_is_refused_with_the_side_and_the_reason(change, message):
    spec = json.loads(json.dumps(SPEC))
    change(spec)
    with pytest.raises(model.SourceError, match=message):
        model.visual_source("sequence", json.dumps(spec))


def test_a_compare_boards_scene_has_one_key_per_row_and_the_sides_as_keys():
    m = scene.sequence_model(flat())
    assert m.keys[-3:] == ["mode:both", "mode:before", "mode:after"]
    assert m.order == ["step:b1", "step:b2", "step:b3", "step:b4", "step:b5", "step:b6", "step:c1", "step:b7"]
    # a changed row is named by its old words as well as its new ones
    assert m.names["returns raw values"] == "step:b6" and m.alias["step:b6"] == ["returns report timeseries"]
    for word, key in (("before", "mode:before"), ("AFTER", "mode:after"), ("both", "mode:both"), ("merged", "mode:both")):
        assert scene.resolve(m, word, "T")[0] == [key]
    assert not any(k.startswith("mode:") for k in scene.sequence_model(
        {"actors": [UI, SVC], "steps": [step("s1", "ui", "svc", "asks")]}).keys)


def test_a_moved_steps_before_row_comes_in_with_its_after_row():
    spec = json.loads(json.dumps(SPEC))
    spec["compare"]["after"]["steps"][2].update({"from": "svc", "to": "svc"})
    m = scene.sequence_model(flat(spec))
    assert "step:was~b3" not in m.order and "step:was~b3" in m.up["step:b3"]


def test_each_sides_ref_reaches_the_popup_of_its_own_step(tmp_path):
    (tmp_path / "Old.java").write_text("a\nb\nc\n")
    (tmp_path / "New.java").write_text("x\ny\nz\n")
    spec = json.loads(json.dumps(SPEC))
    spec["compare"]["before"]["steps"][1]["ref"] = "Old.java:2"
    spec["compare"]["after"]["steps"][1]["ref"] = "New.java:3"
    refs = model.visual_source("sequence", json.dumps(spec), root=tmp_path)["refs"]
    assert (refs["b2"]["path"], refs["b2"]["at"]) == ("New.java", 3)
    assert (refs["before:b2"]["path"], refs["before:b2"]["at"]) == ("Old.java", 2)


def test_the_stage_serves_the_lined_up_spec(tmp_path):
    src = model.parse_source("sequence:-", Path("."), json.dumps(SPEC))
    assert src["spec"]["compare"]["before"]["label"] == "master" and len(src["spec"]["steps"]) == 8
