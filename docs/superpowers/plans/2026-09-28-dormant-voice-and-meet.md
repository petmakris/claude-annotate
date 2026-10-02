# Dormant Voice and /meet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `/talk` call closes its GPT-Live session when nobody is talking and listens on this Mac for free until spoken to, then reopens a session seeded with what was said. `/meet` builds on this: a meeting participant that starts dormant, wakes only on its name, and shows its work on a projector.

**Architecture:** A new `skills/talk/ear.py` holds the local recognizer: a pure energy-gate segmenter, a pure `spot_name`/`wakes` rule, and an `Ear` that transcribes each utterance with parakeet-mlx on one worker thread. `talk.py`'s `LiveController` gains a `state` (`live`/`dormant`/`waking`). `sleep()` closes the session without it counting as a drop, `hear()`/`wake()` turn recognizer segments into a wake, and `session_config()` seeds the new session through the rejoin path's conversation block. The page streams 16 kHz PCM from an AudioWorklet to a new `/api/ear` WebSocket while dormant. The server pushes the wake over that socket, and the page reuses its existing `POST /api/session` flow. `/meet` is `talk.py --mode meeting` plus its own voice instructions, a `?view=projector` layout and a `SKILL.md`.

**Tech Stack:** Python 3.11–3.13 in a `uv run --script` program, aiohttp 3, parakeet-mlx 0.5 (MLX, Apple Silicon only), plain browser JavaScript (AudioWorklet, WebSocket, WebRTC), pytest and optional Playwright.

**Spec:** `docs/superpowers/specs/2026-09-28-dormant-voice-and-meet-design.md` (read it before starting).

## Global Constraints

- `talk.py` stays a `uv run --script` program with `requires-python = ">=3.11,<3.14"`.
- `parakeet-mlx` joins `talk.py`'s script dependencies with the marker `sys_platform == 'darwin' and platform_machine == 'arm64'`, and only there.
- `ear.py` must import without `parakeet-mlx`, `mlx`, `numpy` or `huggingface_hub` present. It imports them lazily, inside `load_parakeet()`, so the tests that fake the transcriber run on any machine.
- Every commit message is a single line: no body, no trailers, no attribution.
- Talk tests: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk -q`. Full suite: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills -q`.
- Browser tests (`test_browser_dormant.py`) skip without Playwright; add `--with playwright` to run them. The end-to-end test (`test_e2e_dormant.py`) also skips without OpenAI credit, which it cannot detect, so it runs only with `TALK_E2E=1`.
- The real-model recognizer test skips unless `parakeet-mlx` is importable and its model is in the Hugging Face cache; add `--with parakeet-mlx` to run it.
- Model id: `mlx-community/parakeet-tdt-0.6b-v3`. Default wake name: `Nova`. `--dormant-after` defaults to 45 for /talk and 20 for a meeting (`0` disables dormancy). A meeting's `--max-minutes` defaults to 120. The seeded transcript is at most the last 6,000 characters.
- Page copy, verbatim from the spec: the orb reads "Dormant · listening on this Mac · free", the waiting button reads "Wake now", the first-download notice reads "Preparing local listening (one-time download)…", and the projector bar reads "Listening · say '<name>' to ask".
- Dormant audio is transcribed and discarded. No PCM is ever written to disk.

## Review Focus

1. **The browser's capture rate.** Chrome may run the capture at 44.1 or 48 kHz, and another browser may ignore the `AudioContext({sampleRate: 16000})` request. The ear must still receive 16 kHz mono 16-bit PCM, 32,000 bytes a second, or every transcript is garbage at the wrong pitch. This is pinned by `test_a_dormant_page_streams_16_khz_pcm_to_the_ear` in Task 5, which measures the byte rate the server receives from a real Chromium.
2. **Echo cancellation across the switch from WebRTC to the worklet and back.** Chrome applies one echo-cancellation setting per capture device. A dormant capture still open, or opened with other constraints, when the live `getUserMedia` runs can leave the voice hearing itself. Both captures therefore use `micConstraints()`, and the ear's stream is stopped before the live one opens. This is pinned by `test_a_wake_stops_the_ear_before_the_session_is_requested_and_a_failure_listens_again` in Task 5. A reviewer should also read `toDormant()`/`startLive()` for the order, and check that the existing `getSettings().echoCancellation === false` warning still runs on the woken session.
3. **A session closed by `sleep()` must not look like a dropped connection.** GPT-Live may report the close with any reason, including `connection_lost`. If the server or the page reads it as a drop, a quiet call opens the 90-second rejoin window and then ends, or the page shows "Connection lost". This is pinned by `test_a_close_reported_as_connection_lost_during_sleep_is_still_a_sleep` in Task 3, which also checks that `end_reason` stays untouched. On the page, `closedByServer()` asks `/api/state` before calling `dropped()`, and `sleep()` sets `state = "dormant"` before it sends `session.close`.
4. **A meeting where nobody says the name for 15 minutes.** `serve()` ends a call that has had no GPT-Live session within `CONNECT_TIMEOUT_MIN`. A meeting has none until its name is said, so without a change it would end a quiet meeting. This is pinned by the `never_started` assertions in `test_frames_reach_the_ear_and_start_a_dormant_period` in Task 4.
5. **A call page in a background tab.** Chrome throttles a hidden tab's timers to about once a minute. If the wake reached the page only through the 700 ms `/api/state` poll, the voice could come back a minute after its name was said. The server therefore pushes `{"state": "waking"}` over the ear socket. This is pinned by `test_a_wake_is_pushed_to_the_page_over_its_socket` in Task 4.

---

## File map

- Create `skills/talk/ear.py`: the segmenter, the wake rule, and the `Ear` that owns the model and its worker thread. Tasks 1–2.
- Modify `skills/talk/talk.py`:
  - `SessionLog`: `Room` turns and asides (Task 3).
  - `LiveController`: the state machine (Tasks 3–4).
  - `build_app`: `/api/ear` and the new state fields (Task 4).
  - `PAGE`: dormant capture and wake (Task 5), projector view (Task 7).
  - `apply_mode`, `ear_doctor_lines`, `main`, `serve`, `doctor` (Task 6).
  - `meeting_instructions` (Task 7).
- Modify `skills/talk/tests/helpers.py`: new `make_args` fields (Task 3) and `FakeEar` (Task 4).
- Create tests in `skills/talk/tests/`: `test_ear.py`, `test_ear_runner.py`, `test_dormant.py`, `test_ear_route.py`, `test_browser_dormant.py`, `test_talk_modes.py`, `test_meeting_mode.py` and `test_e2e_dormant.py`.
- Create `skills/meet/SKILL.md`. Modify `skills/talk/SKILL.md`, `README.md` and `.claude-plugin/marketplace.json` (Task 8).

---

### Task 1: `ear.py`, the pure pieces: `spot_name`, `wakes`, the segmenter

**Files:**
- Create: `skills/talk/ear.py`
- Test: `skills/talk/tests/test_ear.py`

**Interfaces:**
- Produces (module `ear`):
  - `SAMPLE_RATE = 16000`, `HANGOVER_S = 0.7`, `MAX_UTTERANCE_S = 15.0` and `ENERGY_WAKE_S = 0.6`.
  - `spot_name(text: str, names: list[str]) -> bool`.
  - `wakes(segment: dict, wake: str, names: list[str]) -> bool`, where `segment` is `{"text": str, "start": float, "end": float}`, optionally with `"energy_only": True`, and `wake` is `"speech"` or `"name"`.
  - `Utterance(pcm: bytes, start: float, end: float)`, a dataclass whose times are seconds since the segmenter began.
  - `Segmenter(rate=16000, gate=400.0, hangover=0.7, max_len=15.0, min_voiced=0.15)`, with `.feed(pcm: bytes) -> list[Utterance]` and `.flush() -> list[Utterance]`.

- [ ] **Step 1: Write the failing tests**

`skills/talk/tests/test_ear.py`:

```python
import math
import struct

import ear

RATE = ear.SAMPLE_RATE


def tone(seconds: float, amplitude: int = 6000, hz: int = 220) -> bytes:
    n = int(seconds * RATE)
    return struct.pack(f"<{n}h", *(int(amplitude * math.sin(2 * math.pi * hz * i / RATE)) for i in range(n)))


def silence(seconds: float) -> bytes:
    return b"\0\0" * int(seconds * RATE)


# -- spot_name ---------------------------------------------------------------


def test_the_name_is_spotted_as_a_whole_word_in_any_case():
    assert ear.spot_name("Nova, what do you think?", ["Nova"])
    assert ear.spot_name("so what does NOVA say", ["Nova"])
    assert ear.spot_name("ask nova", ["Nova"])


def test_punctuation_around_the_name_does_not_hide_it():
    for text in ("(Nova) any idea?", "Nova? Anyone?", "okay... Nova.", "\"Nova\", please", "what's Nova's view"):
        assert ear.spot_name(text, ["Nova"]), text


def test_a_similar_name_or_a_longer_word_is_not_the_name():
    assert not ear.spot_name("Nora, what do you think?", ["Nova"])
    assert not ear.spot_name("Novak sent the numbers", ["Nova"])
    assert not ear.spot_name("the casanova pattern", ["Nova"])
    assert not ear.spot_name("", ["Nova"])


def test_sound_alikes_count_as_the_name():
    names = ["Nova", "Noa", "Nover"]
    assert ear.spot_name("noa, lower the retry limit", names)
    assert ear.spot_name("Nover what's next", names)
    assert not ear.spot_name("Noah is late", names)


def test_a_two_word_name_matches_across_any_spacing():
    assert ear.spot_name("hey  nova can you", ["Hey Nova"])
    assert not ear.spot_name("hey there nova", ["Hey Nova"])


# -- wakes -------------------------------------------------------------------


def seg(text, start=0.0, end=1.0, **extra):
    return {"text": text, "start": start, "end": end, **extra}


def test_speech_wakes_on_two_words_and_not_on_a_cough():
    assert not ear.wakes(seg("hm"), "speech", ["Nova"])
    assert not ear.wakes(seg(""), "speech", ["Nova"])
    assert ear.wakes(seg("okay so"), "speech", ["Nova"])


def test_name_wakes_only_on_the_name():
    assert not ear.wakes(seg("let us lower the retry limit"), "name", ["Nova"])
    assert ear.wakes(seg("Nova, lower it?"), "name", ["Nova"])


def test_before_the_model_is_ready_speech_wakes_on_energy_alone_and_a_name_never_does():
    long_burst = seg("", 0.0, 1.0, energy_only=True)
    short_burst = seg("", 0.0, 0.3, energy_only=True)
    assert ear.wakes(long_burst, "speech", ["Nova"])
    assert not ear.wakes(short_burst, "speech", ["Nova"])
    assert not ear.wakes(long_burst, "name", ["Nova"])


# -- Segmenter ---------------------------------------------------------------


def test_two_bursts_separated_by_silence_are_two_utterances():
    s = ear.Segmenter()
    out = s.feed(silence(0.5) + tone(1.0) + silence(1.0) + tone(0.5) + silence(1.0))
    assert len(out) == 2
    assert abs(out[0].start - 0.5) < 0.03
    assert abs(out[1].start - 2.5) < 0.03
    # Each utterance keeps the hangover it waited through.
    assert abs(out[0].end - (1.5 + ear.HANGOVER_S)) < 0.03


def test_a_short_pause_inside_speech_does_not_split_it():
    s = ear.Segmenter()
    out = s.feed(tone(1.0) + silence(0.4) + tone(1.0) + silence(1.0))
    assert len(out) == 1
    assert abs(out[0].end - out[0].start - (2.4 + ear.HANGOVER_S)) < 0.03


def test_a_monologue_is_cut_at_fifteen_seconds():
    s = ear.Segmenter()
    out = s.feed(tone(20.0))
    assert len(out) == 1
    assert abs(out[0].end - out[0].start - ear.MAX_UTTERANCE_S) < 0.03
    rest = s.flush()
    assert len(rest) == 1 and abs(rest[0].start - ear.MAX_UTTERANCE_S) < 0.03


def test_a_click_is_not_an_utterance():
    s = ear.Segmenter()
    assert s.feed(silence(0.5) + tone(0.06) + silence(1.0)) == []


def test_a_quiet_room_is_not_speech():
    s = ear.Segmenter()
    assert s.feed(tone(3.0, amplitude=200)) == [] and s.flush() == []


def test_frames_split_mid_sample_are_reassembled():
    s = ear.Segmenter()
    pcm = silence(0.2) + tone(1.0) + silence(1.0)
    out = []
    for i in range(0, len(pcm), 333):  # odd sizes: frames end half-way through a sample
        out += s.feed(pcm[i:i + 333])
    whole = ear.Segmenter().feed(pcm)
    assert [(u.start, u.end, u.pcm) for u in out] == [(u.start, u.end, u.pcm) for u in whole]
    assert len(out) == 1
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk/tests/test_ear.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'ear'`.

- [ ] **Step 3: Implement**

`skills/talk/ear.py`:

```python
"""ear: the local recognizer a dormant call listens with.

16 kHz mono 16-bit PCM comes in from the call page. An energy gate with hangover splits it
into utterances, and each finished utterance is transcribed with parakeet-mlx on one worker
thread, off the event loop, and becomes a segment {text, start, end}.

parakeet-mlx is imported only when the model is first loaded, so this module imports (and
its tests run) on any machine.
"""

import array
import math
import re
import sys
from dataclasses import dataclass

SAMPLE_RATE = 16000
WINDOW_S = 0.02  # the gate decides per 20 ms window
GATE_RMS = 400.0  # 16-bit RMS; speech after browser AGC sits well above, a quiet room well below
HANGOVER_S = 0.7  # an utterance ends after this long below the gate
MAX_UTTERANCE_S = 15.0  # ... or at this length whatever happens
MIN_VOICED_S = 0.15  # shorter bursts (a click, a tap on the table) are not speech
MAX_BACKLOG_S = 30.0  # queued audio beyond this is dropped, oldest first
ENERGY_WAKE_S = 0.6  # before the model is ready, this much voiced audio wakes a --wake speech call
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
```

