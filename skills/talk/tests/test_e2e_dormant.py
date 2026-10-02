"""End to end: a real call goes live, falls dormant after --dormant-after seconds of quiet,
and wakes on "Nova, what is two plus two", whose words reach the brain as a turn.

It spends about a minute of GPT-Live (roughly $0.05), so it runs only when asked:
TALK_E2E=1, with OPENAI_API_KEY (environment or ~/.config/talk/keys.env), Playwright, macOS
`say`, a running webcompanion daemon, and the local listening model already downloaded
(`ear.py --warm`). This test plays the brain itself, through the same HTTP API talk_client uses."""
import base64
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

pytest.importorskip("playwright", reason="browser suite: add --with playwright")

from playwright.sync_api import sync_playwright  # noqa: E402

import ear  # noqa: E402
from helpers import SKILL_DIR, talk  # noqa: E402

talk.load_keys()
MISSING = [why for why, bad in [
    ("set TALK_E2E=1 to spend about a minute of GPT-Live", os.environ.get("TALK_E2E") != "1"),
    ("OPENAI_API_KEY", not os.environ.get("OPENAI_API_KEY")),
    ("uv", shutil.which("uv") is None),
    ("macOS say", shutil.which("say") is None),
    ("an Apple Silicon Mac", sys.platform != "darwin" or platform.machine() != "arm64"),
    ("the local listening model (ear.py --warm)", not ear.model_cached()),
    ("a running webcompanion daemon", talk.stage_mod.daemon_status() is not None),
] if bad]
pytestmark = pytest.mark.skipif(bool(MISSING), reason="needs " + ", ".join(MISSING))

DORMANT_AFTER = 10

# The page's microphone is a WebAudio stream the test plays clips into, so the test decides
# exactly when words are spoken. Every getUserMedia (live, then the ear) gets a clone of it.
FAKE_MIC = """
(() => {
  const ctx = new AudioContext();
  const dest = ctx.createMediaStreamDestination();
  window.__play = async (b64) => {
    await ctx.resume();
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const buf = await ctx.decodeAudioData(bytes.buffer);
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(dest); src.start();
    return buf.duration;
  };
  navigator.mediaDevices.getUserMedia = async () =>
    new MediaStream(dest.stream.getAudioTracks().map(t => t.clone()));
})();
"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def end_group(proc: subprocess.Popen, grace: float = 15.0) -> None:
    """End talk.py, not just uv: uv runs Python as its child, so signal the whole process group
    (the test starts it in a session of its own). SIGTERM first; SIGKILL whatever is left after
    `grace` (talk.py's own SIGTERM shutdown can take about 11.5 s)."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return  # the group is already gone
    deadline = time.time() + grace
    while time.time() < deadline:
        proc.poll()  # reap uv, so a zombie does not keep the group alive
        try:
            os.killpg(proc.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.2)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(5)


def spoken_clip(path, text: str) -> str:
    subprocess.run(["say", "-o", str(path), "--data-format=LEI16@16000", text], check=True)
    return base64.b64encode(path.read_bytes()).decode()


def call(port: int, token: str, method: str, path: str, body: dict | None = None, timeout: float = 10):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Talk-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return resp.status, json.loads(raw) if raw else None


def wait_until(port, token, want, timeout: float, what: str) -> dict:
    deadline, last = time.time() + timeout, None
    while time.time() < deadline:
        _, last = call(port, token, "GET", "/api/state")
        if want(last):
            return last
        time.sleep(0.5)
    raise AssertionError(f"{what} did not happen within {timeout:.0f} s; last state {last}")


def test_a_quiet_call_goes_dormant_and_wakes_on_its_name(tmp_path):
    port, state_file = free_port(), tmp_path / "session.json"
    wake_clip = spoken_clip(tmp_path / "wake.wav", "Nova, what is two plus two")
    log = (tmp_path / "talk.log").open("w")
    proc = subprocess.Popen(
        ["uv", "run", "-q", "--script", str(SKILL_DIR / "talk.py"), "--llm", "session", "--topic", "End to end check",
         "--no-open", "--port", str(port), "--out", str(tmp_path / "out"),
         "--dormant-after", str(DORMANT_AFTER), "--wake", "name", "--name", "Nova"],
        stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, TALK_STATE=str(state_file)),
        start_new_session=True)  # its own process group, so cleanup reaches talk.py under uv
    try:
        deadline = time.time() + 180  # the first run resolves talk.py's dependencies
        while not state_file.exists():
            assert proc.poll() is None, (tmp_path / "talk.log").read_text()
            assert time.time() < deadline, "talk.py did not start"
            time.sleep(0.5)
        state = json.loads(state_file.read_text())
        token, url = state["token"], f"http://127.0.0.1:{port}{state['path']}"

        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                              "--autoplay-policy=no-user-gesture-required"])
            page = browser.new_page()
            page.add_init_script(FAKE_MIC)
            page.goto(url)
            page.click("#start")
            live = lambda s: s["state"] == "live" and s["session_live"]  # noqa: E731
            wait_until(port, token, live, 60, "the first live session")
            wait_until(port, token, lambda s: s["state"] == "dormant", DORMANT_AFTER + 60, "going dormant")
            wait_until(port, token, lambda s: s["ear"] == "ready", 60, "the local recognizer loading")
            page.evaluate("b64 => window.__play(b64)", wake_clip)
            awake = wait_until(port, token, live, 60, "waking into a new live session")
            # cost.dormant_seconds is the field the page's #cost line renders as "asleep Xm (free)"
            # once it passes a minute; this dormant stretch is only ~10-30 s, so check the number
            # behind the line directly rather than wait an extra 30-50 s of local-only listening
            # just to see the rendered text cross that display threshold.
            assert awake["cost"]["dormant_seconds"] > 0, awake["cost"]

            status, turn = call(port, token, "GET", "/api/turn?wait=30", timeout=40)
            assert status == 200 and turn["type"] == "turn", turn
            room = " ".join(line["text"] for line in turn["said"] if line["who"] == "room")
            assert re.search(r"two plus two|2 ?\+ ?2", room, re.IGNORECASE), turn["said"]
            assert ear.spot_name(room, ["Nova"]), turn["said"]
            assert call(port, token, "POST", "/api/reply", {"id": turn["id"], "text": "Four."})[0] == 200
            time.sleep(3)
            call(port, token, "POST", "/api/stop")
            try:
                proc.wait(30)
            except subprocess.TimeoutExpired:
                end_group(proc)
            browser.close()
        transcript = (tmp_path / "out" / "transcript.md").read_text()
        assert "**Room:**" in transcript and "Four." in transcript
    finally:
        end_group(proc)  # also when uv has exited: talk.py may still be running under it
        log.close()
