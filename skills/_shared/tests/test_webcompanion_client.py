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


def test_create_or_attach_sends_supersede_on_create(daemon):
    _FakeDaemon.script = [(201, {"sid": "s1", "slug": "s1", "kind": "dataflow", "url": "/s/s1/", "token": "tok"})]
    wc.create_or_attach("dataflow", "/repo", title="T", supersede=True)
    method, path, headers, body = _FakeDaemon.seen[0]
    assert method == "POST" and path == "/api/sessions"
    assert body == {"kind": "dataflow", "cwd": "/repo", "title": "T", "supersede": True}


def test_create_or_attach_omits_supersede_by_default(daemon):
    _FakeDaemon.script = [(201, {"sid": "s1", "slug": "s1", "kind": "dataflow", "url": "/s/s1/", "token": "tok"})]
    wc.create_or_attach("dataflow", "/repo", title="T")
    body = _FakeDaemon.seen[0][3]
    assert "supersede" not in body


def test_create_or_attach_does_not_send_supersede_on_attach_by_slug(daemon):
    _FakeDaemon.script = [
        (200, [{"sid": "s1", "slug": "my-slug", "kind": "dataflow"}]),
    ]
    res = wc.create_or_attach("dataflow", "/repo", slug="my-slug", supersede=True)
    assert res["sid"] == "s1"
    # Only the GET lookup happened — no POST /api/sessions body to inspect,
    # so nothing carried `supersede` onto a path that creates nothing.
    assert len(_FakeDaemon.seen) == 1
    assert _FakeDaemon.seen[0][0] == "GET"


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
    # The anchor is percent-encoded (`:` included) before it goes into the
    # URL path — the daemon `unquote()`s this segment on its side, so the
    # round trip restores "node:1" exactly.
    assert method == "POST" and path == "/s/s1/threads/node%3A1?kind=dataflow"
    assert body == {"text": "hello", "role": "agent", "source_event_id": "e1"}


def test_append_thread_quotes_an_anchor_with_colons_and_dashes(daemon):
    # Phase 4's interactive-review anchors look like `path:R:42-58` — a shape
    # dataflow's own `node:<id>` anchors never exercise, so this has to be
    # tested directly rather than relying on dataflow's coverage.
    _FakeDaemon.script = [(200, {"appended": True, "version": 1})]
    anchor = "src/Foo.java:R:42-58"
    wc.append_thread("s1", anchor, "hello", kind="interactive-review")
    method, path, headers, body = _FakeDaemon.seen[0]
    from urllib.parse import unquote
    encoded = path.split("/threads/", 1)[1].split("?", 1)[0]
    assert unquote(encoded) == anchor
    assert encoded != anchor  # actually percent-encoded, not passed through raw


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
