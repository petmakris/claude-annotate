import argparse
import asyncio
import concurrent.futures
import io
import sys
import wave
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from unittest.mock import patch

SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR))

import talk  # noqa: E402

TOKEN = "test-token"
CALL = "test-call-id"
AUTH = {"X-Talk-Token": TOKEN}
SERVER_TOKEN = "server-token"
SERVER_AUTH = {"X-Talk-Token": SERVER_TOKEN}


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
    """Stands in for the speech engine: `heard` is what every recording says; every answer is
    `seconds` of silence with its words spread evenly over it."""

    def __init__(self):
        self.heard = "hello there"
        self.spoken: list[str] = []
        self.languages: list = []
        self.fail: str | None = None
        self.hold = None  # a threading.Semaphore: when set, every answer waits for a release
        self.seconds = 1.0  # how long each answer plays

    def transcribe(self, audio: bytes, language=None) -> str:
        self.languages.append(language)
        if self.fail:
            raise talk.speech.SpeechError(self.fail)
        return self.heard

    def speak(self, text: str, voice: str = "", wav: bool = False):
        if self.fail:
            raise talk.speech.SpeechError(self.fail)
        if self.hold is not None:
            self.hold.acquire(timeout=10)
        self.spoken.append(text)
        words = text.split()
        step = self.seconds / max(len(words), 1)
        return talk.speech.Spoken(audio=silent_wav(self.seconds), ext="wav", duration=self.seconds,
                                  words=[(w, round(i * step, 3), round((i + 1) * step, 3)) for i, w in enumerate(words)])


def spoken(call) -> list[str]:
    """The answers shown, in order."""
    return [e["text"] for e in call.entries if e["who"] == "claude"]


def make_args(**overrides) -> argparse.Namespace:
    values = dict(code=None, voice="test-voice", language="auto", idle_minutes=60, port=0, no_open=True,
                  stage_base=None, url_base=None, topic="Test topic", out=None)
    values.update(overrides)
    return argparse.Namespace(**values)


def add_call(server, tmp_path: Path, call_id: str = CALL, token: str = TOKEN, topic: str = "Test topic",
             stage_url=None, **overrides):
    """A call on `server`, as a launch would open it, without its stage."""
    call = talk.Call(make_args(**overrides), topic, tmp_path / f"out-{call_id}")
    return server.add(call, call_id=call_id, token=token, stage_url=stage_url)


@asynccontextmanager
async def running_server(fake: FakeSpeech | None = None):
    """A served talk server with no call yet and a fake speech engine. Yields (client, server, fake)."""
    from aiohttp.test_utils import TestClient, TestServer

    fake = fake or FakeSpeech()
    with patch.object(talk.speech, "transcribe", fake.transcribe), patch.object(talk.speech, "speak", fake.speak):
        server = talk.Server(SERVER_TOKEN)
        async with TestClient(TestServer(talk.build_app(server))) as client:
            server.port = client.server.port
            try:
                yield client, server, fake
            finally:
                server.speech.shutdown()


@asynccontextmanager
async def running_app(tmp_path: Path, stage_url=None, fake: FakeSpeech | None = None, **overrides):
    """A served call with a fake speech engine. Yields (client, call, fake)."""
    async with running_server(fake) as (client, server, fake):
        call = add_call(server, tmp_path, stage_url=stage_url, **overrides)
        yield client, call, fake


@contextmanager
def served_server(fake: FakeSpeech | None = None):
    """A talk server on a loop in its own thread, reachable over real HTTP, as a launch reaches it.
    Yields (server, info), info being what the server's file holds."""
    import threading

    from aiohttp import web

    fake = fake or FakeSpeech()
    loop = asyncio.new_event_loop()
    box = {}
    ready = threading.Event()

    async def start():
        box["server"] = talk.Server(SERVER_TOKEN)
        box["runner"] = web.AppRunner(talk.build_app(box["server"]))
        await box["runner"].setup()
        site = web.TCPSite(box["runner"], "127.0.0.1", 0)
        await site.start()
        box["server"].port = site._server.sockets[0].getsockname()[1]
        ready.set()

    async def stop():
        server = box["server"]
        for call in list(server.calls.values()):
            call.end("test over")
            call.turns.end_collected.set()
            call.closed.set()
        if server.tasks:
            await asyncio.wait(server.tasks, timeout=5)
        server.speech.shutdown()
        await box["runner"].cleanup()

    thread = threading.Thread(target=loop.run_forever, daemon=True)
    with patch.object(talk.speech, "transcribe", fake.transcribe), patch.object(talk.speech, "speak", fake.speak):
        thread.start()
        asyncio.run_coroutine_threadsafe(start(), loop)
        assert ready.wait(10)
        try:
            yield box["server"], {"port": box["server"].port, "token": SERVER_TOKEN}
        finally:
            asyncio.run_coroutine_threadsafe(stop(), loop).result(15)
            loop.call_soon_threadsafe(loop.stop)
            thread.join(10)
