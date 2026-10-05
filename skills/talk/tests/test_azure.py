import array
import io
import json
import urllib.error
from unittest.mock import patch

import pytest

import azure
from helpers import silent_wav


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "testregion")


class Answer:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_key_goes_in_a_header_and_never_in_the_url():
    seen = []

    def urlopen(req, timeout):
        seen.append(req)
        return Answer(b"mp3")

    with patch.object(azure.urllib.request, "urlopen", urlopen):
        assert azure.synthesize("Hi & <bye>") == b"mp3"
    req = seen[0]
    assert req.full_url == "https://testregion.tts.speech.microsoft.com/cognitiveservices/v1"
    assert req.get_header("Ocp-apim-subscription-key") == "k"
    assert b"Hi &amp; &lt;bye&gt;" in req.data


def test_no_key_says_where_to_put_it(monkeypatch):
    monkeypatch.delenv("AZURE_SPEECH_KEY")
    with pytest.raises(azure.SpeechError, match="AZURE_SPEECH_KEY"):
        azure.synthesize("x")


def test_a_rejected_key_says_what_to_check():
    def urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, io.BytesIO(b""))

    with patch.object(azure.urllib.request, "urlopen", urlopen), pytest.raises(azure.SpeechError, match="HTTP 401"):
        azure.transcribe(silent_wav())


def test_transcribe_asks_for_the_locale_and_returns_the_display_text():
    seen = []

    def urlopen(req, timeout):
        seen.append(req)
        return Answer(json.dumps({"RecognitionStatus": "Success", "DisplayText": "Καλημέρα."}).encode())

    with patch.object(azure.urllib.request, "urlopen", urlopen):
        assert azure.transcribe(silent_wav(), "el-GR") == "Καλημέρα."
    assert "language=el-GR" in seen[0].full_url


def test_silence_is_empty_not_an_error():
    with patch.object(azure.urllib.request, "urlopen",
                      lambda req, timeout: Answer(json.dumps({"RecognitionStatus": "NoMatch"}).encode())):
        assert azure.transcribe(silent_wav()) == ""


def test_a_wav_at_another_rate_is_refused():
    with pytest.raises(azure.SpeechError, match="16 kHz"):
        azure.transcribe(silent_wav(rate=44100))


def test_a_long_recording_is_cut_at_its_quietest_moment():
    rate = azure.RATE
    loud = array.array("h", [8000, -8000] * (rate // 2))  # one second of noise
    samples = array.array("h")
    for second in range(130):
        samples.extend(array.array("h", [0]) * rate if second in (47, 100) else loud)
    pieces = azure.pieces(samples)
    assert len(pieces) == 3
    assert all(len(p) <= azure.PIECE_MAX_S * rate for p in pieces)
    assert sum(len(p) for p in pieces) == len(samples)
    assert 47 * rate <= len(pieces[0]) <= 48 * rate  # inside the silent second
