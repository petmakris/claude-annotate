"""~/.config/slides/config.json, read the one way both slides scripts read it.

`framework/inline.py` takes the theme from it and `bin/decks` the decks folder;
both are run as plain scripts, so this sits beside inline.py where either can
import it by name.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def config_dir() -> Path:
    """~/.config/slides, or the same under $XDG_CONFIG_HOME."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "slides"


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> dict:
    """The config as a dict; {} when there is none. Invalid JSON exits."""
    path = config_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except ValueError as err:
        raise SystemExit(f"{path}: not valid JSON ({err})")
    return data if isinstance(data, dict) else {}
