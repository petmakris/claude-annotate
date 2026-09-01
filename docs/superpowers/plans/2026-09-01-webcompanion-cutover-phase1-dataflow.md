# Webcompanion Cutover — Phase 1 (shared client + dataflow) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the one shared, stdlib-only webcompanion HTTP client every remaining skill will use, and migrate `dataflow` onto it as the first, smallest proof of the whole pattern — deleting its private server entirely.

**Architecture:** `skills/_shared/webcompanion_client.py` wraps the daemon's HTTP contract (`~/projects/webcompanion/docs/contract.md`, contract version 1) in typed functions with typed exceptions. `skills/dataflow/push.py` is the only thing that knows how a dataflow document maps onto daemon items — the same shape `skills/annotate/push.py` already proved in production today. `skills/dataflow/server.py` and `skills/dataflow/ensure_server.sh` are deleted outright: the daemon serves everything a thin `Handlers` class used to hand-roll (session pages, threads, polling, SSE), so there is nothing left for dataflow's own server to do. `dataflow.js` is updated to talk to the daemon's routes directly (item body-wrapping, raw thread messages instead of a pre-flattened summary) via one new shared JS helper other skills will reuse in later phases.

**Tech Stack:** Python 3.9+ stdlib only (`urllib`, `json`, `http.server` for test fixtures — no new pip dependency, per this plugin's own zero-dependency rule). Vanilla JS (no new client-side test framework — none exists for skill static JS today; see Testing strategy).

**Spec:** `docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md` — read it before starting; this plan implements its Decisions 1 and 2, and the "dataflow (Phase 1)" section, verbatim.

## Global Constraints

- No new third-party Python dependency. `skills/_shared/webcompanion_client.py` uses only `json`, `os`, `urllib.request`, `urllib.parse`, `urllib.error`, `pathlib`.
- Every daemon request carries `X-WebCompanion-Contract: 1` (the constant `CONTRACT = 1`) and, if the config has one, `X-WebCompanion-Token`.
- `kind` for dataflow is the literal string `"dataflow"` — the canonical spelling in `contract.md`'s kind table, matching the existing per-skill directory name, so a later `webcompanion migrate` finds it under the same partition.
- Claude-authored thread messages use `role: "agent"` (the daemon's own default — do not override it to `"claude"`). Every consumer (JS, docs) checks for `"agent"`, not `"claude"`. This is a deliberate departure from the pre-migration local convention, made once here and carried through every later phase for consistency with the daemon's own vocabulary.
- Every session-scoped daemon call appends `?kind=dataflow` to the path, matching `annotate/push.py`'s existing convention (`_existing_items`, `push`) — defensive against `{sid}` resolving as an ambiguous slug, even when the caller already holds the real `sid`.
- Never delete a file's test coverage without repointing it at whatever survived, per `annotate`'s own migration precedent (`8ebf419`) — a deleted `server.py` takes its `test_server.py` with it only where nothing in it still applies; anything testing `flow.py`'s validation stays.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `skills/_shared/webcompanion_client.py` (new) | The shared HTTP client every migrated skill's `push.py` uses. |
| `skills/_shared/tests/test_webcompanion_client.py` (new) | Tests against a fake HTTP server fixture — no real daemon required. |
| `skills/_shared/static/wc-threads.js` (new) | Canonical source for one shared JS helper: raw daemon thread-bulk → the flattened per-anchor render shape skill JS already expects (`latest_synthesis`/`question`/`title`/`version`/`updated_at`). Lives in a directory sibling to (not inside) `skills/_shared/web_companion/`, which Decision 5 of the full-cutover spec deletes once every skill stops importing it — a static JS asset is invisible to that grep-based safety check, so the canonical copy cannot live inside the directory being deleted. Each migrated skill checks in its own copy (see Task 2) since the daemon serves assets from one directory per session. |
| `skills/dataflow/static/wc-threads.js` (new) | A checked-in copy of the above, inside dataflow's own asset root. |
| `skills/dataflow/static/entry.js` (new) | The registered asset entry point — loads `wc-threads.js` then `dataflow.js`, in order, mirroring `annotate/static/entry.js`'s own loader-stub role. |
| `skills/dataflow/push.py` (new) | Push a `dataflow.json` document to the daemon as the `__flow__` item; registers `skills/dataflow/static/` as the session's asset root with `entry.js` (new, see Task 2) as the entry point — the daemon serves a renderer from exactly one directory, the same constraint `annotate`'s migration hit and solved the same way (its own `entry.js` is a small loader stub for this reason). |
| `skills/dataflow/tests/test_push.py` (new) | Tests for `push.py`, client mocked. |
| `skills/dataflow/server.py` (delete) | Superseded entirely by the daemon. |
| `skills/dataflow/ensure_server.sh` (delete) | No server to ensure. |
| `skills/dataflow/tests/test_server.py` (delete) | Tested the deleted server. |
| `skills/dataflow/static/dataflow.js` (modify) | Talks to `/s/{sid}/items/__flow__`, `/s/{sid}/threads`, `/s/{sid}/stream` directly; uses `wc-threads.js`. |
| `skills/dataflow/SKILL.md` (modify) | Documents the daemon-based flow: `push.py` for session creation, `webcompanion watch`/`ack` for the Mode-D loop. |

**Note on Task ordering below:** Task 3 (deleting the old server) also has to answer "how does a browser reach `dataflow.js`/`dataflow.css` at all once there is no `skills/dataflow/server.py` serving `static_dirs=[SHARED_STATIC_DIR, STATIC_DIR]`?" The daemon serves static assets only for a session that has **registered** them via `POST /s/{sid}/api/assets {static_root, entry}` (see contract.md's route table) — so `push.py` must register dataflow's `static/` directory the same way `annotate/push.py` registers its own, with `entry: "dataflow.js"`, and the daemon's shell page (`GET /s/{sid}/`) loads that entry script automatically. This is folded into Task 1 (`push.py`) rather than a separate task, since it is one function call inside the same file.

---

### Task 1: `webcompanion_client.py` and `dataflow/push.py`

**Files:**
- Create: `skills/_shared/webcompanion_client.py`
- Create: `skills/_shared/tests/test_webcompanion_client.py`
- Create: `skills/_shared/tests/__init__.py` (only if `skills/_shared/tests/` does not already exist as a package — check first: `ls skills/_shared/tests/__init__.py`)
- Create: `skills/dataflow/push.py`
- Create: `skills/dataflow/tests/test_push.py`

**Interfaces:**
- Produces: every function listed in the spec's "The shared client module" section, plus the three exception classes. Exact signatures below (the spec's version is illustrative; this is binding). Task 2 (dataflow.js) and every later phase's `push.py` consume this module's public functions by these exact names.

- [ ] **Step 1: Write the failing client tests**

```python
# skills/_shared/tests/test_webcompanion_client.py
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from skills._shared import webcompanion_client as wc


class _FakeDaemon(BaseHTTPRequestHandler):
    """Records every request it receives; responds per FakeDaemon.script."""
    script = []  # list of (status, body_dict) popped in order, shared across a test
    seen = []    # list of (method, path, headers_dict, body_dict_or_None)

    def _handle(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else None
        _FakeDaemon.seen.append((self.command, self.path, dict(self.headers), body))
        status, resp = _FakeDaemon.script.pop(0)
        data = json.dumps(resp).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self): self._handle()
    def do_POST(self): self._handle()
    def do_PATCH(self): self._handle()
    def do_PUT(self): self._handle()
    def do_DELETE(self): self._handle()
    def log_message(self, *a): pass  # silence per-request stderr noise


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _FakeDaemon)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg_dir = tmp_path / ".claude" / "webcompanion"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.json").write_text(json.dumps({"port": port, "token": "tok"}))
    monkeypatch.setattr(wc, "_CONFIG_PATH", cfg_dir / "config.json")
    _FakeDaemon.script = []
    _FakeDaemon.seen = []
    yield port
    server.shutdown()


def test_load_config_missing_raises_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "_CONFIG_PATH", tmp_path / "nope.json")
    with pytest.raises(wc.DaemonNotConfigured):
        wc.load_config()


def test_create_or_attach_creates_when_no_slug(daemon):
    _FakeDaemon.script = [(201, {"sid": "s1", "slug": "s1", "kind": "dataflow", "url": "/s/s1/", "token": "tok"})]
    res = wc.create_or_attach("dataflow", "/repo", title="T")
    assert res == {"sid": "s1", "slug": "s1", "kind": "dataflow", "url": "/s/s1/", "token": "tok"}
    method, path, headers, body = _FakeDaemon.seen[0]
    assert method == "POST" and path == "/api/sessions"
    assert body == {"kind": "dataflow", "cwd": "/repo", "title": "T"}
    assert headers["X-Webcompanion-Contract"] == "1"
    assert headers["X-Webcompanion-Token"] == "tok"


def test_create_or_attach_attaches_by_slug(daemon):
    _FakeDaemon.script = [
        (200, [{"sid": "s1", "slug": "my-slug", "kind": "dataflow"}]),
    ]
    res = wc.create_or_attach("dataflow", "/repo", slug="my-slug")
    assert res["sid"] == "s1"
    assert _FakeDaemon.seen[0][1].startswith("/api/sessions?")


def test_create_or_attach_falls_through_to_create_when_slug_not_found(daemon):
    _FakeDaemon.script = [
        (200, []),
        (201, {"sid": "s2", "slug": "my-slug", "kind": "dataflow", "url": "/s/s2/", "token": "tok"}),
    ]
    res = wc.create_or_attach("dataflow", "/repo", slug="my-slug")
    assert res["sid"] == "s2"
    assert _FakeDaemon.seen[1][0] == "POST"


def test_put_items_replace(daemon):
    _FakeDaemon.script = [(200, {"ok": True})]
    wc.put_items("s1", {"__flow__": {"a": 1}}, kind="dataflow", replace=True)
    method, path, headers, body = _FakeDaemon.seen[0]
    assert method == "PATCH"
    assert path == "/s/s1/items?kind=dataflow"
    assert body == {"items": {"__flow__": {"a": 1}}, "replace": True}


def test_get_items(daemon):
    _FakeDaemon.script = [(200, {"__flow__": {"body": {"a": 1}, "version": 3}})]
    res = wc.get_items("s1", kind="dataflow")
    assert res == {"__flow__": {"body": {"a": 1}, "version": 3}}


def test_register_assets(daemon):
    _FakeDaemon.script = [(200, {"ok": True})]
    wc.register_assets("s1", "/some/static", "entry.js", kind="dataflow")
    method, path, headers, body = _FakeDaemon.seen[0]
    assert method == "POST" and path == "/s/s1/api/assets?kind=dataflow"
    assert body == {"static_root": "/some/static", "entry": "entry.js"}


def test_get_threads(daemon):
    _FakeDaemon.script = [(200, {"node:1": {"anchor": "node:1", "version": 1, "messages": []}})]
    res = wc.get_threads("s1", kind="dataflow")
    assert res["node:1"]["version"] == 1


def test_append_thread(daemon):
    _FakeDaemon.script = [(200, {"appended": True, "version": 2})]
    res = wc.append_thread("s1", "node:1", "hello", role="agent",
                           source_event_id="e1", kind="dataflow")
    assert res == {"appended": True, "version": 2}
    method, path, headers, body = _FakeDaemon.seen[0]
    assert method == "POST" and path == "/s/s1/threads/node:1?kind=dataflow"
    assert body == {"text": "hello", "role": "agent", "source_event_id": "e1"}


def test_delete_thread(daemon):
    _FakeDaemon.script = [(200, {"deleted": True})]
    res = wc.delete_thread("s1", "node:1", kind="dataflow")
    assert res is True
    method, path, headers, body = _FakeDaemon.seen[0]
    assert body == {"anchor": "node:1"}


def test_submit_event(daemon):
    _FakeDaemon.script = [(202, {"event_id": "evt-1"})]
    eid = wc.submit_event("s1", "node:1", "a question", kind="dataflow")
    assert eid == "evt-1"


def test_contract_mismatch_raises(daemon):
    _FakeDaemon.script = [(426, {"error": "the client speaks contract 1, this daemon speaks 2"})]
    with pytest.raises(wc.ContractMismatch):
        wc.create_or_attach("dataflow", "/repo")


def test_unreachable_daemon_raises(tmp_path, monkeypatch):
    cfg_dir = tmp_path / ".claude" / "webcompanion"
    cfg_dir.mkdir(parents=True)
    # A port nothing listens on.
    (cfg_dir / "config.json").write_text(json.dumps({"port": 1, "token": ""}))
    monkeypatch.setattr(wc, "_CONFIG_PATH", cfg_dir / "config.json")
    with pytest.raises(wc.DaemonUnreachable):
        wc.create_or_attach("dataflow", "/repo")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover && python3 -m pytest skills/_shared/tests/test_webcompanion_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills._shared.webcompanion_client'`

- [ ] **Step 3: Write `webcompanion_client.py`**

```python
"""Shared HTTP client for the webcompanion daemon.

Every skill that has migrated onto the daemon (starting with `dataflow`, see
`skills/dataflow/push.py`) uses this module instead of hand-rolling its own
`urllib` calls. `skills/annotate/push.py` predates this module and is
retrofitted onto it in a later phase of the same cutover program — see
docs/superpowers/specs/2026-09-01-webcompanion-full-cutover-design.md.

Stdlib only, deliberately: this plugin ships with no pip dependencies, and
`webcompanion` itself is only ever `pipx`-installed (an isolated venv the
plain `python3` these skills run under cannot import), so nothing here can
lean on `webcompanion.client.Client` even though it exists and is broader.

Contract reference: ~/projects/webcompanion/docs/contract.md (version 1).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONTRACT = 1
_CONFIG_PATH = Path(os.path.expanduser("~/.claude/webcompanion/config.json"))


class DaemonNotConfigured(Exception):
    """~/.claude/webcompanion/config.json does not exist."""


class DaemonUnreachable(Exception):
    """The config exists but the daemon did not answer (connection/timeout)."""


class ContractMismatch(Exception):
    """The daemon returned 426 — client and daemon disagree on the wire contract."""


def load_config() -> dict:
    if not _CONFIG_PATH.exists():
        raise DaemonNotConfigured(
            "webcompanion is not configured on this machine "
            f"({_CONFIG_PATH} is missing).\n"
            "  pipx install webcompanion && webcompanion install-service")
    return json.loads(_CONFIG_PATH.read_text())


def _request(method: str, path: str, body: dict | list | None = None) -> dict | list:
    cfg = load_config()
    url = "http://127.0.0.1:%d%s" % (int(cfg["port"]), path)
    data = None
    headers = {"X-WebCompanion-Contract": str(CONTRACT)}
    if cfg.get("token"):
        headers["X-WebCompanion-Token"] = cfg["token"]
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace").strip()
        if e.code == 426:
            raise ContractMismatch(detail) from None
        raise RuntimeError("%s %s -> %d %s" % (method, path, e.code, detail)) from None
    except urllib.error.URLError as e:
        raise DaemonUnreachable(
            "cannot reach the webcompanion daemon on port %s (%s).\n"
            "  webcompanion status   # is the service running?\n"
            "  webcompanion doctor   # full check"
            % (cfg["port"], e.reason)) from None
    return json.loads(raw) if raw.strip() else {}


def _kind_qs(kind: str) -> str:
    return "?kind=" + urllib.parse.quote(kind)


def create_or_attach(kind: str, cwd: str, *, title: str | None = None,
                     slug: str | None = None) -> dict:
    """Resolve `slug` to a live session if given and found; otherwise create one.

    Mirrors `annotate/push.py:push()`'s attach-before-create logic: a slug is
    unique only within a kind, so resolving it here (rather than trusting the
    slug string onward to the caller) avoids a later ambiguous-slug 409 at the
    worst possible moment (e.g. inside `webcompanion ack`).
    """
    if slug:
        try:
            rows = _request("GET", "/api/sessions" + "?cwd=%s&kind=%s"
                            % (urllib.parse.quote(cwd), urllib.parse.quote(kind)))
        except (DaemonNotConfigured, DaemonUnreachable):
            rows = []
        for row in (rows if isinstance(rows, list) else rows.get("sessions", [])):
            if row.get("slug") == slug:
                return row
    body: dict = {"kind": kind, "cwd": cwd}
    if title:
        body["title"] = title
    if slug:
        body["slug"] = slug
    return _request("POST", "/api/sessions", body)


def put_items(sid: str, items: dict, *, kind: str, replace: bool = False) -> dict:
    return _request("PATCH", f"/s/{sid}/items" + _kind_qs(kind),
                    {"items": items, "replace": replace})


def get_items(sid: str, *, kind: str) -> dict:
    return _request("GET", f"/s/{sid}/items" + _kind_qs(kind))


def register_assets(sid: str, static_root: str, entry: str, *, kind: str) -> None:
    _request("POST", f"/s/{sid}/api/assets" + _kind_qs(kind),
             {"static_root": static_root, "entry": entry})


def get_threads(sid: str, *, kind: str) -> dict:
    return _request("GET", f"/s/{sid}/threads" + _kind_qs(kind))


def append_thread(sid: str, anchor: str, text: str, *, kind: str, role: str = "agent",
                  source_event_id: str | None = None, title: str | None = None,
                  anchor_text: str | None = None) -> dict:
    body: dict = {"text": text, "role": role}
    if source_event_id is not None:
        body["source_event_id"] = source_event_id
    if title is not None:
        body["title"] = title
    if anchor_text is not None:
        body["anchor_text"] = anchor_text
    return _request("POST", f"/s/{sid}/threads/{anchor}" + _kind_qs(kind), body)


def delete_thread(sid: str, anchor: str, *, kind: str) -> bool:
    res = _request("POST", f"/s/{sid}/api/threads/delete" + _kind_qs(kind), {"anchor": anchor})
    return bool(res.get("deleted"))


def submit_event(sid: str, anchor: str, text: str, *, kind: str,
                 images: list[str] | None = None) -> str:
    body: dict = {"anchor": anchor, "text": text}
    if images:
        body["images"] = images
    res = _request("POST", f"/s/{sid}/api/submit" + _kind_qs(kind), body)
    return res["event_id"]
```

Note on the test's `test_append_thread` expectation `body == {"text": "hello", "role": "agent", "source_event_id": "e1"}` (no `title`/`anchor_text` keys) — the implementation above only adds those keys `if ... is not None`, matching the test's expectation of a minimal body when they are omitted.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover && python3 -m pytest skills/_shared/tests/test_webcompanion_client.py -v`
Expected: PASS (13 tests). If `skills/_shared/tests/__init__.py` did not exist and pytest reports an import error about a missing package, create an empty one and re-run.

- [ ] **Step 5: Write the failing `push.py` tests for dataflow**

First, read `skills/dataflow/flow.py`'s public functions (`load_flow`, `write_flow`, `generated_ts`, `count_nodes`, `valid_anchor`, `anchor_node_id`, `node_ids`) so the test fixtures below construct a realistic minimal flow document — do not guess its shape from this brief; read the file.

```python
# skills/dataflow/tests/test_push.py
from pathlib import Path
from unittest.mock import patch

from skills.dataflow import push


MINIMAL_FLOW = {
    "seed": "OrderService", "question": "how does an order get created",
    "generated_ts": 1700000000, "model": ["claim one"],
    "slices": [{"layer": "api", "nodes": [
        {"id": "n1", "layer": "api", "role": "context", "name": "OrderController",
         "file": "OrderController.java", "line": 10, "summary": "s", "note": "",
         "flag": None, "implicit": False, "members": [], "edges": []}
    ]}],
}


def test_push_creates_session_and_pushes_flow_item(tmp_path):
    flow_path = tmp_path / "dataflow.json"
    flow_path.write_text(__import__("json").dumps(MINIMAL_FLOW))

    with patch("skills.dataflow.push.wc.create_or_attach",
              return_value={"sid": "s1", "slug": "s1", "kind": "dataflow",
                            "url": "http://127.0.0.1:3080/s/s1/", "token": "tok"}) as mock_create, \
         patch("skills.dataflow.push.wc.put_items") as mock_put, \
         patch("skills.dataflow.push.wc.register_assets") as mock_assets, \
         patch("skills.dataflow.push.wc.load_config", return_value={"port": 3080, "token": "tok"}):
        res = push.push(flow_path, "/repo")

    mock_create.assert_called_once_with("dataflow", "/repo", title="OrderService", slug=None)
    mock_put.assert_called_once_with("s1", {"__flow__": MINIMAL_FLOW}, kind="dataflow", replace=True)
    mock_assets.assert_called_once_with(
        "s1", str(push.STATIC_DIR), "entry.js", kind="dataflow")
    assert res["sid"] == "s1"
    assert res["url"] == "http://127.0.0.1:3080/s/s1/"


def test_push_attaches_by_slug(tmp_path):
    flow_path = tmp_path / "dataflow.json"
    flow_path.write_text(__import__("json").dumps(MINIMAL_FLOW))

    with patch("skills.dataflow.push.wc.create_or_attach",
              return_value={"sid": "s2", "slug": "my-slug", "kind": "dataflow",
                            "url": "http://127.0.0.1:3080/s/my-slug/", "token": "tok"}) as mock_create, \
         patch("skills.dataflow.push.wc.put_items"), \
         patch("skills.dataflow.push.wc.register_assets"), \
         patch("skills.dataflow.push.wc.load_config", return_value={"port": 3080, "token": "tok"}):
        push.push(flow_path, "/repo", slug="my-slug")

    mock_create.assert_called_once_with("dataflow", "/repo", title="OrderService", slug="my-slug")
```

- [ ] **Step 6: Run to verify it fails**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover && python3 -m pytest skills/dataflow/tests/test_push.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'skills.dataflow.push'`

- [ ] **Step 7: Write `skills/dataflow/push.py`**

```python
"""Push a dataflow.json document to the webcompanion daemon.

Replaces the old flow — start a per-skill server on a fixed port, let it
serve dataflow.json off disk. There is no dataflow server any more: the
daemon owns storage, comment threads and the event queue, and this module is
the only thing that knows how a dataflow document maps onto it.

The mapping:

    __flow__    the full dataflow.json body, unchanged shape (see flow.py)

Usage:
    python3 -m skills.dataflow.push --flow <dataflow.json> --cwd <repo root>
                                    [--slug <slug>] [--title <title>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from skills._shared import webcompanion_client as wc

KIND = "dataflow"
FLOW_ANCHOR = "__flow__"
STATIC_DIR = Path(__file__).resolve().parent / "static"
ENTRY = "entry.js"


def push(flow_path: Path, cwd: str, slug: str | None = None,
        title: str | None = None) -> dict:
    # `flow.py`'s own `load_flow(state_dir)` takes a *directory* (the
    # session's state_dir) and looks for `dataflow.json` inside it — not
    # what push.py has, which is an explicit file path Claude just wrote.
    # Read and parse directly, the same way annotate/push.py's `blocks_model.load`
    # takes a direct path rather than a directory.
    doc = json.loads(flow_path.read_text())
    title = title or doc.get("seed") or "Dataflow"

    res = wc.create_or_attach(KIND, cwd, title=title, slug=slug)
    sid = res["sid"]

    wc.put_items(sid, {FLOW_ANCHOR: doc}, kind=KIND, replace=True)

    # Idempotent, re-sent on every push so a plugin that has moved on disk
    # since the session was created still resolves — same reasoning as
    # annotate/push.py's own asset registration.
    wc.register_assets(sid, str(STATIC_DIR), ENTRY, kind=KIND)

    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="skills.dataflow.push")
    ap.add_argument("--flow", required=True, help="path to dataflow.json")
    ap.add_argument("--cwd", required=True, help="repo root the session belongs to")
    ap.add_argument("--slug", help="attach to this slug instead of creating a session")
    ap.add_argument("--title")
    a = ap.parse_args(argv)
    try:
        res = push(Path(a.flow), a.cwd, a.slug, a.title)
    except (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch) as e:
        print("dataflow push: %s" % e, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover && python3 -m pytest skills/dataflow/tests/test_push.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/_shared/webcompanion_client.py skills/_shared/tests/test_webcompanion_client.py \
        skills/dataflow/push.py skills/dataflow/tests/test_push.py
git commit -m "Add the shared webcompanion HTTP client and dataflow's push.py"
```

---

### Task 2: Shared JS thread-derivation helper, and dataflow's `entry.js` loader

**Files:**
- Create: `skills/_shared/static/wc-threads.js` (canonical source)
- Create: `skills/dataflow/static/wc-threads.js` (a checked-in copy — see note below)
- Create: `skills/dataflow/static/entry.js`

**Interfaces:**
- Produces: a global function `WcThreads.derive(rawThreadsBulk)` returning `{anchor: {latest_synthesis, question, title, version, updated_at}}` from the daemon's raw `GET /s/{sid}/threads` response shape (`{anchor: {anchor, version, messages, title?, anchor_text?}}`). Task 3 (dataflow.js) is the consumer. `entry.js` is what `push.py` registers as the daemon's asset entry point (Task 1's `ENTRY` constant changes from `"dataflow.js"` to `"entry.js"` — apply that edit here too, in the same commit, since the two changes are only correct together).

**Why a copy, not a shared reference:** the daemon serves a session's assets from exactly one registered `static_root` directory (`contract.md`'s `/api/assets` row) — the same constraint `annotate`'s migration hit, solved the same way: its own `entry.js` is a small loader stub specifically because a renderer can only pull from one directory, so any shared file a skill needs must live inside that skill's own static root. `wc-threads.js`'s canonical source lives in `skills/_shared/static/` — a directory sibling to, not inside, `skills/_shared/web_companion/` — because the full-cutover spec's Decision 5 deletes `web_companion/` entirely once every skill stops importing it, and a grep for Python imports would never catch a static JS asset still living there (it is the shared *source*, and other phases copy from it the same way); each skill that uses it checks in its own copy under its own `static/`, exactly as `annotate` copied `core.css`/`markdown-it.min.js`/`fonts/` into its own tree rather than trying to serve from two roots at once.

- [ ] **Step 1: Write `wc-threads.js`**

No test framework exists for skill static JS today (verified: `vscode-plugin/` has its own Jest-style suite, scoped to that package only; no `skills/*/static/*.test.js` anywhere). This file is small and pure enough to review by reading; do not introduce a new JS test runner for one function — see the plan's Testing strategy section.

```javascript
/* wc-threads.js — shared derivation from the daemon's raw thread-bulk shape
   ({anchor: {anchor, version, messages, title?, anchor_text?}}) to the
   flattened per-anchor render info every migrated skill's static JS expects
   ({latest_synthesis, question, title, version, updated_at}).

   Every skill's Claude-authored messages use role "agent" (the daemon's own
   default — see the cutover plan's Global Constraints); "user" marks the
   human's own submitted questions. A thread with no agent message yet is
   OMITTED from the result, matching every skill's own prior behavior: the
   page owns "pending" state for a question it just submitted, and an empty
   entry would overwrite that with nothing.
*/
(function (global) {
  "use strict";

  function derive(rawThreadsBulk) {
    const out = {};
    for (const anchor of Object.keys(rawThreadsBulk || {})) {
      const t = rawThreadsBulk[anchor];
      const messages = (t && t.messages) || [];
      const agentMsgs = messages.filter((m) => m.role === "agent");
      if (agentMsgs.length === 0) continue;
      const userMsgs = messages.filter((m) => m.role === "user");
      const last = agentMsgs[agentMsgs.length - 1];
      out[anchor] = {
        latest_synthesis: last.text || "",
        version: t.version || 0,
        updated_at: last.ts || 0,
        title: t.title || "",
        question: userMsgs.length ? userMsgs[userMsgs.length - 1].text || "" : "",
      };
    }
    return out;
  }

  global.WcThreads = { derive: derive };
})(typeof window !== "undefined" ? window : this);
```

- [ ] **Step 2: Copy it into dataflow's own static root**

```bash
cd /Users/petros.makris/projects/claude-annotate
cp skills/_shared/static/wc-threads.js skills/dataflow/static/wc-threads.js
```

- [ ] **Step 3: Write `skills/dataflow/static/entry.js`**

A small loader stub, mirroring `annotate/static/entry.js`'s own job ("paints the frame, then loads assets in a strict order") — read that file first so this one follows the same shape rather than inventing a second convention. At minimum it must load `wc-threads.js` and then `dataflow.js`, in that order, before either can be used (`dataflow.js`'s `boot()` calls `WcThreads.derive` at the top of its own execution):

```javascript
/* entry.js — dataflow's registered asset entry point.
   Loads wc-threads.js, then dataflow.js, in that strict order: dataflow.js
   calls WcThreads.derive() as soon as it runs, so it must not start first.
   Mirrors annotate/static/entry.js's own reason for existing — the daemon
   serves a session's renderer from exactly one directory, so anything a
   skill's page needs beyond its own top-level script has to be loaded here,
   in order, rather than declared as separate <script> tags in a <head> that
   dataflow's page never gets to author (the daemon writes the shell).
*/
(function () {
  "use strict";
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error("failed to load " + src));
      document.head.appendChild(s);
    });
  }
  loadScript("wc-threads.js")
    .then(() => loadScript("dataflow.js"))
    .catch((e) => {
      document.body.append(
        Object.assign(document.createElement("div"), { textContent: String(e) }));
    });
})();
```

**Read `annotate/static/entry.js` before finalizing this** — if its actual loader shape differs from the sketch above (e.g. it fetches a manifest, or handles `markdown-it.min.js` and CSS loading the same way), match its established pattern rather than this plan's independently-invented one; the point of citing it is convergence on one convention, not two loaders that happen to both work.

- [ ] **Step 4: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add skills/_shared/static/wc-threads.js skills/dataflow/static/wc-threads.js \
        skills/dataflow/static/entry.js
git commit -m "Add wc-threads.js and dataflow's entry.js loader"
```

---

### Task 3: Delete dataflow's server; update dataflow.js and SKILL.md

**Files:**
- Delete: `skills/dataflow/server.py`
- Delete: `skills/dataflow/ensure_server.sh`
- Delete: `skills/dataflow/tests/test_server.py`
- Modify: `skills/dataflow/static/dataflow.js`
- Modify: `skills/dataflow/SKILL.md`

**Interfaces:**
- Consumes: `WcThreads.derive` (Task 2), and `window.WebCompanion` — the daemon's own browser runtime (`GET /_wc/core.js`), loaded automatically by the daemon's shell page before `entry.js` runs. **Do not hand-roll `fetch`/`EventSource` calls to the daemon's routes** — `window.WebCompanion.api.fetchJSON(path)`/`.submit(payload)` and `window.WebCompanion.init({onDelta})` already exist and already own the contract header, the write token, and SSE-with-poll-fallback reconnection (confirmed by reading `_wc/core.js` directly off the running daemon, and by reading `annotate/static/compat.js`, which builds on exactly this rather than a second hand-rolled transport). This was corrected after Tasks 1-2 shipped, from an earlier draft of this task that did specify raw `fetch`/`EventSource` calls — if you see that pattern referenced anywhere else in this plan's own commit history, it is superseded by this section.

- [ ] **Step 1: Confirm what `test_server.py` covers before deleting it**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover && python3 -m pytest skills/dataflow/tests/test_server.py -v --collect-only`

Read the collected test names against `skills/dataflow/server.py`'s methods. Every test exercising `Handlers` (`serve_root`, `serve_data`, `handle_submit`, `serve_poll`, `create_session_extra`, `comment_count`, `threads_bulk`) is safe to delete along with the file — none of that code survives. If any test in this file is actually testing something in `flow.py` (unlikely, but check — `flow.py` has its own `test_flow.py`), move that specific test there first.

- [ ] **Step 2: Delete the old server**

```bash
cd /Users/petros.makris/projects/claude-annotate
git rm skills/dataflow/server.py skills/dataflow/ensure_server.sh skills/dataflow/tests/test_server.py
```

- [ ] **Step 3: Update `dataflow.js`**

Three changes, each at the exact call site already located during this plan's own research (verify line numbers against the current file before editing — Task 2/Task 3 of an earlier, unrelated phase may have shifted them slightly if this task runs out of order):

**3a. `boot()` (around line 594-603 today):**

```javascript
  async function boot() {
    const [flowItem, rawThreads] = await Promise.all([
      window.WebCompanion.api.fetchJSON("items/__flow__"),
      window.WebCompanion.api.fetchJSON("threads"),
    ]);
    FLOW = flowItem.body;
    THREADS = WcThreads.derive(rawThreads);
    render();
    connect();
  }
```

**3b. `refetchFlow()` (around line 566-570 today):**

```javascript
  async function refetchFlow() {
    const item = await window.WebCompanion.api.fetchJSON("items/__flow__");
    FLOW = item.body;
    render();
  }
```

**3c. `connect()` (around line 572-592 today) — use the daemon's own runtime, not a second hand-rolled `EventSource`.** `_wc/core.js` (loaded automatically by the shell page before `entry.js` runs — verified by fetching it directly off the running daemon during this plan's research) already owns the SSE connection, poll fallback, reconnect-on-error, and the contract/token headers, behind one `init({onDelta})` call. `annotate`'s own migration builds on exactly this (`skills/annotate/static/compat.js`'s `daemon.init({onDelta: toOldShape(...)})`), not a second transport. `onDelta` receives `{kind: "item"|"thread"|"thread-deleted"|"document", anchor, version, initial}` — there is no `flow-changed` frame; a change to the `__flow__` item arrives as `{kind: "item", anchor: "__flow__"}`, and `initial: true` frames (the daemon's stream-open snapshot of everything a client could already see) must be ignored, since `FLOW`/`THREADS` are already current from `boot()`'s own fetch moments earlier:

```javascript
  function connect() {
    window.WebCompanion.init({
      onDelta(ev) {
        if (ev.kind === "item" && ev.anchor === "__flow__" && !ev.initial) {
          refetchFlow();
          return;
        }
        if (ev.kind === "thread-deleted") {
          delete THREADS[ev.anchor];
          const node = findNode(ev.anchor.slice("node:".length));
          const wrap = document.getElementById("n-" + (node ? node.id : ""));
          if (node && wrap) renderThread(wrap.querySelector("[data-thread]"), node);
          return;
        }
        if (ev.kind === "thread" && !ev.initial) {
          // The daemon's thread-changed delta carries only {anchor, version} —
          // re-derive from a fresh bulk fetch rather than trying to flatten one
          // thread's delta in isolation, since WcThreads.derive expects the
          // bulk shape.
          window.WebCompanion.api.fetchJSON("threads").then((raw) => {
            const derived = WcThreads.derive(raw);
            applyThread(ev.anchor, derived[ev.anchor] || null);
          });
        }
      },
    });
    setLive(true, "claude connected");
  }
```

`window.WebCompanion.init` handles reconnection and session-ended internally (`_wc/core.js`'s `startStream`/`startPolling`/`scheduleReconnect`/the `session-ended` listener that sets `document.body.classList.add("session-finished")`) — dataflow.js no longer needs its own `es.onerror`/`session-ended` wiring. If a live "reconnecting…" indicator (`setLive(false, ...)`) still matters here, **read the rest of `_wc/core.js` past what this plan's research already quoted** before assuming no connection-state signal exists — wire into whatever it actually exposes rather than reintroducing a second status tracker; if nothing suitable exists, drop the disconnected-state UI for now rather than rebuilding the transport layer just to feed it, and note that as a concern in your report.

**Note on `applyThread`:** `applyThread(anchor, info)` (existing function, around line 551) currently does `THREADS[anchor] = info;` unconditionally — check whether it already tolerates `info` being `null` before relying on the `derived[ev.anchor] || null` fallback above; if it does not, guard the call site instead of changing `applyThread`'s own contract.

**3d. The ask-form's submit call** (`fetch(BASE + "api/submit", ...)`, inside `openAskForm`'s `submit` closure — find the exact current line, since Tasks 1-2 didn't touch this file and line numbers from this plan's original research should still be close): switch to the daemon's own `api.submit`, which — like every other call in this task — carries the contract header and write token automatically, unlike a raw `fetch`:

```javascript
      try {
        await window.WebCompanion.api.submit({ anchor: anchorOf(n.id), text });
      } catch (_) {
        toast("could not send", true);
        send.disabled = false;
        return;
      }
```

Drop the old payload's `type: "comment"` field — the daemon's `/api/submit` body is `{anchor, text, images?}` only, with no `type` key at all. **Grep dataflow.js's ask-form code for any other value of `type` before removing it** (this plan's own research found only the literal `"comment"`, never `"reject"`, but confirm against the real file rather than this plan's memory of it — a real `"reject"` path would need the same JSON-encoded-into-`text` treatment `annotate/static/compat.js`'s `submit()` uses for its own multi-shape payloads, not a silent drop).

