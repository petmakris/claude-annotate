"""Runs the diff engine's behavioural suite under pytest.

static/diff.js is pure JavaScript, so the only way to assert on what it
actually computes is to execute it. The repo's other JS guards are
source-string checks, which is the right tool for "does this wiring exist"
and the wrong one for "does this alignment produce the correct rows" — a grep
for `wordDiff` passes just as happily when the diff shreds a paragraph into
forty one-word edits as when it doesn't.

node is already a development dependency here (tests/e2e/*.e2e.cjs need it,
plus playwright). It is NOT required to use the skill, so this skips rather
than fails when node is absent, and CI installs node so the suite really runs.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_name("diff_engine.test.cjs")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_diff_engine_suite_passes():
    proc = subprocess.run(
        ["node", str(SUITE)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        pytest.fail(
            "diff engine suite failed:\n"
            + proc.stdout
            + ("\nstderr:\n" + proc.stderr if proc.stderr.strip() else "")
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_suite_actually_asserts_something():
    """Guard against the suite silently degrading into zero tests.

    A require() that throws, or a rename that leaves every `test(...)` call
    unreached, would exit 0 with an empty run and the check above would go
    green while guarding nothing.
    """
    proc = subprocess.run(
        ["node", str(SUITE)], capture_output=True, text=True, timeout=60
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    assert "/" in tail, f"suite printed no result line, got {tail!r}"
    passed, ran = (int(x) for x in tail.split()[0].split("/"))
    assert ran >= 25, f"suite shrank to {ran} tests"
    assert passed == ran
