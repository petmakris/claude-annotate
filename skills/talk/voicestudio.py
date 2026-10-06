"""VoiceStudio speech for talk: text to a WAV, and a recording to text, on this machine.

The VoiceStudio app runs a local server with OpenAI-style audio routes, only while the app is
open. Standard library only. The address comes from VOICESTUDIO_URL (default
http://127.0.0.1:3900). A loopback address needs no key; a remote one needs OMNIVOICE_API_KEY,
which is sent as a bearer token, never in a URL. The server runs one speech job at a time.
"""

import io
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import wave

from speech import SpeechError, Spoken

NAME = "VoiceStudio"
DEFAULT_URL = "http://127.0.0.1:3900"
DEFAULT_VOICE = "Talk"  # a VoiceStudio voice profile, found by name; see resolve_voice()
QUALITY_STEPS = 32  # OmniVoice's documented quality preset; VoiceStudio's own default is 16
TIMEOUT_S = 600  # the first request loads the model; a long answer takes a while on a laptop
BASE_S = 1.5  # a request's own cost, word timing included, before the text's length counts
PER_CHAR_S = 0.05  # measured: 372 characters in 18.8 s on an M-series Mac


def base_url() -> str:
    return (os.environ.get("VOICESTUDIO_URL", "").strip() or DEFAULT_URL).rstrip("/")


