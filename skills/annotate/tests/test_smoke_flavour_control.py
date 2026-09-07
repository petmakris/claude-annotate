"""Structural guards for the layout-flavour control.

Static assertion only, in the same spirit as test_smoke_maximize.py: what a
source read can see. The rules below are the ones whose violation is silent —
a control that paints before the SVG, a localStorage read outside try/catch, or
a control rendered for a block with a single layout.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"
SCRIPT = (STATIC / "script.js").read_text()
CSS = (STATIC / "diagram.css").read_text()
EXPORT_JS = STATIC / "export.js"


def _paint_flowchart_body():
    body = SCRIPT[SCRIPT.index("function paintFlowchart"):]
    return body[:body.index("\n  }")]


def test_paint_flowchart_builds_the_control():
    body = _paint_flowchart_body()
    assert "flavours" in body
    assert "flow-flavours" in body


def test_control_is_skipped_for_a_single_layout():
    # Scoped to paintFlowchart's own body — script.js:897 has an unrelated
    # `segments.length > 1` check that would satisfy an unscoped `"length > 1"
    # in SCRIPT` assertion even if the flavour gate itself were removed.
    body = _paint_flowchart_body()
    assert re.search(r"flavours\s*\|\|\s*\[\]", SCRIPT)
    assert "length > 1" in body


def test_local_storage_access_is_guarded():
    idx = SCRIPT.index("annotate.flavour.")
    window = SCRIPT[max(0, idx - 900):idx + 900]
    assert "try {" in window and "catch" in window


def test_control_has_styles():
    assert ".flow-flavours" in CSS
    assert ".flow-flavours button" in CSS


def test_export_strips_the_control():
    """A shared export carries no JS, so a row of buttons that do nothing
    must not travel with it — same rule as .max-toggle and .cp-widen."""
    strip = EXPORT_JS.read_text()
    assert '".flow-flavours"' in strip
