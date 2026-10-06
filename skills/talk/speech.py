"""Which speech engine talk uses, and the one way talk.py calls it.

Azure speech when its key is found: AZURE_SPEECH_KEY (and AZURE_SPEECH_REGION) in the environment,
else the vault entry `azure-speech` (fields token and region) through `@secrets read`. Without a key,
the local VoiceStudio app. TALK_SPEECH=azure or TALK_SPEECH=voicestudio picks one by hand.

Every answer is made in one request, never piece by piece: pieces joined together pause and click
at every seam. While it is made, the page shows a progress bar timed by estimate() and learn().
"""

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

LANGUAGES = {"auto": None, "en": "en", "el": "el"}  # what the page offers; None lets the engine detect it


class SpeechError(Exception):
    """The engine refused or could not be reached; the message says which, and what to check."""


@dataclass
class Spoken:
    """An answer read aloud: the audio file's bytes and extension, its length, and when each word is said."""
    audio: bytes
    ext: str  # "mp3" or "wav"
    duration: float  # seconds
    words: list = field(default_factory=list)  # (word, start s, end s), as the engine said or heard them


_lock = threading.Lock()
_engine = None
_key: tuple[str, str] | None = None
_key_missed_at = float("-inf")
KEY_RETRY_S = 60.0
_rates: dict[str, float] = {}  # engine name -> seconds of work per character, learned from each answer


def vault_field(name: str) -> str:
    """One field of the vault entry `azure-speech`, or "" when the vault cannot be read."""
    if not shutil.which("@secrets"):
        return ""
    try:
        out = subprocess.run(["@secrets", "read", "azure-speech", name], capture_output=True, text=True,
                             timeout=20, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def azure_key() -> tuple[str, str] | None:
    """(key, region) for Azure speech, or None. The environment wins over the vault. A key found is
    kept until forget_key(); a key not found is looked for again after KEY_RETRY_S, since the vault
    may only have been locked or slow."""
    global _key, _key_missed_at
    with _lock:
        if _key is None and time.monotonic() - _key_missed_at >= KEY_RETRY_S:
            key = os.environ.get("AZURE_SPEECH_KEY", "").strip() or vault_field("token")
            region = os.environ.get("AZURE_SPEECH_REGION", "").strip() or (vault_field("region") if key else "")
            if key:
                _key = (key, region or "westeurope")
            else:
                _key_missed_at = time.monotonic()
        return _key


def forget_key() -> None:
    """Azure rejected the key: read it again next time, so a rotated key is picked up."""
    global _key, _key_missed_at
    with _lock:
        _key, _key_missed_at = None, float("-inf")


def engine():
    """The engine module this process uses, chosen once: azure_speech or voicestudio."""
    global _engine
    if _engine is None:
        choice = os.environ.get("TALK_SPEECH", "").strip().lower()
        if choice not in ("", "azure", "voicestudio"):
            raise SpeechError(f"TALK_SPEECH={choice!r}: use azure or voicestudio")
        if choice == "azure" or (not choice and azure_key()):
            import azure_speech as chosen
        else:
            import voicestudio as chosen
        _engine = chosen
    return _engine


def name() -> str:
    return engine().NAME


def default_voice() -> str:
    return engine().DEFAULT_VOICE


def ensure_running(say=print) -> dict:
    return engine().ensure_running(say=say)


def fix() -> str:
    """What the user does when the engine is not ready."""
    if engine().NAME == "Azure":
        return "Check the vault entry azure-speech (fields token and region)"
    return "Start the VoiceStudio app, or add the vault entry azure-speech to speak with Azure"


def describe(info: dict) -> str:
    return engine().describe(info)


def resolve_voice(voice: str | None) -> tuple[str, str | None]:
    return engine().resolve_voice(voice)


def _reopened(call):
    """`call()`, run once more after the engine is started again when it could not be reached: the
    VoiceStudio app may have been quit since the call opened."""
    try:
        return call()
    except SpeechError as err:
        if not str(err).startswith("cannot reach"):
            raise
        engine().ensure_running(say=lambda line: print(f"speech: {line}", flush=True))
        return call()


def speak(text: str, voice: str, wav: bool = False) -> Spoken:
    """The whole text read aloud in one request. `wav` asks for a 16 kHz WAV that transcribe() takes."""
    return _reopened(lambda: engine().speak(text, voice, wav=wav))


def transcribe(audio: bytes, language: str | None = None) -> str:
    """What was said in a 16 kHz mono WAV; empty when nothing was recognised. None detects the language."""
    return _reopened(lambda: engine().transcribe(audio, language))


def estimate(text: str) -> float:
    """How many seconds making `text` should take, from what the last answers took."""
    eng = engine()
    return round(eng.BASE_S + len(text) * _rates.get(eng.NAME, eng.PER_CHAR_S), 2)


def learn(text: str, seconds: float) -> None:
    """Fold how long `text` took into the next estimates."""
    eng = engine()
    if len(text) < 40:
        return
    seen = max(0.0, seconds - eng.BASE_S) / len(text)
    old = _rates.get(eng.NAME, eng.PER_CHAR_S)
    _rates[eng.NAME] = 0.6 * old + 0.4 * seen
