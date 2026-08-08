"""A flowchart block authored as `source`: compiled on render, never hand-edited."""
from skills.annotate.server import _render_block_for_raw

SRC = '''"""How it goes."""


def flow(request):  # ! request R
    check()  # cache: the corpus
    if ready():  # ? ready?
        return Done()
    raise Stop()
'''


def _blk(source=SRC, **spec):
    return {"id": "section-1", "kind": "flowchart", "spec": dict(source=source, **spec)}


def _hand_written():
    return {"id": "section-1", "kind": "flowchart", "spec": {
        "nodes": [
            {"id": "a", "role": "entry", "label": "start"},
            {"id": "b", "role": "code", "ref": "F:1", "method": "m()"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }}


def test_source_compiles_to_nodes_and_edges():
    out = _render_block_for_raw(_blk(), version=1)
    ids = [n["id"] for n in out["spec"]["nodes"]]
    assert ids == ["request-r", "check", "ready", "done", "stop"]
    assert {"from": "ready", "to": "done", "label": "yes"} in out["spec"]["edges"]


def test_source_renders_an_svg_with_a_hit_target_per_node():
    out = _render_block_for_raw(_blk(), version=1)
    assert out["svg"].startswith("<svg")
    assert out["svg"].count("data-node-id") == len(out["spec"]["nodes"])


def test_the_source_survives_into_the_response():
    # the client needs it to draw the editor pane; without it there is nothing to edit
    out = _render_block_for_raw(_blk(), version=1)
    assert out["spec"]["source"] == SRC


def test_each_compiled_node_carries_its_source_line():
    out = _render_block_for_raw(_blk(), version=1)
    by_id = {n["id"]: n["line"] for n in out["spec"]["nodes"]}
    assert by_id["request-r"] == 4
    assert by_id["check"] == 5
    assert by_id["ready"] == 6


def test_the_title_comes_from_the_docstring():
    assert _render_block_for_raw(_blk(), version=1)["spec"]["title"] == "How it goes."


def test_source_wins_over_hand_written_nodes():
    # the contract says do not write both; if someone does, the editable one is the truth
    blk = _blk(nodes=[{"id": "stale", "role": "entry", "label": "old"}], edges=[])
    out = _render_block_for_raw(blk, version=1)
    assert "stale" not in [n["id"] for n in out["spec"]["nodes"]]


LOOPS = '''"""t."""


def flow(r):
    check()
    for x in xs:
        go()
'''


def test_a_refused_source_yields_an_error_pill_naming_the_line():
    out = _render_block_for_raw(_blk(source=LOOPS), version=1)
    assert "annotate-flow" in out["svg"]
    assert "render failed" in out["svg"]
    assert ":6:" in out["svg"]            # the line the `for` sits on
    assert "DAG" in out["svg"]


def test_an_unreachable_statement_is_refused_through_the_server_too():
    out = _render_block_for_raw(_blk(source=SRC + "    after()\n"), version=1)
    assert "unreachable" in out["svg"]
    assert ":9:" in out["svg"]


def test_a_refused_source_does_not_crash_the_block():
    out = _render_block_for_raw(_blk(source="def broken(:\n"), version=1)
    assert out["kind"] == "flowchart"
    assert out["svg"].startswith("<svg")


def test_the_node_budget_warning_is_surfaced():
    body = "".join("    step_%d()\n" % i for i in range(20))
    out = _render_block_for_raw(_blk(source='"""t."""\n\n\ndef f(r):\n' + body), version=1)
    assert out["warnings"] and "15" in out["warnings"][0]


def test_a_small_flow_reports_no_warnings():
    assert _render_block_for_raw(_blk(), version=1).get("warnings") in (None, [])


def test_hand_written_flowcharts_are_untouched():
    out = _render_block_for_raw(_hand_written(), version=1)
    assert [n["id"] for n in out["spec"]["nodes"]] == ["a", "b"]
    assert "source" not in out["spec"]
    assert out["svg"].startswith("<svg")
