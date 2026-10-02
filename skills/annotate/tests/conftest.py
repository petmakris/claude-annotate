import pytest


@pytest.fixture(autouse=True)
def _isolated_marker(tmp_path, monkeypatch):
    # A test that pushes records the session in this conversation's marker.
    # Without this, a suite run from inside Claude Code wrote its throwaway
    # sessions into the live conversation's real marker.
    monkeypatch.setenv("CLAUDE_ANNOTATE_STATE_DIR", str(tmp_path / "annotate-state"))
