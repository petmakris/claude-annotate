"""talk needs Python 3.11+ and aiohttp; skip its suite cleanly where either is missing.

`talk.py` is a `uv run --script` program that declares its own dependencies, so
nothing else in this repository installs aiohttp. CI installs it on the 3.12 leg.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# The tests import `helpers` and the skill's modules by bare name, as they do
# when run from inside the skill directory.
HERE = Path(__file__).resolve().parent
for path in (HERE, HERE.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

collect_ignore_glob = []
if sys.version_info < (3, 11) or importlib.util.find_spec("aiohttp") is None:
    collect_ignore_glob = ["test_*.py"]


@pytest.fixture(autouse=True)
def private_ledger(tmp_path, monkeypatch):
    """No test reads or writes the real ~/.local/share/talk/ledger.jsonl."""
    if "talk" in sys.modules:
        monkeypatch.setattr(sys.modules["talk"], "LEDGER_FILE", tmp_path / "ledger.jsonl", raising=False)
    yield
