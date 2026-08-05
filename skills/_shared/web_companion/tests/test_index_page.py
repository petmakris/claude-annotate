# GENERATED FILE — DO NOT EDIT. Source: github.com/petmakris/web-companion
"""The workspace index has to work after a reboot, from another device.

A workspace outlives every Claude session that touched it and survives a
restart of the server. The index is the only way back in when the session that
created it is long gone, so these guard the three things that makes possible:
the resume command, the two copyable links, and the fact that closed
workspaces still show but offer no dead-end resume.

Markup/script checks for the page, live HTTP for the endpoint it depends on.
"""
import io
import json
import threading
import urllib.request
from pathlib import Path

import pytest

import skills._shared.web_companion.server as server_mod
from skills._shared.web_companion.handlers import HandlersProtocol

REPO = Path(__file__).resolve().parents[4]
SESSIONS_HTML = REPO / "skills" / "_shared" / "web_companion" / "static" / "sessions.html"

TEST_PORT_RANGE = range(56200, 56240)


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


@pytest.fixture
def port(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / ".claude" / "test_skill").mkdir(parents=True, exist_ok=True)

    started = threading.Event()
    holder = {}
    original_write = server_mod.sys.stdout.write

    def _patched(s):
        if "server-started" in s:
            try:
                holder["port"] = json.loads(s.strip())["port"]
            except Exception:
                pass
            started.set()
        return original_write(s)

    server_mod.sys.stdout.write = _patched
    threading.Thread(
        target=server_mod.run,
        kwargs=dict(skill_name="test_skill", port_range=TEST_PORT_RANGE,
                    handlers=_StubHandlers(), static_dirs=[],
                    shutdown_after_seconds=300),
        daemon=True,
    ).start()
    started.wait(timeout=5)

    server_mod.sys.stdout.write = original_write
    assert "port" in holder
    return holder["port"]


def test_whoami_carries_what_the_index_cannot_derive(port):
    """The page builds a shareable link, and window.location can't give it —
    the owner browses on localhost."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/whoami", timeout=5) as r:
        info = json.loads(r.read())
    assert info["port"] == port
    assert "public_host" in info
    assert info["shareable"] is False, \
        "a loopback-bound server must not advertise a shareable host"


def test_shareable_is_true_once_the_bind_is_opened(monkeypatch):
    """shareable is the page's cue to offer the second copy button at all."""
    monkeypatch.setenv("WEBCOMPANION_BIND", "0.0.0.0")
    monkeypatch.setenv("WEBCOMPANION_PUBLIC_HOST", "somehost")
    assert server_mod._resolve_bind_addr() == "0.0.0.0"
    assert server_mod._resolve_public_host() == "somehost"


# ── The page itself ───────────────────────────────────────────────────────

def test_the_index_offers_a_resume_command():
    """The one string that gets a fresh Claude session back into a workspace
    whose original session is gone."""
    html = SESSIONS_HTML.read_text()
    assert "SKILL_CMD" in html, "no resume command on the index"
    assert '" resume "' in html, "the resume command lost its verb"
    assert "/health" in html, \
        "the command prefix must follow the serving skill, not be hardcoded"


def test_closed_workspaces_get_no_resume_command():
    """Attaching to a closed workspace reopens the directory but still renders
    'this round is closed', so offering the command would be a dead end."""
    html = SESSIONS_HTML.read_text()
    assert 'row.status !== "done"' in html, \
        "closed workspaces are being offered a resume command"


def test_both_links_are_copyable():
    html = SESSIONS_HTML.read_text()
    assert "localUrl" in html and "publicUrl" in html, \
        "the index does not build both links"
    assert "HOSTS.shareable" in html, \
        "the shareable link is offered even when there is nothing to share"


def test_copy_works_without_a_secure_context():
    """navigator.clipboard needs HTTPS or localhost. Browsing this page from
    another device over plain HTTP is exactly when copying matters most."""
    html = SESSIONS_HTML.read_text()
    assert "window.isSecureContext" in html, "no secure-context check before using the clipboard API"
    assert "execCommand" in html, "no fallback for a non-secure context"


def test_copying_does_not_navigate_away():
    html = SESSIONS_HTML.read_text()
    assert "stopPropagation" in html, \
        "a copy click also triggers the row's open handler"


def test_closed_workspaces_are_still_listed():
    """'Deleted' is not a state the server keeps — retention already removes
    those. Closed ones must remain browsable."""
    html = SESSIONS_HTML.read_text()
    assert 'data-seg="open"' in html, "no way to hide closed workspaces"
    assert 'data-seg="all"' in html, "the all-inclusive default is gone"


def test_the_local_link_follows_the_origin_you_are_browsing():
    """Regression: behind a TLS-terminating local proxy (devdomains/Caddy),
    rebuilding the origin as "<protocol>//localhost:<port>" produced
    https://localhost:3080 — the raw server speaks plain HTTP there, so the
    copied link failed to load while looking perfectly plausible."""
    html = SESSIONS_HTML.read_text()
    assert "location.origin" in html, \
        "the local link is being reconstructed instead of taken from the origin"
    assert '"//localhost:"' not in html, \
        "the local link still hardcodes localhost, which breaks behind a proxy"
