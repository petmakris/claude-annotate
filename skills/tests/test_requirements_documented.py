"""The requirement must be stated before someone installs, not after.

A user with no python3 had no way to know the plugin needed it: the word
does not appear in the README or in either marketplace description.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_states_requirements_before_install():
    text = ROOT / "README.md"
    body = text.read_text(encoding="utf-8")
    assert "## Requirements" in body, "README needs a Requirements section"
    assert body.index("## Requirements") < body.index("## Install"), \
        "requirements must appear before install instructions"
    section = body[body.index("## Requirements"):body.index("## Install")]
    for token in ("python3", "3.9", "bash", "curl"):
        assert token in section, f"Requirements section must mention {token!r}"
    assert "pip install" in section, \
        "say there is nothing to pip install — it is the question everyone asks"


def test_both_plugin_descriptions_name_the_python_requirement():
    plugins = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )["plugins"]
    for plugin in plugins:
        assert "Python 3.9" in plugin["description"], \
            f"{plugin['name']} description must state the Python requirement"
