"""What one push costs the open page, in requests, counted in a real browser.

The daemon announces a push one anchor at a time. The page used to answer
each announcement by re-reading the whole document, and assembled that by
reading every block one by one — only to pick up the code anchors the
per-item route resolves. A push that rewrote K blocks of an N-block page cost
K × (1 + N) requests: 65 for five blocks of twelve, measured. Nothing on the
page looked wrong; the daemon's log did.

What it should cost: one snapshot read (it carries every body and version),
plus one per-item read for each rewritten block that declares code anchors,
since only that read resolves them.

Runs against the worker's private webcompanion daemon and Chromium (skills/conftest.py).
It creates its own session, serves the page from THIS checkout, and deletes
the session afterwards.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from skills.tests.harness import T, require_playwright  # noqa: E402

require_playwright()


REPO = Path(__file__).resolve().parents[3]
STATIC = REPO / "skills" / "annotate" / "static"

# Looked up rather than written down, so editing render.py cannot leave the
# anchor too far from its snippet to resolve.
RENDER_BLOCK_LINE = (Path(__file__).resolve().parents[1] / "render.py").read_text(
    encoding="utf-8").splitlines().index("def render_block(blk: dict) -> dict:") + 1

PLAIN = [f"section-{i}" for i in range(1, 9)]
ANCHORED = ["section-9", "section-10"]
ORDER = PLAIN + ANCHORED


def _call(base, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw


def _block(anchor, tag=""):
    body = {"id": anchor, "kind": "markdown", "title": anchor,
            "markdown": f"Paragraph of {anchor}. {tag}"}
    if anchor in ANCHORED:
        body["code"] = [{"file": "skills/annotate/render.py", "line": RENDER_BLOCK_LINE,
                         "snippet": "def render_block(blk: dict) -> dict:"}]
    return body


@pytest.fixture
def document(wc_daemon):
    base = wc_daemon.base
    s = _call(base, "POST", "/api/sessions",
              {"kind": "annotate", "cwd": str(REPO), "title": "refresh requests"})
    sid = s["sid"]
    try:
        _call(base, "POST", f"/s/{sid}/api/assets",
              {"static_root": str(STATIC), "entry": "entry.js"})
        items = {"__doc__": {"response_id": "resp-refresh", "title": "refresh requests",
                             "order": ORDER, "cwd": str(REPO), "glossary": []}}
        items.update({a: _block(a) for a in ORDER})
        _call(base, "PATCH", f"/s/{sid}/items?kind=annotate", {"items": items, "replace": True})
        yield {"base": base, "sid": sid, "url": f"{base}/s/{sid}/"}
    finally:
        try:
            _call(base, "POST", f"/s/{sid}/api/finish")
            _call(base, "DELETE", f"/s/{sid}/?force=1")
        except Exception:  # noqa: BLE001 — cleanup is best effort
            pass


def _item_reads(urls, sid):
    """The item reads among `urls`, as the path after the session."""
    prefix = f"/s/{sid}/items"
    out = []
    for u in urls:
        path = u.split("?", 1)[0]
        at = path.find(prefix)
        if at >= 0:
            out.append(path[at + len(f"/s/{sid}/"):])
    return out


def test_a_push_of_several_blocks_reads_only_what_changed(document, browser):
    page = browser.new_page()
    urls = []
    page.on("request", lambda r: urls.append(r.url) if r.method == "GET" else None)
    page.goto(document["url"])
    page.wait_for_function(f"document.querySelectorAll('section.block').length === {len(ORDER)}",
                           timeout=T(30000))
    # Not "networkidle": the page holds the daemon's event stream open, so the
    # network never idles. The load is done once every anchored block has its
    # code column.
    page.wait_for_function(
        "(ids) => ids.every((id) => document.querySelector("
        "`[data-block-id=\"${id}\"] .code-col`))", arg=ANCHORED, timeout=T(30000))
    page.wait_for_timeout(500)

    urls.clear()
    # Three plain blocks and one anchored block, rewritten in one push.
    rewritten = PLAIN[:3] + ANCHORED[:1]
    _call(document["base"], "PATCH", f"/s/{document['sid']}/items?kind=annotate",
          {"items": {a: _block(a, "REWRITTEN") for a in rewritten}})
    page.wait_for_function(
        "[...document.querySelectorAll('section.block')]"
        ".filter((s) => s.textContent.includes('REWRITTEN')).length === %d" % len(rewritten),
        timeout=T(30000))
    page.wait_for_timeout(1500)

    reads = _item_reads(urls, document["sid"])
    per_item = sorted(r for r in reads if r.startswith("items/"))
    assert per_item == ["items/" + ANCHORED[0]], (
        "only the rewritten block that declares code anchors needs its own read; "
        f"the page read {per_item}")
    snapshots = reads.count("items")
    assert snapshots <= 2, f"{snapshots} snapshot reads for one push of {len(rewritten)} blocks"


def test_a_block_rewritten_after_load_shows_its_resolved_anchor(document, browser):
    """The anchor pane still comes from the per-item read: the snapshot alone
    carries the declared anchor, not the resolved lines."""
    page = browser.new_page()
    page.goto(document["url"])
    page.wait_for_function(f"document.querySelectorAll('section.block').length === {len(ORDER)}",
                           timeout=T(30000))
    _call(document["base"], "PATCH", f"/s/{document['sid']}/items?kind=annotate",
          {"items": {ANCHORED[1]: _block(ANCHORED[1], "REWRITTEN")}})
    sel = f'section.block[data-block-id="{ANCHORED[1]}"]'
    page.wait_for_function(f"document.querySelector('{sel}').textContent.includes('REWRITTEN')",
                           timeout=T(30000))
    pane = page.wait_for_selector(f"{sel} .codepane", timeout=T(10000))
    assert "def render_block" in pane.inner_text()
