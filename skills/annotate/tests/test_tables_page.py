"""Runs the table-row page suite (tables.js) under pytest; skips without node."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_name("tables_page.test.mjs")
STATIC = Path(__file__).resolve().parents[1] / "static"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_tables_page_suite_passes():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) == 5, proc.stdout


def test_markdown_parts_are_decorated_when_painted_and_when_updated():
    for f in ("script-blocks.js", "script-reconcile.js"):
        assert "AnnotateTables.decorate(content)" in (STATIC / f).read_text(), f
    entry = (STATIC / "entry.js").read_text()
    assert entry.index('"tables.js"') < entry.index('"script.js"')
    assert ".row-comment" in (STATIC / "export.js").read_text()
