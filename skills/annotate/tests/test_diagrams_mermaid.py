"""Mermaid diagram validator + renderer tests."""
import shutil

import pytest

from skills.annotate.diagrams.mermaid import (
    ValidationError,
    RenderError,
    SUPPORTED_TYPES,
    validate,
    render,
    _postprocess,
    _strip_init_directives,
    _normalize_line_breaks,
)
from skills.annotate.render import render_block


def _minimal_spec():
    return {"type": "flowchart", "title": "Demo", "source": "graph TD\n  A-->B"}


def test_validate_minimal_spec_ok():
    validate(_minimal_spec())  # no raise


def test_validate_rejects_unknown_type():
    spec = _minimal_spec()
    spec["type"] = "gantt"
    with pytest.raises(ValidationError, match="type"):
        validate(spec)


def test_validate_rejects_missing_type():
    spec = _minimal_spec()
    del spec["type"]
    with pytest.raises(ValidationError, match="type"):
        validate(spec)


def test_validate_rejects_empty_source():
    spec = _minimal_spec()
    spec["source"] = "   "
    with pytest.raises(ValidationError, match="source"):
        validate(spec)


def test_validate_rejects_nonstring_source():
    spec = _minimal_spec()
    spec["source"] = 123
    with pytest.raises(ValidationError, match="source"):
        validate(spec)


def test_supported_types_cover_v1():
    assert set(SUPPORTED_TYPES) == {"flowchart", "architecture", "state", "er", "class"}


_HAVE_MMDC = shutil.which("mmdc") is not None
requires_mmdc = pytest.mark.skipif(not _HAVE_MMDC, reason="mmdc (mermaid-cli) not installed")


@requires_mmdc
def test_render_flowchart_returns_svg():
    svg = render(_minimal_spec(), block_id="section-1")
    assert "<svg" in svg
    assert "annotate-diagram" in svg
    # XML prolog stripped so the string can be injected straight into innerHTML.
    assert not svg.lstrip().startswith("<?xml")


@requires_mmdc
def test_render_uses_svg_text_not_foreignobject():
    """Node labels must be native SVG <text>, never HTML <foreignObject>.

    foreignObject labels carry no baked geometry — they re-layout against the
    host page's CSS when this SVG is inlined into the annotate page, overflowing
    the node boxes mmdc measured at render time (the clipped-text bug). Rendering
    with htmlLabels:false locks label geometry in SVG user-space so the diagram
    looks identical in any host document.
    """
    spec = {"type": "flowchart", "title": "Demo",
            "source": "flowchart TD\n"
                      "  A[Draft + outline authored content] --> B[Manual tutorial]\n"
                      "  B -->|autosave hook| C[Background review job]"}
    svg = render(spec, block_id="section-1")
    assert "<foreignObject" not in svg, "labels rendered as HTML foreignObject — they will clip when embedded"
    assert "<text" in svg


@requires_mmdc
def test_render_state_diagram_returns_svg():
    spec = {"type": "state", "title": "S",
            "source": "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Running"}
    assert "<svg" in render(spec, block_id="section-2")


@requires_mmdc
def test_render_scopes_styles_per_block():
    """Every render must get a per-block SVG id, never mmdc's default.

    mermaid scopes the diagram's whole stylesheet under the root id
    (`#my-svg .node .label text{...}`). With the default id, two diagram
    blocks inlined on one page cross-apply each other's rules — a
    flowchart's `text-anchor:middle` landing on a state diagram's
    start-anchored labels is how "DISCARDED" rendered clipped to
    "SCARDED" on the demo-272 page. The id derives from the block id, so
    it is unique within a page and stable across re-renders of the same
    block."""
    spec = {"type": "state", "title": "S",
            "source": "stateDiagram-v2\n  [*] --> Idle\n  Idle --> Running"}
    svg = render(spec, block_id="section-2")
    assert 'id="mmd-section-2"' in svg
    assert "my-svg" not in svg, (
        "the default mmdc id leaks — its scoped stylesheet will collide "
        "with every other mermaid diagram on the page"
    )


def test_render_rejects_bad_spec_before_shelling_out():
    with pytest.raises(ValidationError):
        render({"type": "gantt", "source": "x"}, block_id="section-3")


