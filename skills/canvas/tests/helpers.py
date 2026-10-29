"""Run the canvas page's pure scripts under node and read back JSON."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def js(body: str):
    """Evaluate `body` (a function body ending in `return …`) with M (canvas-math.js) and S
    (canvas-store.js) in scope, and return its JSON value."""
    prog = (
        f"const M = require({json.dumps(str(STATIC / 'canvas-math.js'))});\n"
        f"const S = require({json.dumps(str(STATIC / 'canvas-store.js'))});\n"
        f"process.stdout.write(JSON.stringify((function () {{ {body} }})()));\n"
    )
    proc = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)
