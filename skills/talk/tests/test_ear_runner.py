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
        return e.status, e.error

    assert run(go()) == ("failed", "no metal device")
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
