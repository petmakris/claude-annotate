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
        self.voices: list[str] = []  # the voice of each answer spoken
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
        self.voices.append(voice)
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


def stage_rule_breaks(call, shown: str) -> list[str]:
    """The rules a reply's scenes break (skills/stage/SKILL.md, "What the stage keeps true"), as far as
    the compiled frames and cues decide them; the page's share is tested in the browser. Call it right
    after call.split_reply(text) returned `shown`."""
    scene_mod, out = talk.stage_scene, []
    cues = call.reply_cues
    fronts = sorted((c["at"], c["view"]) for c in cues if c["kind"] == "front")
    starts = talk.sentence_starts(shown)
    for item in call.board.items:
        built, view = item.get("scene"), item["view"]
        if not built or view not in [v for _, v in fronts]:
            continue
        model, frames = talk.scene_model(item), built["frames"]
        name = item.get("title") or view
        at = {c["n"]: c["at"] for c in cues if c["view"] == view and c["kind"] == "frame"}
        front = next(a for a, v in fronts if v == view)
        end = next((a for a, v in fronts if a > front), len(shown))
        part = {k: (model.up[k][0] if k.startswith("cell#") else k) for k in model.keys}
        for n, f in enumerate(frames):
            focus = {part[k] for k in f["focus"]}
            parts = [k for k in f["cur"] if not k.startswith("edge:")]
            if n in (0, built["rest"]) and f["cur"]:
                out.append(f"R1 {name} frame {n} names {f['cur']} as being said")
            if focus and not set(parts) <= focus:
                out.append(f"R1/R3 {name} frame {n} says {parts} while it points at {sorted(focus)}")
            nodes = [k for k in parts if k.startswith("node:")]
            for e in (k for k in f["cur"] if k.startswith("edge:")):
                if not set(model.up[e]) <= set(f["show"]):
                    out.append(f"R4 {name} frame {n} says {e} without both its ends")
                if nodes and nodes[-1] not in model.up[e]:
                    out.append(f"R4 {name} frame {n} says {e}, which does not touch {nodes[-1]}")
        positions = [at[n] for n in sorted(at)]
        for p in positions:
            if p < len(shown) and shown[p].isspace():
                out.append(f"R8 {name}: a frame cue stands on a space at {p}")
        for p, q in zip(positions, positions[1:]):
            if not shown[p:q].strip():
                out.append(f"R8 {name}: two frames fire on the word at {q}")
        if not built.get("auto"):  # a board revealed by its own verbs comes in where its author put them
            continue
        bounds = [front] + [s for s in starts if front < s < end]
        spans = list(zip(bounds, bounds[1:] + [end]))
        names = scene_mod.part_names(model)
        for k in model.order:
            first = next((n for n, f in enumerate(frames) if k in f["show"]), None)
            said = next(((a, b) for a, b in spans if scene_mod.names_part(scene_mod._words(shown[a:b]), names.get(k, []))), None)
            if first is None or first == built["rest"] or said is None:
                continue
            if at.get(first, -1) < said[0]:
                out.append(f"R2 {name}: {k} arrives before the sentence that names it")
            elif at[first] >= said[1]:
                out.append(f"R2 {name}: {k} is named before it is shown")
    return out
