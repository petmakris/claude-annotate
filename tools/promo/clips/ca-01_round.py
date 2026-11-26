"""ca-01_round.py: what the four annotate clips (ca-01 to ca-04) share.

A clip's own daemon on a scratch HOME, the invented acme-billing repo, pushes
through `claude-annotate`, and the Claude side of a round. The Claude side is
the scripted part of these clips: it runs the same commands a Claude session
runs (watch, progress, push, progress --done, ack), with a rewrite that was
written beforehand. Not a clip by itself; clips load it with `load()`.
"""
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))
import daemon as _daemon  # noqa: E402
from daemon import Daemon, REPO  # noqa: E402
from encode import encode  # noqa: E402
from rec import Recorder, frames_dir, scratch_root  # noqa: E402,F401

PORT = 19120


def _port_free(port):
    """daemon.port_free binds without SO_REUSEADDR, so a port is "taken" for a
    minute after the last clip stopped its daemon (TIME_WAIT). A listener still
    fails this bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


_daemon.port_free = _port_free


class Stage:
    """One clip's world: daemon, repo, one pushed page and its watcher."""

    def __init__(self, clip_id, port=PORT):
        self.root = scratch_root() / "stage" / clip_id
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.daemon = Daemon(self.root / "home", port)
        self.repo = self.root / "acme-billing"
        self.watcher = None
        self.event = None
        self._got = threading.Event()

    def __enter__(self):
        subprocess.run(["sh", str(KIT / "fixtures/acme-billing/make_repo.sh"), str(self.repo)],
                       check=True, capture_output=True)
        self.daemon.start()
        return self

    def __exit__(self, *exc):
        self.stop_watch()
        self.daemon.stop()
        return False

    def ca(self, *args):
        return self.daemon.run([str(REPO / "bin/claude-annotate"), *args])

    def push(self, blocks, first=False):
        args = ["push", "--blocks", str(blocks), "--cwd", str(self.repo), "--eval"]
        if not first:
            args += ["--slug", self.slug]
        out = self.ca(*args).stdout
        vals = dict(l.split("=", 1) for l in out.splitlines() if "=" in l)
        if first:
            self.sid = vals["WC_SID"].strip("'\"")
            self.slug = vals["WC_SLUG"].strip("'\"")
        return self.daemon.url("/s/%s/" % self.slug)

    # ── the watcher, as a Claude session arms it ───────────────────────
    def watch(self):
        self.stop_watch()
        self._got.clear()
        self.watcher = subprocess.Popen(
            ["webcompanion", "watch", "--kind", "annotate", "--sid", self.sid],
            env=self.daemon.env(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

        def read(proc):
            for line in proc.stdout:
                m = re.search(r"event_id=(\S+)", line)
                if m:
                    self.event = m.group(1)
                    self._got.set()
                    return
        threading.Thread(target=read, args=(self.watcher,), daemon=True).start()

    def stop_watch(self):
        if self.watcher and self.watcher.poll() is None:
            self.watcher.terminate()
            self.watcher.wait(timeout=5)
        self.watcher = None

    def round_event(self, timeout=20) -> dict:
        """Wait for the submitted round and read it back from the store."""
        if not self._got.wait(timeout):
            raise RuntimeError("the page sent no round")
        out = self.daemon.run(["webcompanion", "event", "--sid", self.sid,
                               "--event-id", self.event]).stdout
        return json.loads(json.loads(out)["text"])

    def claude_reads(self, text="Read your round of feedback"):
        self.ca("progress", "--sid", self.sid, "--text", text, "--event-id", self.event)

    def claude_done(self):
        self.ca("progress", "--sid", self.sid, "--done")
        self.daemon.run(["webcompanion", "ack", "--sid", self.sid, "--event-id", self.event])
        self.watch()


def wait_idle(r, timeout=30):
    """Let the page unlock after the ack, without recording."""
    for _ in range(int(timeout / 0.2)):
        if not r.page.evaluate("document.body.classList.contains('is-busy')"):
            return
        r.settle(0.2)
    raise RuntimeError("the page stayed busy")


def select_words(r, locator, seconds=0.7, drag_frames=6):
    """Drag over the words of `locator` with the cursor, as a reader selects them."""
    box = locator.bounding_box()
    y = box["y"] + box["height"] / 2
    r.glide((box["x"] + 1, y), seconds)
    r.page.mouse.down()
    for i in range(1, drag_frames + 1):
        x = box["x"] + 1 + (box["width"] - 2) * i / drag_frames
        r.page.mouse.move(x, y)
        r.pos = (x, y)
        r.shot()
    r.page.mouse.up()
    r.settle(0.4)
    r.shot()


def finish(clip_id, width, cap_kb, out_name=None, **kw):
    out = REPO / "docs/img" / (out_name or clip_id + ".webp")
    info = encode(frames_dir(clip_id), out, width=width, **kw)
    info["kb"] = round(info["bytes"] / 1024)
    print(json.dumps(info))
    if info["bytes"] > cap_kb * 1024:
        sys.exit("%s: %d KB is over the cap of %d KB" % (clip_id, info["kb"], cap_kb))
