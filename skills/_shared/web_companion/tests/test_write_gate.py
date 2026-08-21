"""The read/write split: anyone may read a shared link, only the owner writes.

The server is meant to be safe to expose on a LAN or a Tailnet. That is only
true if every state-changing route is gated and every read route is not, so
these tests drive the real HTTP surface rather than inspecting the source.

Non-loopback clients are simulated by patching _is_loopback, since a test
cannot easily originate a connection from another address.
"""
import io
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import skills._shared.web_companion.server as server_mod
from skills._shared.web_companion.handlers import HandlersProtocol
from skills._shared.web_companion.sessions import Registry

TEST_PORT_RANGE = range(56100, 56140)
TOKEN = "test-token-value"


class _StubHandlers(HandlersProtocol):
    def serve_root(self, handler, dirs):
        handler._send_text(200, "root")

    def serve_poll(self, handler, dirs):
        handler._send_json(200, {"events": []})

    def serve_data(self, handler, dirs, query):
        handler._send_text(404, "not found")

    def handle_submit(self, handler, dirs, payload):
        handler._send_text(200, "ok")

    def create_session_extra(self, payload, dirs):
        return {}


def _start_server(tmp_path: Path, monkeypatch, port_range=None):
    # Every call binds a port for the life of the test session, so a second test
    # module reusing this helper drains the range and the failure surfaces here
    # as "server did not start in time" — in THIS file's tests, not the new
    # file's. Callers outside this module pass their own range.
    port_range = port_range if port_range is not None else TEST_PORT_RANGE
    monkeypatch.setenv("WEBCOMPANION_TOKEN", TOKEN)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    skill_name = "test_skill"
    (tmp_path / ".claude" / skill_name).mkdir(parents=True, exist_ok=True)

    registry_holder = {}
    original_init = Registry.__init__

    def _capture_init(self, state_root):
        original_init(self, state_root)
        registry_holder["registry"] = self

    Registry.__init__ = _capture_init

    started = threading.Event()
    port_holder = {}
    original_write = server_mod.sys.stdout.write
    buf = io.StringIO()

    def _patched_write(s):
        buf.write(s)
        if '"type": "server-started"' in s or '"type":"server-started"' in s:
            try:
                port_holder["port"] = json.loads(s.strip())["port"]
            except Exception:
                pass
            started.set()
        return original_write(s)

    server_mod.sys.stdout.write = _patched_write
    threading.Thread(
        target=server_mod.run,
        kwargs=dict(skill_name=skill_name, port_range=port_range,
                    handlers=_StubHandlers(), static_dirs=[],
                    shutdown_after_seconds=300),
        daemon=True,
    ).start()
    started.wait(timeout=5)
    Registry.__init__ = original_init
    server_mod.sys.stdout.write = original_write
    assert "port" in port_holder, "server did not start in time"
    return port_holder["port"], buf.getvalue()


