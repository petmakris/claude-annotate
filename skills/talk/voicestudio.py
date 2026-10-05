"""VoiceStudio speech for talk: text to an mp3, and a recording to text, on this machine.

The VoiceStudio app runs a local server with OpenAI-style audio routes, only while the app is
open. Standard library only. The address comes from VOICESTUDIO_URL (default
http://127.0.0.1:3900). A loopback address needs no key; a remote one needs OMNIVOICE_API_KEY,
which is sent as a bearer token, never in a URL. The server runs one speech job at a time.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

DEFAULT_URL = "http://127.0.0.1:3900"
DEFAULT_VOICE = "alloy"  # VoiceStudio maps OpenAI's voice names to its active engine's default voice
TIMEOUT_S = 300  # the first request loads the model; a long answer takes a while on a laptop
LANGUAGES = {"auto": None, "en": "en", "el": "el"}  # what the page offers; None lets Whisper detect it


class SpeechError(Exception):
    """VoiceStudio refused or could not be reached; the message says which, and what to check."""


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


def synthesize(text: str, voice: str = DEFAULT_VOICE, fmt: str = "mp3") -> bytes:
    """The text read aloud, as audio bytes in `fmt` (mp3 or wav). The voice reads the text's own language."""
    body = json.dumps({"model": "tts-1", "voice": voice, "input": text, "response_format": fmt}).encode()
    return _request("/v1/audio/speech", body, "application/json", "text to speech")


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