@requires_mmdc
def test_render_raises_on_invalid_mermaid_source():
    spec = {"type": "flowchart", "title": "bad",
            "source": "this is not valid mermaid @@@ ->"}
    with pytest.raises(RenderError):
        render(spec, block_id="section-4")


def test_postprocess_strips_prolog_and_adds_class_when_none():
    raw = '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"><g/></svg>'
    result = _postprocess(raw)
    assert not result.lstrip().startswith("<?xml")
    assert 'class="annotate-diagram"' in result
    # exactly one class attribute on the root svg
    assert result.count('class="') == 1


def test_postprocess_appends_to_existing_class():
    raw = '<svg class="mermaid" xmlns="http://www.w3.org/2000/svg"><g/></svg>'
    result = _postprocess(raw)
    # appended, not duplicated: still a single class attribute on the root svg
    assert result.count('class="') == 1
    assert "annotate-diagram" in result
    assert "mermaid" in result


def test_postprocess_idempotent_when_already_tagged():
    raw = '<svg class="annotate-diagram mermaid" xmlns="http://www.w3.org/2000/svg"><g/></svg>'
    assert _postprocess(raw) == raw


def test_postprocess_appends_to_single_quoted_class():
    # mmdc may emit single-quoted attributes; must append, not inject a second
    # (duplicate) class attribute.
    raw = "<svg class='mermaid' xmlns='http://www.w3.org/2000/svg'><g/></svg>"
    result = _postprocess(raw)
    assert result.count("class=") == 1
    assert "annotate-diagram" in result
    assert "mermaid" in result


def test_postprocess_strips_script_tags():
    # The SVG is injected as innerHTML; any <script> must be excised regardless
    # of how it got there.
    raw = ('<svg xmlns="http://www.w3.org/2000/svg">'
           '<script>alert(1)</script><g/></svg>')
    result = _postprocess(raw)
    assert "<script" not in result
    assert "alert(1)" not in result


def test_strip_init_directives_removes_security_override():
    src = '%%{init: {"securityLevel":"loose"}}%%\nflowchart TD\n  A-->B'
    out = _strip_init_directives(src)
    assert "init" not in out
    assert "securityLevel" not in out
    assert "A-->B" in out


def test_strip_init_directives_removes_multiple():
    src = '%%{init: {"theme":"dark"}}%%\n%%{wrap}%%\ngraph TD\n A-->B'
    out = _strip_init_directives(src)
    assert "%%{" not in out
    assert "A-->B" in out


def test_normalize_line_breaks_converts_literal_backslash_n():
    # Models often author multi-line labels with a literal '\n' (backslash-n),
    # which mermaid renders as the two characters rather than a line break.
    src = 'flowchart TD\n  A["line1\\nline2"]'
    out = _normalize_line_breaks(src)
    assert '\\n' not in out
    assert 'A["line1<br/>line2"]' in out


def test_normalize_line_breaks_preserves_real_newlines():
    # Real newline chars (0x0A) separate mermaid statements and must survive.
    src = 'flowchart TD\n  A-->B\n  B-->C'
    out = _normalize_line_breaks(src)
    assert out == src


@requires_mmdc
def test_render_converts_literal_newline_in_label_to_break():
    # End-to-end: a label authored with literal '\n' renders as two lines,
    # never the literal text 'line1\nline2'.
    spec = {"type": "flowchart", "source": 'flowchart TD\n  A["line1\\nline2"]'}
    svg = render(spec, "section-1")
    assert "\\n" not in svg
    assert ">line1<" in svg and ">line2<" in svg


@requires_mmdc
def test_server_renders_diagram_block():
    blk = {"id": "section-1", "kind": "diagram", "spec": _minimal_spec()}
    out = render_block(blk)
    assert out["kind"] == "diagram"
    assert "<svg" in out["svg"]
    assert out["spec"] == _minimal_spec()


def test_server_diagram_render_failure_yields_error_pill():
    # Unknown type → mermaid.validate raises → server catches → error pill,
    # never an exception that blanks /raw. (No mmdc needed: validation fails first.)
    blk = {"id": "section-9", "kind": "diagram", "spec": {"type": "gantt", "source": "x"}}
    out = render_block(blk)
    assert out["kind"] == "diagram"
    assert "diagram render failed" in out["svg"]
