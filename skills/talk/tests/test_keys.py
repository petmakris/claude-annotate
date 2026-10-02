import talk


def test_the_tools_own_key_wins_over_a_shared_one_in_the_environment(tmp_path, monkeypatch):
    keys = tmp_path / "keys.env"
    keys.write_text("TALK_OPENAI_API_KEY=sk-talk\n")
    monkeypatch.setattr(talk, "KEYS_FILE", keys)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shared")
    monkeypatch.setenv("TALK_OPENAI_API_KEY", "")
    talk.load_keys()
    assert talk.os.environ["OPENAI_API_KEY"] == "sk-talk"


def test_without_its_own_key_the_shared_one_stays(tmp_path, monkeypatch):
    keys = tmp_path / "keys.env"
    keys.write_text("OPENAI_API_KEY=sk-file\n")
    monkeypatch.setattr(talk, "KEYS_FILE", keys)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shared")
    monkeypatch.setenv("TALK_OPENAI_API_KEY", "")
    talk.load_keys()
    assert talk.os.environ["OPENAI_API_KEY"] == "sk-shared"
