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


def _blk_multi():
    return {"id": "section-1", "kind": "flowchart", "spec": {
        "title": "guard",
        "nodes": [
            {"id": "a", "role": "entry", "label": "User SAVES"},
            {"id": "b", "role": "code", "ref": "OrderService:154",
             "method": "validateAttachmentsSelection(items)"},
            {"id": "f", "role": "decision", "label": "toggle ON?"},
            {"id": "g", "role": "success", "label": "allow", "sub": "no check"},
            {"id": "h", "role": "error", "label": "throw",
             "method": "MissingAttachmentsException"},
        ],
        "edges": [
            {"from": "a", "to": "b"},
            {"from": "b", "to": "f"},
            {"from": "f", "to": "g", "label": "OFF"},
            {"from": "f", "to": "h", "label": "ON + doc missing"},
        ],
    }}


def test_flowchart_block_ships_one_rendering_and_no_variant_keys():
    # HOUSE_SET holds one entry, so render_flowchart_variants can only ever
    # return a single name — render.py's `len(names) > 1` guard means a block
    # never carries `svgs`/`flavours` any more, only the plain `svg` every
    # client already reads.
    out = render_block(_blk_multi())
    assert out["svg"].startswith("<svg")
    assert "svgs" not in out
    assert "flavours" not in out


def test_flowchart_error_pill_carries_no_variants():
    blk = _blk_multi()
    blk["spec"]["edges"] = [{"from": "a", "to": "ghost"}]
    out = render_block(blk)
    assert "render failed" in out["svg"]
    assert "svgs" not in out
    assert "flavours" not in out
