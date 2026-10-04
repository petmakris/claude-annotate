"""Every daemon failure is one DaemonError, and every push CLI reports it cleanly.

The push mains used to catch only DaemonNotConfigured, DaemonUnreachable and
ContractMismatch. A 4xx/5xx from the daemon (a bare RuntimeError) or a
config.json that does not parse (a bare JSONDecodeError) went straight past
them and ended the command in a raw traceback.
"""
import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from skills._shared import webcompanion_client as wc

PUSH_MODULES = [
    "skills.dataflow.push",
    "skills.walkthrough.push",
    "skills.ask_diff.push",
    "skills.deck.push",
]


class _Refuses(BaseHTTPRequestHandler):
    def _handle(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        data = json.dumps({"error": "item too large"}).encode()
        self.send_response(413)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle

    def log_message(self, *a):
        pass


@pytest.fixture
def refusing_daemon(tmp_path, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _Refuses)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"port": server.server_address[1], "token": "tok"}))
    monkeypatch.setattr(wc, "_CONFIG_PATH", cfg)
    yield
    server.shutdown()


@pytest.fixture
def bad_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text("{not json")
    monkeypatch.setattr(wc, "_CONFIG_PATH", cfg)


def test_an_http_error_is_a_daemon_error_with_its_status(refusing_daemon):
    with pytest.raises(wc.DaemonHTTPError) as info:
        wc.put_items("s1", {"a": 1}, kind="dataflow")
    assert isinstance(info.value, wc.DaemonError)
    assert info.value.status == 413
    assert "item too large" in str(info.value)


def test_a_malformed_config_is_a_daemon_error(bad_config):
    with pytest.raises(wc.DaemonConfigInvalid) as info:
        wc.load_config()
    assert isinstance(info.value, wc.DaemonError)
    assert "config.json" in str(info.value)


def test_a_config_without_a_port_is_a_daemon_error(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"token": "tok"}))
    monkeypatch.setattr(wc, "_CONFIG_PATH", cfg)
    with pytest.raises(wc.DaemonConfigInvalid):
        wc.put_items("s1", {}, kind="dataflow")


def test_every_failure_class_shares_the_base():
    for cls in (wc.DaemonNotConfigured, wc.DaemonUnreachable, wc.ContractMismatch,
                wc.DaemonHTTPError, wc.DaemonConfigInvalid):
        assert issubclass(cls, wc.DaemonError), cls


def _talks_to_the_daemon(*a, **k):
    # Stands in for each skill's push(): whatever it does first, it reaches
    # the daemon through the shared client.
    wc.put_items("s1", {"a": 1}, kind="x")
    raise AssertionError("the daemon was expected to refuse")


@pytest.mark.parametrize("modname", PUSH_MODULES)
@pytest.mark.parametrize("fixture", ["refusing_daemon", "bad_config"])
def test_every_push_main_reports_a_daemon_failure_in_one_line(
        modname, fixture, request, monkeypatch, capsys):
    request.getfixturevalue(fixture)
    mod = importlib.import_module(modname)
    monkeypatch.setattr(mod, "push", _talks_to_the_daemon)
    argv = {
        "skills.dataflow.push": ["--flow", "f.json", "--cwd", "/repo"],
        "skills.walkthrough.push": ["--steps", "s.json", "--cwd", "/repo"],
        "skills.ask_diff.push": ["--pr", "1", "--cwd", "/repo",
                                 "--claude-session-id", "c"],
        "skills.deck.push": ["--deck", "d.html", "--cwd", "/repo"],
    }[modname]
    rc = mod.main(argv)
    err = capsys.readouterr().err
    assert rc == wc.EXIT_FAILURE
    prog = modname.split(".")[1] + " push: "
    assert err.startswith(prog), err
    assert "Traceback" not in err
