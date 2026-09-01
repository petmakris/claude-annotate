from skills.annotate.render import render_block


def _blk():
    return {"id": "section-1", "kind": "flowchart", "spec": {
        "nodes": [
            {"id": "a", "role": "entry", "label": "start"},
            {"id": "b", "role": "code", "ref": "F:1", "method": "m()"},
        ],
        "edges": [{"from": "a", "to": "b"}],
    }}


def test_flowchart_block_renders_svg():
    out = render_block(_blk())
    assert out["kind"] == "flowchart"
    assert out["svg"].startswith("<svg")
    assert 'class="annotate-flow"' in out["svg"]
    assert out["spec"]["nodes"][0]["id"] == "a"


def test_flowchart_bad_spec_yields_error_pill_not_crash():
    blk = _blk()
    blk["spec"]["edges"] = [{"from": "a", "to": "ghost"}]  # dangling edge
    out = render_block(blk)
    assert "render failed" in out["svg"]
    assert "annotate-flow" in out["svg"]
