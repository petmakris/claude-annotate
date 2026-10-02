"""Flowchart validator + renderer tests."""
import pytest

from skills.annotate.diagrams import flowchart as flowchart_module
from skills.annotate.diagrams.flowchart import (
    ValidationError, render, render_variants, validate,
)


def _spec():
    return {
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
    }


def test_validate_minimal_ok():
    validate(_spec())  # no raise


def test_validate_requires_a_node():
    spec = _spec(); spec["nodes"] = []
    with pytest.raises(ValidationError, match="node"):
        validate(spec)


def test_validate_duplicate_node_id():
    spec = _spec(); spec["nodes"].append({"id": "a", "role": "code"})
    with pytest.raises(ValidationError, match="duplicate"):
        validate(spec)


def test_validate_edge_unknown_from():
    spec = _spec(); spec["edges"][0]["from"] = "ghost"
    with pytest.raises(ValidationError, match="from"):
        validate(spec)


def test_validate_edge_unknown_to():
    spec = _spec(); spec["edges"][0]["to"] = "ghost"
    with pytest.raises(ValidationError, match="to"):
        validate(spec)


def test_validate_rejects_cycle():
    spec = _spec(); spec["edges"].append({"from": "h", "to": "a"})
    with pytest.raises(ValidationError, match="cycle"):
        validate(spec)


def test_validate_unknown_role_tolerated():
    spec = _spec(); spec["nodes"][0]["role"] = "banana"
    validate(spec)  # no raise — unknown role renders neutral


def test_render_contains_node_hit_targets():
    svg = render(_spec(), block_id="section-1")
    assert svg.startswith("<svg")
    assert 'class="annotate-flow"' in svg
    for nid in ("a", "b", "f", "g", "h"):
        assert f'data-node-id="{nid}"' in svg
    assert 'data-block-id="section-1"' in svg


def test_render_role_classes():
    svg = render(_spec(), block_id="s")
    assert "node-entry" in svg
    assert "node-decision" in svg
    assert "node-success" in svg
    assert "node-error" in svg


def test_render_decision_is_polygon():
    svg = render(_spec(), block_id="s")
    assert "<polygon" in svg  # the diamond


def test_render_ref_becomes_link_when_href():
    spec = _spec()
    spec["nodes"][1]["href"] = "jetbrains://idea/x?path=/p/File.java:154"
    svg = render(spec, block_id="s")
    assert "<a " in svg and "jetbrains://idea" in svg
    assert 'class="flow-ref"' in svg
    # ref still wins over label/method when all three are present.
    assert '<a href="jetbrains://idea/x?path=/p/File.java:154">' \
        '<text class="flow-ref"' in svg
    assert '<a href="jetbrains://idea/x?path=/p/File.java:154">' \
        '<text class="flow-method"' not in svg


def test_render_ref_without_href_is_not_painted_as_a_link():
    """`.flow-ref` is accent-coloured and underlined, so a ref carries the
    look of a jump-to-source link whether or not the spec gave it an href.
    A ref with no href must therefore opt out of that paint — a reader who
    clicks it gets nothing, and before the node click handler was withdrawn
    they got a comment composer they never asked for.

    The visual half of this (resolved fill and text-decoration in a real
    browser) is proven in tests/e2e/no-granular-diagram.e2e.cjs § 9."""
    spec = _spec()
    assert "href" not in spec["nodes"][1]
    svg = render(spec, block_id="s")
    assert '<text class="flow-ref flow-ref-plain"' in svg, \
        "an href-less ref is still painted with the bare link class"
    assert "<a " not in svg, "a node with no href produced an anchor"


def test_render_ref_with_href_keeps_the_link_paint():
    spec = _spec()
    spec["nodes"][1]["href"] = "jetbrains://idea/x"
    svg = render(spec, block_id="s")
    assert "flow-ref-plain" not in svg, \
        "a real link was demoted to the plain-ref paint"


def test_render_method_only_node_with_href_wraps_method():
    spec = {
        "nodes": [
            {"id": "m", "role": "call", "method": "doThing()",
             "href": "jetbrains://idea/x"},
        ],
        "edges": [],
    }
    svg = render(spec, block_id="s")
    assert "<a " in svg
    assert "jetbrains://idea/x" in svg
    assert '<a href="jetbrains://idea/x"><text class="flow-method"' in svg


def test_render_label_only_node_with_href_wraps_label():
    spec = {
        "nodes": [
            {"id": "n", "role": "entry", "label": "User SAVES",
             "href": "jetbrains://idea/y"},
        ],
        "edges": [],
    }
    svg = render(spec, block_id="s")
    assert "<a " in svg
    assert "jetbrains://idea/y" in svg
    assert '<a href="jetbrains://idea/y"><text class="flow-label"' in svg


def test_render_edge_labels_present():
    svg = render(_spec(), block_id="s")
    assert "OFF" in svg
    assert "ON + doc missing" in svg


def test_render_escapes_text():
    spec = _spec()
    spec["nodes"][0]["label"] = "a & <b>"
    svg = render(spec, block_id="s")
    assert "a &amp; &lt;b&gt;" in svg


def test_render_unknown_role_defaults_neutral():
    spec = _spec()
    spec["nodes"][0]["role"] = "banana"
    svg = render(spec, block_id="s")
    assert "node-code" in svg  # neutral fallback class


