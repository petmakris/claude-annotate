"""Azure speech for talk: text to an mp3, and a 16 kHz mono WAV recording to text.

Standard library only. The key comes from AZURE_SPEECH_KEY (and AZURE_SPEECH_REGION, default
westeurope), in the environment or in talk's keys file. It is sent in a header, never in a URL.

Speech to text uses the short-audio REST API, which takes at most 60 seconds per request. A longer
recording is cut into pieces at its quietest moments and the pieces' text is joined.
"""

import array
import io
import json
import os
import urllib.error
import urllib.request
import wave
from xml.sax.saxutils import escape

DEFAULT_VOICE = "en-US-AvaMultilingualNeural"  # speaks Greek text in Greek too
DEFAULT_REGION = "westeurope"
RATE = 16000  # what the page records and what the API is sent
PIECE_MAX_S = 55.0  # under the API's 60 s limit
PIECE_MIN_S = 40.0  # a cut is looked for between here and PIECE_MAX_S
TIMEOUT_S = 60
LANGUAGES = {"en": "en-US", "el": "el-GR"}


class SpeechError(Exception):
    """Azure refused or could not be reached; the message says which, and what to check."""


def key_and_region() -> tuple[str, str]:
    key = os.environ.get("AZURE_SPEECH_KEY", "").strip()
    if not key:
        raise SpeechError("no AZURE_SPEECH_KEY in the environment or talk's keys file")
    return key, os.environ.get("AZURE_SPEECH_REGION", "").strip() or DEFAULT_REGION


def _post(url: str, data: bytes, headers: dict, what: str) -> bytes:
    key, _ = key_and_region()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={**headers, "Ocp-Apim-Subscription-Key": key, "User-Agent": "talk"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace").strip()[:200]
        if err.code == 401:
            raise SpeechError(f"Azure rejected the key for {what} (HTTP 401): check AZURE_SPEECH_KEY and "
                              "AZURE_SPEECH_REGION") from None
        raise SpeechError(f"Azure {what} failed: HTTP {err.code} {detail}") from None
    except (urllib.error.URLError, OSError) as err:
        raise SpeechError(f"cannot reach Azure for {what}: {getattr(err, 'reason', err)}") from None


def ssml(text: str, voice: str, locale: str = "en-US", rate: float = 1.0) -> str:
    return (f"<speak version='1.0' xml:lang='{locale}'><voice name='{escape(voice)}'>"
            f"<prosody rate='{rate:g}'>{escape(text)}</prosody></voice></speak>")


def synthesize(text: str, voice: str = DEFAULT_VOICE, locale: str = "en-US",
               fmt: str = "audio-24khz-96kbitrate-mono-mp3") -> bytes:
    """The text read aloud, as audio bytes in `fmt` (an mp3 by default)."""
    _, region = key_and_region()
    return _post(f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
                 ssml(text, voice, locale).encode(),
                 {"Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": fmt}, "text to speech")


def pcm_of_wav(data: bytes) -> array.array:
    """The 16-bit mono samples of a WAV at RATE, the only kind the page sends."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, RATE):
                raise SpeechError(f"expected 16 kHz mono 16-bit audio, got {w.getframerate()} Hz, "
                                  f"{w.getnchannels()} channel(s), {8 * w.getsampwidth()} bit")
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as err:
        raise SpeechError(f"not a WAV recording: {err}") from None
    samples = array.array("h")
    samples.frombytes(frames)
    return samples


def wav_of_pcm(samples: array.array) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(samples.tobytes())
    return out.getvalue()


def pieces(samples: array.array) -> list[array.array]:
    """Cut a recording into pieces the API accepts, each cut at the quietest 0.2 s window."""
    out, window, step = [], int(RATE * 0.2), int(RATE * 0.05)
    while len(samples) > PIECE_MAX_S * RATE:
        lo, hi = int(PIECE_MIN_S * RATE), int(PIECE_MAX_S * RATE) - window
        cut = min(range(lo, hi, step), key=lambda i: sum(abs(s) for s in samples[i:i + window:8]))
        cut += window // 2
        out.append(samples[:cut])
        samples = samples[cut:]
    out.append(samples)
    return out


def transcribe(wav: bytes, locale: str = "en-US") -> str:
    """What was said in a recording; empty when nothing was recognised."""
    _, region = key_and_region()
    url = (f"https://{region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
           f"?language={locale}&profanity=raw")
    said = []
    for piece in pieces(pcm_of_wav(wav)):
        if len(piece) < RATE * 0.3:
            continue
        raw = _post(url, wav_of_pcm(piece), {"Content-Type": f"audio/wav; codecs=audio/pcm; samplerate={RATE}"},
                    "speech to text")
        try:
            body = json.loads(raw)
        except ValueError:
            raise SpeechError(f"Azure speech to text answered something that is not JSON: {raw[:120]!r}") from None
        if body.get("RecognitionStatus") == "Success" and body.get("DisplayText"):
            said.append(body["DisplayText"].strip())
    return " ".join(said)
