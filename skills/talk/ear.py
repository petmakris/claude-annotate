"""ear: the local recognizer a dormant call listens with.

16 kHz mono 16-bit PCM comes in from the call page. An energy gate with hangover splits it
into utterances, and each finished utterance is transcribed with parakeet-mlx on one worker
thread, off the event loop, and becomes a segment {text, start, end}.

parakeet-mlx is imported only when the model is first loaded, so this module imports (and
its tests run) on any machine.
"""

import array
import asyncio
import concurrent.futures
import importlib.util
import math
import os
import platform
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

SAMPLE_RATE = 16000
WINDOW_S = 0.02  # the gate decides per 20 ms window
GATE_RMS = 400.0  # 16-bit RMS; speech after browser AGC sits well above, a quiet room well below
HANGOVER_S = 0.7  # an utterance ends after this long below the gate
MAX_UTTERANCE_S = 15.0  # ... or at this length whatever happens
MIN_VOICED_S = 0.15  # shorter bursts (a click, a tap on the table) are not speech
ENERGY_WAKE_S = 0.6  # before the model is ready, this much voiced audio wakes a --wake speech call
MAX_BACKLOG_S = 30.0  # queued audio beyond this is dropped, oldest first
MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"

_WORD = re.compile(r"\w+")


def spot_name(text: str, names: list[str]) -> bool:
    """True when one of `names` occurs in `text` as a whole word (or words), ignoring case."""
    for name in names:
        words = name.split()
        if not words:
            continue
        pattern = r"\s+".join(re.escape(w) for w in words)
        if re.search(rf"(?<!\w){pattern}(?!\w)", text, re.IGNORECASE):
            return True
    return False


def wakes(segment: dict, wake: str, names: list[str]) -> bool:
    """Does this segment wake a dormant call? `wake` is "speech" or "name"."""
    if wake == "name":
        return spot_name(segment["text"], names)
    if segment.get("energy_only"):
        return segment["end"] - segment["start"] >= ENERGY_WAKE_S
    return len(_WORD.findall(segment["text"])) >= 2


def rms(window: bytes) -> float:
    samples = array.array("h", window)
    if sys.byteorder == "big":
        samples.byteswap()
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


@dataclass
class Utterance:
    pcm: bytes
    start: float  # seconds since the segmenter began
    end: float