def test_render_falls_back_to_python_layout_for_an_unregistered_variant():
    # "wide" is no longer in HOUSE_SET, so flavours.options("wide") raises,
    # which layout() catches and turns into the pure-Python fallback layout
    # rather than propagating — render() must still produce a usable SVG.
    svg = render(_spec(), "section-1", variant="wide")
    assert svg.startswith("<svg")
    assert 'class="annotate-flow"' in svg


def test_render_variants_returns_layered_first():
    svgs, names = render_variants(_spec(), "section-1")
    assert names[0] == "layered"
    assert names == ["layered"]
    assert set(svgs) == set(names)
    for svg in svgs.values():
        assert svg.startswith("<svg")


def test_render_variants_ships_exactly_one_variant():
    # HOUSE_SET holds one entry, so render_variants can never offer a reader
    # a choice — this pins that down, in place of the old multi-variant
    # "different pictures" check, which is moot with a single name.
    svgs, names = render_variants(_spec(), "section-1")
    assert names == ["layered"]
    assert set(svgs) == {"layered"}


def test_edge_labels_survive_the_elk_path():
    svg = render(_spec(), "section-1", variant="layered")
    assert "OFF" in svg
    assert "ON + doc missing" in svg
    assert svg.count('class="edge-label"') == 2


def test_render_variants_propagates_when_the_default_variant_fails(monkeypatch):
    real_layout = flowchart_module.layout

    def _boom(nodes, edges, variant):
        if variant == "layered":
            raise RuntimeError("elk exploded")
        return real_layout(nodes, edges, variant)

    monkeypatch.setattr(flowchart_module, "layout", _boom)
    with pytest.raises(RuntimeError, match="elk exploded"):
        render_variants(_spec(), "section-1")


# The former "still works when only a non-default variant fails" test relied
# on "tree" being a second HOUSE_SET entry that could fail independently of
# "layered". With HOUSE_SET holding only "layered", every variant is the
# default variant, so that scenario can no longer occur — the case is now
# fully covered by test_render_variants_propagates_when_the_default_variant_fails
# above.


# ---------------------------------------------------------------------------
# A node's href reaches an <a> that script.js injects with the page's own
# sanitizer deliberately bypassed — flowchart SVG is annotate's own drawing of
# a validated spec, so it never goes through sanitizeFreeHtml. That made
# `href: "javascript:alert(1)"` in a flowchart spec a one-click script in the
# page, and it is checked in the renderer for that reason.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("href", [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    # Chrome strips ASCII whitespace and control characters before it parses
    # the scheme, so all three of these resolve to javascript: on click.
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "  javascript:alert(1)",
    "vbscript:msgbox(1)",
    "data:text/html,<script>1</script>",
    # A relative URL is not one of the four schemes the renderer emits and
    # has no meaning in a flowchart, so it goes too.
    "/x",
    "nope.html",
    "",
    "   ",
])
def test_render_drops_a_node_href_with_a_disallowed_scheme(href):
    spec = _spec()
    spec["nodes"][1]["href"] = href
    svg = render(spec, block_id="s")
    assert "<a " not in svg, "a dropped href still produced an anchor"
    assert "javascript" not in svg.lower()
    assert "vbscript" not in svg.lower()
    assert "data:text/html" not in svg
    # The line falls back to plain text, exactly as it does for a `ref` that
    # carried no href at all — never an underlined promise of a jump that
    # goes nowhere.
    assert '<text class="flow-ref flow-ref-plain"' in svg


@pytest.mark.parametrize("href", [
    "https://example.com/docs",
    "http://example.com/docs",
    "mailto:someone@example.com",
    "#section-2",
    "jetbrains://idea/navigate/reference?project=p&path=File.java:12",
    # Case is not part of the scheme.
    "HTTPS://EXAMPLE.COM/",
])
def test_render_keeps_a_node_href_with_an_allowed_scheme(href):
    spec = _spec()
    spec["nodes"][1]["href"] = href
    svg = render(spec, block_id="s")
    assert "<a " in svg
    assert "flow-ref-plain" not in svg


def test_render_drops_a_non_string_href():
    spec = _spec()
    spec["nodes"][1]["href"] = {"url": "https://example.com"}
    svg = render(spec, block_id="s")
    assert "<a " not in svg


def test_svg_carries_its_natural_size_so_it_is_never_upscaled():
    """A viewBox alone under `width:100%` stretches a narrow diagram to fill
    the card. The width/height attributes let the stylesheet cap it instead."""
    import re

    svg = render(_spec(), "blk")
    m = re.match(r'<svg [^>]*viewBox="0 0 (\d+) (\d+)"[^>]*'
                 r'width="(\d+)" height="(\d+)"', svg)
    assert m, svg[:200]
    assert (m.group(1), m.group(2)) == (m.group(3), m.group(4))


def test_stylesheet_caps_the_flowchart_rather_than_stretching_it():
    import pathlib
    import re

    css = (pathlib.Path(__file__).resolve().parents[1]
           / "static" / "diagram.css").read_text()
    rule = [l for l in css.splitlines() if l.startswith(".annotate-flow {")][0]
    assert "max-width: 100%" in rule
    # a bare `width: 100%` is the stretch this rule exists to avoid
    assert not re.search(r"(?<!max-)width:\s*100%", rule)
