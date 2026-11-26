# /// script
# requires-python = ">=3.9"
# ///
"""daemon.py: a webcompanion daemon of the clip's own, on a scratch HOME and port.

A clip never talks to the daemon a person uses every day. It starts its own:
HOME points at a scratch folder, so the daemon reads its config, keeps its
sessions and writes its log there, and listens on a port the clip picks.

    uv run tools/promo/daemon.py start --home .scratch/home --port 19101
    uv run tools/promo/daemon.py env   --home .scratch/home     # prints HOME=...
    uv run tools/promo/daemon.py stop  --home .scratch/home

In a clip script:

    from daemon import Daemon
    with Daemon(".scratch/home-ca01", 19101) as d:
        d.run(["claude-annotate", "push", "--blocks", f, "--cwd", repo])  # HOME set
        url = d.url("/s/<slug>/")

`start` refuses a port something already listens on and names the holder.
`stop` kills the daemon by the PID it saved, never by name.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR: a port still closing (TIME_WAIT) after the last run is free.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def holder(port: int) -> str:
    lsof = shutil.which("lsof")
    if not lsof:
        return "unknown"
    out = subprocess.run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                         capture_output=True, text=True).stdout.splitlines()
    return out[1] if len(out) > 1 else "unknown"


class Daemon:
    def __init__(self, home, port: int, token="demo-token"):
        self.home = Path(home).resolve()
        self.port = int(port)
        self.token = token
        self.state = self.home / ".claude" / "webcompanion"
        self.pidfile = self.home / "daemon.pid"

    # ── environment ────────────────────────────────────────────────────
    def env(self, extra=None) -> dict:
        """The environment for every command that must reach this daemon."""
        env = dict(os.environ)
        # Playwright finds its browsers under HOME; a scratch HOME has none.
        if "PLAYWRIGHT_BROWSERS_PATH" not in env:
            cache = ("Library/Caches/ms-playwright" if sys.platform == "darwin"
                     else ".cache/ms-playwright")
            env["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.path.expanduser("~"), cache)
        env["HOME"] = str(self.home)
        env["PATH"] = str(REPO / "bin") + os.pathsep + env.get("PATH", "")
        env["CLAUDE_ANNOTATE_NO_UPDATE"] = "1"
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        env.update(extra or {})
        return env

    def run(self, cmd, check=True, **kw):
        kw.setdefault("capture_output", True)
        kw.setdefault("text", True)
        p = subprocess.run(cmd, env=self.env(kw.pop("env", None)), **kw)
        if check and p.returncode:
            raise RuntimeError("%s failed (%d): %s" % (cmd[0], p.returncode, p.stderr.strip()))
        return p

    def url(self, path="/") -> str:
        return "http://127.0.0.1:%d%s" % (self.port, path)

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self):
        wc = shutil.which("webcompanion")
        if not wc:
            sys.exit("daemon.py: webcompanion is not installed (pipx install webcompanion)")
        if not port_free(self.port):
            sys.exit("daemon.py: port %d is taken: %s" % (self.port, holder(self.port)))
        self.state.mkdir(parents=True, exist_ok=True)
        cfg = self.state / "config.json"
        cfg.write_text(json.dumps({"port": self.port, "token": self.token,
                                   "bind": "127.0.0.1", "idle_expiry_hours": None}) + "\n")
        os.chmod(cfg, 0o600)
        log = open(self.home / "daemon.log", "ab")
        p = subprocess.Popen([wc, "serve"], env=self.env(), stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        self.pidfile.write_text(str(p.pid))
        for _ in range(50):
            if not port_free(self.port):
                return self
            if p.poll() is not None:
                sys.exit("daemon.py: webcompanion serve exited; see %s" % (self.home / "daemon.log"))
            time.sleep(0.1)
        sys.exit("daemon.py: the daemon did not listen on %d" % self.port)

    def stop(self):
        try:
            pid = int(self.pidfile.read_text())
        except (OSError, ValueError):
            return
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                os.kill(pid, 0)
                time.sleep(0.1)
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.pidfile.unlink(missing_ok=True)

    def ack_all(self, sid: str, kind="annotate"):
        """Ack every event the session still holds, so a recording starts clean."""
        ev = self.state / "workspaces" / kind / sid / "state" / "events"
        for f in sorted(ev.glob("*.json")) if ev.exists() else []:
            self.run(["webcompanion", "ack", "--sid", sid, "--event-id", f.stem], check=False)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("action", choices=["start", "stop", "env"])
    ap.add_argument("--home", required=True)
    ap.add_argument("--port", type=int, default=19100)
    a = ap.parse_args(argv)
    d = Daemon(a.home, a.port)
    if a.action == "start":
        d.start()
        print("webcompanion on %s, HOME=%s, pid %s" % (d.url(), d.home, d.pidfile.read_text()))
    elif a.action == "stop":
        d.stop()
    else:
        print("HOME=%s" % d.home)


if __name__ == "__main__":
    main()
