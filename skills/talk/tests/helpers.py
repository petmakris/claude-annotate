import argparse
import asyncio
import concurrent.futures
import io
import sys
import wave
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import talk  # noqa: E402

TOKEN = "test-token"
CALL = "test-call-id"
AUTH = {"X-Talk-Token": TOKEN}


def run(coro):
    """asyncio.run on a thread of its own: a worker that ran a browser test has Playwright's loop
    running on its main thread, where asyncio.run refuses to start."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def silent_wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * int(seconds * rate))
    return out.getvalue()


class FakeSpeech:
    """Stands in for VoiceStudio: `heard` is what every recording says; every answer is a second of silence."""

    def __init__(self):
        self.heard = "hello there"
        self.spoken: list[str] = []
        self.languages: list = []
        self.fail: str | None = None

    def transcribe(self, audio: bytes, language=None, filename: str = "turn.wav") -> str:
        self.languages.append(language)
        if self.fail:
            raise talk.speech.SpeechError(self.fail)
        return self.heard

    def synthesize(self, text: str, voice: str = "", fmt: str = "mp3") -> bytes:
        if self.fail:
            raise talk.speech.SpeechError(self.fail)
        self.spoken.append(text)
        return silent_wav()


def spoken(call) -> list[str]:
    """The answers shown, in order."""
    return [e["text"] for e in call.entries if e["who"] == "claude"]


def make_args(**overrides) -> argparse.Namespace:
    values = dict(code=None, voice="test-voice", language="auto", idle_minutes=60, port=0, no_open=True,
                  stage_base=None, url_base=None, topic="Test topic", out=None)
    values.update(overrides)
    return argparse.Namespace(**values)


@asynccontextmanager
async def running_app(tmp_path: Path, stage_url=None, fake: FakeSpeech | None = None, **overrides):
    """A served call with a fake VoiceStudio. Yields (client, call, fake)."""
    from aiohttp.test_utils import TestClient, TestServer

    fake = fake or FakeSpeech()
    with patch.object(talk.speech, "transcribe", fake.transcribe), patch.object(talk.speech, "synthesize", fake.synthesize):
        call = talk.Call(make_args(**overrides), "Test topic", tmp_path / "out")
        app = talk.build_app(call, TOKEN, CALL, stage_url=stage_url)
        async with TestClient(TestServer(app)) as client:
            yield client, call, fake
