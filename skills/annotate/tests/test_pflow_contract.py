"""What pflow emits must satisfy the flowchart block's own contract.

These assert against the real validator and renderer rather than a copy of their
rules, so a change to either side breaks here instead of in a user's browser.
"""
import pytest

from skills.annotate.diagrams.flowchart import _KNOWN_ROLES, validate, render
from skills.annotate.pflow import compile_source

BRANCHY = '''"""A flow with every shape in it."""


def flow(request):  # ! request R
    if not allowed():  # ? allowed?
        raise Refuse(exit=3)  # gate: needs confirmation
    found = look_up()  # cache: the corpus
    if covered(found):  # ? covered?
        return Direct()
    if partial(found):  # ? partially covered?
        stitch()  # note: topological
    else:
        widen()
    return Assembled()
'''

CONVERGING = '''"""Two branches rejoining."""


def flow(r):
    if a():  # ? a?
        left()
    else:
        right()
    return Done()
'''


@pytest.fixture(params=[BRANCHY, CONVERGING], ids=["branchy", "converging"])
def spec(request):
    out = compile_source(request.param)
    return {k: v for k, v in out.items() if k != "warnings"}


def test_output_passes_the_validator(spec):
    validate(spec)                                   # no raise


def test_every_node_becomes_a_comment_hit_target(spec):
    svg = render(spec, block_id="section-1")
    assert svg.count("data-node-id") == len(spec["nodes"])
    for node in spec["nodes"]:
        assert f'data-node-id="{node["id"]}"' in svg


def test_only_roles_the_renderer_knows_are_emitted(spec):
    assert {n["role"] for n in spec["nodes"]} <= _KNOWN_ROLES


def test_node_lines_are_unique_so_caret_and_node_map_one_to_one(spec):
    lines = [n["line"] for n in spec["nodes"]]
    assert len(set(lines)) == len(lines)


def test_converging_branches_produce_a_join_not_a_cycle():
    spec = compile_source(CONVERGING)
    edges = {(e["from"], e["to"]) for e in spec["edges"]}
    assert ("left", "done") in edges and ("right", "done") in edges
    validate({k: v for k, v in spec.items() if k != "warnings"})   # still a DAG
