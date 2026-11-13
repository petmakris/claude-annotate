"""The `compare` kind: before and after code side by side.

The line diff itself is pure JavaScript (static/compare.js) and is exercised
by compare.test.cjs under node; the rest is the kind's wiring through the
document format, the push renderer, the anchor check, Confluence and the page.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from skills.annotate import anchors, render
from skills.annotate.blocks import CompareSpecError, load
from skills.annotate.confluence import body
from skills.annotate.tests.page_source import SCRIPT_JS, STATIC, STYLE_CSS

SUITE = Path(__file__).with_name("compare.test.cjs")

SPEC = {
    "before": {"label": "Today · master", "path": "a/EDR.java", "code": "a\nb\n"},
    "after": {"label": "Proposed", "path": "a/EDR.java", "lang": "java", "code": "a\nc\n"},
}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_line_diff_suite_passes():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "9/9 passed" in proc.stdout


def _write(tmp_path, spec):
    p = tmp_path / "blocks.json"
    p.write_text(json.dumps({"blocks": [{"id": "section-1", "kind": "compare", "spec": spec}]}))
    return p


def test_a_compare_block_loads(tmp_path):
    assert load(_write(tmp_path, SPEC)).blocks[0]["kind"] == "compare"


def test_one_side_alone_loads(tmp_path):
    assert load(_write(tmp_path, {"after": {"code": "new"}})).blocks


@pytest.mark.parametrize("spec, says", [
    ({"before": "x"}, "`before` must be an object"),
    ({"after": {"code": ["a", "b"]}}, "`after.code` must be a string"),
    ({"left": {"code": "a"}, "right": {"code": "b"}}, "`before` and `after`"),
    ({"after": {"code": "a", "lang": "klingon"}}, "has no highlighter"),
])
def test_a_misshapen_side_is_refused(tmp_path, spec, says):
    with pytest.raises(CompareSpecError, match=says.replace("`", ".")):
        load(_write(tmp_path, spec))


def test_the_spec_travels_verbatim_and_takes_no_side_column():
    out = render.render_block({"id": "section-1", "kind": "compare", "spec": SPEC,
                               "code": [{"file": "a/EDR.java", "line": 1}]})
    assert out["spec"] == SPEC
    assert "code" not in out


def test_a_compare_block_takes_no_anchors():
    problems = anchors.block_problems(
        {"id": "section-1", "kind": "compare", "code": [{"file": "a.java", "line": 1}]})
    assert any("compare block takes no anchors" in p for p in problems)


def test_confluence_gets_before_then_after_as_code():
    out = body.render_block({"id": "section-1", "kind": "compare", "title": "T", "spec": SPEC}, [])
    assert out.index("Today · master") < out.index("Proposed")
    assert '<code class="language-java">a\nb</code>' in out
    assert '<code class="language-java">a\nc</code>' in out


def test_confluence_with_nothing_on_either_side_still_renders():
    assert "Nothing to compare" in body.render_block({"id": "s", "kind": "compare", "spec": {}}, [])


def test_the_page_wires_the_kind():
    src = SCRIPT_JS.read_text()
    assert '"compare"' in src[src.index("const FRAMED"):src.index("\n", src.index("const FRAMED"))]
    assert 'kind === "compare"' in src and "renderCompare(content, blk)" in src
    assert "AnnotateCompare.alignLines" in src
    entry = (STATIC / "entry.js").read_text()
    assert entry.index('"compare.js"') < entry.index('"script-blocks.js"')
    assert '"compare"' in (STATIC / "maximize.js").read_text().split("MAXIMIZABLE = ")[1].split("\n")[0]
    assert '"compare"' in (STATIC / "edit.js").read_text().split("NOT_TEXT = ")[1].split("\n")[0]
    css = STYLE_CSS.read_text()
    for rule in (".cmp-row.is-del", ".cmp-row.is-add", ".cmp-row.is-fill", ".cmp-row { height:"):
        assert rule in css, rule


def test_compare_paths_load_their_grammar_before_render():
    assert '"(?:file|path)"' in (STATIC / "code-paint.js").read_text()
