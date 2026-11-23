"""Runs the canvas chrome suite (brief and banner) under pytest; skips without node."""
import re
import subprocess
from pathlib import Path

from .helpers import needs_node

SUITE = Path(__file__).with_name("chrome_page.test.mjs")


@needs_node
def test_canvas_chrome_suite_passes():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    assert m and m.group(1) == m.group(2) and int(m.group(2)) == 4, proc.stdout