class Segmenter:
    """An energy gate with hangover: PCM in, finished utterances out. Pure: no clock, no model."""

    def __init__(self, rate: int = SAMPLE_RATE, gate: float = GATE_RMS, hangover: float = HANGOVER_S,
                 max_len: float = MAX_UTTERANCE_S, min_voiced: float = MIN_VOICED_S):
        self.rate = rate
        self.gate = gate
        self.win = int(rate * WINDOW_S)  # samples per window
        self.hangover = int(hangover * rate)
        self.max_len = int(max_len * rate)
        self.min_voiced = int(min_voiced * rate)
        self._carry = b""  # an incomplete window (or half a sample) held for the next feed
        self._t = 0  # samples seen
        self._start: int | None = None
        self._buf = bytearray()
        self._quiet = 0
        self._voiced = 0

    def feed(self, pcm: bytes) -> list[Utterance]:
        data = self._carry + pcm
        step = self.win * 2
        usable = len(data) // step * step
        self._carry = data[usable:]
        out = []
        for i in range(0, usable, step):
            window = data[i:i + step]
            loud = rms(window) >= self.gate
            if self._start is None:
                if loud:
                    self._start, self._buf, self._quiet, self._voiced = self._t, bytearray(window), 0, self.win
            else:
                self._buf += window
                if loud:
                    self._quiet, self._voiced = 0, self._voiced + self.win
                else:
                    self._quiet += self.win
                if self._quiet >= self.hangover or len(self._buf) // 2 >= self.max_len:
                    if utterance := self._finish():
                        out.append(utterance)
            self._t += self.win
        return out

    def flush(self) -> list[Utterance]:
        """The utterance in progress, if any: the page stopped streaming."""
        if self._start is None:
            return []
        utterance = self._finish()
        return [utterance] if utterance else []

    def _finish(self) -> Utterance | None:
        start, buf, voiced = self._start, bytes(self._buf), self._voiced
        self._start, self._buf, self._quiet, self._voiced = None, bytearray(), 0, 0
        if voiced < self.min_voiced:
            return None
        return Utterance(buf, start / self.rate, (start + len(buf) // 2) / self.rate)


# ---------------------------------------------------------------------------
# The recognizer: the model, where it can run, and the queue in front of it
# ---------------------------------------------------------------------------


def unavailable() -> str | None:
    """Why local listening cannot run on this machine, or None when it can."""
    if sys.platform != "darwin" or platform.machine() != "arm64":
        return "local listening needs an Apple Silicon Mac"
    if importlib.util.find_spec("parakeet_mlx") is None:
        return "parakeet-mlx is not installed"
    return None


def model_cached() -> bool:
    """Is the model already in the Hugging Face cache? The first load downloads it (about 2.5 GB) otherwise.
    Reads the cache folder itself, so it needs no Hugging Face package."""
    home = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    hub = Path(os.environ.get("HF_HUB_CACHE") or home / "hub")
    snapshots = hub / f"models--{MODEL_ID.replace('/', '--')}" / "snapshots"
    return any(snapshots.glob("*/model.safetensors"))


def warm_command() -> str:
    """The one line that downloads the model ahead of the first dormant period."""
    return (f'uv run -q --no-project --python 3.12 --with parakeet-mlx python "{Path(__file__).resolve()}" '
            "--warm")


def load_parakeet():
    """Load the model (downloading it the first time) and return transcribe(pcm) -> text."""
    import mlx.core as mx
    import numpy as np
    from parakeet_mlx import from_pretrained
    from parakeet_mlx.audio import get_logmel

    model = from_pretrained(MODEL_ID)

    def transcribe(pcm: bytes) -> str:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        mel = get_logmel(mx.array(samples), model.preprocessor_config)
        return model.generate(mel)[0].text.strip()

    return transcribe


class Ear:
    """Segments the page's PCM and transcribes each utterance, in order, on one worker thread.

    `status` is "idle" until the first dormant period, then "loading", then "ready"; "failed"
    when the model could not load. Until it is ready, utterances become energy-only segments
    (empty text, `energy_only: True`), so a --wake speech call can still wake."""

    def __init__(self, on_segment, on_note=None, transcribe=None, loader=load_parakeet,
                 clock=time.time, max_backlog: float = MAX_BACKLOG_S):
        self.on_segment = on_segment  # called on the event loop with each segment dict
        self.on_note = on_note or (lambda text: None)
        self.loader = loader
        self.clock = clock
        self.max_backlog = max_backlog
        self._transcribe = transcribe
        self.status = "ready" if transcribe else "idle"
        self.error = ""  # why the model could not load, once status is "failed"
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ear")
        self.segmenter = Segmenter()
        self.t0 = clock()
        self._queue: deque[Utterance] = deque()
        self._worker: asyncio.Task | None = None

    def begin(self) -> None:
        """A dormant period starts: a fresh segmenter, and the model starts loading the first time."""
        self.segmenter = Segmenter()
        self.t0 = self.clock()
        if self.status == "idle":
            self.status = "loading"
            loading = asyncio.get_running_loop().run_in_executor(self.pool, self.loader)
            loading.add_done_callback(self._loaded)

    def _loaded(self, fut: asyncio.Future) -> None:
        if fut.cancelled():
            return
        if fut.exception() is not None:
            self.status = "failed"
            self.error = str(fut.exception())[:200]
            self.on_note(f"local listening could not start: {fut.exception()}")
            return
        self._transcribe = fut.result()
        self.status = "ready"

    def feed(self, pcm: bytes) -> None:
        self._enqueue(self.segmenter.feed(pcm))

    def end(self) -> None:
        """The page stopped streaming: what was being said still counts."""
        self._enqueue(self.segmenter.flush())

    def _enqueue(self, utterances: list[Utterance]) -> None:
        if not utterances:
            return
        self._queue.extend(utterances)
        dropped = 0.0
        while len(self._queue) > 1 and sum(u.end - u.start for u in self._queue) > self.max_backlog:
            oldest = self._queue.popleft()
            dropped += oldest.end - oldest.start
        if dropped:
            self.on_note(f"the local recognizer fell behind and dropped {dropped:.0f} s of speech")
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_running_loop().create_task(self._drain())

    async def _drain(self) -> None:
        loop = asyncio.get_running_loop()
        while self._queue:
            u = self._queue.popleft()
            start, end = self.t0 + u.start, self.t0 + u.end
            if self.status != "ready":
                self.on_segment({"text": "", "start": start, "end": end, "energy_only": True})
                continue
            try:
                text = await loop.run_in_executor(self.pool, self._transcribe, u.pcm)
            except Exception as err:  # one bad utterance never stops listening
                self.on_note(f"the local recognizer failed on one utterance: {err}")
                continue
            self.on_segment({"text": text.strip(), "start": start, "end": end})

    async def idle(self) -> None:
        """Wait until everything queued has been transcribed (tests, and the end of a call)."""
        while self._worker is not None and not self._worker.done():
            await asyncio.shield(self._worker)

    def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    if sys.argv[1:] != ["--warm"]:
        sys.exit("usage: ear.py --warm   (downloads the local listening model)")
    load_parakeet()
    print(f"local listening model ready: {MODEL_ID}")
