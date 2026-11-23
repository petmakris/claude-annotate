"""Sequence-spec validator tests."""
import pytest

from skills._shared.visuals.sequence import ValidationError, validate


def _minimal_spec():
    return {
        "actors": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "steps": [{"id": "s1", "from": "a", "to": "b", "arrow": "request", "label": "hi"}],
    }


def test_validate_minimal_spec_ok():
    validate(_minimal_spec())  # no raise


def test_validate_requires_two_actors():
    spec = _minimal_spec()
    spec["actors"] = [{"id": "a", "label": "A"}]
    with pytest.raises(ValidationError, match="actors"):
        validate(spec)


def test_validate_requires_at_least_one_step():
    spec = _minimal_spec()
    spec["steps"] = []
    with pytest.raises(ValidationError, match="step"):
        validate(spec)


def test_validate_unknown_from_actor():
    spec = _minimal_spec()
    spec["steps"][0]["from"] = "ghost"
    with pytest.raises(ValidationError, match="from"):
        validate(spec)


def test_validate_unknown_to_actor():
    spec = _minimal_spec()
    spec["steps"][0]["to"] = "ghost"
    with pytest.raises(ValidationError, match="to"):
        validate(spec)


def test_validate_self_arrow_requires_same_actor():
    spec = _minimal_spec()
    spec["steps"][0] = {"id": "s1", "from": "a", "to": "b", "arrow": "self", "label": "x"}
    with pytest.raises(ValidationError, match="self"):
        validate(spec)


def test_validate_self_arrow_with_same_actor_ok():
    spec = _minimal_spec()
    spec["steps"][0] = {"id": "s1", "from": "a", "to": "a", "arrow": "self", "label": "loop"}
    validate(spec)


def test_validate_unknown_arrow_type():
    spec = _minimal_spec()
    spec["steps"][0]["arrow"] = "magic"
    with pytest.raises(ValidationError, match="arrow"):
        validate(spec)


def test_validate_duplicate_step_ids():
    spec = _minimal_spec()
    spec["steps"].append(
        {"id": "s1", "from": "b", "to": "a", "arrow": "request", "label": "dup"}
    )
    with pytest.raises(ValidationError, match="duplicate"):
        validate(spec)


def test_validate_phase_start_at_unknown_step():
    spec = _minimal_spec()
    spec["phases"] = [{"id": "p1", "label": "P", "start_at": "s99"}]
    with pytest.raises(ValidationError, match="start_at"):
        validate(spec)


def test_validate_phase_order_must_follow_step_order():
    spec = _minimal_spec()
    spec["steps"].append({"id": "s2", "from": "b", "to": "a", "arrow": "request", "label": "y"})
    spec["phases"] = [
        {"id": "p1", "label": "P1", "start_at": "s2"},
        {"id": "p2", "label": "P2", "start_at": "s1"},  # out of order
    ]
    with pytest.raises(ValidationError, match="phase.*order"):
        validate(spec)


def test_validate_phases_optional():
    spec = _minimal_spec()
    # No "phases" key — should still validate.
    validate(spec)


def test_validate_requires_actor_label():
    """An actor without a label is refused as a ValidationError, never a bare KeyError."""
    spec = _minimal_spec()
    del spec["actors"][0]["label"]
    with pytest.raises(ValidationError, match="label"):
        validate(spec)


def test_validate_requires_phase_label():
    spec = _minimal_spec()
    spec["phases"] = [{"id": "p1", "start_at": "s1"}]
    with pytest.raises(ValidationError, match="label"):
        validate(spec)


# -- replies, boxes and refs: drawn by the stage, checked here for annotate and the stage alike ------------

def _turn():
    return {"actors": [{"id": "p", "label": "Page"}, {"id": "s", "label": "Server"}, {"id": "a", "label": "Azure"}],
            "phases": [{"id": "p1", "label": "Hear", "start_at": "s1"}, {"id": "p2", "label": "Answer", "start_at": "s6"}],
            "groups": [{"id": "g1", "kind": "alt", "branches": ["an echo", "otherwise"]},
                       {"id": "g2", "kind": "loop", "label": "until a turn arrives"}],
            "steps": [{"id": "s1", "from": "p", "to": "s", "arrow": "request", "label": "sends", "ref": "talk.py:2213"},
                      {"id": "s2", "from": "s", "to": "a", "arrow": "request", "label": "transcribes"},
                      {"id": "s3", "from": "a", "to": "s", "arrow": "event", "label": "words", "reply_to": "s2"},
                      {"id": "s4", "from": "s", "to": "s", "arrow": "self", "label": "drops it", "group": "g1", "branch": 0},
                      {"id": "s5", "from": "s", "to": "s", "arrow": "self", "label": "queues it", "group": "g1", "branch": "1"},
                      {"id": "s6", "from": "s", "to": "p", "arrow": "event", "label": "heard", "reply_to": "s1", "group": "g2"},
                      {"id": "s7", "from": "p", "to": "p", "arrow": "self", "label": "plays"}]}


def test_validate_replies_boxes_and_refs_ok():
    validate(_turn())  # no raise


def _with(edit):
    spec = _turn()
    edit(spec)
    return spec


def _step(spec, sid):
    return next(s for s in spec["steps"] if s["id"] == sid)


@pytest.mark.parametrize("edit, match", [
    (lambda s: _step(s, "s3").update(reply_to="s9"), "not an earlier step"),
    (lambda s: _step(s, "s3").update(reply_to="s4"), "not an earlier step"),
    (lambda s: _step(s, "s3").update(reply_to="s3"), "not an earlier step"),
    (lambda s: _step(s, "s6").update(reply_to="s2"), "goes back from 'a' to 's'"),
    (lambda s: _step(s, "s6").update(reply_to="s3"), "joins an event to the request"),
    (lambda s: s["steps"].insert(3, {"id": "s3b", "from": "a", "to": "s", "arrow": "event", "label": "again", "reply_to": "s2"}),
     "already answered"),
    (lambda s: _step(s, "s1").update(ref="talk.py"), "not path:line"),
    (lambda s: _step(s, "s1").update(ref="talk.py:0"), "not path:line"),
    (lambda s: s["groups"][0].pop("branches"), "alt needs branches"),
    (lambda s: s["groups"][0].update(branches=["only one"]), "alt needs branches"),
    (lambda s: s["groups"][1].pop("label"), "loop needs a label"),
    (lambda s: s["groups"][1].update(kind="while"), "kind must be one of"),
    (lambda s: s["groups"].append({"id": "g1", "kind": "opt", "label": "x"}), "duplicate"),
    (lambda s: _step(s, "s7").update(group="g9"), "unknown group"),
    (lambda s: _step(s, "s7").update(group="g1", branch=1), "must follow one another"),
    (lambda s: _step(s, "s4").update(branch=1), "come in order, from 0"),
    (lambda s: _step(s, "s5").update(branch=0), "every branch needs a step"),
    (lambda s: _step(s, "s5").update(branch=2), "from 0 to 1"),
    (lambda s: _step(s, "s6").update(branch=0), "a loop has no branches"),
    (lambda s: _step(s, "s7").update(branch=0), "in no group"),
    (lambda s: s["groups"].append({"id": "g3", "kind": "opt", "label": "never"}), "holds no step"),
    (lambda s: s["phases"][1].update(start_at="s5"), "starts inside group 'g1'"),
])
def test_validate_refuses_a_bad_reply_box_or_ref(edit, match):
    with pytest.raises(ValidationError, match=match):
        validate(_with(edit))