Asset loading is already solved by Task 2's `entry.js`, registered as this session's entry point instead of `dataflow.js` directly (Task 1's `ENTRY` constant is `"entry.js"`) — `dataflow.js` itself needs no changes to how it is loaded, only to what it fetches (3a/3b/3d above) and how it renders threads (`WcThreads.derive`, already global by the time `dataflow.js` runs, since `entry.js` loads it first, and `window.WebCompanion`, already global before `entry.js` even starts, since the daemon's shell page loads `_wc/core.js` first).

- [ ] **Step 4: Update `SKILL.md`**

Read the current `skills/dataflow/SKILL.md` in full first (it was not fully quoted in this plan's own research pass beyond its frontmatter description). Replace every reference to:
- Starting the skill's own server / `ensure_server.sh` → creating a daemon session via `python3 -m skills.dataflow.push --flow <path> --cwd <repo root> [--slug ...] [--title ...]`, printing the returned `url` to the user.
- The watcher/ack flow → arming via `webcompanion watch --kind dataflow --sid <sid>` (Monitor), and acking a handled event via `webcompanion ack --sid <sid> --event-id <event_id>` after appending the reply with `skills._shared.webcompanion_client.append_thread(sid, anchor, text, kind="dataflow", role="agent", source_event_id=<event_id>)` (call this from a small inline Python snippet in SKILL.md's own instructions, matching the style `annotate/references/pushing.md` already uses for its own daemon-era instructions — read that file for the exact prose/code-block conventions to match, since consistency across skills' docs is part of this program's point).
- Regenerating the diagram mid-session → re-running `push.py` with the same `--slug`, which `PATCH .../items {replace: true}` naturally overwrites.

- [ ] **Step 5: Manual smoke test against the real daemon**

No automated end-to-end test exists for this (see Testing strategy) — run one by hand:

```bash
cd /Users/petros.makris/projects/claude-annotate
python3 -c "
import json, tempfile
from pathlib import Path
doc = {'seed': 'smoke-test', 'question': 'q', 'generated_ts': 1, 'model': ['c'],
       'slices': [{'layer': 'api', 'nodes': [
           {'id': 'n1', 'layer': 'api', 'role': 'context', 'name': 'X',
            'file': 'X.java', 'line': 1, 'summary': 's', 'note': '', 'flag': None,
            'implicit': False, 'members': [], 'edges': []}]}]}
p = Path(tempfile.mktemp(suffix='.json'))
p.write_text(json.dumps(doc))
print(p)
"
# feed the printed path into:
python3 -m skills.dataflow.push --flow <printed path> --cwd $(pwd)
# open the returned url in a browser; confirm the board renders and the
# node's ✻ button opens an ask form. Then:
curl -s -X POST "<url>api/submit" -H 'Content-Type: application/json' \
  -d '{"anchor":"node:n1","type":"comment","text":"why"}'
# confirm the daemon queued it: webcompanion status should show the session
# with a pending event, or check ~/.claude/webcompanion/*/events/ directly.
```

Record the outcome in the task report; this step cannot be automated within this plan's scope (see Testing strategy) but must not be skipped — it is the only check that the asset-registration fix chosen in Step 3 actually serves `wc-threads.js` correctly in a real browser.

- [ ] **Step 6: Run the full existing suite to confirm nothing else broke**

Run: `cd /Users/petros.makris/projects/claude-annotate/.worktrees/webcompanion-cutover && python3 -m pytest skills -q`
Expected: same baseline failures as before this program started (`test_landing.py`, `test_bootstrap_guard.py`, `test_write_gate.py` — pre-existing, unrelated), plus every new test from this plan passing, minus `test_server.py`'s now-deleted tests.

- [ ] **Step 7: Commit**

```bash
cd /Users/petros.makris/projects/claude-annotate
git add -A skills/dataflow/
git commit -m "Migrate dataflow onto the webcompanion daemon; delete its private server"
```

---

## Testing strategy

- **Python (Tasks 1):** real unit tests against a fake HTTP server fixture — no real daemon
  required, no network. This is the bulk of this phase's coverage and the only part held to
  the usual TDD bar.
- **JS (Tasks 2-3):** no unit test framework exists for skill static JS anywhere in this repo
  today (`vscode-plugin/` has its own Jest-style suite, scoped to that separate package only).
  Introducing one for a handful of small files is out of scope for this phase — YAGNI, and a
  decision for a future phase or a dedicated task if the pattern repeats enough to justify it.
  Coverage here is: careful, cited reuse of `annotate`'s already-proven loader pattern
  (`entry.js`), and the manual smoke test in Task 3 Step 5, which is mandatory precisely
  because nothing else exercises this code path.
- **Deletion (Task 3):** `test_server.py`'s coverage is either deleted outright (it tested code
  that no longer exists) or repointed at `flow.py`'s own test file, decided per-test in Step 1
  — never silently dropped without that check.

## Final verification

- [ ] `python3 -m pytest skills -q` — same pre-existing baseline failures only, no new ones.
- [ ] Manual smoke test (Task 3, Step 5) completed and recorded.
- [ ] Grep confirms nothing under `skills/dataflow/` still imports `skills._shared.web_companion` (the old engine) — `grep -rn "_shared.web_companion" skills/dataflow/` should return nothing outside of `skills/dataflow/static/wc-threads.js`'s copy, which is a static asset, not a Python import, so it will not match anyway; confirm with `grep -rn "from skills._shared.web_companion\|import skills._shared.web_companion" skills/dataflow/`.
- [ ] `webcompanion doctor` still reports healthy (this phase must not have left the daemon in a bad state from the smoke test's real session — finish or cancel that test session afterward: `curl -X POST "<url>api/finish"`).
