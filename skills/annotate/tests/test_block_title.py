"""Runs the card-title suite under pytest.

static/block-title.js is pure JavaScript, so the only way to assert on what it
actually names a card is to execute it — the same reasoning as
test_diff_engine.py. A grep for "flowchart" in script.js passed happily for the
whole life of the defect: the word was there, in a branch that did not handle
flowcharts.

node is a development dependency here, not a requirement for using the skill,
so this skips rather than fails when node is absent.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_name("block_title.test.cjs")
STATIC = Path(__file__).resolve().parents[1] / "static"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_block_title_suite_passes():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        pytest.fail("block title suite failed:\n" + proc.stdout +
                    ("\nstderr:\n" + proc.stderr if proc.stderr.strip() else ""))


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_suite_actually_asserts_something():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=60)
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    assert m, proc.stdout
    assert int(m.group(2)) >= 8, "the suite shrank — %s" % m.group(0)


def test_the_page_loads_the_rule_before_the_code_that_calls_it():
    """script.js calls blockTitle the first time it paints a card, so
    block-title.js has to be earlier in entry.js's list. Loaded after, every
    card would throw on first paint instead of being misnamed."""
    js = (STATIC / "entry.js").read_text()
    order = re.search(r"const JS = \[(.*?)\]", js, re.S).group(1)
    names = re.findall(r'"([^"]+)"', order)
    assert "block-title.js" in names, "block-title.js is never loaded"
    assert names.index("block-title.js") < names.index("script.js")


def test_script_js_does_not_keep_a_second_copy_of_the_rule():
    """Two copies is how the flowchart branch goes missing from one of them."""
    src = (STATIC / "script.js").read_text()
    assert "AnnotateBlockTitle.blockTitle" in src, "script.js stopped delegating"
    assert '"Decision"' not in src and "'Decision'" not in src, \
        "script.js still carries its own title fallbacks"
