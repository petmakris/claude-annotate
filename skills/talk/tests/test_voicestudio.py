import json
import urllib.error
from unittest.mock import patch

import pytest

import voicestudio
from helpers import silent_wav


@pytest.fixture(autouse=True)
def local(monkeypatch):
    monkeypatch.delenv("VOICESTUDIO_URL", raising=False)
    monkeypatch.delenv("OMNIVOICE_API_KEY", raising=False)


class Answer:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def capture(answer: bytes):
    seen = []

    def urlopen(req, timeout=None):
        seen.append(req)
        return Answer(answer)

    return seen, patch.object(voicestudio.urllib.request, "urlopen", urlopen)


def test_speech_asks_for_a_quality_wav_in_the_texts_language():
    seen, fake = capture(b"wav")
    with fake:
        assert voicestudio.synthesize("Hi & bye", "0b250356") == b"wav"
        voicestudio.synthesize("Καλημέρα σε όλους", "0b250356")
    assert seen[0].full_url == "http://127.0.0.1:3900/v1/audio/speech"
    assert json.loads(seen[0].data) == {"model": "tts-1", "voice": "0b250356", "input": "Hi & bye",
                                        "response_format": "wav", "num_step": 32, "language": "en"}
    assert json.loads(seen[1].data)["language"] == "el"
    assert seen[0].get_header("Authorization") is None


def test_a_profile_is_found_by_name_and_its_id_is_the_voice():
    profiles = [{"id": "demo0001", "name": "VoiceStudio Demo Voice"}, {"id": "0b250356", "name": "Talk"}]
    _, fake = capture(json.dumps(profiles).encode())
    with fake:
        assert voicestudio.resolve_voice("talk") == ("0b250356", None)
        assert voicestudio.resolve_voice("0b250356") == ("0b250356", None)
        voice, problem = voicestudio.resolve_voice("Narrator")
    assert voice == "Narrator" and "different random voice" in problem


def test_a_remote_server_gets_the_key_as_a_bearer_token(monkeypatch):
    monkeypatch.setenv("VOICESTUDIO_URL", "https://voice.example/")
    monkeypatch.setenv("OMNIVOICE_API_KEY", "k")
    seen, fake = capture(b"mp3")
    with fake:
        voicestudio.synthesize("x")
    assert seen[0].full_url == "https://voice.example/v1/audio/speech"
    assert seen[0].get_header("Authorization") == "Bearer k"


def test_transcribe_sends_the_recording_and_the_language():
    seen, fake = capture(json.dumps({"text": " Καλημέρα. "}).encode())
    with fake:
        assert voicestudio.transcribe(silent_wav(), "el") == "Καλημέρα."
    body = seen[0].data
    assert seen[0].full_url.endswith("/v1/audio/transcriptions")
    assert b'name="language"\r\n\r\nel\r\n' in body and b'name="model"\r\n\r\nwhisper-1\r\n' in body
    assert silent_wav() in body


def test_auto_sends_no_language():
    seen, fake = capture(b'{"text": ""}')
    with fake:
        assert voicestudio.transcribe(silent_wav(), None) == ""
    assert b'name="language"' not in seen[0].data


def test_a_server_that_is_not_running_says_to_start_the_app():
    def refuse(req, timeout=None):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    with patch.object(voicestudio.urllib.request, "urlopen", refuse), \
            pytest.raises(voicestudio.SpeechError, match="VoiceStudio app running"):
        voicestudio.synthesize("x")


def test_a_refusal_carries_the_servers_reason():
    def refuse(req, timeout=None):
        import io
        raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, io.BytesIO(b'{"detail":"no_audio_track"}'))

    with patch.object(voicestudio.urllib.request, "urlopen", refuse), \
            pytest.raises(voicestudio.SpeechError, match="HTTP 400.*no_audio_track"):
        voicestudio.transcribe(b"not audio")


def test_ensure_running_waits_while_the_server_starts(monkeypatch):
    answers = iter([{"status": "starting"}, {"status": "starting"}, {"status": "ok", "device": "mps"}])
    monkeypatch.setattr(voicestudio, "health", lambda: next(answers))
    monkeypatch.setattr(voicestudio.time, "sleep", lambda s: None)
    assert voicestudio.ensure_running()["status"] == "ok"


def test_ensure_running_opens_the_app_on_a_mac(monkeypatch):
    calls = []
    states = iter([voicestudio.SpeechError("down"), {"status": "ok"}])

    def health():
        state = next(states)
        if isinstance(state, Exception):
            raise state
        return state

    monkeypatch.setattr(voicestudio, "health", health)
    monkeypatch.setattr(voicestudio.time, "sleep", lambda s: None)
    monkeypatch.setattr(voicestudio.sys, "platform", "darwin")
    monkeypatch.setattr(voicestudio.os.path, "isdir", lambda p: True)
    monkeypatch.setattr(voicestudio.subprocess, "run", lambda argv, check: calls.append(argv))
    assert voicestudio.ensure_running(say=lambda line: None)["status"] == "ok"
    assert calls == [["open", "-g", "-a", "VoiceStudio"]]


def test_ensure_running_without_the_app_says_why(monkeypatch):
    def down():
        raise voicestudio.SpeechError("cannot reach VoiceStudio")

    monkeypatch.setattr(voicestudio, "health", down)
    monkeypatch.setattr(voicestudio.sys, "platform", "linux")
    with pytest.raises(voicestudio.SpeechError, match="cannot reach"):
        voicestudio.ensure_running()


def test_an_answer_that_is_not_wav_is_a_speech_error():
    for body in (b'{"error": "model not loaded"}', b""):
        with capture(body)[1]:
            with pytest.raises(voicestudio.SpeechError, match="not WAV"):
                voicestudio.speak("Hello there", "v")