The gate works on 20 ms windows. The start time is the first loud window. An utterance keeps the hangover silence it waited through, because parakeet transcribes a trailing pause fine and cutting it would clip final consonants. `_carry` holds a partial window, or half a sample, between frames, because WebSocket frames need not align to samples.

- [ ] **Step 4: Run the tests**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk/tests/test_ear.py -q`
Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
git add skills/talk/ear.py skills/talk/tests/test_ear.py
git commit -m "feat(talk): ear.py segments PCM by energy and spots the wake name"
```

---

### Task 2: `ear.py`, the recognizer: `Ear`, lazy model, availability

**Files:**
- Modify: `skills/talk/ear.py` (imports; append the recognizer section)
- Test: `skills/talk/tests/test_ear_runner.py`

**Interfaces:**
- Consumes: `Segmenter`, `Utterance` and `ENERGY_WAKE_S` from Task 1.
- Produces (module `ear`):
  - `MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"` and `MAX_BACKLOG_S = 30.0`.
  - `unavailable() -> str | None`: why local listening cannot run here, or `None`.
  - `model_cached() -> bool`, which reads the Hugging Face cache folder and needs no Hugging Face package.
  - `warm_command() -> str`: the line that downloads the model, `... python "<path>/ear.py" --warm`.
  - `load_parakeet() -> Callable[[bytes], str]`.
  - `Ear(on_segment, on_note=None, transcribe=None, loader=load_parakeet, clock=time.time, max_backlog=30.0)`:
    - `.status` is one of `"idle"`, `"loading"`, `"ready"` and `"failed"`.
    - `.begin()`, `.feed(pcm: bytes)`, `.end()`, `async .idle()` and `.close()`.
    - `on_segment(segment: dict)` and `on_note(text: str)` are called on the event loop.
    - While the model is not ready, each utterance becomes `{"text": "", "start", "end", "energy_only": True}`.

- [ ] **Step 1: Write the failing tests**

`skills/talk/tests/test_ear_runner.py`:

```python
import asyncio
import importlib.util
import math
import shutil
import struct
import subprocess
import threading
import wave

import pytest

import ear

RATE = ear.SAMPLE_RATE


def tone(seconds, amplitude=6000):
    n = int(seconds * RATE)
    return struct.pack(f"<{n}h", *(int(amplitude * math.sin(2 * math.pi * 220 * i / RATE)) for i in range(n)))


def silence(seconds):
    return b"\0\0" * int(seconds * RATE)


def run(coro):
    return asyncio.run(coro)


def test_each_utterance_becomes_a_timed_segment_in_order():
    segments = []
    said = iter(["first thing", "second thing"])

    async def go():
        e = ear.Ear(segments.append, transcribe=lambda pcm: next(said), clock=lambda: 1000.0)
        e.begin()
        e.feed(tone(1.0) + silence(1.0))
        e.feed(tone(0.5) + silence(1.0))
        await e.idle()
        e.close()

    run(go())
    assert [s["text"] for s in segments] == ["first thing", "second thing"]
    assert abs(segments[0]["start"] - 1000.0) < 0.03
    assert abs(segments[1]["start"] - 1002.0) < 0.03


def test_transcription_runs_off_the_event_loop():
    threads = []

    def transcribe(pcm):
        threads.append(threading.current_thread().name)
        return "words here"

    async def go():
        e = ear.Ear(lambda s: None, transcribe=transcribe)
        e.begin()
        e.feed(tone(1.0) + silence(1.0))
        await e.idle()
        e.close()

    run(go())
    assert threads and threads[0].startswith("ear")


def test_the_model_loads_once_lazily_and_speech_wakes_on_energy_meanwhile():
    loads, segments = [], []
    gate = threading.Event()

    def loader():
        loads.append(1)
        gate.wait(5)
        return lambda pcm: "now I can hear words"

    async def go():
        e = ear.Ear(segments.append, loader=loader)
        assert e.status == "idle" and loads == []
        e.begin()
        e.feed(tone(1.0) + silence(1.0))
        await e.idle()
        status_while_loading = e.status
        gate.set()
        while e.status != "ready":
            await asyncio.sleep(0.01)
        e.begin()  # a second dormant period does not load again
        e.feed(tone(1.0) + silence(1.0))
        await e.idle()
        e.close()
        return status_while_loading

    assert run(go()) == "loading"
    assert loads == [1]
    assert segments[0]["energy_only"] and segments[0]["text"] == ""
    assert segments[1] == {"text": "now I can hear words", "start": segments[1]["start"], "end": segments[1]["end"]}


def test_a_model_that_fails_to_load_is_reported_and_listening_goes_on_by_energy():
    notes, segments = [], []

    def loader():
        raise RuntimeError("no metal device")

    async def go():
        e = ear.Ear(segments.append, on_note=notes.append, loader=loader)
        e.begin()
        while e.status == "loading":
            await asyncio.sleep(0.01)
        e.feed(tone(1.0) + silence(1.0))
        await e.idle()
        e.close()
        return e.status

    assert run(go()) == "failed"
    assert "no metal device" in notes[0]
    assert segments[0]["energy_only"]


def test_a_recognizer_that_falls_behind_drops_the_oldest_audio_with_a_note():
    notes, segments = [], []
    gate = threading.Event()

    def transcribe(pcm):
        gate.wait(5)
        return f"{len(pcm) // 2 / RATE:.1f}"

    async def go():
        e = ear.Ear(segments.append, on_note=notes.append, transcribe=transcribe, max_backlog=30)
        e.begin()
        e.feed(tone(1.0) + silence(1.0))  # being transcribed, blocked on the gate
        await asyncio.sleep(0.05)
        for _ in range(3):  # 3 x 15.7 s queued behind it: more than 30 s
            e.feed(tone(15.0) + silence(1.0))
        gate.set()
        await e.idle()
        e.close()

    run(go())
    assert any("fell behind" in n for n in notes)
    assert len(segments) == 3  # the first, then the two newest of the three long ones


def test_the_utterance_in_progress_is_kept_when_the_page_stops_streaming():
    segments = []

    async def go():
        e = ear.Ear(segments.append, transcribe=lambda pcm: "cut short")
        e.begin()
        e.feed(tone(1.0))
        e.end()
        await e.idle()
        e.close()

    run(go())
    assert [s["text"] for s in segments] == ["cut short"]


def test_a_failed_utterance_is_noted_and_listening_goes_on():
    notes, segments = [], []
    said = iter([RuntimeError("bad audio"), "still here"])

    def transcribe(pcm):
        value = next(said)
        if isinstance(value, Exception):
            raise value
        return value

    async def go():
        e = ear.Ear(segments.append, on_note=notes.append, transcribe=transcribe)
        e.begin()
        e.feed(tone(1.0) + silence(1.0) + tone(1.0) + silence(1.0))
        await e.idle()
        e.close()

    run(go())
    assert [s["text"] for s in segments] == ["still here"]
    assert "bad audio" in notes[0]


def test_unavailable_names_the_reason_off_apple_silicon(monkeypatch):
    monkeypatch.setattr(ear.sys, "platform", "linux")
    assert "Apple Silicon" in ear.unavailable()


def test_unavailable_names_a_missing_package(monkeypatch):
    monkeypatch.setattr(ear.sys, "platform", "darwin")
    monkeypatch.setattr(ear.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(ear.importlib.util, "find_spec", lambda name: None)
    assert "parakeet-mlx" in ear.unavailable()


def test_model_cached_reads_the_hugging_face_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    assert not ear.model_cached()
    snap = tmp_path / "models--mlx-community--parakeet-tdt-0.6b-v3" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    assert not ear.model_cached()  # a half-finished download
    (snap / "model.safetensors").write_bytes(b"x")
    assert ear.model_cached()


def test_the_warm_up_command_runs_this_file():
    assert ear.warm_command().endswith('ear.py" --warm')


# -- the real model, only where it is installed and already downloaded ---------

real_model = pytest.mark.skipif(
    importlib.util.find_spec("parakeet_mlx") is None or not ear.model_cached() or shutil.which("say") is None,
    reason="needs parakeet-mlx, its model in the Hugging Face cache, and macOS say",
)


@real_model
def test_the_real_model_hears_the_name(tmp_path):
    clip = tmp_path / "clip.wav"
    subprocess.run(["say", "-o", str(clip), "--data-format=LEI16@16000",
                    "Nova, what do you think about lowering the retry limit"], check=True)
    with wave.open(str(clip)) as w:
        pcm = w.readframes(w.getnframes())
    segments = []

    async def go():
        e = ear.Ear(segments.append)
        e.begin()
        while e.status == "loading":
            await asyncio.sleep(0.05)
        e.feed(silence(0.5) + pcm + silence(1.0))
        await e.idle()
        e.close()

    run(go())
    heard = " ".join(s["text"] for s in segments)
    assert ear.spot_name(heard, ["Nova"]), heard
    assert "retry" in heard.lower()
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk/tests/test_ear_runner.py -q`
Expected: FAIL, with `AttributeError: module 'ear' has no attribute 'Ear'` (and likewise `unavailable`, `model_cached` and `warm_command`).

- [ ] **Step 3: Implement**

In `ear.py`, replace the import block with:

```python
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
```

After `ENERGY_WAKE_S = 0.6  # ...`, add:

```python
MAX_BACKLOG_S = 30.0  # queued audio beyond this is dropped, oldest first
MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"
```

Append to the end of the file:

```python
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
```

Notes for the implementer:
- `get_logmel` must get a **float32** array. A bfloat16 input fails inside parakeet with a matmul shape error, which I hit while prototyping.
- Utterances are transcribed one at a time by a `_drain` task that owns the deque. `_enqueue` can drop the oldest ones, which `run_in_executor` futures could not offer.
- The model loads on the same single worker thread as transcription. `begin()` loads it lazily, and only the first time.

- [ ] **Step 4: Run the tests**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk/tests/test_ear_runner.py -q`
Expected: `11 passed, 1 skipped` (the real-model test).

On an Apple Silicon Mac with the model cached, also run:
`uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with parakeet-mlx python -m pytest skills/talk/tests/test_ear_runner.py -q`
Expected: `12 passed`. The real-model test takes about 8 s warm.

- [ ] **Step 5: Commit**

```bash
git add skills/talk/ear.py skills/talk/tests/test_ear_runner.py
git commit -m "feat(talk): ear transcribes utterances with parakeet-mlx off the event loop"
```

---

### Task 3: the `talk.py` state machine: sleep, hear, wake, seeded session

**Files:**
- Modify: `skills/talk/talk.py`:
  - imports (after `from live_turns import TurnQueue`), and constants after `REJOIN_LINE`;
  - `conversation_block`/`wake_block`, before `GREETING`;
  - `SessionLog`: `SPEAKERS`, `conversation_text`, `new_lines`, plus the new `heard`/`aside`;
  - `LiveController`: `__init__`, `session_config`, `create`, `sideband_ended`, `open_rejoin_window`, `greet`, `on_event` and `tick`.
- Modify: `skills/talk/tests/helpers.py` (`make_args`)
- Test: `skills/talk/tests/test_dormant.py`

**Interfaces:**
- Consumes: `ear.wakes(segment, wake, names)` from Task 1.
- Produces:
  - `args.dormant_after: int`, `args.wake: "speech"|"name"`, `args.name: str`, `args.sounds_like: str` and `args.mode: "talk"|"meeting"`. `make_args` defaults them to `0, "speech", "Nova", "", "talk"`.
  - Module constants `REJOIN_INTRO`, `WAKE_INTRO`, `WAKE_LINE` (formatted with `said=`), `WAKE_NOW_LINE` and `WAKE_HANDOFF_S = 4.0`.
  - `conversation_block(intro: str, conversation: str) -> str` and `wake_block(heard: list[dict], wake: dict | None) -> str`.
  - `SessionLog.heard(text: str)` adds a `Room` turn, which `new_lines()` returns as `{"who": "room", ...}`. `SessionLog.aside(text: str)` writes an italic transcript line.
  - `LiveController` fields: `state: str` (`"dormant"` initially in meeting mode, otherwise `"live"`), `ear` (None until serve sets it), `ear_ws`, `ear_seen: bool`, `heard_since: list[dict]`, `heard_recent: list[str]`, `wake_segment: dict | None`, `woke_with: dict | None`, `rested: asyncio.Event`, `dormant_task` and `away_task`.
  - `LiveController` methods:
    - `should_sleep(now: float) -> bool` and `idle_expired(now: float) -> bool`;
    - `async sleep(wait: float = 10)`, `rest()`, `start_dormant_watch()` and `async dormant_watch(every: float = 1.0)`;
    - `forget_session()` and `wake_names() -> list[str]`;
    - `hear(segment: dict)`, `wake(segment: dict | None = None) -> bool` and `tell_page(message: dict)`;
    - `async ensure_wake_handed_off(wait: float = WAKE_HANDOFF_S)`.

- [ ] **Step 1: Give the test arguments the new flags**

In `skills/talk/tests/helpers.py`, `make_args`, replace `stage_base=None,` with:

```python
        stage_base=None, dormant_after=0, wake="speech", name="Nova", sounds_like="", mode="talk",
