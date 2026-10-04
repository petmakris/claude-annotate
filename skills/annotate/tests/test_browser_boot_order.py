"""entry.js's scripts download together and still run in list order.

They used to be inserted one at a time, each awaited before the next was even
requested — a round trip per file, ~29 of them, before the page could do
anything — on the belief that order needed it. It does not: a script inserted
with async = false joins one ordered queue, downloads at once, and runs only
after every script queued before it. These two tests hold both halves: the
order (a script reading what an earlier one defined must find it), and the
parallelism (the last script is requested before the first has finished
running the page).

Runs against the worker's private webcompanion daemon and Chromium (skills/conftest.py).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from skills.tests.harness import T, require_playwright  # noqa: E402

require_playwright()


REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"

ENTRY = (STATIC / "entry.js").read_text()
LISTED = re.findall(r'^\s*"([\w.-]+\.js)"', ENTRY[ENTRY.index("const JS = ["):], re.M)

# Every script element's load event, in the order they fire. For scripts
# inserted with async = false, a script's load event follows its own execution
# and precedes the next one's, so this is execution order.
INIT = """
window.__ran = [];
document.addEventListener('load', (e) => {
  const t = e.target;
  if (t && t.tagName === 'SCRIPT' && t.src) {
    window.__ran.push({name: t.src.split('/').pop(), at: performance.now()});
  }
}, true);
"""


def _call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


@pytest.fixture(scope="module")
def booted(wc_daemon, browser_session):
    base = wc_daemon.base
    s = _call(base, "POST", "/api/sessions",
              {"kind": "annotate", "cwd": str(REPO), "title": "boot order"})
    sid = s["sid"]
    try:
        _call(base, "POST", f"/s/{sid}/api/assets",
              {"static_root": str(STATIC), "entry": "entry.js"})
        _call(base, "PATCH", f"/s/{sid}/items?kind=annotate", {"replace": True, "items": {
            "__doc__": {"response_id": "resp-boot", "title": "boot order", "order": ["section-1"],
                        "cwd": str(REPO), "glossary": []},
            "section-1": {"id": "section-1", "kind": "markdown", "title": "One", "markdown": "Hello."},
        }})
        pg = browser_session.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.add_init_script(INIT)
        pg.goto(f"{base}/s/{sid}/")
        pg.wait_for_selector("section.block", timeout=T(30000))
        pg.wait_for_function(f"window.__ran.filter((r) => {json.dumps(LISTED)}.includes(r.name)).length"
                             f" === {len(LISTED)}", timeout=T(30000))
        ran = pg.evaluate("window.__ran")
        starts = pg.evaluate("""(names) => Object.fromEntries(performance.getEntriesByType('resource')
            .filter((e) => names.includes(e.name.split('/').pop()))
            .map((e) => [e.name.split('/').pop(), e.fetchStart]))""", LISTED)
        yield {"ran": ran, "starts": starts, "errors": errors}
        pg.context.close()
    finally:
        try:
            _call(base, "POST", f"/s/{sid}/api/finish")
            _call(base, "DELETE", f"/s/{sid}/?force=1")
        except Exception:  # noqa: BLE001 — cleanup is best effort
            pass


def test_the_scripts_run_in_the_order_entry_js_lists_them(booted):
    order = [r["name"] for r in booted["ran"] if r["name"] in LISTED]
    assert order == LISTED, f"ran out of order:\n  listed {LISTED}\n  ran    {order}"
    assert not booted["errors"], booted["errors"]


def test_they_are_all_requested_before_script_js_has_run(booted):
    script_ran = next(r["at"] for r in booted["ran"] if r["name"] == "script.js")
    late = {n: round(t) for n, t in booted["starts"].items() if t > script_ran}
    assert not late, (f"requested only after script.js had run ({round(script_ran)} ms) — "
                      f"loaded one at a time again: {late}")
