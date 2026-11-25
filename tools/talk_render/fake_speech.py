"""A silent stand-in speech engine for the render harness: no Azure, no VoiceStudio, no cost.

It has the module shape speech.py expects of an engine (NAME, DEFAULT_VOICE, BASE_S, PER_CHAR_S,
ensure_running, describe, resolve_voice, speak, transcribe, VOICES). speak() returns a silent WAV
whose length follows the text the way a voice does (time per character, a pause at each sentence
end) and a (word, start, end) list for every word, the form Azure's word boundaries give.
TALK_FAKE_PACE scales the time: 1.0 is a calm voice (about 0.4 s a word), 0.5 is twice as fast.
"""
from __future__ import annotations

import io
import os
import re
import wave

from speech import SpeechError, Spoken  # noqa: F401  (SpeechError is part of the engine contract)

NAME = "Silent"
DEFAULT_VOICE = "silent"
VOICES = ()
BASE_S = 0.05
PER_CHAR_S = 0.0005
RATE = 8000


def pace() -> float:
    try:
        return max(0.05, float(os.environ.get("TALK_FAKE_PACE", "1.0")))
    except ValueError:
        return 1.0


def ensure_running(wait_s: float = 0, say=print) -> dict:
    return {"status": "ok", "device": "silent", "version": "harness"}


def describe(info: dict) -> str:
    return "Silent harness engine"


def resolve_voice(name):
    return name or DEFAULT_VOICE, None


def word_times(text: str) -> tuple[list[tuple[str, float, float]], float]:
    k = pace()
    words, t = [], 0.25 * k
    for m in re.finditer(r"\S+", text):
        w = m.group()
        d = (0.12 + 0.055 * len(re.sub(r"\W", "", w))) * k
        words.append((w, round(t, 3), round(t + d, 3)))
        t += d + 0.03 * k
        if re.search(r"[.!?…][)\]\"'”’]*$", w):
            t += 0.38 * k
        elif re.search(r"[,;:]$", w):
            t += 0.12 * k
    return words, t + 0.3 * k


def speak(text: str, voice: str = DEFAULT_VOICE, wav: bool = False) -> Spoken:
    words, duration = word_times(text)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(RATE)
        w.writeframes(b"\x80" * int(duration * RATE))
    return Spoken(audio=buf.getvalue(), ext="wav", duration=round(duration, 3), words=words)


def transcribe(audio: bytes, language=None) -> str:
    return ""