```

`dormant_after=0` keeps every existing test on today's behaviour.

- [ ] **Step 2: Write the failing tests**

`skills/talk/tests/test_dormant.py`:

```python
import asyncio

from helpers import instructions, running_app, talk


def run(coro):
    return asyncio.run(coro)


def seg(text, start=0.0, end=1.0, **extra):
    return {"text": text, "start": start, "end": end, **extra}


def live(ctl, log, quiet_since=1000.0):
    """A greeted live session, quiet since `quiet_since`."""
    ctl.session_id, ctl.sessions, ctl.greeted = "s1", 1, True
    ctl.attached.set()
    log.last_learner_speech = quiet_since
    ctl.last_output = quiet_since


async def sleep_through(ctl, reason="client_closed"):
    """sleep(), with GPT-Live answering the close the way it does: session.closed, then the sideband ends."""
    task = asyncio.create_task(ctl.sleep(wait=2))
    await asyncio.sleep(0)
    await ctl.on_event({"type": "session.closed", "reason": reason})
    ctl.sideband_ended()
    await task


class FakeResponse:
    def __init__(self, status, body):
        self.status, self._body = status, body

    async def json(self, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeHttp:
    """Stands in for OpenAI's session-create endpoint and records what was sent."""

    def __init__(self, status=201, body=None):
        self.status = status
        self.body = body if body is not None else {"session": {"id": "s2"}, "transport": {"sdp": "v=0"}}
        self.sent = []

    def post(self, url, headers=None, json=None):
        self.sent.append(json)
        return FakeResponse(self.status, self.body)


# -- live -> dormant -----------------------------------------------------------


def test_a_quiet_live_call_sleeps_after_dormant_after_seconds(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            return ctl.should_sleep(1044.0), ctl.should_sleep(1045.0)

    assert run(go()) == (False, True)


def test_recent_speech_from_either_side_keeps_the_call_live(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            ctl.last_output = 1030.0
            voice = ctl.should_sleep(1050.0)
            ctl.last_output, log.last_learner_speech = 1000.0, 1030.0
            learner = ctl.should_sleep(1050.0)
            return voice, learner

    assert run(go()) == (False, False)


def test_no_sleep_while_a_turn_waits_or_the_brain_works(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            ctl.turns.offer("d1", [{"who": "you", "text": "check jira"}])
            pending = ctl.should_sleep(2000.0)
            await ctl.turns.next(timeout=1)
            working = ctl.should_sleep(2000.0)
            ctl.turns.accept_reply("d1")
            ctl.thinking = True
            thinking = ctl.should_sleep(2000.0)
            ctl.thinking = False
            return pending, working, thinking, ctl.should_sleep(2000.0)

    assert run(go()) == (False, False, False, True)


def test_dormant_after_zero_never_sleeps(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=0) as (client, ctl, log):
            live(ctl, log, quiet_since=1000.0)
            return ctl.should_sleep(99999.0)

    assert run(go()) is False


def test_sleep_closes_the_session_without_ending_the_call_or_opening_a_rejoin_window(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await sleep_through(ctl)
            return (ctl.state, ctl.session_id, ctl.done.is_set(), ctl.rejoinable, log.end_reason,
                    ctl.dormant_task is not None)

    assert run(go()) == ("dormant", None, False, False, "stopped", True)


def test_sleep_sends_session_close_on_the_sideband(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            ws = ctl.ws
            await sleep_through(ctl)
            return [e["type"] for e in ws.events]

    assert run(go()) == ["session.close"]


def test_a_close_reported_as_connection_lost_during_sleep_is_still_a_sleep(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await sleep_through(ctl, reason="connection_lost")
            return ctl.state, ctl.rejoinable, ctl.done.is_set(), log.end_reason

    assert run(go()) == ("dormant", False, False, "stopped")


def test_a_real_drop_while_live_still_opens_the_rejoin_window(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            live(ctl, log)
            await ctl.on_event({"type": "session.closed", "reason": "connection_lost"})
            ctl.sideband_ended()
            return ctl.state, ctl.rejoinable

    assert run(go()) == ("live", True)


def test_the_idle_end_does_not_apply_while_dormancy_is_on(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, idle_minutes=5) as (client, ctl, log):
            log.last_learner_speech = 0.0
            with_dormancy = ctl.idle_expired(3600.0)
            ctl.args.dormant_after = 0
            return with_dormancy, ctl.idle_expired(3600.0)

    assert run(go()) == (False, True)


def test_a_dormant_call_still_ends_at_its_time_limit(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, max_minutes=60) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.limit_at = talk.time.time() - 1
            await asyncio.wait_for(ctl.dormant_watch(every=0.01), 2)
            return ctl.done.is_set(), log.end_reason

    assert run(go()) == (True, "reached the 60 min limit")


# -- dormant -> waking ---------------------------------------------------------


def test_talk_wakes_on_two_words_and_not_on_a_cough(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, wake="speech") as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("hm"))
            after_cough = ctl.state
            ctl.hear(seg("what about retries"))
            return after_cough, ctl.state, ctl.wake_segment["text"]

    assert run(go()) == ("dormant", "waking", "what about retries")


def test_a_meeting_wakes_only_on_its_name_or_a_sound_alike(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, wake="name", name="Nova", sounds_like="Noa, Nover",
                               mode="meeting") as (client, ctl, log):
            start = ctl.state
            ctl.hear(seg("Nora, what do you think about the retry limit"))
            ctl.hear(seg("Novak has the numbers"))
            before = ctl.state
            ctl.hear(seg("noa, lower it to three?"))
            return start, before, ctl.state

    assert run(go()) == ("dormant", "dormant", "waking")


def test_what_the_ear_hears_goes_into_the_transcript_and_the_next_turn(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("we should lower the limit"))
            return log.new_lines(), log.transcript.read_text(), log.conversation_text()

    lines, transcript, conversation = run(go())
    assert lines == [{"who": "room", "text": "we should lower the limit"}]
    assert "**Room:** we should lower the limit" in transcript
    assert "Room: we should lower the limit" in conversation


def test_an_empty_segment_is_not_written_down(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("", energy_only=True, end=0.3))
            return log.new_lines(), ctl.heard_since, ctl.state

    assert run(go()) == ([], [], "dormant")


# -- waking -> live: the seeded session ------------------------------------------


def test_the_woken_session_carries_the_dormant_transcript_and_the_wake_words(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45, wake="name") as (client, ctl, log):
            ctl.state = "dormant"
            ctl.hear(seg("we were talking about retries"))
            ctl.hear(seg("Nova, should it be three?"))
            return ctl.session_config()["instructions"]

    text = run(go())
    assert "Room: we were talking about retries" in text
    assert 'Just said, answer this: "Nova, should it be three?"' in text
    assert "Room: Nova, should it be three?" not in text  # the wake words appear once, as the question


def test_the_dormant_transcript_is_cut_to_the_last_6000_characters(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.state = "dormant"
            ctl.heard_since = [seg(f"early {i} " + "x" * 90) for i in range(100)]
            ctl.state = "waking"
            return ctl.session_config()["instructions"]

    text = run(go())
    assert "early 99" in text and "early 0 " not in text


def test_a_rejoin_after_a_drop_keeps_its_own_block(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.sessions = 1
            log.delta("input", "what is a proposal")
            log.flush("You")
            return ctl.session_config()["instructions"]

    text = run(go())
    assert talk.REJOIN_INTRO in text and "Learner: what is a proposal" in text
    assert "Just said" not in text


def test_a_successful_wake_goes_live_and_clears_what_was_heard(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.http = FakeHttp()
            ctl.run_sideband = lambda: asyncio.sleep(0)
            ctl.state = "dormant"
            ctl.hear(seg("Nova, is it three?"))
            status, _ = await ctl.create("v=0")
            sent = ctl.http.sent[0]["session"]["instructions"]
            return status, ctl.state, ctl.heard_since, ctl.wake_segment, ctl.woke_with["text"], sent

    status, state, heard, pending, woke, sent = run(go())
    assert (status, state, heard, pending, woke) == (201, "live", [], None, "Nova, is it three?")
    assert 'Just said, answer this: "Nova, is it three?"' in sent


def test_a_failed_wake_stays_dormant_and_keeps_the_wake_words_for_the_next_attempt(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.http = FakeHttp(status=429, body={"error": {"message": "insufficient_quota"}})
            ctl.run_sideband = lambda: asyncio.sleep(0)
            ctl.state = "dormant"
            ctl.hear(seg("Nova, is it three?"))
            status, body = await ctl.create("v=0")
            return status, "insufficient_quota" in body["error"], ctl.state, ctl.session_config()["instructions"]

    status, reported, state, config = run(go())
    assert (status, reported, state) == (429, True, "dormant")
    assert 'Just said, answer this: "Nova, is it three?"' in config


def test_a_woken_session_does_not_greet_and_hands_the_wake_words_on(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.attached.set()
            ctl.sessions = 2
            ctl.woke_with = seg("Nova, is it three?")
            await ctl.greet()
            return instructions(ctl)

    said = run(go())
    assert said == [talk.WAKE_LINE.format(said="Nova, is it three?")]


def test_wake_now_without_words_just_says_it_is_listening(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.attached.set()
            ctl.sessions = 2
            ctl.woke_with = {}
            await ctl.greet()
            return instructions(ctl)

    assert run(go()) == [talk.WAKE_NOW_LINE]


def test_wake_words_the_voice_never_handed_off_are_offered_to_the_brain(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.session_id = "s2"
            ctl.state = "dormant"
            ctl.hear(seg("Nova, what is two plus two"))
            await ctl.ensure_wake_handed_off(wait=0.01)
            event = await ctl.turns.next(timeout=1)
            return event["said"], event["id"] in ctl.stale_delegations

    said, untied = run(go())
    assert said == [{"who": "room", "text": "Nova, what is two plus two"}] and untied


def test_wake_words_the_voice_did_hand_off_are_not_offered_twice(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.session_id = "s2"
            ctl.delegations.add("d9")
            await ctl.ensure_wake_handed_off(wait=0.01)
            return ctl.turns.pending

    assert run(go()) is False
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk/tests/test_dormant.py -q`
Expected: FAIL, with `AttributeError: 'LiveController' object has no attribute 'should_sleep'` (and similar).

- [ ] **Step 4: Implement**

**Imports.** After `from live_turns import TurnQueue  # noqa: E402`:

```python
import ear as ear_mod  # noqa: E402
```

**Constants.** After the `REJOIN_LINE = (...)` statement:

```python
REJOIN_INTRO = "This call was interrupted by a dropped connection and is resuming."
WAKE_INTRO = ("This call went quiet, so the live voice was switched off to save cost while a recognizer on the "
              "user's machine kept listening. It is back on now. What that recognizer heard meanwhile is below.")
WAKE_LINE = ('The user has just said: "{said}". Hand it to the backend now. Do not greet, and say nothing '
             "until the backend's reply arrives.")
WAKE_NOW_LINE = "You are back after a quiet spell. Say in three or four words that you're listening, then listen."
WAKE_HANDOFF_S = 4.0  # a woken voice that has not handed the wake words off by then: the server does it
```

**The conversation blocks.** Immediately before `GREETING = (`:

```python
def conversation_block(intro: str, conversation: str) -> str:
    """The conversation so far, for a new session's instructions: the rejoin path and the wake path."""
    return (f"\n{intro} The conversation so far, most recent last:\n"
            f"<conversation>\n{conversation[-6000:]}\n</conversation>\n")


def wake_block(heard: list[dict], wake: dict | None) -> str:
    """What a woken session is told: the dormant transcript, and the words that woke it."""
    lines = "\n".join(f"Room: {s['text']}" for s in heard if s is not wake and s["text"].strip())
    block = conversation_block(WAKE_INTRO, lines or "(nothing was heard)")
    said = ((wake or {}).get("text") or "").strip()
    if said:
        block += (f'\nJust said, answer this: "{said}"\nThese words woke you. Do not greet. Hand them to the '
                  "backend at once, and say nothing until its reply arrives.\n")
    return block
```

The rejoin text that `conversation_block(REJOIN_INTRO, ...)` produces is byte for byte what `session_config` builds today, so `test_a_lost_connection_opens_a_rejoin_window` keeps passing.

**`SessionLog`.** Under `SPEAKERS = {...}`:

```python
    WHO = {"You": "you", "Tutor": "voice", "Room": "room"}  # a turn's `said` lines
    LABEL = {"You": "Learner", "Tutor": "Tutor", "Room": "Room"}  # the conversation as Claude reads it
```

In `conversation_text`, replace both `{'Learner' if s == 'You' else 'Tutor'}` and `{'Learner' if speaker == 'You' else 'Tutor'}` with `{self.LABEL[s]}` and `{self.LABEL[speaker]}`. In `new_lines`, replace the return with `return [{"who": self.WHO[s], "text": t} for s, t in fresh]`. After `new_lines`, add:

```python
    def heard(self, text: str) -> None:
        """A segment the local recognizer heard while the call was dormant: a closed turn of its own."""
        self.flush_all()
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return
        self.turns.append(("Room", text))
        with self.transcript.open("a") as f:
            f.write(f"**Room:** {text}\n\n")
        say(f"heard: {text}")

    def aside(self, text: str) -> None:
        """A line about the call itself, such as dropped audio, kept in the transcript in italics."""
        self.flush_all()
        with self.transcript.open("a") as f:
            f.write(f"_{text}_\n\n")
        say(f"ear: {text}")
```

**`LiveController.__init__`.** After `self.limit_at: float | None = None`:

```python
        # Dormancy: while nobody talks there is no GPT-Live session, and the page's audio goes to a
        # recognizer on this machine instead (the ear). A meeting starts that way.
        self.state = "dormant" if args.mode == "meeting" else "live"  # live | dormant | waking
        self.ear = None  # an ear.Ear, set by serve() when dormancy is on
        self.ear_ws = None  # the page's open /api/ear socket
        self.ear_seen = False  # the page has streamed to /api/ear at least once
        self.heard_since: list[dict] = []  # segments since the last live session, for the next one
        self.heard_recent: list[str] = []  # the last few, for the page
        self.wake_segment: dict | None = None  # what woke the call, until a session opens with it
        self.woke_with: dict | None = None  # the same, handed to greet() of the session it opened
        self.rested = asyncio.Event()  # set when a session closed by sleep() is gone
        self.dormant_task: asyncio.Task | None = None
        self.away_task: asyncio.Task | None = None
```

**`session_config`.** Replace its first five lines, from `instructions = frontend_instructions(...)` through the rejoin `instructions += (...)`, with:

```python
        instructions = frontend_instructions(self.topic, read_key_terms(self.brief))
        if self.state != "live":
            instructions += wake_block(self.heard_since, self.wake_segment)
        elif self.sessions:
            instructions += conversation_block(REJOIN_INTRO, self.log.conversation_text())
```

**`create`.** Make its first line `woken = self.state != "live"  # a wake, or "Wake now" pressed while dormant`. In the error branch, right before `return resp.status, {"error": self.log.last_error}`, add:

```python
                if woken:
                    self.state = "dormant"  # still listening; the wake segment waits for the next attempt
```

After `self.sessions += 1`:

```python
        if woken:
            self.woke_with = self.wake_segment or {}
            self.wake_segment = None
            self.heard_since = []
        self.state = "live"
```

**`sideband_ended`.** Add these as its first lines:

```python
        if self.state == "dormant" and not self.closing and not self.done.is_set():
            self.rest()
            return
```

**`open_rejoin_window`.** Move its session-forgetting lines into a new method, and call it:

```python
    def forget_session(self) -> None:
        """The GPT-Live session is gone but the call is not: after a dropped connection, and after sleep()."""
        self.session_id, self.ws = None, None
        self.attached = asyncio.Event()
        self.greeted = False
        self.thinking = False
        self.stale_delegations |= self.delegations
        self.delegations = set()
        self.voice_base = self.log.voice_seconds or 0.0
        if self.task and not self.task.done():
            self.task.cancel()
        self.log.flush_all()

    def open_rejoin_window(self) -> None:
        """The connection dropped: forget the session, keep the call, and let the page start a new session."""
        self.lost = False
        self.forget_session()
        self.rejoin_until = time.time() + REJOIN_SECONDS
        self.rejoin_task = asyncio.create_task(self.end_unless_rejoined())
        say(f"GPT-Live connection lost; the page may rejoin within {REJOIN_SECONDS} s")
```

**Dormancy methods.** Insert these immediately before `async def greet`:

```python
    # -- dormancy: sleep when quiet, wake on what the ear hears ------------------

    def should_sleep(self, now: float) -> bool:
        """Quiet for --dormant-after seconds: nobody spoke, the voice said nothing, no turn waits on the
        brain and the brain is not working."""
        if self.args.dormant_after <= 0 or self.state != "live" or not self.greeted or self.call_over:
            return False
        if self.thinking or (self.task is not None and not self.task.done()):
            return False
        if self.turns and (self.turns.pending or self.turns.working):
            return False
        return now - max(self.log.last_learner_speech, self.last_output) >= self.args.dormant_after

    def idle_expired(self, now: float) -> bool:
        """The --idle-minutes end, which only applies without dormancy: a dormant call costs nothing."""
        if self.args.dormant_after > 0 or (self.turns and self.turns.working):
            return False
        return now - self.log.last_learner_speech > self.args.idle_minutes * 60

    async def sleep(self, wait: float = 10) -> None:
        """Close the GPT-Live session because nobody is talking. Not a dropped connection, not the end."""
        if self.state != "live" or not self.session_live or self.call_over:
            return
        self.state = "dormant"  # first: the session.closed that follows must see it
        self.rested = asyncio.Event()
        ws = self.ws
        say(f"quiet for {self.args.dormant_after} s: closing the GPT-Live session, listening on this machine")
        await self.send({"type": "session.close", "event_id": self.next_id("close")})
        try:
            await asyncio.wait_for(self.rested.wait(), timeout=wait)
        except asyncio.TimeoutError:
            await ws.close()  # the sideband's end then calls rest()

    def rest(self) -> None:
        """The session sleep() closed is gone: the call is dormant."""
        self.forget_session()
        self.lost = False
        self.heard_since = []
        self.rested.set()
        self.start_dormant_watch()

    def start_dormant_watch(self) -> None:
        if self.dormant_task is None or self.dormant_task.done():
            self.dormant_task = asyncio.create_task(self.dormant_watch())

    async def dormant_watch(self, every: float = 1.0) -> None:
        """No session means no tick(): this keeps the call's time limit while it is dormant or waking."""
        self.limit_at = self.limit_at or time.time() + self.args.max_minutes * 60
        while self.state != "live" and not self.done.is_set():
            if time.time() > self.limit_at:
                self.log.end_reason = f"reached the {self.args.max_minutes} min limit"
                say("time limit reached while dormant; ending the call")
                self.done.set()
                return
            await asyncio.sleep(every)

    def wake_names(self) -> list[str]:
        extra = [s.strip() for s in (self.args.sounds_like or "").split(",")]
        return [self.args.name] + [s for s in extra if s]

    def hear(self, segment: dict) -> None:
        """A segment from the ear: kept for the transcript and the next session, and a wake when it qualifies."""
        if self.call_over:
            return
        text = segment["text"].strip()
        if text:
            if self.state != "live":  # the ear finishing its queue after a wake belongs to the log only
                self.heard_since.append(segment)
            self.heard_recent = (self.heard_recent + [text])[-5:]
            self.log.heard(text)
        if self.state == "dormant" and ear_mod.wakes(segment, self.args.wake, self.wake_names()):
            self.wake(segment)

    def wake(self, segment: dict | None = None) -> bool:
        """Dormant to waking: the page is told to open a session, seeded with what the ear heard."""
        if self.state != "dormant" or self.call_over:
            return False
        if segment is not None:
            self.wake_segment = segment
        self.state = "waking"
        say(f"waking: {(segment or {}).get('text') or 'on request'}")
        self.tell_page({"state": "waking"})
        return True

    def tell_page(self, message: dict) -> None:
        """Push to the page over its /api/ear socket: a background tab's poll can lag by a minute."""
        ws = self.ear_ws
        if ws is not None and not ws.closed:
            asyncio.get_running_loop().create_task(ws.send_str(json.dumps(message)))

    async def ensure_wake_handed_off(self, wait: float = WAKE_HANDOFF_S) -> None:
        """GPT-Live never heard the wake words itself and may not hand them off: if it has not within
        `wait`, offer them to the brain as a turn of the server's own, answered untied."""
        await asyncio.sleep(wait)
        if self.delegations or not self.session_live or self.call_over:
            return
        turn_id = self.next_id("wake")
        self.stale_delegations.add(turn_id)  # no hand-off in this session to tie the answer to
        self.turns.offer(turn_id, self.log.new_lines())
        say("the voice did not hand off the wake words; offering them to the brain directly")
```

**`greet`.** After `self.log.last_learner_speech = time.time()` and before the `if self.sessions > 1:` rejoin branch, add:

```python
        if self.woke_with is not None:
            said = (self.woke_with.get("text") or "").strip()
            self.woke_with = None
            if said:
                await self.append("instructions", WAKE_LINE.format(said=said))
                if self.turns:
                    asyncio.create_task(self.ensure_wake_handed_off())
            else:
                await self.append("instructions", WAKE_NOW_LINE)
            say("Awake: GPT-Live is back on the call.")
            return
```

A woken session never greets. If the voice does not delegate the wake words within 4 s, the server offers them as its own turn, and `answer()` speaks the reply untied because the id is in `stale_delegations`. A meeting's sessions are all woken, so a meeting never greets.

**`on_event`, `session.closed`.** Replace `if reason == "connection_lost" and not self.closing:` with:

```python
            if self.state == "dormant":
                pass  # closed by sleep(): neither a dropped connection nor the end of the call
            elif reason == "connection_lost" and not self.closing:
```

**`tick`.** Replace the idle `elif`, the one ending in `> self.args.idle_minutes * 60):`, with:

```python
            elif self.should_sleep(time.time()):
                asyncio.create_task(self.sleep())
            elif self.idle_expired(time.time()):
```

Keep its body (`self.log.end_reason = f"no speech for ..."` and `close_after_speech(max_wait=5)`) unchanged.

- [ ] **Step 5: Run the talk suite**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk -q`
Expected: everything passes: the 23 new tests and every existing test, the rejoin tests included.

- [ ] **Step 6: Commit**

```bash
git add skills/talk/talk.py skills/talk/tests/helpers.py skills/talk/tests/test_dormant.py
git commit -m "feat(talk): a quiet call sleeps instead of ending, and wakes into a session seeded with what was heard"
```

---

### Task 4: the `/api/ear` WebSocket and the dormant state for the page

**Files:**
- Modify: `skills/talk/talk.py`:
  - constants: add `EAR_REPLACED`;
  - `LiveController`: `never_started`, `ear_opened`, `ear_closed` and `end_unless_back`;
  - `build_app`: `state`, `ear_socket` and the routes;
  - `serve`: `connect_deadline` and the `finally` cancellations.
- Modify: `skills/talk/tests/helpers.py` (add `FakeEar`)
- Test: `skills/talk/tests/test_ear_route.py`

**Interfaces:**
- Consumes: the `Ear` interface from Task 2 (`status`, `begin()`, `feed(pcm)`, `end()`, `close()`). Consumes `LiveController.hear`, `wake`, `tell_page`, `start_dormant_watch` and `state` from Task 3.
- Produces:
  - `GET /api/ear?token=<call token>` is a WebSocket. It accepts binary 16 kHz PCM frames, and sends `{"state": "waking"}` text messages to the page. It answers 403 on a bad token, 404 when dormancy is off, 410 when the call is over and 409 while the call is live. An older socket is closed with code `EAR_REPLACED = 4001` when a newer one opens.
  - `/api/state` gains `state`, `heard` (the last three texts), `ear` (the `Ear.status`, or `null`) and `wake_name` (the name with `--wake name`, else `null`).
  - `LiveController.never_started` is a property; `ear_opened(ws)`, `ear_closed(ws)` and `async end_unless_back(sessions: int)` are methods.
  - `helpers.FakeEar`.

- [ ] **Step 1: Add `FakeEar` to `helpers.py`**, above `def spoken`:

```python
class FakeEar:
    """Stands in for ear.Ear: records what the page streams."""

    status = "ready"

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
```

- [ ] **Step 2: Write the failing tests**

`skills/talk/tests/test_ear_route.py`:

```python
import asyncio

import aiohttp
import pytest

from helpers import AUTH, TOKEN, FakeEar, running_app, talk


def run(coro):
    return asyncio.run(coro)


EAR = f"/api/ear?token={TOKEN}"


async def refused(client, path):
    with pytest.raises(aiohttp.WSServerHandshakeError) as err:
        await client.ws_connect(path)
    return err.value.status


def test_the_ear_needs_the_call_token(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ear, ctl.state = FakeEar(), "dormant"
            return await refused(client, "/api/ear"), await refused(client, "/api/ear?token=wrong")

    assert run(go()) == (403, 403)


def test_the_ear_is_refused_while_the_call_is_live(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=45) as (client, ctl, log):
            ctl.ear = FakeEar()
            return await refused(client, EAR)

    assert run(go()) == 409


def test_the_ear_is_404_when_dormancy_is_off(tmp_path):
    async def go():
        async with running_app(tmp_path) as (client, ctl, log):
            ctl.state = "dormant"
            return await refused(client, EAR)

    assert run(go()) == 404


def test_frames_reach_the_ear_and_start_a_dormant_period(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            never_before = ctl.never_started
            ws = await client.ws_connect(EAR)
            await ws.send_bytes(b"\x01\x00" * 320)
            await ws.send_bytes(b"\x02\x00" * 320)
            for _ in range(50):
                if len(ctl.ear.frames) == 2:
                    break
                await asyncio.sleep(0.01)
            await ws.close()
            await asyncio.sleep(0.05)
            return never_before, ctl.never_started, ctl.ear.begun, ctl.ear.frames, ctl.ear.ended

    never_before, never_after, begun, frames, ended = run(go())
    assert (never_before, never_after, begun, ended) == (True, False, 1, 1)
    assert frames == [b"\x01\x00" * 320, b"\x02\x00" * 320]


def test_a_second_page_replaces_the_first_socket(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            first = await client.ws_connect(EAR)
            second = await client.ws_connect(EAR)
            msg = await asyncio.wait_for(first.receive(), 2)
            await second.send_bytes(b"\x05\x00" * 10)
            await asyncio.sleep(0.05)
            await second.close()
            return (msg.type, msg.data), ctl.ear.frames

    kind, frames = run(go())
    assert kind == (aiohttp.WSMsgType.CLOSE, talk.EAR_REPLACED)
    assert frames == [b"\x05\x00" * 10]


def test_a_wake_is_pushed_to_the_page_over_its_socket(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting", wake="name") as (client, ctl, log):
            ctl.ear = FakeEar()
            ws = await client.ws_connect(EAR)
            await asyncio.sleep(0.05)
            ctl.hear({"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
            msg = await asyncio.wait_for(ws.receive_json(), 2)
            await ws.close()
            return msg

    assert run(go()) == {"state": "waking"}


def test_a_page_that_closes_while_dormant_ends_the_call_after_the_rejoin_window(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "REJOIN_SECONDS", 0.05)

    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            ws = await client.ws_connect(EAR)
            await ws.close()
            await asyncio.wait_for(ctl.done.wait(), 2)
            return log.end_reason

    assert run(go()) == "page closed while dormant"


def test_a_page_that_comes_back_in_time_keeps_the_call(tmp_path, monkeypatch):
    monkeypatch.setattr(talk, "REJOIN_SECONDS", 0.2)

    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting") as (client, ctl, log):
            ctl.ear = FakeEar()
            await (await client.ws_connect(EAR)).close()
            await asyncio.sleep(0.05)
            again = await client.ws_connect(EAR)
            await asyncio.sleep(0.3)
            done = ctl.done.is_set()
            await again.close()
            return done

    assert run(go()) is False


def test_state_tells_the_page_the_dormant_state_and_what_was_heard(tmp_path):
    async def go():
        async with running_app(tmp_path, dormant_after=20, mode="meeting", wake="name") as (client, ctl, log):
            ctl.ear = FakeEar()
            ctl.hear({"text": "we should lower it", "start": 0.0, "end": 1.0})
            return await (await client.get("/api/state", headers=AUTH)).json()

    state = run(go())
    assert (state["state"], state["heard"], state["ear"], state["wake_name"]) == (
        "dormant", ["we should lower it"], "ready", "Nova")
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk/tests/test_ear_route.py -q`
Expected: FAIL. The handshakes get 404 from the router instead of 403 or 409, and `never_started` does not exist.

- [ ] **Step 4: Implement**

Constants, after `WAKE_NOW_LINE`:

```python
EAR_REPLACED = 4001  # the close code of an /api/ear socket a newer page has taken over
```

`LiveController`, before `def publish`:

```python
    @property
    def never_started(self) -> bool:
        """Nobody pressed Start: no session yet, and no local listening either (a meeting starts that way)."""
        return not self.sessions and not self.ear_seen
```

`LiveController`, before `def wake_names`:

```python
    def ear_opened(self, ws) -> None:
        """The page started streaming to the ear. The newest socket wins: a reload or a second tab
        must not interleave two streams in one segmenter."""
        old, self.ear_ws, self.ear_seen = self.ear_ws, ws, True
        if old is not None and not old.closed:  # 4001 tells that page not to reconnect
            asyncio.get_running_loop().create_task(old.close(code=EAR_REPLACED, message=b"replaced by a newer page"))
        if self.away_task:
            self.away_task.cancel()
            self.away_task = None
        self.ear.begin()
        self.start_dormant_watch()

    def ear_closed(self, ws) -> None:
        """A page stopped streaming. Unless the call went live, give the page the rejoin window to come back."""
        if ws is not self.ear_ws:
            return  # a socket already replaced by a newer one
        self.ear_ws = None
        self.ear.end()
        if self.state != "live" and not self.call_over:
            self.away_task = asyncio.create_task(self.end_unless_back(self.sessions))

    async def end_unless_back(self, sessions: int) -> None:
        await asyncio.sleep(REJOIN_SECONDS)
        if self.ear_ws is None and self.sessions == sessions and not self.done.is_set():
            if self.log.end_reason == "stopped":
                self.log.end_reason = "page closed while dormant"
            say("the page stopped listening and did not come back; ending the call")
            self.done.set()
```

The page closes its ear socket when it wakes, so `ear_closed` also runs then. `end_unless_back` spares the call once a session has opened, since `self.sessions` has moved on. When the wake fails, the page's reconnect cancels the timer in `ear_opened`.

`build_app`, `state`: replace the closing `... if ctl.rejoinable else 0}` of the `body = {...}` literal with:

```python
                "rejoin_seconds": max(0, round(ctl.rejoin_until - time.time())) if ctl.rejoinable else 0,
                "state": ctl.state, "heard": ctl.heard_recent[-3:], "ear": ctl.ear.status if ctl.ear else None,
                "wake_name": ctl.args.name if ctl.args.wake == "name" else None}
```

`build_app`, before `async def next_turn`:

```python
    async def ear_socket(request):
        """Binary PCM frames (16 kHz mono 16-bit) from the page while the call is dormant. A browser
        WebSocket cannot send headers, so the token comes as a query parameter."""
        if not secrets.compare_digest(request.query.get("token", ""), token):
            return web.json_response({"error": "forbidden"}, status=403)
        if ctl.ear is None:
            return web.json_response({"error": "local listening is off for this call"}, status=404)
        if ctl.call_over:
            return web.json_response({"error": "the call has ended"}, status=410)
        if ctl.state == "live":
            return web.json_response({"error": "the call is live; its audio goes to GPT-Live"}, status=409)
        ws = web.WebSocketResponse(max_msg_size=1 << 16, heartbeat=20)
        await ws.prepare(request)
        ctl.ear_opened(ws)
        try:
            async for msg in ws:
                if msg.type == web.WSMsgType.BINARY and ws is ctl.ear_ws:
                    ctl.ear.feed(msg.data)
        finally:
            ctl.ear_closed(ws)
        return ws
```

Routes: after `web.get("/api/state", state),`, add `web.get("/api/ear", ear_socket),`.

`serve`, `connect_deadline`: replace `if not ctl.sessions:` with `if ctl.never_started:`. In the `finally` block, replace `for t in (ctl.task, ctl.rejoin_task):` with `for t in (ctl.task, ctl.rejoin_task, ctl.dormant_task, ctl.away_task):`.

- [ ] **Step 5: Run the talk suite**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/talk/talk.py skills/talk/tests/helpers.py skills/talk/tests/test_ear_route.py
git commit -m "feat(talk): /api/ear carries the page's audio to the ear while a call is dormant"
```

---

### Task 5: the call page: AudioWorklet capture, dormant orb, wake flow

**Files:**
- Modify: `skills/talk/talk.py`: the `PAGE` CSS, card HTML and script, and the `page` handler's config in `build_app`.
- Test: `skills/talk/tests/test_browser_dormant.py`

**Interfaces:**
- Consumes: `/api/ear` and the `/api/state` fields from Task 4; `LiveController.create` (Task 3) returning to `dormant` on failure.
- Produces:
  - page config keys `mode`, `dormancy`, `state` and `wakeName`;
  - page functions `toDormant()`, `stopEar()`, `teardownLive()`, `closedByServer()`, `startLive()` and `dormantHint()`;
  - page globals `listening`, `serverState` and `started`, which Task 7's projector bar reads through `setState`.

- [ ] **Step 1: Write the failing browser tests**

`skills/talk/tests/test_browser_dormant.py`:

```python
"""The dormant page in a real browser: it streams 16 kHz PCM to the ear, and a wake closes that
stream before it asks for a live session. Chrome's fake microphone (a beep) stands in for the
user; no OpenAI session is created.

Skips without playwright: run with `--with playwright` (and `playwright install chromium` once)."""
import asyncio
import threading
import time
from contextlib import contextmanager

import pytest

pytest.importorskip("playwright", reason="browser suite: add --with playwright")

from aiohttp import web  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from helpers import CALL, TOKEN, FakeEar, make_args, talk  # noqa: E402

FAKE_MIC = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]


class TimedEar(FakeEar):
    def __init__(self):
        super().__init__()
        self.arrivals: list[tuple[float, int]] = []

    def feed(self, pcm):
        super().feed(pcm)
        self.arrivals.append((time.monotonic(), len(pcm)))


@contextmanager
def served(tmp_path, **overrides):
    """The talk app on a real port, on its own loop in a thread (Playwright's sync API owns this one)."""
    loop = asyncio.new_event_loop()
    ready, box = threading.Event(), {}

    async def start():
        args = make_args(**overrides)
        log = talk.SessionLog(tmp_path / "out", "Test topic", "test")
        ctl = talk.LiveController(args, "Test topic", "", log, None, None)
        ctl.ear = TimedEar()
        runner = web.AppRunner(talk.build_app(args, "Test topic", log, ctl, TOKEN, CALL))
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        box.update(ctl=ctl, runner=runner, loop=loop,
                   url=f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}/c/{CALL}")
        ready.set()

    def main():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start())
        loop.run_forever()

    threading.Thread(target=main, daemon=True).start()
    assert ready.wait(10)
    try:
        yield box
    finally:
        async def stop():
            for task in (box["ctl"].dormant_task, box["ctl"].away_task):
                if task:
                    task.cancel()
            await box["runner"].cleanup()

        asyncio.run_coroutine_threadsafe(stop(), loop).result(10)
        loop.call_soon_threadsafe(loop.stop)


def on_loop(box, fn, *args):
    """Run fn on the server's loop and wait for it: the controller is not thread-safe."""
    async def call():
        return fn(*args)
    return asyncio.run_coroutine_threadsafe(call(), box["loop"]).result(5)


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def test_a_dormant_page_streams_16_khz_pcm_to_the_ear(tmp_path):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        ear = box["ctl"].ear
        assert wait_for(lambda: len(ear.arrivals) > 20)
        time.sleep(3)
        arrivals = list(ear.arrivals)[10:]
        title = page.text_content("#cardtitle")
        browser.close()
    seconds = arrivals[-1][0] - arrivals[0][0]
    rate = sum(n for _, n in arrivals[1:]) / seconds
    assert 16000 * 2 * 0.85 < rate < 16000 * 2 * 1.15, rate  # 16-bit mono at 16 kHz
    assert all(n % 2 == 0 for _, n in arrivals)
    assert title == "Dormant · listening on this Mac · free"


def test_a_wake_stops_the_ear_before_the_session_is_requested_and_a_failure_listens_again(tmp_path):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name") as box, sync_playwright() as p:
        ctl, seen = box["ctl"], {}

        async def failing_create(sdp):
            seen["ear_open"] = ctl.ear_ws is not None
            ctl.state = "dormant"  # what create() does when OpenAI refuses a wake
            return 429, {"error": "session create HTTP 429: insufficient_quota"}

        ctl.create = failing_create
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"])
        page.click("#start")
        assert wait_for(lambda: ctl.ear_ws is not None and ctl.ear.frames)
        on_loop(box, ctl.hear, {"text": "Nova, is it three?", "start": 0.0, "end": 1.0})
        assert wait_for(lambda: "ear_open" in seen)
        assert wait_for(lambda: ctl.ear.begun == 2)  # listening again
        page.wait_for_function("document.getElementById('status').textContent.includes('insufficient_quota')")
        status = page.text_content("#status")
        browser.close()
    assert seen["ear_open"] is False
    assert "Still listening on this Mac" in status
    assert ctl.wake_segment["text"] == "Nova, is it three?"
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright python -m pytest skills/talk/tests/test_browser_dormant.py -q`
(Once per machine, first: `uv run -q --no-project --python 3.12 --with playwright python -m playwright install chromium`.)
Expected: FAIL. The first test times out in `wait_for` because no frames arrive: the page's Start still opens a live session.

- [ ] **Step 3: Implement**

The page config in `build_app`, `page`:

```python
        config = {"topic": topic, "token": token,
                  "inputDevice": args.input_device, "outputDevice": args.output_device, "stageUrl": stage_url,
                  "mode": args.mode, "dormancy": args.dormant_after > 0, "state": ctl.state,
                  "wakeName": args.name if args.wake == "name" else None}
```

In `PAGE`, make these changes.

1. **CSS.** After the `body[data-state="connecting"] .orb,body.working .orb{animation:...}` rule:

```css
body[data-state="dormant"] .orb{--c:var(--faint)}
body[data-state="waking"] .orb{--c:var(--acc);animation:breathe 1.4s ease-in-out infinite}
.heard{grid-column:2;font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.heard[hidden]{display:none}
```

2. **Card.** After `<div class="state" id="status">...</div>`, add `<div class="heard" id="heard" hidden></div>`.

3. **Titles.** Replace the `TITLES` literal's last line, `tutor: "Speaking", thinking: ..., ended: "Call ended" };`, with:

```js
  tutor: "Speaking", thinking: "Working on your question", ended: "Call ended",
  dormant: "Dormant · listening on this Mac · free", waking: "Waking…" };
```

4. **Globals.** After the `let peer, events, mic, ...` line:

```js
// Dormancy: no GPT-Live session; the mic goes to the ear on the server as 16 kHz PCM.
let earWs = null, earCtx = null, earStream = null, earNode = null, listening = false, started = false, leaving = false;
let serverState = CFG.state, earShown = null;
```

5. **Microphone change while dormant.** In `$("mic").onchange`, between the `if (mic && peer) {...}` branch and `} else if (preview) {`, add:

```js
  } else if (listening) {
    stopEar(); await toDormant();
```

6. **`cleanup`.** Add `stopEar();` as its first line.

7. **The ear, and Start.** Replace the line `$("start").onclick = async () => {` and the three lines after it, up to and including `try {`, with the block below. Then change the handler's last line, `} catch (e) { cleanup(); status(String(e.message || e), true); }` followed by `};`, as shown after it.

```js
// The ear: an AudioWorklet turns the mic into 16 kHz mono 16-bit PCM, 20 ms per message. The
// context asks for 16 kHz so Chrome resamples with a proper filter; where a browser ignores that,
// the worklet decimates from whatever rate it got.
const EAR_WORKLET = `class Pcm16k extends AudioWorkletProcessor {
  constructor() { super(); this.step = sampleRate / 16000; this.pos = 0; this.out = new Int16Array(320); this.n = 0; }
  process(inputs) {
    const ch = inputs[0][0]; if (!ch) return true;
    for (; this.pos < ch.length; this.pos += this.step) {
      const i = Math.floor(this.pos), f = this.pos - i, a = ch[i], b = i + 1 < ch.length ? ch[i + 1] : a;
      const v = Math.max(-1, Math.min(1, a + (b - a) * f));
      this.out[this.n++] = v < 0 ? v * 32768 : v * 32767;
      if (this.n === 320) { this.port.postMessage(this.out.buffer, [this.out.buffer]); this.out = new Int16Array(320); this.n = 0; }
    }
    this.pos -= ch.length;
    return true;
  }
}
registerProcessor("pcm16k", Pcm16k);`;
const dormantHint = () => CFG.wakeName ? `Say "${CFG.wakeName}" to ask. Nothing leaves this Mac until then.`
  : "Speak to bring the voice back, or press Wake now.";
function stopEar() {
  listening = false;
  const ws = earWs; earWs = null;
  if (ws) { ws.onclose = null; ws.onmessage = null; ws.close(); }
  earNode?.port.close(); earNode?.disconnect();
  earStream?.getTracks().forEach(t => t.stop()); earCtx?.close().catch(() => {});
  earNode = null; earStream = null; earCtx = null; $("heard").hidden = true;
}
// Leave the live session without ending the call: the server closed it (dormancy) or the page is waking.
function teardownLive() {
  running = false; readers = []; micReader = -1;
  if (events) { events.onclose = null; events.onmessage = null; }
  mic?.getTracks().forEach(t => t.stop()); events?.close(); peer?.close(); audioCtx?.close().catch(() => {});
  $("out").srcObject = null; peer = null; events = null; mic = null; audioCtx = null;
  $("mute").disabled = true; $("start").style.setProperty("--lvl", 0);
}
async function toDormant() {
  if (listening || finalized) return;
  listening = true; teardownLive();
  setState("dormant", "Wake now"); $("start").disabled = false; $("stop").disabled = false;
  earShown = null; status(dormantHint());
  try {
    // The same constraints as the live call: Chrome applies one echo-cancellation setting per device.
    earStream = await navigator.mediaDevices.getUserMedia(micConstraints());
    try { earCtx = new AudioContext({ sampleRate: 16000 }); } catch { earCtx = new AudioContext(); }
    await earCtx.audioWorklet.addModule(URL.createObjectURL(new Blob([EAR_WORKLET], { type: "text/javascript" })));
    earNode = new AudioWorkletNode(earCtx, "pcm16k");
    earCtx.createMediaStreamSource(earStream).connect(earNode);
    earNode.connect(earCtx.destination);  // keeps the node pulled; it writes only silence
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ear?token=${encodeURIComponent(CFG.token)}`);
    ws.binaryType = "arraybuffer";
    ws.onmessage = ({ data }) => {
      let m = {}; try { m = JSON.parse(data); } catch {}
      if (m.state === "waking") { serverState = "waking"; startLive(); }
    };
    ws.onclose = (e) => {
      if (earWs !== ws) return;
      stopEar();
      if (e.code === 4001) { started = false; setState("ended", "In use"); status("Listening moved to another tab.", true); }
    };
    earNode.port.onmessage = ({ data }) => { if (ws.readyState === 1) ws.send(data); };
    earWs = ws;
    if (!listening) stopEar();  // woken or ended while this was opening
  } catch (e) { stopEar(); status("Could not listen on this Mac: " + (e.message || e), true); }
}
// A session.closed from GPT-Live is a drop unless the server put the call to sleep.
async function closedByServer() {
  if (finalized || leaving || !peer) return;
  leaving = true;
  let s = null;
  try { s = await (await fetch("/api/state", { headers: { "X-Talk-Token": CFG.token } })).json(); } catch {}
  if (s && s.state === "dormant") { serverState = "dormant"; await toDormant(); } else dropped();
  leaving = false;
}

$("start").onclick = () => {
  if (running || peer) return;
  started = true;
  if (serverState === "dormant" && !listening) toDormant(); else startLive();
};
async function startLive() {
  if (running || peer) return;
  const waking = serverState !== "live";
  stopEar(); leaving = false;
  $("start").disabled = true; setState(waking ? "waking" : "connecting", ""); status(waking ? "Waking the voice…" : "Connecting…");
  try {
```

The end of the former handler, now `startLive`:

```js
    await peer.setRemoteDescription({ type: "answer", sdp: body.transport.sdp });
  } catch (e) {
    if (waking && CFG.dormancy) {  // the server is dormant again and keeps the wake words for the next try
      serverState = "dormant"; await toDormant(); status(String(e.message || e) + " Still listening on this Mac.", true);
    } else { cleanup(); status(String(e.message || e), true); }
  }
}
```

`startLive` sets `peer` synchronously, as the first statement in its `try`, before any `await`. That makes the `if (running || peer) return;` guard safe when the socket push and the poll both call it for the same wake. `stopEar()` runs before the live `getUserMedia`: Review Focus 2.

8. **Data channel.** In `events.onmessage`, replace `else if (ev.type === "session.closed") dropped();` with `else if (ev.type === "session.closed") closedByServer();`, and replace `events.onclose = dropped;` with `events.onclose = closedByServer;`.

9. **Ending from any state.** Make these four replacements:
   - `endSession`: `if (!running) return;` becomes `if (!running && !listening) return;`.
   - The End button: `if (running && armEnd(` becomes `if ((running || listening) && armEnd(`.
   - The Escape handler: `&& running && armEnd(` becomes `&& (running || listening) && armEnd(`.
   - `beforeunload`: `(running || peer)` becomes `(running || peer || listening)`.

10. **The poll.** Replace `thinking = !!s.thinking; renderWork(s);` and the `if (!running && !peer && !finalized) {` line under it with:

```js
    thinking = !!s.thinking; renderWork(s);
    serverState = s.state || "live";
    const heard = s.heard || [];
    $("heard").hidden = !listening || !heard.length;
    $("heard").textContent = heard.length ? "Heard: " + heard[heard.length - 1] : "";
    if (listening && s.ear !== earShown) {
      earShown = s.ear; status(s.ear === "loading" ? "Preparing local listening (one-time download)…" : dormantHint());
    }
    // The ear socket pushes a wake at once; the poll backs it up if that message was lost.
    if (s.state === "waking" && listening) startLive();
    else if (s.state === "dormant" && started && !listening && !peer && !finalized && !leaving) toDormant();
    if (!running && !peer && !finalized && !listening && serverState === "live") {
```

The rest of that block (Rejoin, In use, back to Start) stays as it is.

- [ ] **Step 4: Run the browser tests and the talk suite**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright python -m pytest skills/talk -q`
Expected: PASS, the two browser tests included. Without `--with playwright` the browser file skips.

- [ ] **Step 5: Look at it.** Open the page by hand in meeting mode, and send the user a screenshot of the dormant orb:

```bash
uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright python - <<'EOF'
import sys; sys.path.insert(0, "skills/talk/tests"); sys.path.insert(0, "skills/talk")
from pathlib import Path
import tempfile
from playwright.sync_api import sync_playwright
from test_browser_dormant import served, FAKE_MIC
with tempfile.TemporaryDirectory() as d, served(Path(d), dormant_after=20, mode="meeting", wake="name") as box, sync_playwright() as p:
    b = p.chromium.launch(args=FAKE_MIC); page = b.new_page(viewport={"width": 1280, "height": 800})
    page.goto(box["url"]); page.click("#start"); page.wait_for_timeout(1500)
    page.screenshot(path="/tmp/talk-dormant.png"); b.close()
EOF
```

- [ ] **Step 6: Commit**

```bash
git add skills/talk/talk.py skills/talk/tests/test_browser_dormant.py
git commit -m "feat(talk): the call page listens locally while dormant and reconnects the voice on a wake"
```

---

### Task 6: the command line, `--doctor`, and switching the ear on in `serve`

**Files:**
- Modify: `skills/talk/talk.py`:
  - the script header;
  - new `apply_mode` and `ear_doctor_lines`, before `write_state_file`;
  - `main`: argparse, and `apply_mode` after the doctor branch;
  - `serve`: build the `Ear`, and close it in `finally`;
  - `doctor`.
- Test: `skills/talk/tests/test_talk_modes.py`

**Interfaces:**
- Consumes: `ear.unavailable`, `ear.model_cached`, `ear.warm_command`, `ear.MODEL_ID`, `ear.Ear`, `LiveController.hear` and `SessionLog.aside`.
- Produces:
  - CLI flags `--mode talk|meeting`, `--dormant-after SECONDS`, `--wake speech|name`, `--name NAME` and `--sounds-like "A,B"`. `--max-minutes` now defaults to `None`, which resolves to 60, or 120 for a meeting.
  - `apply_mode(args) -> str | None` and `ear_doctor_lines() -> list[str]`.

- [ ] **Step 1: Write the failing tests**

`skills/talk/tests/test_talk_modes.py`:

```python
import argparse
import re

from helpers import SKILL_DIR, talk


def cli(**values) -> argparse.Namespace:
    base = dict(mode="talk", wake=None, max_minutes=None, dormant_after=None, name="Nova", sounds_like="")
    base.update(values)
    return argparse.Namespace(**base)


def test_talk_defaults_to_waking_on_speech_after_45_quiet_seconds(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    args = cli()
    assert talk.apply_mode(args) is None
    assert (args.wake, args.dormant_after, args.max_minutes) == ("speech", 45, 60)


def test_a_meeting_wakes_on_its_name_and_runs_two_hours(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    args = cli(mode="meeting")
    assert talk.apply_mode(args) is None
    assert (args.wake, args.dormant_after, args.max_minutes) == ("name", 20, 120)


def test_explicit_flags_win_over_the_mode_defaults(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    args = cli(mode="meeting", max_minutes=30, wake="speech", dormant_after=10)
    talk.apply_mode(args)
    assert (args.wake, args.dormant_after, args.max_minutes) == ("speech", 10, 30)


def test_talk_without_local_listening_runs_as_before_and_says_so(monkeypatch, capsys):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: "local listening needs an Apple Silicon Mac")
    args = cli()
    assert talk.apply_mode(args) is None
    assert args.dormant_after == 0
    assert "Dormancy is off for this call: local listening needs an Apple Silicon Mac." in capsys.readouterr().out


def test_a_meeting_without_local_listening_refuses_to_start(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: "parakeet-mlx is not installed")
    assert talk.apply_mode(cli(mode="meeting")) == "/meet needs local listening: parakeet-mlx is not installed"


def test_a_meeting_cannot_switch_dormancy_off(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    assert "--dormant-after" in talk.apply_mode(cli(mode="meeting", dormant_after=0))


def test_dormant_after_zero_never_checks_for_the_ear(monkeypatch):
    def boom():
        raise AssertionError("checked")
    monkeypatch.setattr(talk.ear_mod, "unavailable", boom)
    args = cli(dormant_after=0)
    assert talk.apply_mode(args) is None and args.dormant_after == 0


def test_the_doctor_reports_the_model_and_offers_the_warm_up(monkeypatch):
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: None)
    monkeypatch.setattr(talk.ear_mod, "model_cached", lambda: False)
    lines = talk.ear_doctor_lines()
    assert len(lines) == 1 and "not downloaded yet" in lines[0] and "ear.py\" --warm" in lines[0]
    monkeypatch.setattr(talk.ear_mod, "model_cached", lambda: True)
    assert talk.ear_doctor_lines()[0].startswith("[ok] local listening")
    monkeypatch.setattr(talk.ear_mod, "unavailable", lambda: "local listening needs an Apple Silicon Mac")
    assert talk.ear_doctor_lines() == ["[--] local listening (dormancy, /meet): local listening needs an Apple Silicon Mac"]


def test_the_script_installs_parakeet_only_on_apple_silicon():
    header = (SKILL_DIR / "talk.py").read_text().split("# ///", 2)[1]
    line = next(l for l in header.splitlines() if "parakeet-mlx" in l)
    assert re.search(r"sys_platform == 'darwin' and platform_machine == 'arm64'", line)
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk/tests/test_talk_modes.py -q`
Expected: FAIL, with `AttributeError: module 'talk' has no attribute 'apply_mode'` and a `StopIteration` in the header test.

- [ ] **Step 3: Implement**

Script header dependencies:

```python
# dependencies = [
#   "aiohttp>=3.10,<4",
#   "anthropic>=1.0,<2",
#   "parakeet-mlx>=0.5,<0.6; sys_platform == 'darwin' and platform_machine == 'arm64'",
# ]
```

Before `def write_state_file`:

```python
def apply_mode(args) -> str | None:
    """Fill in the defaults that depend on --mode, and switch dormancy off where the ear cannot run.
    Returns why the call cannot start (a meeting without local listening), or None."""
    meeting = args.mode == "meeting"
    if args.wake is None:
        args.wake = "name" if meeting else "speech"
    if args.max_minutes is None:
        args.max_minutes = 120 if meeting else 60
    if args.dormant_after is None:
        args.dormant_after = 20 if meeting else 45
    if meeting and args.dormant_after <= 0:
        return "a meeting listens locally between questions: --dormant-after must be above 0"
    if args.dormant_after <= 0:
        return None
    if problem := ear_mod.unavailable():
        if meeting:
            return f"/meet needs local listening: {problem}"
        say(f"Dormancy is off for this call: {problem}.")
        args.dormant_after = 0
    return None


def ear_doctor_lines() -> list[str]:
    """What --doctor says about local listening. Informational: /talk works without it."""
    if problem := ear_mod.unavailable():
        return [f"[--] local listening (dormancy, /meet): {problem}"]
    if ear_mod.model_cached():
        return [f"[ok] local listening: {ear_mod.MODEL_ID} is downloaded"]
    return [f"[--] local listening: {ear_mod.MODEL_ID} is not downloaded yet; the first dormant period downloads "
            f"it (about 2.5 GB). To do it now: {ear_mod.warm_command()}"]
```

`main`. Replace the `--max-minutes` and `--idle-minutes` lines with:

```python
    parser.add_argument("--max-minutes", type=int, default=None, help="default 60, or 120 with --mode meeting")
    parser.add_argument("--idle-minutes", type=int, default=5,
                        help="end a call after this long without speech; only with --dormant-after 0")
    parser.add_argument("--mode", choices=["talk", "meeting"], default="talk",
                        help="meeting: start dormant, wake only on --name, answer only when asked (/meet)")
    parser.add_argument("--dormant-after", type=int, default=None, metavar="SECONDS",
                        help="close the GPT-Live session after this long without speech and listen on this "
                             "machine for free until spoken to (default 45, 20 with --mode meeting; 0 = never)")
    parser.add_argument("--wake", choices=["speech", "name"], default=None,
                        help="what wakes a dormant call: any speech of two words or more (talk's default), "
                             "or the --name (meeting's default)")
    parser.add_argument("--name", default="Nova", help="the wake name for --wake name (default Nova)")
    parser.add_argument("--sounds-like", default="",
                        help='comma-separated spellings the recognizer may produce for the name, e.g. "Noa,Nover"')
```

After the `if args.doctor: return doctor(args)` lines:

```python
    if problem := apply_mode(args):
        say(problem)
        return 2
```

`serve`, after `ctl.stage_cwd = stage_cwd`:

```python
    if args.dormant_after > 0:
        ctl.ear = ear_mod.Ear(on_segment=ctl.hear, on_note=log.aside)
```

`serve`, `finally`, after `ctl.stage_pool.shutdown(...)`:

```python
        if ctl.ear:
            ctl.ear.close()
```

`doctor`, before the `normalisation:` line:

```python
    for line in ear_doctor_lines():
        say(line)
```

These lines do not change the doctor's exit code, because /talk runs without local listening.

- [ ] **Step 4: Run the tests, and check that the script resolves**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills/talk -q`
Expected: PASS.

Run: `uv run --script skills/talk/talk.py --help | grep -E "dormant-after|sounds-like|--mode"`
Expected: the three flags are listed. The first run on Apple Silicon installs parakeet-mlx and its dependencies, about 65 packages.

Run: `uv run --script skills/talk/talk.py --doctor 2>&1 | grep "local listening"`
Expected on this Mac: `[ok] local listening: mlx-community/parakeet-tdt-0.6b-v3 is downloaded`, or the `[--]` line with the warm-up command.

- [ ] **Step 5: Commit**

```bash
git add skills/talk/talk.py skills/talk/tests/test_talk_modes.py
git commit -m "feat(talk): --dormant-after, --wake, --name and --mode flags, and the doctor checks local listening"
```

---

### Task 7: meeting mode: the voice's instructions, and the projector view

**Files:**
- Modify: `skills/talk/talk.py`:
  - new `meeting_instructions`, before `BACKEND_PROMPT`;
  - `LiveController.session_config`;
  - `PAGE`: CSS, the status bar HTML, and the script (`PROJECTOR`, `setState`, `paintBar`).
- Test: `skills/talk/tests/test_meeting_mode.py`; append to `skills/talk/tests/test_browser_dormant.py`

**Interfaces:**
- Consumes: `args.mode` and `args.name` (Task 6), `wake_block` (Task 3), and the page's `setState` and `CFG.wakeName` (Task 5).
- Produces: `meeting_instructions(name: str, topic: str, key_terms: list[str]) -> str`. The page, opened with `?view=projector`, adds `body.projector`, a `#pbar` status bar with `#pbartext`, and a `#pstart` button.

- [ ] **Step 1: Write the failing tests**

`skills/talk/tests/test_meeting_mode.py`:

```python
import asyncio

from helpers import CALL, running_app, talk


def run(coro):
    return asyncio.run(coro)


def test_meeting_instructions_name_the_voice_and_forbid_greeting_and_backchannel():
    text = talk.meeting_instructions("Nova", "Retry policy review", ["idempotency"])
    assert "You are Nova, a participant in an in-person meeting" in text
    assert "Never greet" in text and "Never backchannel" in text
    assert "say nothing at all while you wait" in text
    assert "follow-up" in text
    assert "idempotency" in text


def test_a_meeting_session_uses_the_meeting_instructions_and_the_wake_words(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20, name="Nova") as (c, ctl, log):
            ctl.hear({"text": "we keep hitting the retry limit", "start": 0.0, "end": 1.0})
            ctl.hear({"text": "Nova, what is the limit today?", "start": 2.0, "end": 3.0})
            return ctl.state, ctl.session_config()["instructions"]

    state, text = run(go())
    assert state == "waking"
    assert text.startswith("You are Nova, a participant")
    assert "tutor" not in text.lower()
    assert "Room: we keep hitting the retry limit" in text
    assert 'Just said, answer this: "Nova, what is the limit today?"' in text


def test_talk_keeps_the_tutor_voice(tmp_path):
    async def go():
        async with running_app(tmp_path) as (c, ctl, log):
            return ctl.session_config()["instructions"]

    assert run(go()).startswith("You are the voice of a thoughtful, sharp tutor")


def test_the_projector_view_is_the_same_call_page(tmp_path):
    async def go():
        async with running_app(tmp_path, mode="meeting", wake="name", dormant_after=20) as (client, ctl, log):
            resp = await client.get(f"/c/{CALL}?view=projector")
            return resp.status, await resp.text()

    status, html = run(go())
    assert status == 200
    assert 'id="pbar"' in html and 'get("view") === "projector"' in html
    assert '"wakeName": "Nova"' in html and '"mode": "meeting"' in html
```

Append to `skills/talk/tests/test_browser_dormant.py`:

```python
def test_the_projector_view_gives_the_stage_the_screen_and_says_how_to_ask(tmp_path):
    with served(tmp_path, dormant_after=20, mode="meeting", wake="name", name="Nova") as box, sync_playwright() as p:
        browser = p.chromium.launch(args=FAKE_MIC)
        page = browser.new_page()
        page.goto(box["url"] + "?view=projector")
        before = page.text_content("#pbartext")
        page.click("#pstart")
        page.wait_for_function("document.getElementById('pbartext').textContent.startsWith('Listening')")
        bar, aside = page.text_content("#pbartext"), page.is_visible("aside")
        started_hidden = page.is_hidden("#pstart")
        browser.close()
    assert before == "Press Start to begin listening"
    assert bar == "Listening · say 'Nova' to ask"
    assert not aside and started_hidden
```

- [ ] **Step 2: Run them and confirm they fail**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright python -m pytest skills/talk/tests/test_meeting_mode.py skills/talk/tests/test_browser_dormant.py -q`
Expected: FAIL, with `AttributeError: module 'talk' has no attribute 'meeting_instructions'`, and the projector test failing on `#pbartext`.

- [ ] **Step 3: Implement**

Before `BACKEND_PROMPT = f"""`:

```python
def meeting_instructions(name: str, topic: str, key_terms: list[str]) -> str:
    """GPT-Live's prompt in a meeting: a participant that speaks only when named, and briefly."""
    terms = f"\nWords people in the room may use: {', '.join(key_terms)}.\n" if key_terms else ""
    return f"""You are {name}, a participant in an in-person meeting. The meeting is about: {topic}.
Several people are in the room. Most of what you hear is them talking to each other, not to you.

You are only the voice. A backend assistant holds the context and does all of the thinking. You never answer, explain or give facts from your own knowledge.

When to speak: only when someone addresses you by name ("{name}, ...") or, right after you answered, asks you a direct follow-up ("and what about ...") without repeating your name. Everything else is the room talking among themselves: stay completely silent.
Never greet. Never backchannel: no "mm-hmm", no "right", no listening sounds. Never comment on the discussion, summarise it or offer help unprompted.

Delegation policy:
Backend tools:
- Assistant: holds the context of this meeting and the work behind it; answers every question put to {name}.
Delegate to the backend when:
- Someone asks {name} a question or asks {name} to do something.
- Someone asks a follow-up to the answer you just gave.
Do not delegate to the backend when:
- People are talking to each other, even about you.
- Someone only acknowledges your answer ("thanks", "okay").
Delegate at once, and say nothing at all while you wait: no bridge, no filler. The people in the room may see a board where the assistant shows things, so "on the screen" is expected.

When the backend's reply arrives, say it to the person who asked, in natural spoken words and in a few sentences, adding nothing of your own. Then go silent again.

Pronunciation: {PRONUNCIATION}
{terms}"""
```

`session_config`: replace its first line, `instructions = frontend_instructions(self.topic, read_key_terms(self.brief))`, with:

```python
        terms = read_key_terms(self.brief)
        if self.args.mode == "meeting":
            instructions = meeting_instructions(self.args.name, self.topic, terms)
        else:
            instructions = frontend_instructions(self.topic, terms)
```

The follow-up window needs no code of its own. After an answer, 20 s of quiet (`--dormant-after 20`) puts the call to sleep, and from then on only the name wakes it.

`PAGE`, CSS, immediately before `@media (max-width:900px){`:

```css
.pbar{display:none}
body.projector .app{grid-template-columns:1fr;height:calc(100% - 44px)}
body.projector aside{display:none}
body.projector .pbar{display:flex;align-items:center;gap:10px;height:44px;padding:0 16px;background:var(--panel);border-bottom:1px solid var(--line);font:500 14px var(--sans)}
body.projector .pbar .dot{width:10px;height:10px;border-radius:50%;background:var(--faint);flex:none}
body.projector[data-state="dormant"] .pbar .dot{background:var(--acc)}
body.projector .pbar .btn{flex:none;margin-left:auto}
body.projector .pbar .btn[hidden]{display:none}
```

`PAGE`, HTML: between `<body data-state="idle">` and `<div class="app">`:

```html
<div class="pbar" id="pbar" aria-live="polite"><span class="dot"></span><span id="pbartext"></span><button class="btn" id="pstart" type="button">Start</button></div>
```

`PAGE`, script, right after `const $ = (id) => document.getElementById(id);`:

```js
// ?view=projector: the stage fills the screen under a thin status bar, for a room to watch.
const PROJECTOR = new URLSearchParams(location.search).get("view") === "projector";
if (PROJECTOR) document.body.classList.add("projector");
$("pstart").onclick = () => $("start").click();
```

Replace `setState` with the following, which adds `paintBar`:

```js
const setState = (s, label) => {
  document.body.dataset.state = s; if (label !== undefined) $("orblabel").textContent = label;
  $("cardtitle").textContent = label === "Muted" ? "Muted" : (TITLES[s] || "");
  paintBar();
};
function paintBar() {
  if (!PROJECTOR) return;
  const s = document.body.dataset.state, who = CFG.wakeName || "The voice";
  $("pbartext").textContent = s === "idle" ? "Press Start to begin listening"
    : s === "dormant" ? (CFG.wakeName ? `Listening · say '${CFG.wakeName}' to ask` : "Listening")
    : s === "ended" ? "Call ended" : ["waking", "connecting"].includes(s) ? `${who} is joining…`
    : `${who} is live · follow-ups need no name`;
  $("pstart").hidden = s !== "idle";
}
paintBar();
```

`paintBar` must not read `finalized` or any other `let` declared further down. It runs at load, and those bindings are still in their temporal dead zone then.

- [ ] **Step 4: Run the talk suite with the browser tests**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright python -m pytest skills/talk -q`
Expected: PASS. Without playwright: PASS, with the browser file skipped.

- [ ] **Step 5: Commit**

```bash
git add skills/talk/talk.py skills/talk/tests/test_meeting_mode.py skills/talk/tests/test_browser_dormant.py
git commit -m "feat(talk): meeting mode speaks only when named, and a projector view gives the stage the screen"
```

---

### Task 8: `/meet` skill, plugin manifest, README, talk SKILL.md

**Files:**
- Create: `skills/meet/SKILL.md`
- Modify: `.claude-plugin/marketplace.json` (add `"./skills/meet"` after `"./skills/talk"`)
- Modify: `skills/talk/SKILL.md` (how it works, launch, section 3, preconditions)
- Modify: `README.md` (install comment, and the sentence about `talk` serving its own page)

**Interfaces:**
- Consumes: the CLI from Task 6, `?view=projector` from Task 7, and `room` lines in `said` from Task 3.

- [ ] **Step 1: Write `skills/meet/SKILL.md`**

````markdown
---
name: meet
description: Sit in an in-person meeting as a named participant ("Nova" unless told otherwise) that listens on this Mac for free and speaks only when someone says its name. Answers come from this Claude Code session with its full history and tools, spoken by GPT-Live, and anything visual goes on the stage, which a projector can show full screen. Use when the user says "/meet", "join the meeting", "sit in on this meeting", or wants an assistant in the room that people can ask out loud.
user-invocable: true
argument-hint: optional — what the meeting is about, and a name other than Nova
---

# /meet — a meeting participant that speaks only when named

/meet is /talk in meeting mode: the same server (`talk.py`), the same doorbell and reply
commands, the same stage. `$SKILL_DIR` is this skill's base directory; the talk skill is
`$SKILL_DIR/../talk`, written `$TALK` below. Read `$TALK/SKILL.md` once: everything it says
applies here unless this file says otherwise.

What differs from /talk:

- **It starts dormant.** After Start, the page streams the room's audio to a recognizer on
  this Mac (parakeet-mlx). That costs nothing and sends nothing anywhere. No GPT-Live
  session exists.
- **Its name wakes it.** When the recognizer hears the name, a GPT-Live session opens, told
  what the room said since the last answer, and the words that named it reach you as a turn.
- **It answers only what was asked of it**, in a few sentences, then goes silent. A
  follow-up within 20 seconds needs no name; after 20 s of quiet it goes dormant again and
  the name is needed again. It never greets and never backchannels.
- **It runs up to 120 minutes.** GPT-Live costs $0.05 a minute only while it is live.

## 1. Preconditions (check silently)

1. Everything in `$TALK/SKILL.md` section 1: a local machine, `uv`, `OPENAI_API_KEY`, the webcompanion daemon.
2. **An Apple Silicon Mac.** Local listening needs one. Elsewhere `talk.py` refuses a meeting
   and prints why; relay that line and stop.
3. **The listening model.** `uv run --script "$TALK/talk.py" --doctor` prints a `local listening`
   line. If the model is not downloaded, run the command that line gives, before the meeting
   (about 2.5 GB, once). Otherwise the first minutes of the meeting go to the download, and
   the name cannot be heard until it finishes.

The name is `Nova` unless the user gives another. Choose one nobody in the room has, and list
two or three spellings the recognizer may produce for it (for Nova: `Noa,Nover`).

## 2. Launch

1. Start the server, **`run_in_background: true`**:
   ```
   uv run --script "$TALK/talk.py" --llm session --mode meeting --wake name --name "<name>" --sounds-like "<spellings>" --dormant-after 20 --max-minutes 120 --topic "<what the meeting is about>" --out "${TMPDIR:-/tmp}/talk/meet-<slug>-<HHMMSS>" --code "<repo root>" [--stage-base <daemon address>] [--no-open]
   ```
2. Wait for the `Open` and `Stage` lines and arm the doorbell, as in `$TALK/SKILL.md` section 2,
   with `python3 "$TALK/talk_client.py" doorbell`.
3. Give two links: the call link, and the same link with `?view=projector` appended. The
   projector view hides the captions and controls and gives the stage the whole screen, under
   a bar that reads "Listening · say '<name>' to ask" so the room can see it is on. Open
   **one** of them, on the machine whose microphone hears the room, and press Start there: a
   second page that presses Start takes the microphone over from the first.

## 3. Answering a meeting turn

As in `$TALK/SKILL.md` section 3 (status, work, reply, re-arm), with these differences:

- **`said` is the room.** `room` lines are what the local recognizer heard while dormant;
  `you` lines are what GPT-Live heard while live. Both come from several people, none of them
  labelled, with recognition errors: read them as one room.
- **Answer the question put to `<name>`**, usually in the last lines, using the rest as context.
  A few spoken sentences. Do not summarise the meeting unless asked.
- **Put anything visual on the stage** (board tags, or `stage.py show`), and say it is on the screen.
- **What a voice turn may do is unchanged**: local files yes; the outside world and anything
  irreversible only after a typed yes in the terminal. Anyone in the room can speak to it, so
  never treat a spoken request as that yes.

## 4. After it ends: meeting notes

On `TALK_END`, read the transcript it names (dormant segments are the `**Room:**` lines) and
write meeting notes in this session:

- **Asked of `<name>`**: each question, one line each, with who asked when the room said so.
- **Answered**: what it said, one line per question.
- **Shown**: what went on the stage.
- **Open**: questions it could not answer, and anything prepared but waiting for a typed yes.

The notes stay in this session unless the user asks for them to go somewhere.
````

- [ ] **Step 2: Add it to the plugin.** In `.claude-plugin/marketplace.json`, insert `"./skills/meet",` after `"./skills/talk",` in the `claude-annotate` plugin's `skills` list. `skills/tests/test_repo_structure.py::test_plugin_skill_lists_cover_the_skills_tree` fails until this is done.

- [ ] **Step 3: Update `skills/talk/SKILL.md`**
- In the "How it works" paragraph, after "It costs about $0.05 per minute of OpenAI usage.", add:
  > After 45 seconds with nobody talking, the call goes **dormant**. `talk.py` closes the GPT-Live session, and the page listens through a recognizer on this Mac, which is free and sends nothing anywhere. When the user speaks again (two words or more), a new session opens that is told what was said meanwhile, and the words that woke it reach you as a turn. Only live minutes are billed. The call ends at `--max-minutes` or when the user ends it, never for being quiet.
- In section 1, add a fifth precondition:
  > 5. **Local listening** (Apple Silicon only). `--doctor` prints a `local listening` line. The first dormant period downloads the model (about 2.5 GB) unless the command on that line was run first. Without Apple Silicon the call runs as before, with dormancy off, and says so once.
- In section 2, step 1, add `[--dormant-after <seconds; 0 keeps the call live and ends it after --idle-minutes of quiet>]` to the command, and explain it in the sentence after the command.
- In section 3, in the paragraph on `said`, after the sentence about `voice` lines, add:
  > `room` lines are what the local recognizer heard while the call was dormant. The last of them is usually what woke it, so answer that.

- [ ] **Step 4: Update `README.md`**
- In the install block, under `/plugin install claude-annotate`, add the comment line `# sit in a meeting and answer when named (/meet)` after the `/talk` line.
- Replace "(`talk` serves its own call page too, and additionally needs `uv` and an `OPENAI_API_KEY`; its board is the stage.)" with "(`talk` and `meet` serve their own call page too, and additionally need `uv` and an `OPENAI_API_KEY`; their board is the stage. Both listen on the Mac for free while nobody is talking; `meet` needs Apple Silicon for that.)"
- The "All eight skills" counts stay as they are: they list daemon-backed skills, and `meet`, like `talk`, is not one.

- [ ] **Step 5: Run the whole suite**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' python -m pytest skills -q`
Expected: PASS. Browser, real-model and end-to-end tests skip.

- [ ] **Step 6: Commit**

```bash
git add skills/meet/SKILL.md .claude-plugin/marketplace.json skills/talk/SKILL.md README.md
git commit -m "docs: meet skill, and talk explains dormancy"
```

---

### Task 9: the end-to-end test

**Files:**
- Test: `skills/talk/tests/test_e2e_dormant.py`

**Interfaces:**
- Consumes: the whole call, as a subprocess: `talk.py --dormant-after 10 --wake name`, the state file named by `TALK_STATE`, and the `/api/state`, `/api/turn`, `/api/reply` and `/api/stop` routes. Also `ear.model_cached`, `ear.spot_name` and `talk.stage_mod.daemon_status`.

The spec asks for a fake-mic Chrome playing a clip with a pause of `--dormant-after` + 5 s. Chrome's `--use-file-for-fake-audio-capture` plays its file on its own clock. The moment the call goes dormant depends on how long the greeting takes, and this call opens the mic twice: live, then the ear. The test therefore replaces `getUserMedia` with a WebAudio stream and plays "Nova, what is two plus two" once the server reports `dormant`. That tests the same thing without depending on timing.

- [ ] **Step 1: Write the test**

```python
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
        stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, TALK_STATE=str(state_file)))
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
            wait_until(port, token, live, 60, "waking into a new live session")

            status, turn = call(port, token, "GET", "/api/turn?wait=30", timeout=40)
            assert status == 200 and turn["type"] == "turn", turn
            room = " ".join(line["text"] for line in turn["said"] if line["who"] == "room")
            assert re.search(r"two plus two|2 ?\+ ?2", room, re.IGNORECASE), turn["said"]
            assert ear.spot_name(room, ["Nova"]), turn["said"]
            assert call(port, token, "POST", "/api/reply", {"id": turn["id"], "text": "Four."})[0] == 200
            time.sleep(3)
            call(port, token, "POST", "/api/stop")
            proc.wait(30)
            browser.close()
        transcript = (tmp_path / "out" / "transcript.md").read_text()
        assert "**Room:**" in transcript and "Four." in transcript
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(10)
        log.close()
```

- [ ] **Step 2: Confirm it skips cleanly**

Run: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright python -m pytest skills/talk/tests/test_e2e_dormant.py -q -rs`
Expected: `1 skipped`, with a reason that names `TALK_E2E=1`.

- [ ] **Step 3: Run it for real, once, with the user's go-ahead.** It spends about a minute of GPT-Live. Ask the user before running it:

```bash
TALK_E2E=1 uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright python -m pytest skills/talk/tests/test_e2e_dormant.py -q
```

Expected: `1 passed` in about 60–90 s. If it fails at "the first live session" with an HTTP 429 `insufficient_quota` in `talk.log`, the account has no credit. Report that; it is not a code failure.

- [ ] **Step 4: Commit**

```bash
git add skills/talk/tests/test_e2e_dormant.py
git commit -m "test(talk): end to end, a quiet call goes dormant and wakes on its name"
```

---

## After the last task

1. Run the full suite with every optional part: `uv run -q --no-project --python 3.12 --with pytest --with 'aiohttp>=3.10,<4' --with playwright --with parakeet-mlx python -m pytest skills -q`. Expected: PASS, with only the end-to-end test skipped.
2. The spec's manual check, done by the user:
   - start a real `/talk` call, say one thing, then leave it idle for five minutes;
   - confirm that the page shows "Dormant · listening on this Mac · free", and that the terminal printed `quiet for 45 s: closing the GPT-Live session`;
   - say something, and confirm that the voice answers it without greeting;
   - on the OpenAI usage page, confirm that the idle minutes were not billed.
3. `/meet` in a real room: open the projector link, say the name with a question, and send the user a screenshot of the projector view while it answers.

---

### Task 10: what a call costs, live on the page and totalled at the end

Added 2026-09-28 at the user's request: "I need to have a way to see how much a session costs. Either live either when it ends."

**Files:**
- Modify: `skills/talk/talk.py` (`SessionLog.finish`, `LiveController` state bookkeeping, `/api/state`, the call page)
- Modify: `skills/talk/SKILL.md` ("After it ends")
- Test: `skills/talk/tests/test_cost.py` (new); a browser assertion in `skills/talk/tests/test_browser_dormant.py` if that file exists by then

**Interfaces:**
- Consumes: `SessionLog.voice_seconds` (GPT-Live audio seconds as reported by `session.usage.updated`, summed over sessions through `voice_base`), `LiveController.state`, `rest()`, `wake()`, `create()`.
- Produces:
  - `LIVE_PRICE_PER_MIN = 0.05`, a module constant next to `LIVE_MODEL`, with a comment naming its source (OpenAI's published gpt-live-1 rate, September 2026);
  - `LiveController.cost_view() -> dict` = `{"voice_seconds": float, "dormant_seconds": float, "cost_usd": float}`;
  - `/api/state` gains `"cost": ctl.cost_view()`;
  - `SessionLog.finish()`'s summary gains `cost_usd` and `dormant_seconds`, and the transcript footer names both.

Rules:
- **What is billed.** Only GPT-Live seconds cost money. Dormant listening is local, so its cost is 0. In `--llm session` mode the brain is this Claude session, whose use is covered by the user's subscription and not measured here. The page says "Claude: your plan", and the recap says so in one clause.
- **Live number.** `voice_seconds` is the last reported total plus the seconds the current session has been open since that report, while `state == "live"`. The number keeps moving between usage events, and it never drops when the next report arrives: take the max of the estimate and the reported total. `cost_usd = voice_seconds / 60 * LIVE_PRICE_PER_MIN`, rounded to cents for display only.
- **Dormant time.** `dormant_seconds` accumulates every stretch where `state` is `dormant` (including a meeting's initial dormant stretch). A stretch runs from entering dormant (`rest()` or the meeting start) until `wake()` moves the state on, or until the call ends.
- **Page.** One line in the orb card, under the status: `GPT-Live 3m 12s · $0.16 · asleep 14m (free) · Claude: your plan`, updated on each `/api/state` poll. Hide the asleep part while it is 0. The projector view hides the line: the room does not need to see costs.
- **End.**
  - The transcript footer gains `· $0.16 GPT-Live · 14m asleep (free)`.
  - `session.json` gains `cost_usd` and `dormant_seconds`.
  - `skills/talk/SKILL.md` "After it ends" adds a **Cost** line to the recap, read from the footer: GPT-Live minutes and dollars, and time asleep.
  - `skills/meet/SKILL.md` gets the same line if Task 8 has created it by then.

- [ ] **Step 1: Write the failing tests** in `skills/talk/tests/test_cost.py`, using the fake clock and faked session the Task 3 tests use (`test_dormant.py`):
  - A live session reported at 60 s shows `voice_seconds >= 60` and `cost_usd == 0.05`.
  - Between reports, the estimate grows with the clock while live and never goes below the last report.
  - After `sleep()` → `rest()`, 30 s dormant, then `wake()`: `dormant_seconds == 30` and `voice_seconds` has not grown during the dormant stretch.
  - A meeting that starts dormant counts its first stretch.
  - `/api/state` includes `cost` with the three keys.
  - `finish()` writes `cost_usd` and `dormant_seconds` into `session.json`, and the footer contains `$` and `asleep`.
- [ ] **Step 2: Run them, confirm they fail.**
- [ ] **Step 3: Implement** per the rules above.
- [ ] **Step 4:** Run the talk suite (command in Global Constraints). If `test_browser_dormant.py` exists, add one assertion that the cost line is present and changes after a fake usage event, and run it with `--with playwright`.
- [ ] **Step 5: Commit** `feat(talk): the call page shows what the call costs, and the recap totals it`
