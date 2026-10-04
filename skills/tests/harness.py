"""What the browser and daemon-backed tests share: a private webcompanion
daemon, a Chromium per worker, the strict switch, and the timeout scale.

The daemon-backed tests used to find the daemon through the developer's own
~/.claude/webcompanion/config.json. On CI there is none, so all of them
skipped and the run still read green; locally they all landed on the one live
daemon, fifteen xdist workers at once, and under load the setup alone timed
out. Each worker now starts its own daemon from the pinned `webcompanion`
package, under a throwaway HOME, on a free port. Nothing a test writes reaches
the daemon anyone is reading, and no two workers share one.

CLAUDE_ANNOTATE_STRICT_TESTS=1 (set by CI and the pre-push hook) turns every
"cannot run here" skip — no playwright, no webcompanion — into a failure, so a
missing dependency cannot pass for a green run.

PYTEST_TIMEOUT_SCALE multiplies the explicit waits (`T(3000)`), for a loaded
machine or a slow runner. It never shortens one.
"""
from __future__ import annotations

import contextlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

STRICT_ENV = "CLAUDE_ANNOTATE_STRICT_TESTS"
CONFIG_TAIL = (".claude", "webcompanion", "config.json")
_ORIGINAL_HOME = os.environ.get("HOME")


@contextlib.contextmanager
def original_home():
    """HOME as it was when the run started, for the duration of the block."""
    saved = os.environ.get("HOME")
    if _ORIGINAL_HOME is not None:
        os.environ["HOME"] = _ORIGINAL_HOME
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved


def strict() -> bool:
    return os.environ.get(STRICT_ENV, "") not in ("", "0")


def unavailable(reason: str, *, module: bool = False):
    """Skip — or, under CLAUDE_ANNOTATE_STRICT_TESTS, fail."""
    if strict():
        pytest.fail(f"{reason} ({STRICT_ENV} is set, so this is an error, not a skip)",
                    pytrace=False)
    pytest.skip(reason, allow_module_level=module)


def require_playwright():
    """The module-level guard every browser suite opens with."""
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        unavailable("browser suite: pip install playwright", module=True)


def timeout_scale() -> float:
    try:
        return max(1.0, float(os.environ.get("PYTEST_TIMEOUT_SCALE", "1")))
    except ValueError:
        return 1.0


def T(timeout: float) -> float:
    """An explicit timeout (Playwright's ms, or a subprocess's seconds),
    scaled by PYTEST_TIMEOUT_SCALE."""
    return timeout * timeout_scale()


_TRANSITIONS_DONE = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return true;
  // getAnimations() flushes pending style first, so a transition the last
  // action triggered already exists here even if no frame has painted yet.
  return el.getAnimations({subtree: true}).every(
    (a) => !(a instanceof CSSTransition) || (a.playState !== 'running' && !a.pending));
}"""


def transitions_done(page, selector: str = "body", timeout: float = 5000) -> None:
    """Wait until no CSS transition is running under `selector` — the
    condition a fixed "let the 160ms transition land" sleep stood in for."""
    page.wait_for_function(_TRANSITIONS_DONE, arg=selector, timeout=T(timeout))


# ── the private daemon ──────────────────────────────────────────────────────


def _daemon_command(args=("serve",)) -> list[str] | None:
    """How to run `webcompanion <args>`: an explicit override, the package in
    this interpreter (pinned in requirements-test.txt), or the CLI on PATH."""
    override = os.environ.get("WEBCOMPANION_TEST_BIN")
    if override:
        return [override, *args]
    try:
        import webcompanion.cli  # noqa: F401
    except ImportError:
        found = shutil.which("webcompanion")
        return [found, *args] if found else None
    return [sys.executable, "-c",
            "import sys; from webcompanion.cli import main; sys.exit(main(sys.argv[1:]))",
            *args]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class Daemon:
    """A running private daemon. `cfg` is the config.json it was started from."""

    def __init__(self, home: Path, cfg: dict, proc: subprocess.Popen, log: Path):
        self.home = home
        self.cfg = cfg
        self.proc = proc
        self.log = log
        self.config_path = home.joinpath(*CONFIG_TAIL)
        self.base = f"http://127.0.0.1:{cfg['port']}"

    def call(self, method: str, path: str, body=None):
        """One request with the owner token, the way the skills' clients send
        it. JSON in, JSON (or text) out; an HTTP error raises."""
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-WebCompanion-Contract", "1")
        req.add_header("X-WebCompanion-Token", self.cfg["token"])
        with urllib.request.urlopen(req, timeout=10 * timeout_scale()) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip().startswith(("{", "[")) else raw

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        """Run a `webcompanion` subcommand against this daemon, as a user
        would from a shell whose config names it. Raises on a non-zero exit."""
        r = subprocess.run(_daemon_command(args), env=dict(os.environ, HOME=str(self.home)),
                           capture_output=True, text=True, timeout=20 * timeout_scale())
        if r.returncode != 0:
            raise AssertionError(f"webcompanion {' '.join(args)} exited {r.returncode}:\n"
                                 f"{r.stdout}{r.stderr}")
        return r

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()


def start_daemon() -> Daemon:
    cmd = _daemon_command()
    if cmd is None:
        unavailable("no webcompanion to start a private daemon from: "
                    "uv run --with-requirements requirements-test.txt, "
                    "or pipx install webcompanion")
    home = Path(tempfile.mkdtemp(prefix="wc-test-home-"))
    cfg_path = home.joinpath(*CONFIG_TAIL)
    cfg_path.parent.mkdir(parents=True)
    env = dict(os.environ, HOME=str(home))
    last = ""
    # A port picked here can be taken before the daemon binds it, by another
    # worker doing the same thing; `serve` then refuses loudly and we retry.
    for _ in range(5):
        cfg = {"port": _free_port(), "token": secrets.token_urlsafe(24),
               # Not loopback-only: the guest test needs a LAN address that
               # `_is_owner` cannot mistake for the owner.
               "bind": "0.0.0.0", "idle_expiry_hours": None}
        fd = os.open(str(cfg_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(cfg, f)
        log = home / "daemon.log"
        with open(log, "wb") as out:
            proc = subprocess.Popen(cmd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, cwd=str(home))
        d = Daemon(home, cfg, proc, log)
        deadline = time.monotonic() + 20 * timeout_scale()
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                urllib.request.urlopen(d.base + "/health", timeout=2).read()
                return d
            except (urllib.error.URLError, OSError):
                time.sleep(0.05)
        d.stop()
        last = log.read_text(errors="replace")
    pytest.fail(f"the private webcompanion daemon never answered /health:\n{last}",
                pytrace=False)


def point_clients_at(daemon: Daemon, monkeypatch) -> None:
    """Make in-process clients and child processes read this daemon's config.

    HOME covers anything that resolves `~` at call time and every subprocess.
    A module that resolved the path once at import keeps the old one, so any
    already-imported `skills.*` attribute holding a .../webcompanion/config.json
    Path is repointed too — whichever client code path is in use."""
    monkeypatch.setenv("HOME", str(daemon.home))
    for name, mod in list(sys.modules.items()):
        if not name.startswith("skills.") or mod is None:
            continue
        for attr, value in list(vars(mod).items()):
            if isinstance(value, Path) and value.parts[-3:] == CONFIG_TAIL \
                    and value != daemon.config_path:
                monkeypatch.setattr(mod, attr, daemon.config_path)