def _request(port, path, method="GET", token=None, body=b"", headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    if token:
        req.add_header(server_mod.WRITE_TOKEN_HEADER, token)
    if method == "POST":
        req.data = body
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def port(tmp_path, monkeypatch):
    p, _ = _start_server(tmp_path, monkeypatch)
    return p


# ── The predicate itself ──────────────────────────────────────────────────

@pytest.mark.parametrize("addr,expected", [
    ("127.0.0.1", True),
    ("127.0.0.2", True),      # macOS hands these out too
    ("::1", True),
    ("192.168.6.7", False),   # LAN
    ("100.103.4.112", False), # Tailscale
    ("not-an-ip", False),     # never fail open on a malformed address
])
def test_loopback_detection(addr, expected):
    assert server_mod._is_loopback(addr) is expected


def test_token_is_minted_when_not_supplied(monkeypatch):
    monkeypatch.delenv("WEBCOMPANION_TOKEN", raising=False)
    a, b = server_mod._resolve_write_token(), server_mod._resolve_write_token()
    assert a and b and a != b, "token must be unguessable and per-call fresh"
    assert len(a) >= 32


# ── Reads stay open ───────────────────────────────────────────────────────

def test_a_shared_link_can_still_be_read(port, monkeypatch):
    monkeypatch.setattr(server_mod, "_is_loopback", lambda addr: False)
    assert _request(port, "/health")[0] == 200
    assert _request(port, "/api/whoami")[0] == 200


def test_whoami_reports_the_mode(port, monkeypatch):
    status, body = _request(port, "/api/whoami")
    assert status == 200 and json.loads(body)["writable"] is True

    monkeypatch.setattr(server_mod, "_is_loopback", lambda addr: False)
    status, body = _request(port, "/api/whoami")
    assert status == 200 and json.loads(body)["writable"] is False

    status, body = _request(port, "/api/whoami", token=TOKEN)
    assert status == 200 and json.loads(body)["writable"] is True


# ── Writes are gated ──────────────────────────────────────────────────────

WRITE_ROUTES = [
    "/api/sessions",
    # The one route that destroys data. It was the only POST missing from this
    # list — gated in practice by the blanket check, but pinned by nothing, so
    # a refactor could unguard it in silence.
    "/api/sessions/delete",
    # Runs a program on the host with a path the caller supplies. Reachable
    # from a shared link it would be remote file-opening, so the blanket gate
    # is doing real work here and is pinned rather than assumed.
    "/api/open",
    "/api/cancel_for_claude_session",
    "/s/000000-000000-0000000000000000/api/submit",
    "/s/000000-000000-0000000000000000/api/finish",
    "/s/000000-000000-0000000000000000/api/cancel",
    "/s/000000-000000-0000000000000000/api/upload",
    "/s/000000-000000-0000000000000000/api/threads/delete",
]


@pytest.mark.parametrize("route", WRITE_ROUTES)
def test_every_write_route_is_refused_without_the_token(port, monkeypatch, route):
    monkeypatch.setattr(server_mod, "_is_loopback", lambda addr: False)
    status, body = _request(port, route, method="POST", body=b"{}")
    assert status == 403, f"{route} accepted a write from a shared link"
    assert "read-only" in body


@pytest.mark.parametrize("route", WRITE_ROUTES)
def test_the_token_gets_past_the_gate(port, monkeypatch, route):
    """Past the gate, not necessarily to a 200 — an unknown session id is a
    404 and an empty create payload is a 400. What matters is that neither is
    the 403 the gate produces."""
    monkeypatch.setattr(server_mod, "_is_loopback", lambda addr: False)
    status, _ = _request(port, route, method="POST", token=TOKEN, body=b"{}")
    assert status != 403, f"{route} rejected a correctly-tokened write"


def test_a_wrong_token_is_still_refused(port, monkeypatch):
    monkeypatch.setattr(server_mod, "_is_loopback", lambda addr: False)
    status, _ = _request(port, "/api/sessions", method="POST",
                         token=TOKEN + "x", body=b"{}")
    assert status == 403


def test_loopback_writes_without_any_token(port):
    """The Claude session driving the server talks over loopback and has no
    token — it must keep working with no configuration."""
    status, _ = _request(port, "/api/sessions", method="POST", body=b"{}")
    assert status == 400, "expected the route's own validation, not the gate"


# ── The workspace index is not part of a shared link ──────────────────────

def test_the_index_is_owner_only(port, monkeypatch):
    monkeypatch.setattr(server_mod, "_is_loopback", lambda addr: False)
    assert _request(port, "/")[0] == 403
    assert _request(port, "/api/sessions?scope=all")[0] == 403
    # ...and reachable again with the token.
    assert _request(port, "/api/sessions?scope=all", token=TOKEN)[0] == 200


# ── A website you visit is not the owner ──────────────────────────────────
#
# Loopback IS the owner, and JavaScript on any page runs from loopback. So
# the gate above cannot tell the sessions index apart from evil.example — and
# `text/plain` makes a POST a CORS "simple request", which the browser sends
# with no preflight to block it. Without a look at where the request came
# from, a page you merely visit can delete every workspace you own.

CSRF_ROUTE = "/api/sessions/delete"


def test_a_cross_site_write_is_refused(port):
    status, body = _request(port, CSRF_ROUTE, method="POST", body=b'{"key":"x"}',
                            headers={"Sec-Fetch-Site": "cross-site",
                                     "Origin": "https://evil.example"})
    assert status == 403, "a hostile page's write was accepted"
    assert "cross-site" in body


@pytest.mark.parametrize("route", WRITE_ROUTES)
def test_every_write_route_refuses_cross_site(port, route):
    status, _ = _request(port, route, method="POST", body=b"{}",
                         headers={"Sec-Fetch-Site": "cross-site"})
    assert status == 403, f"{route} accepted a cross-site write"


def test_the_index_page_itself_still_writes(port):
    """Same-origin is how the sessions page talks to its own server."""
    status, _ = _request(port, "/api/sessions", method="POST", body=b"{}",
                         headers={"Sec-Fetch-Site": "same-origin",
                                  "Origin": f"http://127.0.0.1:{port}"})
    assert status == 400, "expected the route's own validation, not a CSRF refusal"


def test_a_client_that_sends_neither_header_is_unaffected(port):
    """curl, and the Claude session driving the server, send no Origin and no
    Sec-Fetch-Site. Requiring either would break every non-browser caller."""
    status, _ = _request(port, "/api/sessions", method="POST", body=b"{}")
    assert status == 400


def test_a_tls_terminating_proxy_is_still_same_origin(port):
    """The owner browses https://annotate, Caddy forwards to localhost:3080
    preserving Host. The browser's Origin is therefore https://annotate while
    the server speaks plain http — comparing full origin strings would call
    that cross-site and lock the owner out of their own page. Host is what
    matters; scheme and port are the proxy's business."""
    status, _ = _request(port, "/api/sessions", method="POST", body=b"{}",
                         headers={"Origin": "https://annotate",
                                  "Host": "annotate"})
    assert status == 400, "the reverse-proxied owner was refused"


def test_an_old_browser_without_sec_fetch_site_is_still_checked(port):
    """Sec-Fetch-Site is the reliable signal, but a browser too old to send it
    still sends Origin — so a foreign Origin alone is enough to refuse."""
    status, _ = _request(port, CSRF_ROUTE, method="POST", body=b'{"key":"x"}',
                         headers={"Origin": "https://evil.example"})
    assert status == 403


# ── The credential must not leak through the log ──────────────────────────

def test_the_token_is_not_written_to_stdout(tmp_path, monkeypatch):
    _, printed = _start_server(tmp_path, monkeypatch)
    assert TOKEN not in printed, "the write token reached the server log"
    info = json.loads((tmp_path / ".claude" / "test_skill" / "server.json").read_text())
    assert info["write_token"] == TOKEN, "server.json must carry it for the owner"
    mode = (tmp_path / ".claude" / "test_skill" / "server.json").stat().st_mode & 0o777
    assert mode == 0o600, f"server.json holds a credential but is mode {mode:o}"
