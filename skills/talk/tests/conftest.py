"""talk needs Python 3.11+ and aiohttp; skip its suite cleanly where either is missing.

`talk.py` is a `uv run --script` program that declares its own dependencies;
requirements-test.txt installs aiohttp for its tests on Python 3.11 and newer.
"""
import importlib.util
import os
import sys
import tempfile
from pathlib import Path

# Servers and clients started by the tests keep their files here, never in the real talk folder.
os.environ["TALK_RUN_DIR"] = tempfile.mkdtemp(prefix="talk-run-")
# Tests never run a key command or reach Azure: the engine is VoiceStudio, faked where a test speaks.
os.environ["TALK_SPEECH"] = "voicestudio"
os.environ["TALK_REVIVE"] = "0"

# The tests import `helpers` and the skill's modules by bare name, as they do
# when run from inside the skill directory.
HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

collect_ignore_glob = []
if sys.version_info < (3, 11) or importlib.util.find_spec("aiohttp") is None:
    collect_ignore_glob = ["test_*.py"]


def pytest_report_header(config):
    if collect_ignore_glob:
        return ("talk: every talk test is SKIPPED, this Python lacks 3.11+ or aiohttp; "
                "run with: uv run --with pytest --with requests --with aiohttp python -m pytest")


if not collect_ignore_glob:
    import pytest

    @pytest.fixture(autouse=True)
    def no_real_server(monkeypatch):
        """A test never starts a detached talk server: it would outlive the test and hold the real port."""
        import talk

        def refuse(port, log_path):
            raise AssertionError("a test tried to start a real talk server")

        monkeypatch.setattr(talk, "spawn_server", refuse)

    @pytest.fixture(autouse=True)
    def no_real_service(monkeypatch, tmp_path):
        """A test never sees the machine's launchd service, nor drives launchctl: the plist is looked
        for in the test's own folder, and a test that wants launchctl fakes it."""
        import talk_service

        def refuse(*args):
            raise AssertionError(f"a test tried to run launchctl {' '.join(args)}")

        monkeypatch.setattr(talk_service, "plist_path", lambda: tmp_path / "LaunchAgents" / "dev.talk.plist")
        monkeypatch.setattr(talk_service, "launchctl", refuse)
