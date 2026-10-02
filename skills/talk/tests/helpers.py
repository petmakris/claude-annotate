import argparse
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import talk  # noqa: E402

TOKEN = "test-token"
CALL = "test-call-id"
AUTH = {"X-Talk-Token": TOKEN}


class RecordingSocket:
    """Stands in for GPT-Live's sideband: records every event the server sends."""

    closed = False

    def __init__(self):
        self.events = []

    async def send_str(self, data):
        self.events.append(json.loads(data))

    async def close(self):
        self.closed = True


class FakeEar:
    """Stands in for ear.Ear: records what the page streams."""

    status = "ready"
    error = ""

    def __init__(self):
        self.frames: list[bytes] = []
        self.begun = 0
        self.ended = 0

    def begin(self):
        self.begun += 1

    def feed(self, pcm: bytes):
        self.frames.append(pcm)

    def end(self):
        self.ended += 1

    def close(self):
        pass


def spoken(ctl) -> list[str]:
    return [e["content"] for e in ctl.ws.events if e["type"] == "session.commentary.append"]


def instructions(ctl) -> list[str]:
    return [e["content"] for e in ctl.ws.events if e["type"] == "session.instructions.append"]


def make_args(**overrides) -> argparse.Namespace:
    values = dict(
        llm="session", code=None, voice="marin", verbose=False, max_minutes=60,
        idle_minutes=5, input_device=None, output_device=None, port=0, no_open=True, model="unused",
        stage_base=None, dormant_after=0, wake="speech", name="Nova", sounds_like="", mode="talk",
        max_live_minutes=30, daily_live_minutes=120,
    )
    values.update(overrides)
    return argparse.Namespace(**values)


@asynccontextmanager
async def running_app(tmp_path: Path, stage_url=None, **overrides):
    from aiohttp.test_utils import TestClient, TestServer

    args = make_args(**overrides)
    log = talk.SessionLog(tmp_path / "out", "Test topic", "test")
    ctl = talk.LiveController(args, "Test topic", "", log, None, None)
    ctl.ws = RecordingSocket()
    app = talk.build_app(args, "Test topic", log, ctl, TOKEN, CALL, stage_url=stage_url)
    async with TestClient(TestServer(app)) as client:
        yield client, ctl, log
