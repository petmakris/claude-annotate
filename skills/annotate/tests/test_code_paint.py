"""Runs the code-colouring suite under pytest, and keeps code-paint.js the only door.

Uncoloured code reached the reader several times, each time through a
different surface calling a highlighter its own way, and the browser suites
that could see it skip in CI, where playwright is not installed.
code_paint.test.cjs needs only node, which CI has, and runs the page's own
vendored Shiki. The structural tests below keep a new surface from calling the
highlighter directly again, and keep the old one from coming back.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SUITE = Path(__file__).with_name("code_paint.test.cjs")
STATIC = Path(__file__).resolve().parents[1] / "static"
VENDORED = {"shiki.min.js", "markdown-it.min.js", "fuse.min.js"}


def _page_js():
    return [p for p in STATIC.glob("*.js") if p.name not in VENDORED]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_code_paint_suite_passes():
    proc = subprocess.run(["node", str(SUITE)], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        pytest.fail("code paint suite failed:\n" + proc.stdout +
                    ("\nstderr:\n" + proc.stderr if proc.stderr.strip() else ""))
    m = re.search(r"(\d+)/(\d+) passed", proc.stdout)
    assert m and int(m.group(2)) >= 50, "the suite shrank — %s" % (m and m.group(0))


def test_only_code_paint_calls_the_highlighter():
    offenders = []
    for js in _page_js():
        if js.name == "code-paint.js":
            continue
        for n, line in enumerate(js.read_text().splitlines(), 1):
            code = line.split("//", 1)[0]
            if re.search(r"\bShiki\s*\.|\bcodeTo(Tokens|Html|Hast)\b", code):
                offenders.append(f"{js.name}:{n}: {line.strip()}")
    assert not offenders, "colour code through CodePaint, not Shiki directly:\n" + "\n".join(offenders)


def test_no_second_highlighter_is_shipped_or_called():
    assert not (STATIC / "highlight.min.js").exists(), "highlight.js is back beside Shiki"
    offenders = [f"{js.name}:{n}" for js in _page_js()
                 for n, line in enumerate(js.read_text().splitlines(), 1)
                 if re.search(r"\bhljs\b", line.split("//", 1)[0])]
    assert not offenders, "highlight.js calls remain: " + ", ".join(offenders)


def test_the_page_waits_for_the_highlighter_before_script_js():
    entry = (STATIC / "entry.js").read_text()
    order = re.findall(r'^\s*"([\w.-]+\.js)"', entry, re.M)
    idx = {f: order.index(f) for f in order}
    assert idx["shiki.min.js"] < idx["code-paint.js"] < idx["script.js"], order
    assert "await window.ShikiReady" in entry, "script.js could render before the grammars load"
