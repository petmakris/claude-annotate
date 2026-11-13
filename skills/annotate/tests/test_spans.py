"""Runs the spans suite under pytest; skips without node."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_name("spans.test.cjs")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_spans_suite_passes():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    assert m and int(m.group(2)) >= 9, proc.stdout
