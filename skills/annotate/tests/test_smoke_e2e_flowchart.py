"""End-to-end: a realistic flowchart block renders through the /raw path."""
from skills.annotate.render import render_block

_SPEC = {
    "title": "Both actions funnel into one guard",
    "nodes": [
        {"id": "a", "role": "entry", "label": "User SAVES / edits orders"},
        {"id": "c", "role": "entry", "label": "User SHARES", "sub": "VALIDATE lifecycle action"},
        {"id": "b", "role": "code", "ref": "OrderService:154",
         "method": "validateAttachmentsSelection(items)",
         "href": "jetbrains://idea/navigate/reference?project=p&path=/a/OrderService.java:154"},
        {"id": "d", "role": "code", "ref": "WorkflowActionsExecutor:129",
         "method": "validateOrder(order)"},
        {"id": "e", "role": "call", "method": "validateRequiredDocuments(...)"},
        {"id": "f", "role": "decision", "label": "toggle ON?"},
        {"id": "g", "role": "success", "label": "allow", "sub": "no check"},
        {"id": "h", "role": "error", "label": "throw",
         "method": "MissingAttachmentsException"},
    ],
    "edges": [
        {"from": "a", "to": "b"}, {"from": "c", "to": "d"},
        {"from": "b", "to": "e"}, {"from": "d", "to": "e"}, {"from": "e", "to": "f"},
        {"from": "f", "to": "g", "label": "OFF"},
        {"from": "f", "to": "h", "label": "ON + doc missing"},
    ],
}


def test_full_flowchart_renders():
    out = render_block({"id": "section-5", "kind": "flowchart", "spec": _SPEC})
    svg = out["svg"]
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    for nid in ("a", "b", "c", "d", "e", "f", "g", "h"):
        assert f'data-node-id="{nid}"' in svg
    # jump-to-source link: href must sit inside an <a>, not just appear
    # anywhere in the SVG (e.g. a stray data attribute).
    assert '<a href="jetbrains://idea/navigate/reference?project=p' in svg
    assert "<polygon" in svg                    # decision diamond
    assert "OFF" in svg and "ON + doc missing" in svg  # edge labels
    assert "render failed" not in svg
