"""The field-view engine is three files that render.py joins into one script.

engine.js ran to 1500 lines: validation, a 1200-line layout solver, and the
view that draws and drives the canvas. It is split along those three sections
into fields/engine/, and render.py inlines them, in order, where the one file
went. The pieces are one program — the first opens the scope the last closes —
so these tests hold the join, not the pieces: it must be exactly what the page
gets, and it must parse.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from skills.dataflow.fields import render


def test_the_engine_is_its_parts_joined_in_order():
    parts = [render.ENGINE_DIR / name for name in render.ENGINE_PARTS]
    assert [p.name for p in parts] == ["validate.js", "layout.js", "view.js"]
    assert all(p.is_file() and p.read_text().strip() for p in parts)
    assert render.engine_source() == "".join(p.read_text(encoding="utf-8") for p in parts)


def test_the_page_inlines_the_whole_engine():
    spec = json.loads((render.HERE / "example-order.json").read_text())
    page = render.render(spec)
    assert render.engine_source() in page
    assert "/*ENGINE*/" not in page


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_joined_engine_parses(tmp_path):
    js = tmp_path / "engine.js"
    js.write_text(render.engine_source(), encoding="utf-8")
    proc = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
