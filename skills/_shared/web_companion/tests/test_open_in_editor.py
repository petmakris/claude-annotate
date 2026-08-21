"""`POST /api/open` — the page asks the SERVER to open a file, not the OS.

A browser cannot hand a path to a native application: `file://` is refused from
an http origin, and the browser would render the file rather than open an editor.
The old answer was a `jetbrains://` URI built in the page, which had to carry the
IDE's project NAME — guessed from the workspace directory's basename. That guess
is wrong whenever a project's name differs from its folder's (an IntelliJ project
in `montblanc-worktrees/PMP-272` is named `montblanc`), and the failure was
silent: the IDE logged the request and did nothing.

The server has no such limit, so it runs the opener itself and the launcher
resolves the project from the file. These tests pin the two things that matter
once a web request can start a process: it opens only files inside the session's
own root, and it reports why when it will not.
"""
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import skills._shared.web_companion.server as server_mod
from skills._shared.web_companion.tests.test_write_gate import (
    TOKEN, _request, _start_server,
)


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A running server plus a session whose workspace root holds one file."""
    launched = []
    monkeypatch.setattr(
        server_mod.subprocess, "Popen",
        lambda cmd, **kw: launched.append(list(cmd)) or _DummyProc())

    # Its own range: every started server holds its port for the whole session,
    # so sharing test_write_gate's would drain it and fail THAT file's tests.
    port, _ = _start_server(tmp_path, monkeypatch, port_range=range(56140, 56180))

    root = tmp_path / "workspace"
    (root / "src").mkdir(parents=True)
    (root / "src" / "service.py").write_text("def validate(order):\n    return True\n")
    # A file that exists, but OUTSIDE the workspace — the thing a `..` must not reach.
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "secrets.env").write_text("TOKEN=hunter2\n")

    status, body = _request(
        port, "/api/sessions", method="POST", token=TOKEN,
        body=json.dumps({"cwd": str(root), "title": "T", "slug": "ws"}).encode())
    assert status == 200, body
    return port, json.loads(body), launched, tmp_path


class _DummyProc:
    pid = 1234


def _open(port, **payload):
    return _request(port, "/api/open", method="POST", token=TOKEN,
                    body=json.dumps(payload).encode())


def test_a_file_inside_the_workspace_is_opened(server):
    port, _sess, launched, _tmp = server
    status, body = _open(port, key="ws", file="src/service.py", line=2)
    assert status == 200, body
    assert launched, "nothing was launched"
    cmd = launched[0]
    assert cmd[-1].endswith("src/service.py")
    # The line rides along when the launcher can take one; either way the file does.
    if "--line" in cmd:
        assert cmd[cmd.index("--line") + 1] == "2"


def test_the_project_name_is_never_part_of_it(server):
    """The whole point of moving this server-side: the launcher resolves the
    project from the file's own location, so no name is guessed or sent."""
    port, _sess, launched, _tmp = server
    assert _open(port, key="ws", file="src/service.py", line=2)[0] == 200
    assert not any("jetbrains://" in part for part in launched[0])


def test_a_path_climbing_out_of_the_workspace_is_refused(server):
    port, _sess, launched, _tmp = server
    status, body = _open(port, key="ws", file="../elsewhere/secrets.env", line=1)
    assert status == 400
    assert "not a file inside this workspace" in body
    assert not launched, "a file outside the workspace was opened"


def test_an_absolute_path_cannot_escape_either(server):
    """`root / "/etc/passwd"` is `/etc/passwd` in pathlib — an absolute right-hand
    side discards the root entirely, so this needs its own case, not just `..`."""
    port, _sess, launched, tmp = server
    status, body = _open(port, key="ws", file=str(tmp / "elsewhere" / "secrets.env"))
    assert status == 400
    assert "not a file inside this workspace" in body
    assert not launched


def test_a_symlink_pointing_out_is_refused(server):
    port, _sess, launched, tmp = server
    link = tmp / "workspace" / "src" / "escape.env"
    link.symlink_to(tmp / "elsewhere" / "secrets.env")
    status, body = _open(port, key="ws", file="src/escape.env")
    assert status == 400, "a symlink walked out of the workspace"
    assert not launched


def test_a_missing_file_is_refused_rather_than_launched(server):
    port, _sess, launched, _tmp = server
    status, _ = _open(port, key="ws", file="src/does-not-exist.py")
    assert status == 400
    assert not launched


def test_an_unknown_session_is_a_404(server):
    port, _sess, launched, _tmp = server
    assert _open(port, key="no-such-workspace", file="src/service.py")[0] == 404
    assert not launched


def test_a_missing_file_field_is_a_400(server):
    port, _sess, launched, _tmp = server
    assert _open(port, key="ws")[0] == 400
    assert not launched
