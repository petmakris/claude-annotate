"""Which engine talk speaks with: Azure when a key is found, else VoiceStudio, never the vault in a test."""
import pytest

import azure_speech
import speech
import voicestudio


@pytest.fixture
def fresh(monkeypatch):
    """A process that has not chosen its engine or read a key yet."""
    monkeypatch.setattr(speech, "_engine", None)
    monkeypatch.setattr(speech, "_key", None)
    monkeypatch.setattr(speech, "_key_missed_at", float("-inf"))
    monkeypatch.delenv("TALK_SPEECH", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SPEECH_REGION", raising=False)
    vault = {}
    monkeypatch.setattr(speech, "vault_field", lambda name: vault.get(name, ""))
    return vault


def test_a_key_in_the_environment_picks_azure(fresh, monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "k")
    assert speech.engine() is azure_speech and speech.name() == "Azure"
    assert speech.azure_key() == ("k", "westeurope")


def test_a_key_in_the_vault_picks_azure_with_its_region(fresh):
    fresh.update(token="vault-key", region="switzerlandwest")
    assert speech.engine() is azure_speech
    assert speech.azure_key() == ("vault-key", "switzerlandwest")


def test_no_key_falls_back_to_voicestudio(fresh):
    assert speech.engine() is voicestudio and speech.azure_key() is None


def test_talk_speech_picks_by_hand(fresh, monkeypatch):
    fresh.update(token="vault-key")
    monkeypatch.setenv("TALK_SPEECH", "voicestudio")
    assert speech.engine() is voicestudio
    monkeypatch.setattr(speech, "_engine", None)
    monkeypatch.setenv("TALK_SPEECH", "nonsense")
    with pytest.raises(speech.SpeechError, match="azure or voicestudio"):
        speech.engine()


def test_each_engine_takes_its_own_voices_and_defaults_the_other_s():
    assert azure_speech.resolve_voice("en-GB-SoniaNeural") == ("en-GB-SoniaNeural", None)
    assert azure_speech.resolve_voice("Talk") == (azure_speech.DEFAULT_VOICE, None)
    assert azure_speech.resolve_voice(None) == (azure_speech.DEFAULT_VOICE, None)


def test_a_boundary_of_several_words_is_shared_out_by_length():
    assert azure_speech.split_boundary("idcll", 1.0, 0.5) == [("idcll", 1.0, 1.5)]
    parts = azure_speech.split_boundary("5 October", 2.0, 0.8)
    assert [p[0] for p in parts] == ["5", "October"]
    assert parts[0][1] == 2.0 and parts[0][2] == parts[1][1] and abs(parts[1][2] - 2.8) < 0.01


def test_ssml_escapes_the_text():
    assert "a &lt; b &amp; c" in azure_speech.ssml("a < b & c", "v")


def test_a_key_the_vault_could_not_give_is_looked_for_again_later(fresh, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(speech.time, "monotonic", lambda: clock[0])
    assert speech.azure_key() is None
    fresh.update(token="late-key")
    assert speech.azure_key() is None
    clock[0] += speech.KEY_RETRY_S
    assert speech.azure_key() == ("late-key", "westeurope")


def test_a_key_azure_rejects_is_read_again(fresh, monkeypatch):
    from types import SimpleNamespace
    fresh.update(token="old-key")
    assert speech.azure_key() == ("old-key", "westeurope")
    fresh.update(token="rotated-key")
    rejected = SimpleNamespace(cancellation_details=SimpleNamespace(error_details="401 Authentication failed"))
    assert "rejected the key" in str(azure_speech._failure(None, rejected, "text to speech"))
    assert speech.azure_key() == ("rotated-key", "westeurope")


def test_voicestudio_quit_mid_call_is_opened_again_once(fresh, monkeypatch):
    attempts, opened = [], []

    def speak(text, voice, wav=False):
        attempts.append(text)
        if len(attempts) == 1:
            raise speech.SpeechError("cannot reach VoiceStudio at http://127.0.0.1:3900 for text to speech")
        return "made"

    monkeypatch.setattr(voicestudio, "speak", speak)
    monkeypatch.setattr(voicestudio, "ensure_running", lambda say=print: opened.append(1) or {})
    assert speech.speak("hi", "v") == "made" and len(attempts) == 2 and opened == [1]
    monkeypatch.setattr(voicestudio, "speak", lambda *a, **k: (_ for _ in ()).throw(speech.SpeechError("HTTP 500")))
    with pytest.raises(speech.SpeechError, match="HTTP 500"):
        speech.speak("hi", "v")
    assert opened == [1]