def _request(path: str, data: bytes, content_type: str, what: str, timeout: float = TIMEOUT_S) -> bytes:
    headers = {"Content-Type": content_type, "User-Agent": "talk"}
    if key := os.environ.get("OMNIVOICE_API_KEY", "").strip():
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(base_url() + path, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace").strip()[:200]
        raise SpeechError(f"VoiceStudio {what} failed: HTTP {err.code} {detail}") from None
    except (urllib.error.URLError, OSError) as err:
        raise SpeechError(f"cannot reach VoiceStudio at {base_url()} for {what} "
                          f"({getattr(err, 'reason', err)}): is the VoiceStudio app running?") from None


def health() -> dict:
    """VoiceStudio's own health answer, e.g. {"status": "ok", "device": "mps"}."""
    try:
        with urllib.request.urlopen(base_url() + "/health", timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise SpeechError(f"cannot reach VoiceStudio at {base_url()} ({getattr(err, 'reason', err)}): "
                          "is the VoiceStudio app running?") from None


def ensure_running(wait_s: float = 120.0, say=print) -> dict:
    """VoiceStudio's health once it is ready. On a Mac with the app installed, a server that is not
    answering is started with `open -a VoiceStudio` and waited for; a cold start takes about a minute."""
    try:
        info = health()
        if info.get("status") == "ok":
            return info
    except SpeechError:
        if sys.platform != "darwin" or not os.path.isdir("/Applications/VoiceStudio.app"):
            raise
        say("VoiceStudio is not running; opening it (a cold start takes about a minute).")
        subprocess.run(["open", "-g", "-a", "VoiceStudio"], check=False)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            info = health()
        except SpeechError:
            continue
        if info.get("status") == "ok":
            return info
    raise SpeechError(f"VoiceStudio at {base_url()} was not ready after {wait_s:g} s")


def describe(info: dict) -> str:
    return f"VoiceStudio at {base_url()}: {info.get('status')} on {info.get('device')}, version {info.get('version')}"


def resolve_voice(name: str | None) -> tuple[str, str | None]:
    """(what to send as `voice`, a warning or None). A VoiceStudio profile named `name` (any case)
    gives its id, so every answer has that profile's voice. Without one, OmniVoice draws a new
    random speaker for every request, so the voice changes from answer to answer. An Azure voice
    name, or none, means the profile named DEFAULT_VOICE."""
    if not name or name.endswith("Neural"):
        name = DEFAULT_VOICE
    try:
        with urllib.request.urlopen(base_url() + "/profiles", timeout=10) as resp:
            profiles = json.loads(resp.read())
    except (urllib.error.URLError, OSError, ValueError) as err:
        return name, f"could not list VoiceStudio's voice profiles ({getattr(err, 'reason', err)})"
    rows = profiles if isinstance(profiles, list) else profiles.get("profiles", [])
    for row in rows:
        if name == row.get("id") or str(row.get("name", "")).lower() == name.lower():
            return str(row["id"]), None
    return name, (f"no VoiceStudio voice profile named {name!r}: every answer may come in a different "
                  "random voice. Create one in VoiceStudio, or pass --voice <profile id>")


def language_of(text: str) -> str:
    """'el' when the text is mostly Greek letters, else 'en'."""
    letters = [c for c in text if c.isalpha()]
    greek = sum(1 for c in letters if "\u0370" <= c <= "\u03ff" or "\u1f00" <= c <= "\u1fff")
    return "el" if letters and greek / len(letters) > 0.3 else "en"


def synthesize(text: str, voice: str = DEFAULT_VOICE, fmt: str = "wav") -> bytes:
    """The text read aloud, as audio bytes in `fmt` (wav: 24 kHz mono 16-bit), at quality settings."""
    body = json.dumps({"model": "tts-1", "voice": voice, "input": text, "response_format": fmt,
                       "num_step": QUALITY_STEPS, "language": language_of(text)}).encode()
    return _request("/v1/audio/speech", body, "application/json", "text to speech")


def speak(text: str, voice: str = DEFAULT_VOICE, wav: bool = True) -> Spoken:
    """The whole text read aloud in one request, then run back through Whisper to time each word.
    A word-timing failure is not fatal: the page then shares the time out by word length."""
    audio = synthesize(text, voice)
    try:
        with wave.open(io.BytesIO(audio)) as w:
            duration = w.getnframes() / w.getframerate()
    except (wave.Error, EOFError) as err:
        raise SpeechError(f"VoiceStudio text to speech answered something that is not WAV ({err}): {audio[:120]!r}") from None
    try:
        words = word_times(audio, language_of(text))
    except SpeechError as err:
        print(f"speech: word timing failed, shared out by length instead: {err}", flush=True)
        words = []
    return Spoken(audio=audio, ext="wav", duration=duration, words=words)


def transcribe(audio: bytes, language: str | None = None, filename: str = "turn.wav") -> str:
    """What was said in a recording; empty when nothing was recognised. `language` None detects it."""
    boundary = uuid.uuid4().hex
    fields = {"model": "whisper-1", **({"language": language} if language else {})}
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
             for name, value in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n".encode() + audio + b"\r\n")
    raw = _request("/v1/audio/transcriptions", b"".join(parts) + f"--{boundary}--\r\n".encode(),
                   f"multipart/form-data; boundary={boundary}", "speech to text")
    try:
        return str(json.loads(raw).get("text") or "").strip()
    except (ValueError, AttributeError):
        raise SpeechError(f"VoiceStudio speech to text answered something that is not JSON: {raw[:120]!r}") from None


def word_times(audio: bytes, language: str | None = None) -> list[tuple[str, float, float]]:
    """When each word is said in a recording: (word, start, end) in seconds, from Whisper."""
    boundary = uuid.uuid4().hex
    fields = [("model", "whisper-1"), ("response_format", "verbose_json"), ("timestamp_granularities[]", "word")]
    if language:
        fields.append(("language", language))
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
             for name, value in fields]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="piece.wav"\r\n'
                 "Content-Type: application/octet-stream\r\n\r\n".encode() + audio + b"\r\n")
    raw = _request("/v1/audio/transcriptions", b"".join(parts) + f"--{boundary}--\r\n".encode(),
                   f"multipart/form-data; boundary={boundary}", "word timing")
    try:
        words = json.loads(raw).get("words") or []
        return [(str(w["word"]), float(w["start"]), float(w["end"])) for w in words]
    except (ValueError, AttributeError, KeyError, TypeError):
        raise SpeechError(f"VoiceStudio word timing answered something unexpected: {raw[:120]!r}") from None

