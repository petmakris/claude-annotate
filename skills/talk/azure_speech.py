"""Azure speech for talk: an answer to an mp3 with the time of every word, and a recording to text.

Runs on Microsoft's Speech SDK (azure-cognitiveservices-speech), imported only when Azure is used.
The key comes from speech.azure_key() and is handed to the SDK in-process, never on a command line.
Text to speech reports each word as it is made, so no second pass is needed to time the words.
Named azure_speech, not azure, so it never shadows the SDK's own `azure` package.
"""

from __future__ import annotations

import io
import threading
import wave
from xml.sax.saxutils import escape

from speech import SpeechError, Spoken, azure_key, forget_key

NAME = "Azure"
DEFAULT_VOICE = "en-US-AvaMultilingualNeural"  # speaks Greek text in Greek too
LOCALES = {"en": "en-US", "el": "el-GR"}
BASE_S = 0.8  # a request's own cost, before the text's length counts
PER_CHAR_S = 0.006  # measured: 260 characters in about 2.2 s, from Switzerland West
LISTEN_TIMEOUT_S = 120


def _sdk():
    try:
        import azure.cognitiveservices.speech as sdk
    except ImportError:
        raise SpeechError("Azure speech needs the azure-cognitiveservices-speech package: "
                          "run talk.py with uv run --script, which installs it") from None
    return sdk


def _config():
    found = azure_key()
    if not found:
        raise SpeechError("no Azure speech key: set AZURE_SPEECH_KEY or TALK_AZURE_KEY_COMMAND")
    key, region = found
    return _sdk().SpeechConfig(subscription=key, region=region)


def _failure(sdk, result, what: str) -> SpeechError:
    detail = getattr(result, "cancellation_details", None)
    reason = getattr(detail, "error_details", "") or getattr(detail, "reason", "") or result.reason
    if "401" in str(reason) or "Authentication" in str(reason):
        forget_key()
        return SpeechError(f"Azure rejected the key for {what}: check the key and its region")
    return SpeechError(f"Azure {what} failed: {reason}")


def ensure_running(say=print) -> dict:
    """Azure needs nothing started: only a key. What doctor and a launch print about it."""
    found = azure_key()
    if not found:
        raise SpeechError("no Azure speech key: set AZURE_SPEECH_KEY or TALK_AZURE_KEY_COMMAND")
    _sdk()
    return {"status": "ok", "region": found[1]}


def describe(info: dict) -> str:
    return f"Azure speech, region {info.get('region')}"


def resolve_voice(voice: str | None) -> tuple[str, str | None]:
    """An Azure neural voice by name; anything else (VoiceStudio's profile name) means the default."""
    if voice and voice.endswith("Neural"):
        return voice, None
    return DEFAULT_VOICE, None


def ssml(text: str, voice: str) -> str:
    return f"<speak version='1.0' xml:lang='en-US'><voice name='{escape(voice)}'>{escape(text)}</voice></speak>"


def split_boundary(text: str, start: float, length: float) -> list[tuple[str, float, float]]:
    """One word boundary as words: Azure reports "5 October" as one, the page shows two."""
    parts = text.split()
    if len(parts) <= 1:
        return [(text, start, start + length)]
    total = sum(len(p) for p in parts)
    out, t = [], start
    for p in parts:
        share = length * len(p) / total
        out.append((p, round(t, 3), round(t + share, 3)))
        t += share
    return out


def speak(text: str, voice: str = DEFAULT_VOICE, wav: bool = False) -> Spoken:
    sdk = _sdk()
    config = _config()
    fmt = sdk.SpeechSynthesisOutputFormat
    config.set_speech_synthesis_output_format(fmt.Riff16Khz16BitMonoPcm if wav else fmt.Audio24Khz96KBitRateMonoMp3)
    synth = sdk.SpeechSynthesizer(speech_config=config, audio_config=None)
    words: list[tuple[str, float, float]] = []

    def boundary(event):
        if event.boundary_type == sdk.SpeechSynthesisBoundaryType.Word:
            words.extend(split_boundary(event.text, event.audio_offset / 1e7, event.duration.total_seconds()))

    synth.synthesis_word_boundary.connect(boundary)
    result = synth.speak_ssml_async(ssml(text, voice)).get()
    if result.reason != sdk.ResultReason.SynthesizingAudioCompleted:
        raise _failure(sdk, result, "text to speech")
    return Spoken(audio=bytes(result.audio_data), ext="wav" if wav else "mp3",
                  duration=result.audio_duration.total_seconds(), words=words)


def transcribe(audio: bytes, language: str | None = None) -> str:
    """What was said in a WAV recording, of any length; empty when nothing was recognised.
    `language` None tells English from Greek by the start of the recording."""
    sdk = _sdk()
    try:
        with wave.open(io.BytesIO(audio)) as w:
            rate, width, channels = w.getframerate(), w.getsampwidth(), w.getnchannels()
            frames = w.readframes(w.getnframes())
    except (wave.Error, EOFError) as err:
        raise SpeechError(f"not a WAV recording: {err}") from None
    if width != 2:
        raise SpeechError(f"expected 16-bit audio, got {8 * width} bit")
    stream = sdk.audio.PushAudioInputStream(sdk.audio.AudioStreamFormat(
        samples_per_second=rate, bits_per_sample=16, channels=channels))
    stream.write(frames)
    stream.close()
    kwargs = {"speech_config": _config(), "audio_config": sdk.audio.AudioConfig(stream=stream)}
    if language in LOCALES:
        kwargs["language"] = LOCALES[language]
    else:
        kwargs["auto_detect_source_language_config"] = sdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=list(LOCALES.values()))
    recognizer = sdk.SpeechRecognizer(**kwargs)
    said: list[str] = []
    problem: list = []
    done = threading.Event()

    def recognized(event):
        if event.result.reason == sdk.ResultReason.RecognizedSpeech and event.result.text:
            said.append(event.result.text.strip())

    def canceled(event):
        if event.cancellation_details.reason == sdk.CancellationReason.Error:
            problem.append(event.result)
        done.set()

    recognizer.recognized.connect(recognized)
    recognizer.canceled.connect(canceled)
    recognizer.session_stopped.connect(lambda event: done.set())
    recognizer.start_continuous_recognition_async().get()
    finished = done.wait(LISTEN_TIMEOUT_S)
    recognizer.stop_continuous_recognition_async().get()
    if problem:
        raise _failure(sdk, problem[0], "speech to text")
    if not finished:
        raise SpeechError(f"Azure speech to text did not finish within {LISTEN_TIMEOUT_S} s")
    return " ".join(said)
